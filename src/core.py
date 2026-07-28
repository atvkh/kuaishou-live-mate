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
from src.platforms import create_platform, Platform
from src import APP_DIR, DATA_DIR


class LiveCompanionEngine:
    def __init__(self, config_path: str = None, cookie_file: str = "cookies.json", role: str = "master"):
        # 默认配置路径：保存在用户数据目录
        if config_path is None:
            config_path = str(DATA_DIR / "config.yaml")
        self.config_path = config_path
        self.config = self._load_config()

        # 账号隔离
        self.cookie_file = DATA_DIR / cookie_file  # 每个账号独立 Cookie 文件
        self.role = role  # "master"=主账号(完整功能) / "slave"=副账号(仅发送)
        self.engine_id = role  # 引擎标识，由 EngineManager 设置为账号名

        # 平台抽象：根据 config.platform 创建对应实例（快手/抖音/...）
        platform_name = self.config.get("platform", "kuaishou") if self.config else "kuaishou"
        self.platform: Platform = create_platform(platform_name)

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
        self._owns_browser = True  # 是否自管 browser（False=由 EngineManager 共享）

        # GUI回调
        self.on_danmu = None          # (username, content) -> None
        self.on_transcription = None  # (text) -> None
        self.on_comment = None        # (text) -> None
        self.on_status = None         # (msg) -> None
        self.on_error = None          # (msg) -> None
        self.on_room_switch = None    # () -> None  切换直播间时通知GUI清除记录
        self.on_comment_generated = None  # (comment: str) -> coroutine  主引擎生成评论后由 EngineManager 分配

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
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    async def _save_cookies(self):
        """保存当前浏览器的Cookie到本地"""
        if self._context:
            try:
                cookies = await self._context.cookies()
                with open(self.cookie_file, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Engine] 保存Cookie失败: {e}")

    async def _wait_for_login(self):
        """等待用户在浏览器中完成登录（扫码/手机号）"""
        self._emit_status(f"请在浏览器中登录{self.platform.display_name}账号...")

        # 轮询检查是否已登录（用 platform.check_logged_in，支持 HttpOnly cookie 检测）
        for _ in range(300):  # 最多等待5分钟
            if not self.is_running:
                return False
            try:
                logged_in = await self.platform.check_logged_in(self._page, self._context)
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

    async def start(self, shared_browser=None):
        """启动旁白

        :param shared_browser: 由 EngineManager 传入的共享浏览器实例。
            传入时跳过 playwright/browser 创建，只 new_context（多账号共享一个浏览器进程）。
            不传时（单账号模式）自行 launch。
        """
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

            if shared_browser is not None:
                # 多账号模式：共享浏览器，只创建独立上下文（cookie/storage 完全隔离）
                self._browser = shared_browser
                self._owns_browser = False
            else:
                # 单账号模式：自管 playwright + browser
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                self._owns_browser = True

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
            self._danmu_reader = DanmuReader(self._page, self.platform)

            # 尝试加载已保存的Cookie
            saved_cookies = await self._load_saved_cookies()
            if saved_cookies:
                await self._context.add_cookies(saved_cookies)
                self._emit_status("已加载保存的登录状态")

            # 先导航到平台首页检查登录状态
            needs_login = True
            try:
                await self._page.goto(
                    self.platform.home_url,
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                # 等页面渲染一下，避免 DOM 还没出来就检测
                await asyncio.sleep(2)
                logged_in = await self.platform.check_logged_in(self._page, self._context)
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
            # 直播流特征由 platform.is_real_stream 判断（快手/抖音各不相同）
            stream_url = None
            in_live_room = False

            def is_real_stream(url: str, ctype: str = "") -> bool:
                """判断是否是直播流（委托给平台实现）"""
                return self.platform.is_real_stream(url, ctype)

            async def handle_response(response):
                nonlocal stream_url, in_live_room
                url = response.url
                try:
                    ctype = response.headers.get("content-type", "")
                    # 调试：始终打印含flv/video的响应（不管是否在直播间）
                    if ".flv" in url.lower() or ".m3u8" in url.lower() or "video/" in ctype.lower():
                        print(f"[Core-Stream] 响应: {url[:150]} ctype={ctype}")
                    # 未找到流时，始终尝试匹配（不要求 in_live_room，因为流可能先于 URL 判断到达）
                    if stream_url is not None:
                        return
                    if is_real_stream(url, ctype):
                        stream_url = url
                        self._emit_status(f"已检测到直播流: {url[:80]}...")
                except Exception as e:
                    print(f"[Core-Stream] handle_response异常: {e}")

            async def handle_request(request):
                nonlocal stream_url
                url = request.url
                # 调试：始终打印含flv/m3u8的请求
                if ".flv" in url.lower() or ".m3u8" in url.lower():
                    print(f"[Core-Stream] 请求: {url[:150]}")
                # 未找到流时，始终尝试匹配
                if stream_url is not None:
                    return
                # 请求阶段没有Content-Type，只靠URL特征匹配
                if is_real_stream(url):
                    stream_url = url
                    self._emit_status(f"已检测到直播流: {url[:80]}...")

            self._page.on("response", handle_response)
            self._page.on("request", handle_request)

            # 等待用户进入直播间，最多等待10分钟
            import re as _re
            room_pattern = _re.compile(self.platform.room_url_pattern)
            last_url = ""
            last_page_count = 1
            for _ in range(600):
                if not self.is_running:
                    return

                # ── 检测新标签页：抖音推荐可能用 target=_blank 打开直播间 ──
                try:
                    pages = self._context.pages
                    if len(pages) > last_page_count:
                        last_page_count = len(pages)
                        # 有新标签页打开，切换到最新的 page
                        new_page = pages[-1]
                        if new_page != self._page:
                            # 移除旧 page 的监听器
                            try:
                                self._page.remove_listener("response", handle_response)
                                self._page.remove_listener("request", handle_request)
                            except Exception:
                                pass
                            # 切换到新标签页
                            self._page = new_page
                            # 同步弹幕采集器的 page 引用
                            if self._danmu_reader:
                                self._danmu_reader.page = self._page
                            # 同步评论发送器的 page 引用（否则 sender 还在用首页 page，找不到 room_id 和输入框）
                            if self._sender:
                                self._sender.page = self._page
                            # 注册监听器到新 page
                            self._page.on("response", handle_response)
                            self._page.on("request", handle_request)
                            self._emit_status(f"检测到新标签页，已切换")
                except Exception:
                    pass

                current_url = self._page.url
                # URL变化时输出到 GUI 状态栏（方便用户调试）
                if current_url != last_url:
                    print(f"[Core] URL变化: {current_url}")
                    # 只对关键 URL 变化输出到 GUI，避免刷屏
                    if room_pattern.search(current_url) or "about:blank" not in current_url:
                        self._emit_status(f"当前页面: {current_url[:80]}")
                    last_url = current_url
                # 放宽检测：只要不在首页/搜索页，就认为可能进入了直播间
                # 真正的判断依赖直播流URL是否出现
                if room_pattern.search(current_url):
                    # 排除首页本身（live.kuaishou.com 无路径 / live.douyin.com 无路径）
                    home_path = self.platform.home_url.replace("https://", "").replace("http://", "")
                    if (not current_url.endswith(home_path) and
                        not current_url.endswith(home_path + "/") and
                        "/search" not in current_url):
                        if not in_live_room:
                            in_live_room = True
                            self._emit_status("已进入直播间，等待直播流...")
                if in_live_room and not stream_url:
                    probed = await self._probe_current_stream_url()
                    if probed:
                        stream_url = probed
                        self._emit_status(f"已从页面资源补获直播流: {stream_url[:80]}...")
                    else:
                        # 调试：打印页面 video 元素状态，看为什么找不到流
                        try:
                            debug_info = await self._page.evaluate("""() => {
                                const videos = document.querySelectorAll('video');
                                const result = [];
                                for (const v of videos) {
                                    result.push({
                                        currentSrc: v.currentSrc || '',
                                        src: v.src || '',
                                        readyState: v.readyState,
                                        networkState: v.networkState,
                                    });
                                }
                                return {
                                    videoCount: videos.length,
                                    videos: result,
                                    resourceCount: (performance.getEntriesByType('resource') || []).length,
                                    flvResources: (performance.getEntriesByType('resource') || [])
                                        .filter(r => r.name.includes('.flv') || r.name.includes('pull-flv'))
                                        .map(r => r.name.slice(0, 100)),
                                };
                            }""")
                            print(f"[Core-Stream] 补捞失败，页面状态: {debug_info}")
                        except Exception as e:
                            print(f"[Core-Stream] 调试信息获取失败: {e}")
                if stream_url and in_live_room:
                    # 直播流检测到后再截图，确保画面已开始播放
                    self._emit_status("直播流已检测到，等待画面加载...")
                    await asyncio.sleep(5)  # 额外等待5秒确保视频画面渲染
                    asyncio.create_task(self._fetch_live_room_info())
                    break
                # 如果检测到流但不在直播间（首页推荐直播的预览流），清除误判
                if stream_url and not in_live_room:
                    stream_url = None
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
                self._page, self.config.get("sender", {}), self.platform
            )
            self._sender.set_status_callback(self._emit_status)
            # 把 stream_url 注入给 sender，点赞时用于提取 liveStreamId
            self._sender.set_stream_url(self._stream_url or "")

            # 副账号：只保留 sender，不启动转录/弹幕/LLM/评论循环
            if self.role == "slave":
                self._emit_status(f"[{self.engine_id}] 副账号已就绪（仅发送模式）")
                # 副账号也启动自动点赞（如果配置开启）
                slave_tasks = []
                if self.config.get("sender", {}).get("like_enabled", True):
                    slave_tasks.append(asyncio.create_task(self._run_like_loop()))
                    self._emit_status(f"[{self.engine_id}] 副账号自动点赞已启动")
                if slave_tasks:
                    await asyncio.gather(*slave_tasks)
                else:
                    # 没有任务，保持浏览器打开等待评论分配
                    while self.is_running:
                        await asyncio.sleep(5)
                return

            self._transcriber = AudioTranscriber(
                self.config.get("audio", {})
            )
            # 如果 EngineManager 已注入共用 LLM，则不再创建
            if self._llm is None:
                self._llm = LLMClient(self.config.get("llm", {}))
            # 如果已经抓取到直播间信息，注入到LLM
            self._inject_live_context_to_llm()

            # 启动各任务
            tasks = []

            if self.config.get("danmu", {}).get("enabled", True):
                tasks.append(asyncio.create_task(self._run_danmu()))

            tasks.append(asyncio.create_task(self._run_audio()))
            tasks.append(asyncio.create_task(self._run_comment_loop()))

            # 自动点赞任务（默认开启，可由配置 sender.like_enabled 关闭）
            if self.config.get("sender", {}).get("like_enabled", True):
                tasks.append(asyncio.create_task(self._run_like_loop()))
                self._emit_status("自动点赞已启动")

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

    async def _probe_current_stream_url(self) -> str:
        """从当前页面已加载资源里补捞直播流，避免新标签页切换时漏掉网络事件。"""
        if not self._page or self._page.is_closed():
            return ""
        try:
            urls = await self._page.evaluate("""() => {
                const found = [];
                const add = value => {
                    if (value && typeof value === 'string' && !value.startsWith('blob:')) {
                        found.push(value);
                    }
                };

                // 1. <video> 元素的 src
                for (const video of document.querySelectorAll('video')) {
                    add(video.currentSrc);
                    add(video.src);
                    for (const source of video.querySelectorAll('source')) {
                        add(source.src);
                    }
                }

                // 2. Performance API 里的资源（含 flv/m3u8 请求）
                try {
                    const resources = performance.getEntriesByType('resource') || [];
                    for (const entry of resources) add(entry.name);
                } catch (_) {}

                // 3. 播放器内部状态：抖音 xgplayer / flv.js 等会缓存流 URL
                try {
                    // xgplayer（西瓜播放器）实例
                    const players = document.querySelectorAll('.xgplayer, [class*="player"]');
                    for (const p of players) {
                        // xgplayer 可能把流 URL 挂在 __xgplayer__ 或 player 属性上
                        const inst = p.__xgplayer__ || p.player || p._player;
                        if (inst) {
                            add(inst.url || inst.src || inst.config?.url || inst.config?.src);
                        }
                    }
                } catch (_) {}

                // 4. flv.js / hls.js 实例（常见于 MSE 播放器）
                try {
                    // flv.js 会把 URL 存在 MediaDataSource 上
                    if (window.flvjs || window.Flvjs) {
                        // 无法直接访问实例，但可以从 performance 里找
                    }
                } catch (_) {}

                // 5. 抖音 __NEXT_DATA__ 或 __RENDER_DATA__ 里可能含流地址
                try {
                    const nextData = document.getElementById('__NEXT_DATA__');
                    if (nextData) {
                        const text = nextData.textContent || '';
                        // 匹配 .flv URL
                        const flvMatches = text.match(/https?:\/\/[^\s"]+\.flv[^\s"]*/g) || [];
                        for (const m of flvMatches) add(m);
                        const m3u8Matches = text.match(/https?:\/\/[^\s"]+\.m3u8[^\s"]*/g) || [];
                        for (const m of m3u8Matches) add(m);
                    }
                    const renderData = document.getElementById('__RENDER_DATA__');
                    if (renderData) {
                        const text = renderData.textContent || '';
                        const flvMatches = text.match(/https?:\/\/[^\s"\\]+\.flv[^\s"\\]*/g) || [];
                        for (const m of flvMatches) add(m);
                        const m3u8Matches = text.match(/https?:\/\/[^\s"\\]+\.m3u8[^\s"\\]*/g) || [];
                        for (const m of m3u8Matches) add(m);
                    }
                } catch (_) {}

                return Array.from(new Set(found)).reverse();
            }""")
            for url in urls or []:
                if self.platform.is_real_stream(url):
                    return url
        except Exception as e:
            print(f"[Core-Stream] 页面资源补捞失败: {e}")
        return ""

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

        # 直播流判断委托给平台实现（消除重复代码）
        def is_real_stream(url: str, ctype: str = "") -> bool:
            return self.platform.is_real_stream(url, ctype)

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
                    # 同步到 sender，点赞时用于提取 liveStreamId
                    if self._sender:
                        self._sender.set_stream_url(url)
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
                # 同步到 sender，点赞时用于提取 liveStreamId
                if self._sender:
                    self._sender.set_stream_url(url)

        if self._page:
            self._page.on("response", handle_response)
            self._page.on("request", handle_request)

        try:
            while self.is_running:
                current_url = latest_stream["url"]
                if not current_url:
                    probed_url = await self._probe_current_stream_url()
                    if probed_url:
                        latest_stream["url"] = probed_url
                        self._stream_url = probed_url
                        # 同步到 sender，点赞时用于提取 liveStreamId
                        if self._sender:
                            self._sender.set_stream_url(probed_url)
                        self._emit_status(f"已从页面资源补获直播流: {probed_url[:80]}...")
                        continue
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

                # 拼接 AI 后缀标记
                if sender_config.get("ai_suffix", False):
                    suffix = sender_config.get("suffix_text", "[AI]")
                    comment = f"{comment}{suffix}"

                self.last_comment = comment
                if self.on_comment:
                    self.on_comment(comment)

                # 发送评论：多账号模式下交给 EngineManager 分配，单账号直接发送
                if self.on_comment_generated:
                    result = await self.on_comment_generated(comment)
                    success = True if result is None else bool(result)
                else:
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

        # 播放器选择器由平台提供（快手/抖音 DOM 结构不同）
        player_selectors = self.platform.get_player_selectors()

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
                # 抖音直播间：视频在左大半，聊天栏在右侧；截取左70%区域
                if self.platform and self.platform.name == "douyin":
                    viewport = self._page.viewport_size
                    if viewport:
                        clip = {"x": 0, "y": 0, "width": int(viewport["width"] * 0.7), "height": viewport["height"]}
                        screenshot_bytes = await self._page.screenshot(type="jpeg", quality=70, clip=clip)
                        print(f"[Core] 截取抖音左70%区域 clip={clip}")
                        self._emit_status("截取抖音直播画面区域")
                    else:
                        screenshot_bytes = await self._page.screenshot(type="jpeg", quality=70)
                        print("[Core] 截取整个页面")
                        self._emit_status("截取整个页面")
                else:
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

        def clean_vision_summary(text: str) -> str:
            """把视觉模型可能输出的推理过程压成一句可注入 LLM 的短概括。"""
            if not text:
                return ""

            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                return ""

            # 优先读取 JSON/标签/显式答案字段。
            for pattern in [
                r"<answer>(.*?)</answer>",
                r'"summary"\s*:\s*"([^"]+)"',
                r"'summary'\s*:\s*'([^']+)'",
                r"(?:最终答案|最终结果|答案|概括(?:为)?|总结(?:为)?)[：:]\s*[“\"']?([^。；\n，,！？?\"'”]{2,30})",
                r"(?:直播内容是|核心是|内容是)\s*[“\"']?([^。；\n，,！？?\"'”]{2,30})",
            ]:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    text = match.group(1).strip()
                    break

            # 长输出通常是模型把分析过程吐进 content；从后往前找最像结论的短句。
            bad_keywords = [
                "用户", "需要", "截图", "文字", "不超过", "只输出", "分析",
                "应该", "不过", "其次", "再整理", "结合", "最终确定",
                "检查字数", "比如", "或者", "可能", "不对", "然后",
                "JSON", "json", "构造", "返回", "格式", "输出", "字段",
            ]
            if len(text) > 30 or any(kw in text for kw in bad_keywords):
                candidates = []
                quoted = re.findall(r"[“\"']([^”\"']{2,20})[”\"']", text)
                candidates.extend(quoted)
                candidates.extend(re.split(r"[\n。；！？?]", text))
                for candidate in reversed(candidates):
                    candidate = candidate.strip().strip(" ：:，,。；！？?\"'“”")
                    if not candidate or any(kw in candidate for kw in bad_keywords):
                        continue
                    if len(candidate) <= 20:
                        text = candidate
                        break

            text = re.sub(r"^(直播画面描述|直播内容|画面内容|概括|总结|答案)[：:]\s*", "", text)
            text = re.split(r"[。；！？?\n]", text, maxsplit=1)[0]
            text = text.strip().strip(" ：:，,。；！？?\"'“”")
            if any(kw in text for kw in bad_keywords + ["用户现在需要", "不要输出", "内心独白"]):
                return ""
            if not re.search(r"[\u4e00-\u9fff]", text):
                return ""
            # 最小长度校验：少于 2 字的通常是残缺片段（如"再"、"的"）
            if len(text) < 2:
                return ""
            return text[:15]

        def parse_vision_response(msg) -> str:
            """解析视觉模型响应，兼容多种格式。

            思考模型（thinking）的 content 可能是推理过程末尾的残缺片段，
            若清洗后过短（<2字）则回退到 reasoning_content 再清洗一次。
            """
            content = msg.content or ""
            rc = getattr(msg, "reasoning_content", "") or ""
            # 先用 content，过短则回退到 reasoning_content
            result = clean_vision_summary(content)
            if len(result) >= 2:
                return result
            # content 清洗后过短，尝试 reasoning_content
            rc_result = clean_vision_summary(rc)
            if len(rc_result) >= 2:
                return rc_result
            # 两个都过短，返回较长的那个（可能都是空）
            return result or rc_result

        # 需要开启 thinking 参数的模型（思考模型列表，content字段可能为空或包含思考过程）
        thinking_models = {"glm-4.1v-thinking-flash", "glm-4.5v", "glm-4.5v-flash"}

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
                                 "text": "看这张直播截图，忽略画面上飘过的弹幕文字和聊天区内容，只根据视频画面本身判断：这是什么类型的直播？主播在做什么？用15字以内中文短语概括，直接输出短语本身，不要解释，不要分析。"},
                            ],
                        }],
                        "max_tokens": 200,
                        "temperature": 0.1,
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
            # 选择器由平台提供（快手/抖音 DOM 不同），通过 evaluate 参数传入避免 f-string 转义
            params = {
                "nameSels": self.platform.get_streamer_selectors(),
                "tagSels": self.platform.get_category_selectors(),
                "titleRegex": self.platform.title_regex,
            }
            info = await self._page.evaluate("""
                (params) => {
                    const nameSels = params.nameSels;
                    const tagSels = params.tagSels;
                    const titleRegexStr = params.titleRegex;
                    let streamer = '';
                    let category = '';
                    const badNamePatterns = ['抖音', '快手', 'douyin', 'kuaishou', 'live', '直播', 'live.douyin'];

                    // ---- 主播名提取（3层策略）----

                    // 策略1：页面标题正则匹配（最可靠）
                    const title = document.title || '';
                    const titleMatch = title.match(new RegExp(titleRegexStr));
                    if (titleMatch) {
                        const candidate = titleMatch[1].trim();
                        if (candidate && !badNamePatterns.some(p => candidate.toLowerCase() === p)) {
                            streamer = candidate;
                        }
                    }

                    // 策略2：SSR 数据提取（标题匹配失败时，从 __RENDER_DATA__ / __NEXT_DATA__ 取 nickname）
                    if (!streamer) {
                        try {
                            for (const id of ['__RENDER_DATA__', '__NEXT_DATA__']) {
                                const el = document.getElementById(id);
                                if (!el) continue;
                                const text = el.textContent || '';
                                // 匹配 "nickname":"XXX" 或 "anchor_name":"XXX"
                                const nickMatch = text.match(/"(?:nickname|anchor_name|owner_name)"\\s*:\\s*"([^"]{1,30})"/);
                                if (nickMatch) {
                                    const n = nickMatch[1].trim();
                                    if (n && !badNamePatterns.some(p => n.toLowerCase().includes(p))) {
                                        streamer = n;
                                        break;
                                    }
                                }
                            }
                        } catch(_) {}
                    }

                    // 策略3：DOM 选择器兜底
                    if (!streamer) {
                        for (const sel of nameSels) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim()) {
                                const name = el.textContent.trim();
                                // 跳过含换行的（不是主播名，如"标清\\n更多直播"）
                                if (name.includes('\\n') || name.length !== name.replace(/[\\r\\n]/g,'').length) continue;
                                // 跳过纯平台名/通用词
                                if (name.length <= 6 && badNamePatterns.some(p => name.toLowerCase().includes(p))) continue;
                                // 跳过过长的文本
                                if (name.length > 30) continue;
                                streamer = name;
                                break;
                            }
                        }
                    }

                    // ---- 直播分类/标签 ----
                    for (const sel of tagSels) {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const t = el.textContent.trim();
                            if (t && t.length < 20) {
                                category = (category ? category + '、' : '') + t;
                            }
                        }
                    }

                    return { streamer, category, _title: title };
                }
            """, params)
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

        # 共享浏览器模式下，只关自己的 context，不关 browser（browser 由 EngineManager 统一关闭）
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass

        if self._owns_browser and self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass

        if self._owns_browser and self._playwright:
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

    def is_ready_to_send(self) -> bool:
        """该引擎是否已就绪可以发送评论（已进入直播间）"""
        return self._page is not None and self._sender is not None and self.is_running

    async def send_comment_direct(self, comment: str) -> bool:
        """供 EngineManager 调用，直接发送评论（不经过 LLM 生成）"""
        if not self.is_ready_to_send():
            return False
        try:
            success = await self._sender.send_comment(comment)
            if success:
                self.last_comment = comment
                self._emit_status(f"[{self.engine_id}] 已发送评论: {comment}")
                if self.on_comment:
                    self.on_comment(comment)
            return success
        except Exception as e:
            self._emit_error(f"[{self.engine_id}] 发送评论失败: {e}")
            return False

    async def _run_like_loop(self):
        """自动点赞循环任务

        - 进直播间后等 2 秒让 video 元素加载
        - 按 sender.like_interval（默认 5 秒）周期调用 send_like
        - 连续失败 5 次自动停止（由 sender 内部逻辑处理）
        - 退出直播间/停止引擎时自动结束
        """
        # 等 2 秒让 video 元素完全加载
        await asyncio.sleep(2)

        # 点赞间隔（秒），默认 3 秒（抖音响应快 2 秒内，快手抓包确认客户端 ~2 秒）
        interval = self.config.get("sender", {}).get("like_interval", 3)
        try:
            interval = max(2, float(interval))
        except Exception:
            interval = 3

        self._emit_status(f"自动点赞循环启动，间隔 {interval:.0f} 秒")

        while self.is_running:
            try:
                if not self.is_ready_to_send():
                    await asyncio.sleep(5)
                    continue

                # 检查是否还在直播间（避免在主页/跳转后点赞）
                import re as _re
                if not _re.search(self.platform.room_url_pattern, self._page.url):
                    await asyncio.sleep(5)
                    continue

                await self._sender.send_like(1)
            except Exception as e:
                self._emit_error(f"点赞循环异常: {e}")

            await asyncio.sleep(interval)

    async def send_like_direct(self, count: int = None) -> bool:
        """供 EngineManager / GUI 调用，发送一次点赞

        Args:
            count: 单次点赞次数（None 用配置默认值，限制 1-5）
        Returns:
            是否发送成功
        """
        if not self.is_ready_to_send():
            return False
        try:
            success = await self._sender.send_like(count)
            return success
        except Exception as e:
            self._emit_error(f"[{self.engine_id}] 点赞失败: {e}")
            return False
