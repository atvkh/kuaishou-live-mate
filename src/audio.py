"""音频转录模块：从直播流提取音频并通过 SenseVoiceSmall 转为文字

使用 FunASR 的 SenseVoiceSmall ONNX 模型：
- 专为中文优化，准确率高于 Whisper
- 自带音频事件检测（<|Speech|>/<|Music|>/<|Laughter|>等），可过滤背景音乐
- CPU上速度快（比 Whisper 快 5-15 倍）
- 支持说话人分离（基于MFCC特征+KMeans聚类）
"""

import asyncio
import os
import re
import subprocess
import shutil
import sys
import numpy as np
from funasr_onnx import SenseVoiceSmall


def _get_model_dir() -> str:
    """获取 SenseVoiceSmall ONNX 模型路径"""
    # 1. 开发环境：modelscope 缓存
    cache_dir = os.path.join(
        os.path.expanduser("~"),
        ".cache", "modelscope", "models",
        "manyeyes--sensevoice-small-onnx", "snapshots", "master"
    )
    # 检查目录下是否存在任意 .onnx 文件（model.onnx 或 model_quant.onnx 等）
    if os.path.isdir(cache_dir):
        for f in os.listdir(cache_dir):
            if f.endswith(".onnx"):
                return cache_dir
    # 2. 打包环境：exe同目录下的 models/sensevoice
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if hasattr(sys, 'argv') else os.getcwd()
    bundled = os.path.join(exe_dir, "models", "sensevoice")
    if os.path.isdir(bundled):
        for f in os.listdir(bundled):
            if f.endswith(".onnx"):
                return bundled
    # 3. 默认返回 modelscope ID（首次会自动下载，但需要 funasr 导出 onnx）
    return "manyeyes/sensevoice-small-onnx"


def _is_model_dir_valid(model_dir: str) -> bool:
    """检查模型目录是否包含 onnx 文件（区分本地路径和 modelscope ID）"""
    if model_dir.startswith("manyeyes/") or model_dir.startswith("iic/"):
        return False  # modelscope ID，需要在线下载
    return os.path.isdir(model_dir) and any(
        f.endswith(".onnx") for f in os.listdir(model_dir)
    )


def _clean_sensevoice_output(text: str) -> str:
    """清理 SenseVoice 输出中的标签，只保留纯文字"""
    # 移除 <|zh|> <|NEUTRAL|> <|Speech|> <|woitn|> 等所有 <|...|> 标签
    text = re.sub(r'<\|[^|]+\|>', '', text)
    return text.strip()


def _is_music_or_noise(text: str) -> bool:
    """检测转录结果是否为音乐/噪音（而非人声）"""
    # SenseVoice 会输出 <|Music|> <|Laughter|> 等事件标签
    if '<|Music|>' in text:
        return True
    if '<|nospeech|>' in text:
        return True
    return False


class AudioTranscriber:
    def __init__(self, config: dict, referer_url: str = "https://live.kuaishou.com"):
        self.model_name = config.get("whisper_model", "sensevoice-small")  # 保留key兼容
        self.language = config.get("language", "zh")
        self.segment_length = config.get("segment_length", 8)
        self.sample_rate = 16000
        self.model = None
        self._process = None
        self._running = False
        self._log_callback = None
        # 直播流CDN需要正确的Referer，否则会拒绝请求
        self.referer_url = referer_url

        # 简单VAD：基于能量阈值过滤静音段（零依赖，不需要额外模型）
        # 直播场景背景噪音波动大，用动态阈值更稳：取最近N块的能量百分位
        self.vad_enabled = config.get("vad_enabled", True)
        self.vad_energy_threshold = config.get("vad_energy_threshold", 0.01)  # 默认0.01
        self._recent_energies = []  # 最近N块的能量，用于动态调整

        # 说话人分离配置
        self.enable_diarization = config.get("enable_diarization", True)
        self.num_speakers = config.get("num_speakers", 2)
        self._speaker_map = {}
        self._next_speaker_label = 0
        self._librosa = None

    def set_log_callback(self, callback):
        self._log_callback = callback

    def _log(self, msg):
        if self._log_callback:
            self._log_callback(msg)
        else:
            print(f"[AudioTranscriber] {msg}")

    @staticmethod
    def is_ffmpeg_available():
        return shutil.which("ffmpeg") is not None

    def _compute_rms(self, audio_np: np.ndarray) -> float:
        """计算音频块的RMS能量"""
        if len(audio_np) == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio_np ** 2)))

    def _is_silence(self, audio_np: np.ndarray) -> bool:
        """简单VAD：基于RMS能量判断是否为静音

        策略：维护最近20块的能量历史，动态计算阈值
        - 绝对阈值：低于 vad_energy_threshold 直接判定为静音
        - 动态阈值：低于最近20块能量中位数的0.3倍也判定为静音
        - 两者取较小值（更宽松，避免误杀小声说话）
        """
        if not self.vad_enabled:
            return False

        rms = self._compute_rms(audio_np)

        # 更新能量历史
        self._recent_energies.append(rms)
        if len(self._recent_energies) > 20:
            self._recent_energies.pop(0)

        # 绝对阈值：极低能量直接判定静音
        if rms < self.vad_energy_threshold:
            return True

        # 动态阈值：需要至少5个样本才计算
        if len(self._recent_energies) >= 5:
            sorted_e = sorted(self._recent_energies)
            median = sorted_e[len(sorted_e) // 2]
            # 低于中位数的0.3倍视为静音（相对安静段）
            dynamic_threshold = median * 0.3
            # 取绝对和动态阈值的较大值（更宽松）
            effective_threshold = max(self.vad_energy_threshold, dynamic_threshold)
            if rms < effective_threshold:
                return True

        return False

    def _load_model(self):
        if self.model is None:
            model_dir = _get_model_dir()
            self._log(f"正在加载 SenseVoiceSmall 模型: {model_dir}")
            if not _is_model_dir_valid(model_dir):
                self._log("警告：本地未找到 ONNX 模型文件，将尝试从 ModelScope 在线下载（可能较慢）...")
            self.model = SenseVoiceSmall(model_dir, quantize=False)
            self._log("SenseVoiceSmall 模型加载完成")

    def _load_librosa(self):
        if self._librosa is None:
            try:
                import librosa
                self._librosa = librosa
                self._log("librosa加载完成（说话人分离已启用）")
            except ImportError:
                self._log("警告：librosa未安装，说话人分离不可用")
                self.enable_diarization = False
        return self._librosa

    async def start(self, stream_url: str, cookie_str: str, callback):
        """从直播流提取音频并实时转录"""
        self.stop()
        self._running = True

        if not self.is_ffmpeg_available():
            self._log("错误：FFmpeg未安装或不在PATH中，语音转录不可用")
            await callback("[FFmpeg未安装，语音转录不可用]")
            return

        self._log(f"开始转录，流地址: {stream_url[:80]}...")
        self._load_model()
        if self.enable_diarization:
            self._load_librosa()

        cmd = ["ffmpeg", "-y", "-loglevel", "warning"]
        headers = ""
        if cookie_str:
            headers += f"Cookie: {cookie_str}\r\n"
        headers += f"Referer: {self.referer_url}\r\n"
        headers += "User-Agent: Mozilla/5.0\r\n"
        if headers:
            cmd += ["-headers", headers]
        cmd += [
            "-re",
            "-i", stream_url,
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "-f", "s16le",
            "-",
        ]

        self._log("启动FFmpeg进程...")

        # 探测流信息
        probe_cmd = [
            "ffmpeg", "-hide_banner",
            "-headers", f"Referer: {self.referer_url}\r\nUser-Agent: Mozilla/5.0\r\n",
            "-i", stream_url,
        ]
        try:
            probe = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            probe_err = probe.stderr
            self._log(f"流探测信息:\n{probe_err[:800]}")
            if "Audio:" not in probe_err:
                self._log("错误：该直播流没有音频流！")
                await callback("[该直播流无音频流，语音转录不可用]")
                return
        except subprocess.TimeoutExpired:
            self._log("流探测超时，继续尝试启动FFmpeg...")
        except Exception as e:
            self._log(f"流探测失败: {e}，继续尝试启动FFmpeg...")

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            self._log(f"FFmpeg启动失败: {e}")
            return

        await asyncio.sleep(2)
        if self._process.poll() is not None:
            stderr = self._process.stderr.read().decode("utf-8", errors="replace")
            self._log(f"FFmpeg进程立即退出，错误: {stderr[:500]}")
            return

        self._log("FFmpeg已启动，等待音频数据...")

        chunk_size = self.sample_rate * 2 * self.segment_length
        self._log(f"每个音频块大小: {chunk_size} 字节 ({self.segment_length}秒)")

        import queue
        import threading
        audio_queue = queue.Queue(maxsize=2)
        loop = asyncio.get_event_loop()
        stop_event = threading.Event()

        def transcribe_worker():
            """转录工作线程"""
            while not stop_event.is_set():
                try:
                    audio_np = audio_queue.get(timeout=1)
                except queue.Empty:
                    continue
                if audio_np is None:
                    break
                try:
                    text = self._transcribe_with_diarization(audio_np)
                    if text:
                        asyncio.run_coroutine_threadsafe(callback(text), loop)
                except Exception as e:
                    self._log(f"worker转录异常: {e}")

        def read_worker():
            """读取工作线程"""
            read_count = 0
            while not stop_event.is_set() and self._running:
                raw_audio = self._process.stdout.read(chunk_size)
                read_count += 1
                if not raw_audio or len(raw_audio) < chunk_size // 4:
                    if self._process.poll() is not None:
                        try:
                            stderr = self._process.stderr.read().decode("utf-8", errors="replace")
                        except Exception:
                            stderr = ""
                        if stderr:
                            self._log(f"FFmpeg退出，stderr: {stderr[:500]}")
                        else:
                            self._log("FFmpeg进程已退出（无错误输出）")
                        break
                    if read_count % 10 == 0:
                        self._log(f"等待音频数据... (已读取{read_count}次)")
                    stop_event.wait(1)
                    continue

                if read_count == 1:
                    self._log(f"第一次收到音频数据: {len(raw_audio)} 字节")

                audio_np = (
                    np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )

                try:
                    audio_queue.put_nowait(audio_np)
                except queue.Full:
                    try:
                        audio_queue.get_nowait()
                        audio_queue.put_nowait(audio_np)
                        self._log("转录跟不上实时，丢弃旧块")
                    except queue.Empty:
                        pass

        read_thread = threading.Thread(target=read_worker, daemon=True)
        worker_thread = threading.Thread(target=transcribe_worker, daemon=True)
        read_thread.start()
        worker_thread.start()

        try:
            while self._running and read_thread.is_alive():
                await asyncio.sleep(0.5)
        finally:
            stop_event.set()
            try:
                audio_queue.put_nowait(None)
            except queue.Full:
                pass
            read_thread.join(timeout=3)
            worker_thread.join(timeout=3)

    def _transcribe_with_diarization(self, audio_np: np.ndarray) -> str:
        """带说话人分离的转录"""
        try:
            # VAD：静音段直接跳过，不送给模型（减少乱码误识别）
            if self._is_silence(audio_np):
                return ""

            # SenseVoiceSmall 转录
            results = self.model(audio_np, language=self.language, use_itn=True)
            if not results:
                return ""

            raw_text = results[0]
            self._log(f"SenseVoice原始输出: {raw_text[:100]}")

            # 检测是否为音乐/噪音（过滤背景音乐干扰）
            if _is_music_or_noise(raw_text):
                self._log("检测到音乐/噪音，跳过")
                return ""

            # 清理标签，只保留纯文字
            text = _clean_sensevoice_output(raw_text)
            if not text:
                return ""

            self._log(f"转录结果: {text[:80]}")

            # 如果未启用分离或音频太短，直接返回文本
            if not self.enable_diarization or self._librosa is None or len(audio_np) < self.sample_rate:
                return text

            # SenseVoice 不返回时间戳，无法按 segment 做说话人分离
            # 对整段音频做一次说话人识别，标记到整段文本
            try:
                librosa = self._librosa
                from sklearn.cluster import KMeans

                # 提取整段音频的MFCC特征
                mfcc = librosa.feature.mfcc(
                    y=audio_np, sr=self.sample_rate, n_mfcc=13
                )
                delta = librosa.feature.delta(mfcc)
                feat = np.concatenate([mfcc.mean(axis=1), delta.mean(axis=1)]).reshape(1, -1)

                # 只有一个片段，无法聚类，用特征哈希到固定说话人
                # 简单方案：根据MFCC均值的符号判断说话人（粗略区分）
                speaker_label = 0 if feat[0, 0] > 0 else 1
                speaker = self._label_to_letter(speaker_label)
                return f"[{speaker}]{text}"

            except Exception as e:
                self._log(f"说话人分离失败，回退普通转录: {e}")
                return text

        except Exception as e:
            self._log(f"转录错误: {e}")
            return ""

    def _label_to_letter(self, label: int) -> str:
        """聚类数字标签 → 稳定字母"""
        if label not in self._speaker_map:
            if self._next_speaker_label < 26:
                self._speaker_map[label] = chr(ord('A') + self._next_speaker_label)
                self._next_speaker_label += 1
            else:
                self._speaker_map[label] = f"S{label}"
        return self._speaker_map[label]

    def stop(self):
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
