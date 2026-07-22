"""音频转录模块：从直播流提取音频并通过 Whisper 转为文字

支持说话人分离（基于MFCC特征+KMeans聚类）：
- 将音频按VAD分段，每段提取MFCC特征
- 用KMeans聚类区分不同说话人（默认2人，适合连麦PK场景）
- 输出格式：[说话人A] 文本 [说话人B] 文本
"""

import asyncio
import subprocess
import shutil
import numpy as np
from faster_whisper import WhisperModel


class AudioTranscriber:
    def __init__(self, config: dict):
        self.model_size = config.get("whisper_model", "base")
        self.language = config.get("language", "zh")
        self.segment_length = config.get("segment_length", 10)
        self.sample_rate = 16000
        self.model = None
        self._process = None
        self._running = False
        self._log_callback = None

        # 说话人分离配置
        self.enable_diarization = config.get("enable_diarization", True)
        self.num_speakers = config.get("num_speakers", 2)  # 默认2人（连麦PK场景）
        self._speaker_map = {}  # 聚类标签 → 稳定编号（A/B/C）
        self._next_speaker_label = 0
        # 懒加载：librosa首次用才导入（启动快）
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
        """检查FFmpeg是否在PATH中"""
        return shutil.which("ffmpeg") is not None

    def _load_model(self):
        if self.model is None:
            self._log(f"正在加载Whisper模型: {self.model_size}")
            self.model = WhisperModel(
                self.model_size, device="cpu", compute_type="int8"
            )
            self._log("Whisper模型加载完成")

    def _load_librosa(self):
        """懒加载librosa（首次使用时导入，避免启动慢）"""
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
        """从直播流提取音频并实时转录

        Args:
            stream_url: 直播流地址（m3u8/flv等）
            cookie_str: 用于鉴权的Cookie字符串
            callback: 转录文本回调 async (text) -> None
        """
        self._running = True

        # 检查FFmpeg
        if not self.is_ffmpeg_available():
            self._log("错误：FFmpeg未安装或不在PATH中，语音转录不可用")
            self._log("请从 https://ffmpeg.org/download.html 下载并添加到系统PATH")
            await callback("[FFmpeg未安装，语音转录不可用]")
            return

        self._log(f"开始转录，流地址: {stream_url[:80]}...")
        self._load_model()
        if self.enable_diarization:
            self._load_librosa()

        cmd = ["ffmpeg", "-y", "-loglevel", "warning"]
        # 传入Cookie和Referer用于鉴权
        headers = ""
        if cookie_str:
            headers += f"Cookie: {cookie_str}\r\n"
        headers += f"Referer: https://live.kuaishou.com\r\n"
        headers += "User-Agent: Mozilla/5.0\r\n"
        if headers:
            cmd += ["-headers", headers]
        cmd += [
            "-re",  # 按实时速度读取（输入选项，必须在-i之前）
            "-i", stream_url,
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "-f", "s16le",
            "-",  # 输出到stdout
        ]

        self._log("启动FFmpeg进程...")

        # 先探测流信息，确认有音频流
        probe_cmd = [
            "ffmpeg", "-hide_banner", "-i", stream_url,
            "-headers", f"Referer: https://live.kuaishou.com\r\nUser-Agent: Mozilla/5.0\r\n",
        ]
        try:
            probe = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=10
            )
            # ffmpeg -i 不带输出会报错退出，但stderr里有流信息
            probe_err = probe.stderr
            self._log(f"流探测信息:\n{probe_err[:800]}")
            if "Audio:" not in probe_err:
                self._log("错误：该直播流没有音频流！可能纯视频或游戏直播未开麦")
                await callback("[该直播流无音频流，语音转录不可用]")
                return
        except subprocess.TimeoutExpired:
            self._log("流探测超时，继续尝试启动FFmpeg...")
        except Exception as e:
            self._log(f"流探测失败: {e}，继续尝试启动FFmpeg...")

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except Exception as e:
            self._log(f"FFmpeg启动失败: {e}")
            return

        # 等待一下看FFmpeg是否立即出错
        await asyncio.sleep(2)
        if self._process.poll() is not None:
            stderr = self._process.stderr.read().decode("utf-8", errors="replace")
            self._log(f"FFmpeg进程立即退出，错误: {stderr[:500]}")
            return

        self._log("FFmpeg已启动，等待音频数据...")

        # 每个segment对应的字节数：采样率 * 2字节(16bit) * 声道数(1) * 秒数
        chunk_size = self.sample_rate * 2 * self.segment_length
        self._log(f"每个音频块大小: {chunk_size} 字节 ({self.segment_length}秒)")

        # 重要：阻塞I/O（stdout.read）必须在独立线程，不能在asyncio loop线程
        # 否则会冻结event loop，导致run_coroutine_threadsafe投递的callback永远不执行
        import queue
        import threading
        audio_queue = queue.Queue(maxsize=2)  # 最多缓冲2块，超出丢弃旧的
        loop = asyncio.get_event_loop()
        stop_event = threading.Event()

        def transcribe_worker():
            """转录工作线程：从队列取音频块转录，调用callback"""
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
                        # 把callback投递回asyncio loop线程执行
                        asyncio.run_coroutine_threadsafe(callback(text), loop)
                except Exception as e:
                    print(f"[AudioTranscriber] worker转录异常: {e}")

        def read_worker():
            """读取工作线程：阻塞读FFmpeg stdout，避免冻结asyncio loop"""
            read_count = 0
            while not stop_event.is_set() and self._running:
                raw_audio = self._process.stdout.read(chunk_size)
                read_count += 1
                if not raw_audio or len(raw_audio) < chunk_size // 4:
                    # 数据不足，等待重试
                    if self._process.poll() is not None:
                        # 进程已退出，读取stderr
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
                        self._log(f"等待音频数据... (已读取{read_count}次，上次得到{len(raw_audio) if raw_audio else 0}字节)")
                    stop_event.wait(1)
                    continue

                if read_count == 1:
                    self._log(f"第一次收到音频数据: {len(raw_audio)} 字节")

                # 转 float32 numpy 数组
                audio_np = (
                    np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )

                # 投入队列，满则丢弃最旧的（保证处理最新内容，避免延迟堆积）
                try:
                    audio_queue.put_nowait(audio_np)
                except queue.Full:
                    # 队列满，说明转录跟不上，丢弃最旧的
                    try:
                        audio_queue.get_nowait()
                        audio_queue.put_nowait(audio_np)
                        print(f"[AudioTranscriber] 转录跟不上实时，丢弃旧块")
                    except queue.Empty:
                        pass

        # 启动两个工作线程
        read_thread = threading.Thread(target=read_worker, daemon=True)
        worker_thread = threading.Thread(target=transcribe_worker, daemon=True)
        read_thread.start()
        worker_thread.start()

        # asyncio loop线程只负责等待停止，不阻塞event loop
        # 这样run_coroutine_threadsafe投递的callback才能正常执行
        try:
            while self._running and read_thread.is_alive():
                await asyncio.sleep(0.5)
        finally:
            stop_event.set()
            # 通知worker退出
            try:
                audio_queue.put_nowait(None)
            except queue.Full:
                pass
            read_thread.join(timeout=3)
            worker_thread.join(timeout=3)

    def _transcribe_with_diarization(self, audio_np: np.ndarray) -> str:
        """带说话人分离的转录"""
        # 注意：此方法在asyncio.to_thread的子线程中运行
        # 用print输出到控制台，_log走GUI回调可能跨线程丢失
        try:
            print(f"[AudioTranscriber] 开始转录，音频长度={len(audio_np)/self.sample_rate:.2f}秒")
            # 先用whisper转录，拿到每个segment的起止时间
            segments, _ = self.model.transcribe(
                audio_np,
                language=self.language,
                vad_filter=True,
                beam_size=1,
                condition_on_previous_text=False,
                initial_prompt="以下是普通话的句子，这是一个直播间的内容，主播正在和观众聊天互动。",
            )
            segments = list(segments)
            print(f"[AudioTranscriber] whisper返回 {len(segments)} 个segment")
            for i, seg in enumerate(segments):
                print(f"[AudioTranscriber]   seg[{i}] start={seg.start:.2f}s end={seg.end:.2f}s text={repr(seg.text[:80])}")
            if not segments:
                # VAD可能过滤掉了所有内容，关闭VAD重试一次
                print("[AudioTranscriber] VAD过滤后无segment，关闭VAD重试...")
                segments, _ = self.model.transcribe(
                    audio_np,
                    language=self.language,
                    vad_filter=False,
                    beam_size=1,
                    condition_on_previous_text=False,
                )
                segments = list(segments)
                print(f"[AudioTranscriber] 关闭VAD后返回 {len(segments)} 个segment")
                for i, seg in enumerate(segments):
                    print(f"[AudioTranscriber]   seg[{i}] start={seg.start:.2f}s end={seg.end:.2f}s text={repr(seg.text[:80])}")
                if not segments:
                    print("[AudioTranscriber] 关闭VAD后仍无segment，返回空")
                    return ""

            # 如果未启用分离 或 librosa不可用 或 音频太短，直接拼接文本
            if not self.enable_diarization or self._librosa is None or len(audio_np) < self.sample_rate:
                parts = [seg.text.strip() for seg in segments if seg.text.strip()]
                result = " ".join(parts)
                print(f"[AudioTranscriber] 普通转录结果: {repr(result[:100])}")
                return result

            # 提取每个segment对应音频片段的MFCC特征，做说话人聚类
            try:
                speaker_labels = self._cluster_segments(audio_np, segments)
            except Exception as e:
                print(f"[AudioTranscriber] 说话人分离失败，回退普通转录: {e}")
                parts = [seg.text.strip() for seg in segments if seg.text.strip()]
                result = " ".join(parts)
                print(f"[AudioTranscriber] 回退转录结果: {repr(result[:100])}")
                return result

            # 按说话人标签拼接
            parts = []
            for seg, label in zip(segments, speaker_labels):
                text = seg.text.strip()
                if not text:
                    continue
                speaker = self._label_to_letter(label)
                parts.append(f"[{speaker}]{text}")
            result = " ".join(parts)
            print(f"[AudioTranscriber] 分离转录结果: {repr(result[:100])}")
            return result

        except Exception as e:
            print(f"[AudioTranscriber] 转录错误: {e}")
            import traceback
            traceback.print_exc()
            # 回退到不带分离的转录
            try:
                segments, _ = self.model.transcribe(
                    audio_np,
                    language=self.language,
                    vad_filter=True,
                    beam_size=1,
                    condition_on_previous_text=False,
                )
                parts = [seg.text.strip() for seg in segments if seg.text.strip()]
                return " ".join(parts)
            except Exception:
                return ""

    def _cluster_segments(self, audio_np: np.ndarray, segments) -> list:
        """对每个segment提取MFCC特征并聚类，返回每个segment的说话人标签"""
        librosa = self._librosa
        from sklearn.cluster import KMeans

        features = []
        valid_segments = []

        for seg in segments:
            # 计算segment在音频中的起止样本
            start = int(seg.start * self.sample_rate)
            end = int(seg.end * self.sample_rate)
            # 边界保护
            start = max(0, min(start, len(audio_np) - 1))
            end = max(start + 1, min(end, len(audio_np)))

            seg_audio = audio_np[start:end]
            # 片段太短无法提取可靠特征，跳过（后面用前一标签填充）
            if len(seg_audio) < self.sample_rate * 0.3:  # <0.3秒
                features.append(None)
                valid_segments.append(None)
                continue

            # 提取MFCC特征（13维+一阶差分），取均值作为该片段的说话人特征
            mfcc = librosa.feature.mfcc(
                y=seg_audio, sr=self.sample_rate, n_mfcc=13
            )
            # 加上delta特征增强区分度
            delta = librosa.feature.delta(mfcc)
            feat = np.concatenate([mfcc.mean(axis=1), delta.mean(axis=1)])
            features.append(feat)
            valid_segments.append(seg)

        # 有效特征数量
        valid_feats = [f for f in features if f is not None]
        if len(valid_feats) < self.num_speakers:
            # 有效片段太少，无法聚类，全部归为同一说话人
            return [0] * len(segments)

        # KMeans聚类
        X = np.array(valid_feats)
        n_clusters = min(self.num_speakers, len(valid_feats))
        kmeans = KMeans(n_clusters=n_clusters, n_init=3, random_state=0)
        valid_labels = kmeans.fit_predict(X)

        # 把标签填回（None的位置用前一有效标签填充）
        labels = []
        valid_idx = 0
        last_label = 0
        for f in features:
            if f is None:
                labels.append(last_label)
            else:
                label = int(valid_labels[valid_idx])
                labels.append(label)
                last_label = label
                valid_idx += 1
        return labels

    def _label_to_letter(self, label: int) -> str:
        """聚类数字标签 → 稳定字母（A/B/C...），跨音频块保持一致"""
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
