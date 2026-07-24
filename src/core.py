"""核心引擎：协调弹幕采集、语音转录、LLM评论生成、评论发送"""

import asyncio
import base64
import json
import os
import random
import subprocess
import time
import yaml
from pathlib import Path
from src.audio import AudioTranscriber
from src.danmu import DanmuReader
from src.llm_client import LLMClient
from src.sender import CommentSender
from src import APP_DIR, DATA_DIR

# Cookie本地存储路径（保存在用户数据目录）
COOKIE_FILE = DATA_DIR / "cookies.json"


class LiveCompanionEngine:
    def __init__(self, config_path: str = None):
        # 默认配置路径：保存在用户数据目录
        if config_path is None:
            config_path = str(DATA_DIR / "config.yaml")
        self.config_path = config_path
        self.config = self._load_config()

        # 状态
        self.is_running = False
        self.danmu_list = []       # 最近的弹幕文本（用于LLM上下文）
        self.transcription = ""    # 最近的语音转录（保留最新一条，兼容旧逻辑）
        self.transcription_history = []  # 转录历史列表，用于评论循环检测新内容
        self.last_comment = ""
        self._stream_url = None
        self._live_context = ""    # 直播间上下文（主播名、分类等）

        # 模块实例
        self._sender = None
        self._danmu_reader = None
        self._transcriber = None
        self._llm = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        # GUI回调
        self.on_danmu = None          # (username, content) -> None
        self.on_transcription = None  # (text) -> None
        self.on_comment = None        # (text) -> None
        self.on_status = None         # (msg) -> None
        self.on_error = None          # (msg) -> None
        self.on_room_switch = None    # () -> None  切换直播间时通知GUI清除记录

    def _load_config(self) -> dict:
        config_path = Path(self.config_path)
        # 如果 config.yaml 不存在，从示例文件复制
        if not config_path.exists():
            # exe模式下 config.example.yaml 可能在 _internal 子目录
            example_path = APP_DIR / "config.example.yaml"
            if not example_path.exists():
                example_path = APP_DIR / "_internal" / "config.example.yaml"
            if example_path.exists():
                try:
                    import shutil
                    shutil.copy2(example_path, config_path)
                    print(f"[Engine] 已从 config.example.yaml 创建 config.yaml，请修改 API 密钥后重新启动")
                except Exception as e:
                    print(f"[Engine] 复制示例配置失败: {e}，使用空配置")
            else:
                print(f"[Engine] config.example.yaml 未找到，使用空配置")
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config if config else {}
        except Exception as e:
            print(f"[Engine] 加载配置失败: {e}，使用空配置")
            return {}

    def save_config(self, config: dict = None):
        if config:
            self.config = config
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)

    async def _load_saved_cookies(self) -> list:
        """从本地文件加载已保存的Cookie"""
        if COOKIE_FILE.exists():
            try:
                with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    async def _save_cookies(self):
        """保存当前浏览器的Cookie到本地"""
        if self._context:
            try:
                cookies = await self._context.cookies()
                with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Engine] 保存Cookie失败: {e}")

    async def _wait_for_login(self):
        """等待用户在浏览器中完成登录（扫码/手机号）"""
        self._emit_status("请在浏览器中登录快手账号...")

        # 轮询检查是否已登录
        for _ in range(300):  # 最多等待5分钟
            if not self.is_running:
                return False
            try:
                logged_in = await self._page.evaluate("""
                    () => {
                        const avatar = document.querySelector('[class*="avatar"]');
                        const loginBtn = document.querySelector('[class*="login-btn"], [class*="LoginBtn"]');
                        if (avatar && avatar.offsetParent !== null) return true;
                        if (loginBtn && loginBtn.offsetParent === null) return true;
                        return document.cookie.includes('userId') || document.cookie.includes('kuaishou.live.web_st');
                    }
                """)
                if logged_in:
                    self._emit_status("登录成功！")
                    await self._save_cookies()
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)

        self._emit_error("登录超时，请重试")
        return False

    def _ensure_chromium(self):
        """检测chromium浏览器是否存在，不存在则自动下载安装"""
        # 使用与main.py中一致的PLAYWRIGHT_BROWSERS_PATH
        browsers_path = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH",
                                            os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")))

        try:
            # 查找已安装的chromium
            if browsers_path.exists():
                for item in browsers_path.iterdir():
                    if item.name.startswith("chromium-"):
                        chrome_exe = item / "chrome-win64" / "chrome.exe"
                        if chrome_exe.exists():
                            print(f"[Engine] 找到chromium: {chrome_exe}")
                            return True

            # 未找到chromium，自动安装
            self._emit_status("首次运行，正在下载chromium浏览器（约150MB）...")
            print(f"[Engine] 未找到chromium，正在安装到: {browsers_path}")

            from playwright._impl._driver import compute_driver_executable
            node_exe, cli_js = compute_driver_executable()

            result = subprocess.run(
                [node_exe, cli_js, "install", "chromium"],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                print("[Engine] chromium下载安装成功")
                self._emit_status("chromium浏览器安装完成")
                return True
            else:
                print(f"[Engine] chromium安装失败: {result.stderr}")
                self._emit_error("chromium浏览器下载失败，请检查网络")
                return False

        except Exception as e:
            print(f"[Engine] 检测chromium异常: {e}")
            self._emit_error(f"chromium检测异常: {e}")
            return False

    async def start(self):
        """启动旁白"""
        if self.is_running:
            return

        self.is_running = True
        self._emit_status("正在初始化...")

        try:
            # 检测并自动安装chromium浏览器
            if not self._ensure_chromium():
                self.is_running = False
                return

            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            )

            self._page = await self._context.new_page()

            # 注入反检测脚本 + WebSocket hook（必须在页面导航前注入）
            from src.danmu import WS_HOOK_JS
            await self._page.add_init_script(f"""
                Object.defineProperties(navigator, {{
                    webdriver: {{ get: () => undefined }}
                }});
                ({WS_HOOK_JS})();
            """)

            # 立即创建弹幕采集器（必须在页面导航前注册WebSocket监听器）
            self._danmu_reader = DanmuReader(self._page)

            # 尝试加载已保存的Cookie
            saved_cookies = await self._load_saved_cookies()
            if saved_cookies:
                await self._context.add_cookies(saved_cookies)
                self._emit_status("已加载保存的登录状态")

            # 先导航到快手检查登录状态
            needs_login = True
            try:
                await self._page.goto(
                    "https://live.kuaishou.com",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                logged_in = await self._page.evaluate("""
                    () => document.cookie.includes('userId') ||
                          document.cookie.includes('kuaishou.live.web_st')
                """)
                if logged_in:
                    needs_login = False
                    self._emit_status("登录状态有效")
            except Exception:
                pass

            # 如果未登录，等待用户扫码
            if needs_login:
                success = await self._wait_for_login()
                if not success:
                    await self.stop()
                    return

            # 告诉用户进入直播间
            self._emit_status("请在浏览器中进入目标直播间...")

            # 拦截网络请求获取直播流URL
            # 基于实际抓包测试确认的快手直播流特征：
            #   URL: https://tx-origin.pull.yximgs.com/gifshow/{streamId}_{quality}.flv?txSecret=xxx&txTime=6
            #   Content-Type: video/x-flv
            #   CDN域名: *.pull.yximgs.com
            # 需要排除的非流URL：
            #   live*.static.yximgs.com — 封面截图（application/octet-stream）
            #   ntp.nc.gifshow.com — NTP时间同步
            stream_url = None
            in_live_room = False

            def is_real_stream(url: str, ctype: str = "") -> bool:
                """准确判断是否是快手直播流（基于抓包测试确认）"""
                url_lower = url.lower()
                ctype_lower = ctype.lower() if ctype else ""

                # 排除非流域名
                if "static.yximgs.com" in url_lower:
                    return False  # 封面截图
                if "ntp.nc.gifshow.com" in url_lower:
                    return False  # NTP时间同步
                if any(kw in url_lower for kw in [
                    "websocketinfo", "live_api", "/api/", "graphql",
                    ".json", ".js", ".css", ".png", ".jpg", ".webp",
                    ".woff", ".svg", ".gif",
                ]):
                    return False

                # 条件1: Content-Type 是 video/x-flv（最准确）
                if "video/x-flv" in ctype_lower:
                    return True
                # 条件2: Content-Type 是其他视频类型且包含flv
                if "video/" in ctype_lower and ".flv" in url_lower:
                    return True
                # 条件3: 快手CDN域名 + flv + 鉴权参数
                if "pull.yximgs.com" in url_lower and ".flv" in url_lower:
                    return True
                # 条件4: 通用流扩展名 + video Content-Type
                if any(ext in url_lower for ext in [".m3u8", ".flv", ".ts"]) and "video" in ctype_lower:
                    return True

                return False

            async def handle_response(response):
                nonlocal stream_url
                url = response.url
                if not in_live_room or stream_url is not None:
                    return
                try:
                    ctype = response.headers.get("content-type", "")
                    # 调试：打印含flv/video/video-x-flv的响应
                    if ".flv" in url.lower() or "video/" in ctype.lower() or "yximgs" in url.lower():
                        print(f"[Core-Stream] 响应: {url[:120]} ctype={ctype}")
                    if is_real_stream(url, ctype):
                        stream_url = url
                        self._emit_status(f"已检测到直播流: {url[:80]}...")
                except Exception as e:
                    print(f"[Core-Stream] handle_response异常: {e}")

            async def handle_request(request):
                nonlocal stream_url
                url = request.url
                if not in_live_room or stream_url is not None:
                    return
                # 调试：打印含flv/yximgs的请求
                if ".flv" in url.lower() or "yximgs" in url.lower():
                    print(f"[Core-Stream] 请求: {url[:120]}")
                # 请求阶段没有Content-Type，只靠URL特征匹配
                if is_real_stream(url):
                    stream_url = url
                    self._emit_status(f"已检测到直播流: {url[:80]}...")

            self._page.on("response", handle_response)
            self._page.on("request", handle_request)

            # 等待用户进入直播间，最多等待10分钟
            last_url = ""
            for _ in range(600):
                if not self.is_running:
                    return
                current_url = self._page.url
                # URL变化时打印日志，方便调试
                if current_url != last_url:
                    print(f"[Core] URL变化: {current_url}")
                    last_url = current_url
                # 放宽检测：只要不在首页/搜索页，就认为可能进入了直播间
                # 真正的判断依赖直播流URL是否出现
                if ("live.kuaishou.com" in current_url and
                    not current_url.endswith("live.kuaishou.com/") and
                    not current_url.endswith("live.kuaishou.com") and
                    "/search" not in current_url):
                    if not in_live_room:
                        in_live_room = True
                        self._emit_status("已进入直播间，等待直播流...")
                if stream_url:
                    # 直播流检测到后再截图，确保画面已开始播放
                    self._emit_status("直播流已检测到，等待画面加载...")
                    await asyncio.sleep(5)  # 额外等待5秒确保视频画面渲染
                    asyncio.create_task(self._fetch_live_room_info())
                    break
                await asyncio.sleep(1)

            self._page.remove_listener("response", handle_response)
            self._page.remove_listener("request", handle_request)

            # 保存Cookie以备下次使用
            await self._save_cookies()

            self._stream_url = stream_url

            if not self._stream_url:
                self._emit_status("未检测到直播流，语音识别不可用（弹幕和评论仍可工作）")
            else:
                self._emit_status("直播流已就绪")

            # 初始化各模块
            self._sender = CommentSender(
                self._page, self.config.get("sender", {})
            )
            self._transcriber = AudioTranscriber(
                self.config.get("audio", {})
            )
            self._llm = LLMClient(self.config.get("llm", {}))
            # 如果已经抓取到直播间信息，注入到LLM
            self._inject_live_context_to_llm()

            # 启动各任务
            tasks = []

            if self.config.get("danmu", {}).get("enabled", True):
                tasks.append(asyncio.create_task(self._run_danmu()))

            tasks.append(asyncio.create_task(self._run_audio()))
            tasks.append(asyncio.create_task(self._run_comment_loop()))

            self._emit_status("运行中")

            await asyncio.gather(*tasks)

        except Exception as e:
            self._emit_error(f"启动失败: {e}")
            await self.stop()

    async def _run_danmu(self):
        """弹幕采集循环"""
        async def on_danmu(username, content):
            self.danmu_list.append(f"{username}: {content}" if username else content)
            if len(self.danmu_list) > 50:
                self.danmu_list = self.danmu_list[-30:]
            if self.on_danmu:
                self.on_danmu(username, content)

        await self._danmu_reader.start(on_danmu)

    async def _run_audio(self):
        """音频转录循环（持久监听直播流变化，自动切换）"""
        async def on_transcription(text):
            self.transcription = text
            self.transcription_history.append(text)
            if len(self.transcription_history) > 20:
                self.transcription_history = self.transcription_history[-20:]
            if self.on_transcription:
                self.on_transcription(text)

        # 设置音频模块的日志回调
        self._transcriber.set_log_callback(self._emit_status)

        # 使用dict作为可变容器，在闭包中共享最新流URL
        latest_stream = {"url": self._stream_url}

        def is_real_stream(url: str, ctype: str = "") -> bool:
            """准确判断是否是快手直播流（基于抓包测试确认）"""
            url_lower = url.lower()
            ctype_lower = ctype.lower() if ctype else ""
            if "static.yximgs.com" in url_lower:
                return False
            if "ntp.nc.gifshow.com" in url_lower:
                return False
            if any(kw in url_lower for kw in [
                "websocketinfo", "live_api", "/api/", "graphql",
                ".json", ".js", ".css", ".png", ".jpg", ".webp",
                ".woff", ".svg", ".gif",
            ]):
                return False
            if "video/x-flv" in ctype_lower:
                return True
            if "video/" in ctype_lower and ".flv" in url_lower:
                return True
            if "pull.yximgs.com" in url_lower and ".flv" in url_lower:
                return True
            if any(ext in url_lower for ext in [".m3u8", ".flv", ".ts"]) and "video" in ctype_lower:
                return True
            return False

        # 注册持久的网络监听器（整个运行期间都活跃，不会错过切换时的流请求）
        async def handle_response(response):
            try:
                url = response.url
                if url == latest_stream["url"]:
                    return
                ctype = response.headers.get("content-type", "")
                if is_real_stream(url, ctype):
                    self._emit_status(f"监听到新直播流: {url[:80]}...")
                    latest_stream["url"] = url
                    self._stream_url = url
            except Exception:
                pass

        async def handle_request(request):
            url = request.url
            if url == latest_stream["url"]:
                return
            if is_real_stream(url):
                self._emit_status(f"监听到新直播流请求: {url[:80]}...")
                latest_stream["url"] = url
                self._stream_url = url

        if self._page:
            self._page.on("response", handle_response)
            self._page.on("request", handle_request)

        try:
            while self.is_running:
                current_url = latest_stream["url"]
                if not current_url:
                    # 打印页面URL帮助调试
                    page_url = self._page.url if self._page else "无页面"
                    self._emit_status(f"未获取到直播流地址，等待进入直播间... (页面: {page_url[-40:]})")
                    print(f"[Core-Stream] 等待流中，latest_stream=None, 页面URL={page_url}")
                    await asyncio.sleep(5)
                    continue

                # 启动转录任务（非阻塞）
                transcription_task = asyncio.create_task(
                    self._transcriber.start(current_url, "", on_transcription)
                )

                # 等待转录完成或检测到新流URL
                while self.is_running:
                    try:
                        await asyncio.wait_for(asyncio.shield(transcription_task), timeout=2.0)
                        break  # 转录完成（ffmpeg退出）
                    except asyncio.TimeoutError:
                        # 转录还在进行，检查是否有新流URL
                        if latest_stream["url"] != current_url:
                            self._emit_status("检测到直播流切换，清除旧数据并重启...")
                            # 清除旧房间的弹幕和转录数据，避免跨房间污染
                            self.danmu_list.clear()
                            self.transcription = ""
                            self.transcription_history.clear()
                            self.last_comment = ""
                            self._live_context = ""
                            # 清除LLM对话历史，避免旧直播间上下文干扰
                            if self._llm:
                                self._llm.clear_history()
                            # 通知GUI清除显示记录
                            if self.on_room_switch:
                                self.on_room_switch()
                            # 先停止旧的转录进程
                            self._transcriber.stop()
                            try:
                                await transcription_task
                            except Exception:
                                pass
                            # 不清除新流URL！监听器已更新为新直播间流URL
                            # 等待新画面加载后再截图
                            await asyncio.sleep(5)
                            asyncio.create_task(self._fetch_live_room_info())
                            break

                if not self.is_running:
                    break

                # 如果是正常退出（非切换），短暂等待后用当前URL重启
                await asyncio.sleep(1)
        finally:
            if self._page:
                try:
                    self._page.remove_listener("response", handle_response)
                    self._page.remove_listener("request", handle_request)
                except Exception:
                    pass

    async def _run_comment_loop(self):
        """主评论生成与发送循环"""
        sender_config = self.config.get("sender", {})
        min_interval = sender_config.get("min_interval", 20)
        max_interval = sender_config.get("max_interval", 50)

        # 等待初始数据积累
        await asyncio.sleep(15)

        # 用于评论去重
        recent_comments = []  # 最近发送过的评论（用于去重）
        max_recent = 15

        # 水弹幕池：15%概率直接发，不经过LLM
        water_comments = ["6", "？", "hhh", "来了", "。。。", "啊这", "可以", "确实"]

        while self.is_running:
            try:
                interval = random.uniform(min_interval, max_interval)
                await asyncio.sleep(interval)

                if not self.is_running:
                    break

                # 构建上下文：用最近几条转录拼接，提供更完整的语境
                recent_transcripts = self.transcription_history[-5:]
                context = " ".join(recent_transcripts).strip()
                danmu_context = "\n".join(self.danmu_list[-10:])

                print(f"[CommentLoop] 转录={repr(context[:50])} 弹幕数={len(self.danmu_list)}")

                if not context and not danmu_context:
                    self._emit_status("无上下文数据，跳过评论生成")
                    continue

                # === 真人特征1：水弹幕（15%概率跳过LLM直接发）===
                if random.random() < 0.15:
                    comment = random.choice(water_comments)
                    self._emit_status(f"水弹幕: {comment}")
                else:
                    # === 真人特征2：长度随机分布 ===
                    # 30%短(1-3字)，50%中(4-8字)，20%长(9-15字)
                    rand_len = random.random()
                    if rand_len < 0.3:
                        dynamic_max_tokens = 10
                    elif rand_len < 0.8:
                        dynamic_max_tokens = 20
                    else:
                        dynamic_max_tokens = 35
                    # 临时覆盖LLM的max_tokens
                    original_max_tokens = self._llm.max_tokens
                    self._llm.max_tokens = dynamic_max_tokens

                    # LLM生成评论
                    self._emit_status("正在生成评论...")
                    comment = await asyncio.to_thread(
                        self._llm.generate_comment, context, danmu_context, recent_comments
                    )
                    # 恢复原始max_tokens
                    self._llm.max_tokens = original_max_tokens

                    if not comment:
                        self._emit_status("LLM未生成评论，跳过")
                        continue

                # 评论去重检查：与最近发送过的评论比对
                if comment in recent_comments:
                    self._emit_status(f"评论与最近发送过的重复，跳过: {comment}")
                    continue

                # === 真人特征3：随机加语气词后缀（30%概率）===
                if random.random() < 0.3:
                    suffixes = ["啊", "吧", "呢", "hhh", "？", "。。。", "！"]
                    comment += random.choice(suffixes)

                self.last_comment = comment
                if self.on_comment:
                    self.on_comment(comment)

                # 发送评论
                success = await self._sender.send_comment(comment)
                if success:
                    self._emit_status(f"已发送评论: {comment}")
                    # 记录已发送评论用于去重
                    recent_comments.append(comment)
                    if len(recent_comments) > max_recent:
                        recent_comments = recent_comments[-max_recent:]
                else:
                    self._emit_error("评论发送失败")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._emit_error(f"评论循环错误: {e}")
                await asyncio.sleep(10)

    async def _fetch_live_room_info(self):
        """从快手直播间页面抓取信息（截图+DOM双保险），注入到LLM上下文"""
        try:
            # 等待页面加载完成（视频画面渲染需要时间）
            await asyncio.sleep(5)
            if not self._page or self._page.is_closed():
                return

            # ── 方案1: 截图识别（如果启用）──
            vision_desc = ""
            vision_config = self.config.get("vision", {})
            if vision_config.get("enabled", True):
                try:
                    vision_desc = await self._screenshot_and_recognize()
                except Exception as e:
                    import traceback
                    err_detail = traceback.format_exc()
                    print(f"[Core] 截图识别失败: {e}\n{err_detail}")
                    self._emit_status(f"截图识别异常: {type(e).__name__}: {e}")

            # ── 方案2: DOM抓取（兜底/补充）──
            dom_info = await self._fetch_dom_info()

            # ── 合并结果 ──
            parts = []
            if dom_info.get("streamer"):
                parts.append(f"主播：{dom_info['streamer']}")
            if dom_info.get("category"):
                parts.append(f"直播分类：{dom_info['category']}")
            if vision_desc:
                parts.append(f"直播画面描述：{vision_desc}")

            if parts:
                self._live_context = "，".join(parts)
                self._emit_status(f"直播间信息：{self._live_context}")
                self._inject_live_context_to_llm()
            else:
                self._emit_status("未能获取直播间分类信息")

        except Exception as e:
            print(f"[Core] 获取直播间信息失败: {e}")

    async def _screenshot_and_recognize(self) -> str:
        """截取直播画面并调用视觉模型识别直播类型"""
        vision_config = self.config.get("vision", {})
        if not self._page or self._page.is_closed():
            return ""

        # 截图：优先截取视频播放器区域，避免截到侧边栏聊天区
        self._emit_status("正在截取直播画面...")
        screenshot_bytes = None

        # 尝试定位视频播放器元素（含快手专属选择器）
        player_selectors = [
            'video',                    # 原生video标签
            '#player video',            # 快手播放器
            '.live-player',             # 快手播放器容器
            '.player-container',        # 通用播放器容器
            '[class*="player"] video',  # player类下的video
            '[class*="video-wrap"] video',  # 视频包裹
            '[class*="player"]',        # 任何player类元素
            'canvas',                   # 部分直播用canvas渲染
        ]

        # 先等待视频开始播放（最多等8秒）
        try:
            for _ in range(8):
                video_ready = await self._page.evaluate("""() => {
                    const v = document.querySelector('video');
                    if (v && v.readyState >= 2 && v.videoWidth > 0) return true;
                    return false;
                }""")
                if video_ready:
                    print("[Core] 视频已就绪，开始截图")
                    self._emit_status("视频已就绪，开始截图")
                    break
                await asyncio.sleep(1)
            else:
                print("[Core] 视频未就绪，仍尝试截图")
                self._emit_status("视频未就绪，仍尝试截图")
        except Exception as e:
            print(f"[Core] 视频就绪检测异常: {e}")
            self._emit_status(f"视频就绪检测异常: {e}")

        for sel in player_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    box = await el.bounding_box()
                    if box and box["width"] > 200 and box["height"] > 150:
                        screenshot_bytes = await el.screenshot(type="jpeg", quality=70)
                        print(f"[Core] 截取播放器元素: {sel}, 尺寸={box['width']:.0f}x{box['height']:.0f}")
                        self._emit_status(f"已截取播放器: {sel} ({box['width']:.0f}x{box['height']:.0f})")
                        break
            except Exception:
                continue

        # 回退：截取页面主体区域（排除侧边栏）
        if not screenshot_bytes:
            # 尝试截取主内容区，避免截到侧边栏文字
            try:
                main_el = await self._page.query_selector('main, [class*="main"], [class*="content"], #app')
                if main_el:
                    screenshot_bytes = await main_el.screenshot(type="jpeg", quality=70)
                    print("[Core] 截取主内容区域")
                    self._emit_status("截取主内容区域")
                else:
                    screenshot_bytes = await self._page.screenshot(type="jpeg", quality=70)
                    print("[Core] 截取整个页面")
                    self._emit_status("截取整个页面")
            except Exception as e:
                print(f"[Core] 主内容区截图失败: {e}，回退整页")
                self._emit_status(f"主内容区截图失败，回退整页: {e}")
                try:
                    screenshot_bytes = await self._page.screenshot(type="jpeg", quality=70)
                except Exception as e2:
                    print(f"[Core] 整页截图也失败: {e2}")
                    self._emit_status(f"截图全部失败: {e2}")
                    return ""

        b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")
        print(f"[Core] 截图完成，大小={len(screenshot_bytes)//1024}KB")
        self._emit_status(f"截图完成 {len(screenshot_bytes)//1024}KB，调用视觉模型...")

        # 调用视觉模型
        provider = vision_config.get("provider", "dashscope")
        api_key = vision_config.get("api_key", "") or self.config.get("llm", {}).get("api_key", "")

        if not api_key:
            print("[Core] 视觉模型API密钥为空，跳过截图识别")
            self._emit_status("视觉模型API密钥为空，跳过识别")
            return ""

        from openai import OpenAI

        if provider == "dashscope":
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        elif provider == "zhipu":
            base_url = "https://open.bigmodel.cn/api/paas/v4"
        else:
            base_url = vision_config.get("base_url", "https://api.openai.com/v1")

        client = OpenAI(api_key=api_key, base_url=base_url)

        # 视觉模型优先级队列：用户在配置里按行填写的模型列表
        # 兼容旧配置: 优先读 models 列表，回退到 model 单字段
        # 若两者都没有，使用智谱三个免费视觉模型作为默认回退链
        DEFAULT_VISION_MODELS = ["glm-4.6v-flash", "glm-4.1v-thinking-flash", "glm-4v-flash"]
        models_list = vision_config.get("models")
        if not models_list or not isinstance(models_list, list):
            single = vision_config.get("model")
            models_list = [single] if single else DEFAULT_VISION_MODELS
        # 去空去重，保持顺序
        seen = set()
        model_fallbacks = []
        for m in models_list:
            m = (m or "").strip()
            if m and m not in seen:
                seen.add(m)
                model_fallbacks.append(m)
        if not model_fallbacks:
            model_fallbacks = DEFAULT_VISION_MODELS

        import re

        def parse_vision_response(msg) -> str:
            """解析视觉模型响应，兼容多种格式"""
            content = msg.content or ""
            rc = getattr(msg, "reasoning_content", "") or ""
            # 格式1: 4.1v-thinking-flash 等，content含<think>..<answer>标签
            answer_match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)
            if answer_match:
                return answer_match.group(1).strip()
            # 格式2: content有内容（可能带换行，如 4.6v-flash）
            if content.strip():
                return content.strip()
            # 格式3: content为空，回退到reasoning_content（思考模型兼容）
            if rc.strip():
                return rc.strip()
            return ""

        # 需要开启 thinking 参数的模型（思考模型列表，content字段可能为空）
        thinking_models = {"glm-4.6v-flash", "glm-4.5v", "glm-4.5v-flash"}

        def call_vision_api():
            last_err = None
            for m in model_fallbacks:
                try:
                    self._emit_status(f"调用视觉模型 {m}...")
                    kwargs = {
                        "model": m,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "image_url",
                                 "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}},
                                {"type": "text",
                                 "text": "看这张直播截图，用一句话概括直播的具体内容，不超过15个字。只输出概括内容本身，不要加任何解释或描述。"},
                            ],
                        }],
                        "max_tokens": 300,
                        "temperature": 0.3,
                    }
                    # 思考模型需要显式开启 thinking 确保 content 字段有输出
                    if m in thinking_models:
                        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

                    response = client.chat.completions.create(**kwargs)
                    result = parse_vision_response(response.choices[0].message)
                    if result:
                        print(f"[Core] 视觉识别成功 ({m}): {result!r}")
                        self._emit_status(f"视觉识别完成 ({m}): {result[:30]}")
                        return result
                    else:
                        print(f"[Core] {m} 返回空，尝试下一个模型")
                        last_err = f"{m}返回空"
                except Exception as e:
                    err_msg = str(e)
                    print(f"[Core] {m} 调用失败: {type(e).__name__}: {err_msg[:80]}")
                    last_err = f"{m}: {type(e).__name__}"
                    # 429限流、余额不足、模型不存在等错误，尝试下一个模型
                    if any(code in err_msg for code in ["429", "1305", "1113", "1211", "400"]):
                        self._emit_status(f"{m} 调用失败，切换下一个模型...")
                        continue
                    raise
            # 所有模型都失败
            raise RuntimeError(f"所有视觉模型均失败，最后错误: {last_err}")

        # 视觉API调用在独立线程，避免阻塞
        try:
            result = await asyncio.to_thread(call_vision_api)
        except Exception as e:
            import traceback
            print(f"[Core] 视觉API调用失败: {e}\n{traceback.format_exc()}")
            self._emit_status(f"视觉API调用失败: {type(e).__name__}: {e}")
            return ""
        # 立即释放截图内存（不落盘，用完即弃）
        del b64_image, screenshot_bytes
        print(f"[Core] 视觉识别最终结果: {result!r}")
        return result

    async def _fetch_dom_info(self) -> dict:
        """从页面DOM抓取主播名和直播分类"""
        if not self._page or self._page.is_closed():
            return {"streamer": "", "category": ""}

        try:
            info = await self._page.evaluate("""
                () => {
                    let streamer = '';
                    let category = '';

                    // 主播名：多种选择器尝试
                    const nameSelectors = [
                        '.user-name', '.live-room-info-name', '.author-name',
                        '[class*="anchor"] [class*="name"]', '[class*="streamer"] [class*="name"]',
                        '.player-room-info .user-name', '.room-info-wrapper .user-name',
                    ];
                    for (const sel of nameSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim()) {
                            streamer = el.textContent.trim();
                            break;
                        }
                    }

                    // 直播分类/标签
                    const tagSelectors = [
                        '.live-room-info-tag', '.tag-item', '.category-name',
                        '[class*="tag"] [class*="name"]', '[class*="category"]',
                        '.player-room-info .tag', '.room-info-wrapper .tag',
                    ];
                    for (const sel of tagSelectors) {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const t = el.textContent.trim();
                            if (t && t.length < 20) {
                                category = (category ? category + '、' : '') + t;
                            }
                        }
                    }

                    // 备选：从页面标题提取
                    if (!streamer) {
                        const title = document.title || '';
                        const match = title.match(/^(.+?)(?:的直播间|[-_|])/);
                        if (match) streamer = match[1].trim();
                    }

                    return { streamer, category };
                }
            """)
            return info
        except Exception as e:
            print(f"[Core] DOM抓取失败: {e}")
            return {"streamer": "", "category": ""}

    def _inject_live_context_to_llm(self):
        """将直播间上下文注入到LLM的system_prompt中"""
        if not self._llm or not self._live_context:
            return
        base_prompt = self.config.get("llm", {}).get("system_prompt", "")
        self._llm.system_prompt = f"[直播间信息：{self._live_context}]\n\n{base_prompt}"

    async def stop(self):
        """停止旁白"""
        self.is_running = False

        if self._transcriber:
            self._transcriber.stop()

        if self._danmu_reader:
            self._danmu_reader.stop()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

        self._emit_status("已停止")

    def _emit_status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def _emit_error(self, msg: str):
        if self.on_error:
            self.on_error(msg)
