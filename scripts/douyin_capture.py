"""抖音直播间抓包分析工具（实机收集真实数据，不再靠猜）

用法：
    python scripts/douyin_capture.py [直播间URL]

不传 URL 则只打开抖音首页，等用户手动进入直播间。

脚本会：
  1. 启动浏览器，加载已保存的抖音 cookie
  2. 等用户进入直播间
  3. 收集 60 秒真实数据：
     - 所有 WebSocket 连接 URL + 前 5 个帧的 hex dump
     - 所有视频流相关请求（flv/m3u8）+ Content-Type
     - /webcast/ /api/ 等业务 API 请求
     - 页面所有输入元素的 outerHTML
     - 主播名/分类的 DOM 结构
  4. 输出报告到 douyin_capture_report.txt

报告请发给开发者，用于修正 DouyinPlatform 的选择器和协议实现。
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 把项目根目录加入 sys.path，方便复用 src.platforms
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 复用项目的 PLAYWRIGHT_BROWSERS_PATH 配置（避免 chromium 找不到）
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
)

from playwright.async_api import async_playwright

# ── 配置 ──
DOUYIN_HOME = "https://live.douyin.com"
COOKIE_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "旁白" / "cookies_douyin_main.json"
# 兜底：项目根目录
if not COOKIE_FILE.exists():
    COOKIE_FILE = PROJECT_ROOT / "cookies_douyin_main.json"
if not COOKIE_FILE.exists():
    COOKIE_FILE = PROJECT_ROOT / "cookies.json"

REPORT_FILE = PROJECT_ROOT / "douyin_capture_report.txt"
CAPTURE_SECONDS = 60  # 默认收集 60 秒


class DouyinCapture:
    def __init__(self, target_url: str = None):
        self.target_url = target_url
        self.report_lines: list[str] = []
        self.websockets: dict = {}  # url -> {frames_received: [], frames_sent: []}
        self.stream_responses: list[dict] = []
        self.api_requests: list[dict] = []
        self.input_elements: list[dict] = []
        self.room_info: dict = {}
        self._capture_phase = "init"  # A_passive / B_comment / C_after
        self._comment_send_requests: list[dict] = []

    def log(self, msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line)
        self.report_lines.append(line)

    def section(self, title: str):
        sep = "=" * 60
        self.log("")
        self.log(sep)
        self.log(title)
        self.log(sep)

    async def run(self):
        self.log("=== 抖音直播间抓包分析工具启动 ===")
        self.log(f"Cookie 文件: {COOKIE_FILE}")
        self.log(f"目标 URL: {self.target_url or '（未指定，需手动进入直播间）'}")
        self.log(f"收集时长: {CAPTURE_SECONDS} 秒")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            # 注入反检测
            await page.add_init_script(
                'Object.defineProperties(navigator, { webdriver: { get: () => undefined } })'
            )

            # ── 注册监听器（必须在导航前） ──
            await self._register_listeners(page)

            # ── 监听新标签页：如果直播间在新标签打开，自动切换监控 ──
            self._active_page = page  # 当前监控的页面
            context.on("page", lambda new_page: asyncio.ensure_future(self._on_new_page(new_page)))

            # ── 加载 cookie ──
            if COOKIE_FILE.exists():
                try:
                    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                        cookies = json.load(f)
                    await context.add_cookies(cookies)
                    self.log(f"已加载 {len(cookies)} 条 cookie")
                except Exception as e:
                    self.log(f"加载 cookie 失败: {e}")

            # ── 导航 ──
            self.log(f"导航到: {DOUYIN_HOME}")
            await page.goto(DOUYIN_HOME, wait_until="domcontentloaded", timeout=15000)

            # 检查登录态
            logged_in = await self._check_login(page, context)
            if not logged_in:
                self.log("⚠ 未登录，请在浏览器中扫码登录抖音")
                self.log("等待登录中...（最多 5 分钟）")
                ok = await self._wait_login(page, context)
                if not ok:
                    self.log("登录超时，退出")
                    await browser.close()
                    return

            self.log("✓ 登录状态有效")

            # 如果传了 URL，自动导航
            if self.target_url:
                self.log(f"自动导航到目标直播间: {self.target_url}")
                try:
                    await page.goto(self.target_url, wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    self.log(f"导航失败: {e}，请手动进入直播间")

            # 等待用户进入直播间
            self.log("")
            self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.log("请在浏览器中进入任意抖音直播间")
            self.log(f"脚本将自动检测直播间，并收集 {CAPTURE_SECONDS} 秒数据")
            self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 检测直播间：URL模式 或 DOM特征（video元素 + 聊天区）
            import re
            room_pattern = re.compile(r"live\.douyin\.com/\d+")
            waited = 0
            while waited < 300:
                cur_page = self._active_page
                url = cur_page.url
                if room_pattern.search(url):
                    self.log(f"✓ 检测到进入直播间（URL）: {url}")
                    break
                # DOM 兜底检测：有 video 元素 + contenteditable/chatroom 元素
                try:
                    has_live = await cur_page.evaluate("""() => {
                        const hasVideo = document.querySelector('video') !== null;
                        const hasChat = document.querySelector(
                            '[contenteditable="true"][data-slate-editor], ' +
                            '[data-e2e="chatroom"], [class*="chatroom"], ' +
                            '[data-e2e="chat-input"], [data-e2e="player"]'
                        ) !== null;
                        return hasVideo && hasChat;
                    }""")
                    if has_live:
                        self.log(f"✓ 检测到进入直播间（DOM特征）: {url}")
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)
                waited += 2
                if waited % 20 == 0:
                    self.log(f"等待进入直播间... ({waited}s) 当前: {url[:80]}")
            else:
                self.log("⚠ 5 分钟未进入直播间，开始收集当前页面数据")

            # ── 收集 DOM 结构 ──
            self.section("【1】页面 DOM 结构分析")
            await self._collect_dom(self._active_page)

            # ── 阶段A：被动观察 30 秒（收集 WS/流/常态 API） ──
            self.section("【2A】被动观察 30 秒（收集 WebSocket/直播流/常态 API）")
            self.log("开始被动观察，请保持页面不动...")
            self._capture_phase = "A_passive"
            await asyncio.sleep(30)

            # ── 阶段B：评论发送抓包 ──
            self.section("【2B】评论发送抓包（关键！）")
            self._capture_phase = "B_comment"
            self._comment_send_requests = []  # 专门记录评论发送期间的请求
            self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.log("【请在接下来的 30 秒内手动发 1-2 条评论】")
            self.log("  - 在抖音直播间的评论框输入文字")
            self.log("  - 按回车或点发送按钮发送")
            self.log("  - 脚本会捕获评论发送的真实 API 请求")
            self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            await asyncio.sleep(30)

            # ── 阶段C：发送后 DOM 状态 ──
            self.section("【2C】评论发送后 DOM 状态")
            self.log("重新收集 DOM（评论框可能已变化）...")
            await self._collect_dom(self._active_page)

            # ── 输出报告 ──
            self.section("【3】WebSocket 连接报告")
            self._report_websockets()

            self.section("【4】直播流响应报告")
            self._report_streams()

            self.section("【5】业务 API 请求报告（含评论发送接口）")
            self._report_apis()

            self.section("【6】★ 评论发送专属请求（最关键）")
            self._report_comment_requests()

            self.section("【7】输入元素 DOM 报告")
            self._report_inputs()

            self.section("【8】直播间信息报告")
            self._report_room_info()

            # 写入文件
            await self._write_report()

            self.log("")
            self.log(f"✓ 报告已生成: {REPORT_FILE}")
            self.log("请将此文件发给开发者，或粘贴关键内容反馈")

            # 关闭浏览器
            await browser.close()

    async def _on_new_page(self, new_page):
        """新标签页打开时，切换监控目标到新标签"""
        try:
            await new_page.add_init_script(
                'Object.defineProperties(navigator, { webdriver: { get: () => undefined } })'
            )
            await self._register_listeners(new_page)
            self._active_page = new_page
            self.log(f"✓ 检测到新标签页，已切换监控目标: {new_page.url[:80]}")
        except Exception as e:
            self.log(f"新标签页监听失败: {e}")

    async def _register_listeners(self, page):
        """注册所有网络监听器"""

        async def on_response(response):
            try:
                url = response.url
                ctype = response.headers.get("content-type", "")
                # 直播流：flv/m3u8/video
                url_lower = url.lower()
                if (".flv" in url_lower or ".m3u8" in url_lower
                    or "video/" in ctype.lower()
                    or "mpegurl" in ctype.lower()):
                    self.stream_responses.append({
                        "url": url,
                        "content_type": ctype,
                        "status": response.status,
                    })
                    self.log(f"[流] {response.status} {ctype} {url[:120]}")
            except Exception:
                pass

        async def on_request(request):
            try:
                url = request.url
                url_lower = url.lower()
                # 业务 API
                if ("/webcast/" in url_lower or "/api/" in url_lower
                    or "im-front" in url_lower or "webcast" in url_lower
                    or "/comment" in url_lower or "/send" in url_lower
                    or "/chat" in url_lower or "/msg" in url_lower):
                    # 只记录关键 API，跳过静态资源
                    if not any(url_lower.endswith(ext) for ext in [".js", ".css", ".png", ".jpg", ".webp", ".gif", ".ico"]):
                        req_info = {
                            "url": url,
                            "method": request.method,
                            "headers": dict(request.headers),
                            "phase": getattr(self, "_capture_phase", "unknown"),
                            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        }
                        # 尝试读 POST body（评论发送一般是 POST）
                        if request.method == "POST":
                            try:
                                body = request.post_data
                                if body:
                                    req_info["body"] = body[:1000]
                                    req_info["body_is_binary"] = isinstance(body, (bytes, bytearray))
                            except Exception:
                                pass
                        self.api_requests.append(req_info)
                        # 阶段B（评论发送阶段）的请求单独标记
                        if req_info["phase"] == "B_comment":
                            self._comment_send_requests.append(req_info)
                            self.log(f"[阶段B-评论] [{req_info['timestamp']}] {request.method} {url[:120]}")
            except Exception:
                pass

        def on_websocket(ws):
            url = ws.url
            self.log(f"[WS] 新连接: {url}")
            self.websockets[url] = {
                "frames_received": [],
                "frames_sent": [],
            }

            def _normalize_payload(payload):
                """Playwright WS frame 可能是 bytes/str/dict，统一转成 bytes"""
                if isinstance(payload, dict):
                    # 有些版本传 {"data": ...} 或 {"payload": ...}
                    payload = payload.get("data", payload.get("payload", b""))
                if isinstance(payload, str):
                    # 文本帧：编码成 utf-8 bytes
                    return payload.encode("utf-8"), "text"
                if isinstance(payload, (bytes, bytearray)):
                    return bytes(payload), "binary"
                # 其他类型：转字符串
                return str(payload).encode("utf-8"), "other"

            def on_frame_received(payload):
                if len(self.websockets[url]["frames_received"]) < 5:
                    normalized, ptype = _normalize_payload(payload)
                    self.websockets[url]["frames_received"].append((normalized, ptype))
                    self.log(f"[WS-recv] {len(normalized)} bytes ({ptype})  hex头部: {normalized[:40].hex()}")

            def on_frame_sent(payload):
                if len(self.websockets[url]["frames_sent"]) < 5:
                    normalized, ptype = _normalize_payload(payload)
                    self.websockets[url]["frames_sent"].append((normalized, ptype))
                    self.log(f"[WS-sent] {len(normalized)} bytes ({ptype})  hex头部: {normalized[:40].hex()}")

            ws.on("framereceived", lambda p: on_frame_received(p))
            ws.on("framesent", lambda p: on_frame_sent(p))

        page.on("response", on_response)
        page.on("request", on_request)
        page.on("websocket", on_websocket)

    async def _check_login(self, page, context) -> bool:
        """检查登录态（用 context.cookies 读 HttpOnly cookie）"""
        try:
            cookies = await context.cookies()
            names = {c.get("name", "") for c in cookies}
            if any(n in names for n in ("sessionid", "sessionid_ss", "PASSID", "sid_guard")):
                return True
        except Exception:
            pass
        return False

    async def _wait_login(self, page, context, timeout=300) -> bool:
        """等待用户扫码登录"""
        for _ in range(timeout):
            if await self._check_login(page, context):
                return True
            await asyncio.sleep(1)
        return False

    async def _collect_dom(self, page):
        """收集页面 DOM 结构"""
        try:
            # 输入元素
            self.input_elements = await page.evaluate("""() => {
                const results = [];
                const selectors = 'textarea, input[type="text"], input:not([type]), [contenteditable="true"]';
                document.querySelectorAll(selectors).forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        index: i,
                        tag: el.tagName,
                        type: el.type || '',
                        class: (el.className || '').toString().slice(0, 200),
                        placeholder: el.placeholder || el.getAttribute('data-placeholder') || '',
                        contentEditable: el.contentEditable,
                        visible: rect.width > 0 && rect.height > 0,
                        id: el.id || '',
                        outerHTML: el.outerHTML.slice(0, 500),
                        parentClass: (el.parentElement?.className || '').toString().slice(0, 200),
                        parentDataE2e: el.parentElement?.getAttribute('data-e2e') || '',
                    });
                });
                return results;
            }""")

            # 直播间信息
            self.room_info = await page.evaluate("""() => {
                const info = {};
                // 标题
                info.title = document.title;
                // 主播名候选
                const nameEls = document.querySelectorAll(
                    '[data-e2e="anchor-nickname"], [data-e2e="anchor-name"], ' +
                    '[class*="anchor"], [class*="streamer"], [class*="host-name"]'
                );
                info.name_candidates = [];
                nameEls.forEach(el => {
                    info.name_candidates.push({
                        tag: el.tagName,
                        text: (el.innerText || '').slice(0, 50),
                        class: (el.className || '').toString().slice(0, 100),
                        dataE2e: el.getAttribute('data-e2e') || '',
                    });
                });
                // 分类候选
                const catEls = document.querySelectorAll(
                    '[data-e2e="category"], [class*="category"], [class*="tag"]'
                );
                info.category_candidates = [];
                catEls.forEach(el => {
                    info.category_candidates.push({
                        tag: el.tagName,
                        text: (el.innerText || '').slice(0, 50),
                        class: (el.className || '').toString().slice(0, 100),
                    });
                });
                // 发送按钮候选
                const sendBtns = document.querySelectorAll(
                    '[data-e2e="chat-send"], [class*="send"], [class*="submit"]'
                );
                info.send_button_candidates = [];
                sendBtns.forEach(el => {
                    info.send_button_candidates.push({
                        tag: el.tagName,
                        text: (el.innerText || '').slice(0, 30),
                        class: (el.className || '').toString().slice(0, 100),
                        dataE2e: el.getAttribute('data-e2e') || '',
                    });
                });
                return info;
            }""")
        except Exception as e:
            self.log(f"收集 DOM 失败: {e}")

    def _report_websockets(self):
        if not self.websockets:
            self.log("⚠ 未捕获到任何 WebSocket 连接")
            self.log("可能原因：弹幕区未加载 / 页面未完全渲染 / 抖音改了协议")
            return

        for url, data in self.websockets.items():
            self.log(f"WebSocket URL: {url}")
            self.log(f"  接收帧数（已记录前5个）: {len(data['frames_received'])}")
            self.log(f"  发送帧数（已记录前5个）: {len(data['frames_sent'])}")

            for i, item in enumerate(data["frames_received"]):
                # 兼容旧格式（纯 bytes）和新格式（tuple: (bytes, type)）
                if isinstance(item, tuple):
                    frame, ptype = item
                else:
                    frame, ptype = item, "unknown"
                self.log(f"  [recv {i}] {len(frame)} bytes ({ptype})")
                self.log(f"    hex前200: {frame[:200].hex()}")
                # 尝试 gzip 解压
                try:
                    import gzip
                    decompressed = gzip.decompress(frame)
                    self.log(f"    gzip解压成功: {len(decompressed)} bytes")
                    self.log(f"    解压后hex前200: {decompressed[:200].hex()}")
                except Exception:
                    pass
                # 尝试当文本解码
                try:
                    text = frame.decode("utf-8")
                    if text.isprintable() or "\\x" not in repr(text):
                        self.log(f"    文本解读: {text[:200]}")
                except Exception:
                    pass

            for i, item in enumerate(data["frames_sent"]):
                if isinstance(item, tuple):
                    frame, ptype = item
                else:
                    frame, ptype = item, "unknown"
                self.log(f"  [sent {i}] {len(frame)} bytes ({ptype})")
                self.log(f"    hex前200: {frame[:200].hex()}")
                # 尝试当文本解码（评论发送可能是文本帧）
                try:
                    text = frame.decode("utf-8")
                    self.log(f"    文本解读: {text[:300]}")
                except Exception:
                    pass

    def _report_streams(self):
        if not self.stream_responses:
            self.log("⚠ 未捕获到任何直播流响应")
            self.log("可能原因：直播未开始 / 流走 WebRTC / CDN 域名未匹配")
            return

        seen = set()
        for r in self.stream_responses:
            key = r["url"][:100]
            if key in seen:
                continue
            seen.add(key)
            self.log(f"直播流: status={r['status']} content_type={r['content_type']}")
            self.log(f"  URL: {r['url']}")

    def _report_apis(self):
        if not self.api_requests:
            self.log("⚠ 未捕获到任何业务 API 请求")
            return

        # 按 URL 前缀分组，只显示前 30 条
        seen_paths = set()
        count = 0
        for r in self.api_requests[:100]:
            # 提取 path 部分
            try:
                from urllib.parse import urlparse
                path = urlparse(r["url"]).path
                if path in seen_paths:
                    continue
                seen_paths.add(path)
            except Exception:
                pass

            self.log(f"[{r['method']}] [{r.get('phase','?')}] {r['url'][:150]}")
            # 打印关键 headers
            headers = r.get("headers", {})
            for h in ("user-agent", "referer", "origin", "cookie"):
                if h in headers:
                    val = headers[h]
                    if h == "cookie":
                        val = val[:80] + "..." if len(val) > 80 else val
                    self.log(f"  {h}: {val}")
            # POST body
            if "body" in r:
                self.log(f"  body: {r['body']}")
            count += 1
            if count >= 30:
                self.log(f"... 还有 {len(self.api_requests) - 30} 条未显示")
                break

    def _report_comment_requests(self):
        """★ 评论发送专属请求报告（修复 CommentSender 的关键数据）"""
        comment_reqs = getattr(self, "_comment_send_requests", [])
        if not comment_reqs:
            self.log("⚠ 阶段B（评论发送阶段）未捕获到任何 API 请求")
            self.log("可能原因：")
            self.log("  1. 用户未在 30 秒内发评论")
            self.log("  2. 抖音评论走 WebSocket 而非 HTTP（看 WebSocket 报告的 frames_sent）")
            self.log("  3. 评论接口 URL 不含 /webcast//api//comment/send/chat/msg 关键词（需扩大捕获范围）")
            return

        self.log(f"★ 阶段B 共捕获 {len(comment_reqs)} 条请求（按时间排序）：")
        self.log("这些请求中很可能包含评论发送接口，开发者据此修正 CommentSender")
        self.log("")

        for i, r in enumerate(comment_reqs):
            self.log(f"── 评论阶段请求 [{i}] ──")
            self.log(f"  时间: {r.get('timestamp','')}")
            self.log(f"  方法: {r['method']}")
            self.log(f"  URL: {r['url']}")
            # 完整 headers
            self.log(f"  Headers:")
            for k, v in r.get("headers", {}).items():
                if k.lower() == "cookie":
                    v = v[:100] + "..." if len(v) > 100 else v
                self.log(f"    {k}: {v}")
            # POST body
            if "body" in r:
                self.log(f"  Body ({'binary' if r.get('body_is_binary') else 'text'}):")
                self.log(f"    {r['body']}")
            self.log("")

    def _report_inputs(self):
        if not self.input_elements:
            self.log("⚠ 页面上没有任何输入元素")
            return

        self.log(f"共找到 {len(self.input_elements)} 个输入元素：")
        for el in self.input_elements:
            self.log(f"  [{el['index']}] <{el['tag']}> type={el['type']} visible={el['visible']}")
            self.log(f"    class: {el['class'][:100]}")
            self.log(f"    placeholder: {el['placeholder']}")
            self.log(f"    contentEditable: {el['contentEditable']}")
            self.log(f"    id: {el['id']}")
            self.log(f"    parentClass: {el['parentClass'][:100]}")
            self.log(f"    parentDataE2e: {el['parentDataE2e']}")
            self.log(f"    outerHTML: {el['outerHTML'][:200]}")

    def _report_room_info(self):
        if not self.room_info:
            self.log("未收集到直播间信息")
            return

        self.log(f"页面标题: {self.room_info.get('title', '')}")
        self.log("")
        self.log("主播名候选元素:")
        for c in self.room_info.get("name_candidates", [])[:10]:
            self.log(f"  <{c['tag']}> text={c['text']!r} class={c['class'][:60]} data-e2e={c['dataE2e']}")
        self.log("")
        self.log("分类候选元素:")
        for c in self.room_info.get("category_candidates", [])[:10]:
            self.log(f"  <{c['tag']}> text={c['text']!r} class={c['class'][:60]}")
        self.log("")
        self.log("发送按钮候选元素:")
        for c in self.room_info.get("send_button_candidates", [])[:10]:
            self.log(f"  <{c['tag']}> text={c['text']!r} class={c['class'][:60]} data-e2e={c['dataE2e']}")

    async def _write_report(self):
        self.section("=== 报告结束 ===")
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(self.report_lines))
        self.log(f"报告写入: {REPORT_FILE}")


def main():
    target_url = sys.argv[1] if len(sys.argv) > 1 else None
    capture = DouyinCapture(target_url=target_url)
    try:
        asyncio.run(capture.run())
    except KeyboardInterrupt:
        print("\n用户中断，正在生成报告...")
        if capture.report_lines:
            with open(REPORT_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(capture.report_lines))
            print(f"报告已写入: {REPORT_FILE}")


if __name__ == "__main__":
    main()
