"""核心引擎：协调弹幕采集、语音转录、LLM评论生成、评论发送"""

import asyncio
import json
import random
import yaml
from pathlib import Path
from src.audio import AudioTranscriber
from src.danmu import DanmuReader
from src.llm_client import LLMClient
from src.sender import CommentSender

# Cookie本地存储路径
COOKIE_FILE = Path(__file__).parent.parent / "cookies.json"


class LiveCompanionEngine:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()

        # 状态
        self.is_running = False
        self.danmu_list = []       # 最近的弹幕文本（用于LLM上下文）
        self.transcription = ""    # 最近的语音转录（保留最新一条，兼容旧逻辑）
        self.transcription_history = []  # 转录历史列表，用于评论循环检测新内容
        self.last_comment = ""
        self._stream_url = None

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

    def _load_config(self) -> dict:
        config_path = Path(self.config_path)
        # 如果 config.yaml 不存在，从示例文件复制
        if not config_path.exists():
            example_path = config_path.parent / "config.example.yaml"
            if example_path.exists():
                import shutil
                shutil.copy2(example_path, config_path)
                print(f"[Engine] 已从 config.example.yaml 创建 config.yaml，请修改 API 密钥后重新启动")
            else:
                raise FileNotFoundError("config.yaml 不存在，请复制 config.example.yaml 为 config.yaml 并填写配置")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

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

    async def start(self):
        """启动直播伴侣"""
        if self.is_running:
            return

        self.is_running = True
        self._emit_status("正在初始化...")

        try:
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
            # 只在用户进入直播间后才记录流地址
            stream_url = None
            in_live_room = False  # 标记是否已进入直播间

            # 必须排除的API接口关键词（这些不是视频流）
            api_keywords = [
                "websocketinfo", "live_api", "/api/", "graphql",
                ".json", ".js", ".css", ".png", ".jpg", ".webp",
                ".woff", ".svg", ".gif",
            ]

            def is_stream_url(url: str) -> bool:
                url_lower = url.lower()
                # 1. 先排除API接口和静态资源
                for kw in api_keywords:
                    if kw in url_lower:
                        return False
                # 2. 严格扩展名匹配（真正的流媒体文件）
                for ext in [".m3u8", ".flv", ".ts", ".mp4", ".m4s", ".mpd"]:
                    if url_lower.endswith(ext) or f"{ext}?" in url_lower:
                        return True
                return False

            def is_stream_content_type(ctype: str) -> bool:
                """通过Content-Type判断是否是视频流"""
                if not ctype:
                    return False
                ctype_lower = ctype.lower()
                return any(k in ctype_lower for k in [
                    "video/", "mpegurl", "mp2t", "octet-stream"
                ])

            async def handle_response(response):
                nonlocal stream_url
                url = response.url
                if not in_live_room:
                    return
                try:
                    ctype = response.headers.get("content-type", "")
                    # 调试：打印视频类响应
                    if is_stream_content_type(ctype):
                        print(f"[Core-Stream] 视频响应: {url[:120]} type={ctype}")
                        # 通过Content-Type + 排除API 来识别流地址
                        if stream_url is None and not any(kw in url.lower() for kw in api_keywords):
                            stream_url = url
                            self._emit_status(f"已检测到直播流: {url[:60]}...")
                            return
                except Exception:
                    pass
                if stream_url is None and is_stream_url(url):
                    stream_url = url
                    self._emit_status(f"已检测到直播流: {url[:60]}...")

            # 同时拦截请求
            async def handle_request(request):
                nonlocal stream_url
                url = request.url
                if not in_live_room:
                    return
                # 调试：进入直播间后打印疑似流请求（严格扩展名匹配）
                if is_stream_url(url):
                    print(f"[Core-Stream] 疑似流请求: {url[:120]}")
                if stream_url is None and is_stream_url(url):
                    stream_url = url
                    self._emit_status(f"已检测到直播流: {url[:60]}...")

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
        """音频转录循环"""
        if not self._stream_url:
            self._emit_status("未获取到直播流地址，语音识别不可用")
            return

        async def on_transcription(text):
            self.transcription = text
            self.transcription_history.append(text)
            # 保留最近20条，避免无限增长
            if len(self.transcription_history) > 20:
                self.transcription_history = self.transcription_history[-20:]
            if self.on_transcription:
                self.on_transcription(text)

        # 设置音频模块的日志回调
        self._transcriber.set_log_callback(self._emit_status)

        try:
            await self._transcriber.start(self._stream_url, "", on_transcription)
        except Exception as e:
            self._emit_error(f"音频转录异常: {e}")

    async def _run_comment_loop(self):
        """主评论生成与发送循环"""
        sender_config = self.config.get("sender", {})
        min_interval = sender_config.get("min_interval", 20)
        max_interval = sender_config.get("max_interval", 50)

        # 等待初始数据积累
        await asyncio.sleep(15)

        # 用于检测上下文是否有更新 + 评论去重
        last_danmu_count = 0
        last_transcription = ""
        last_transcription_history_len = 0  # 追踪转录历史列表长度
        recent_comments = []  # 最近发送过的评论（用于去重）
        max_recent = 15

        while self.is_running:
            try:
                interval = random.uniform(min_interval, max_interval)
                await asyncio.sleep(interval)

                if not self.is_running:
                    break

                # 构建上下文：用最近几条转录拼接，提供更完整的语境
                # self.transcription_history 最近 N 条转录
                recent_transcripts = self.transcription_history[-5:]
                context = " ".join(recent_transcripts).strip()
                danmu_context = "\n".join(self.danmu_list[-10:])

                # 检测上下文是否有更新
                danmu_changed = len(self.danmu_list) != last_danmu_count
                transcription_changed = (
                    len(self.transcription_history) != last_transcription_history_len
                    or context != last_transcription
                )

                print(f"[CommentLoop] 转录={repr(context[:50])} 弹幕数={len(self.danmu_list)} 弹幕变化={danmu_changed} 转录变化={transcription_changed}")

                if not context and not danmu_context:
                    self._emit_status("无上下文数据，跳过评论生成")
                    continue

                # 如果弹幕和转录都没变化，说明没有新内容，跳过避免重复
                if not danmu_changed and not transcription_changed:
                    self._emit_status("无新内容，跳过评论生成（避免重复）")
                    continue

                # LLM生成评论
                self._emit_status("正在生成评论...")
                comment = await asyncio.to_thread(
                    self._llm.generate_comment, context, danmu_context, recent_comments
                )

                if not comment:
                    self._emit_status("LLM未生成评论，跳过")
                    continue

                # 评论去重检查：与最近发送过的评论比对
                if comment in recent_comments:
                    self._emit_status(f"评论与最近发送过的重复，跳过: {comment}")
                    # 仍然记录上下文状态，避免下一轮又生成同样的
                    last_danmu_count = len(self.danmu_list)
                    last_transcription = context
                    last_transcription_history_len = len(self.transcription_history)
                    continue

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
                    # 更新上下文状态
                    last_danmu_count = len(self.danmu_list)
                    last_transcription = context
                    last_transcription_history_len = len(self.transcription_history)
                else:
                    self._emit_error("评论发送失败")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._emit_error(f"评论循环错误: {e}")
                await asyncio.sleep(10)

    async def stop(self):
        """停止直播伴侣"""
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
