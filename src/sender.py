"""评论发送模块：通过Playwright自动化在直播间发送评论（平台无关）

评论输入框选择器由 Platform 提供，发送机制（click/fill/press）平台通用。
支持两种输入框：
  - textarea/input：用 fill() + press("Enter")
  - contenteditable div：用 type() + 模拟回车键，并尝试点击发送按钮
"""

import asyncio


class CommentSender:
    """通过Playwright模拟用户操作发送直播间评论"""

    def __init__(self, page, config: dict, platform=None):
        self.page = page
        self.platform = platform  # Platform 实例，提供输入框选择器
        self.min_interval = config.get("min_interval", 20)
        self.max_interval = config.get("max_interval", 50)
        self.max_length = config.get("max_length", 20)
        self._last_send_time = 0
        self._comment_count = 0
        self._debug_logged = False  # 只打印一次调试信息
        self._on_status = None  # GUI 状态回调（由 engine 注入）

    def set_status_callback(self, cb):
        """注入 GUI 状态回调，让调试日志能在 GUI 状态栏显示"""
        self._on_status = cb

    def _log(self, msg: str):
        """同时输出到 stdout 和 GUI 状态栏"""
        print(f"[CommentSender] {msg}")
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

    async def send_comment(self, text: str) -> bool:
        """发送评论到直播间

        抖音平台：优先走 fetch API（稳定，不依赖 contenteditable DOM 操作）
        其他平台：走 DOM 模拟（fill + Enter 或 type + Enter）

        Args:
            text: 评论文本

        Returns:
            是否发送成功
        """
        if len(text) > self.max_length:
            text = text[: self.max_length]

        # 抖音平台：优先用 fetch 方式（抓包确认走 GET /webcast/room/chat/）
        if self.platform and hasattr(self.platform, 'send_comment_via_fetch'):
            self._log(f"使用 fetch 方式发送（platform={self.platform.name}）")
            try:
                fetch_result = await self.platform.send_comment_via_fetch(self.page, text)
                # 返回值可能是 (ok, detail_dict) 或 bool
                if isinstance(fetch_result, tuple):
                    ok, detail = fetch_result
                else:
                    ok, detail = fetch_result, {}
                if ok:
                    self._last_send_time = asyncio.get_event_loop().time()
                    self._comment_count += 1
                    debug = detail.get("debug_info", "") if isinstance(detail, dict) else ""
                    self._log(f"fetch 发送成功: {text[:20]}" + (f" [{debug}]" if debug else ""))
                    return True
                else:
                    err_info = ""
                    if isinstance(detail, dict):
                        parts = []
                        if detail.get("statusCode") is not None:
                            parts.append(f"status_code={detail['statusCode']}")
                        if detail.get("statusMsg"):
                            parts.append(detail["statusMsg"])
                        if detail.get("error"):
                            parts.append(detail["error"])
                        err_info = ", ".join(parts)
                    self._log(f"fetch 发送失败: {err_info}，回退到 DOM 方式")
            except Exception as e:
                self._log(f"fetch 发送异常: {e}，回退到 DOM 方式")

        # 其他平台或 fetch 失败：走 DOM 模拟
        try:
            input_box = await self._find_input_box()
            if not input_box:
                self._log("未找到评论输入框")
                return False

            # 判断输入框类型
            tag = await input_box.evaluate("el => el.tagName.toLowerCase()")
            is_contenteditable = await input_box.evaluate(
                'el => el.getAttribute("contenteditable") === "true" || el.isContentEditable'
            )

            # 点击输入框使其获得焦点
            await input_box.click()
            await asyncio.sleep(0.3)

            if is_contenteditable:
                # contenteditable div：fill() 不生效，用 type() 模拟键盘输入
                # 先清空（全选后删除）
                await input_box.press("Control+a")
                await asyncio.sleep(0.05)
                await input_box.press("Delete")
                await asyncio.sleep(0.1)
                # 用 type 模拟真人按键
                await input_box.type(text, delay=30)
                await asyncio.sleep(0.3)
                self._log(f"已输入到 contenteditable（长度={len(text)}），尝试发送...")
                # 尝试发送：先按回车，失败则找发送按钮
                sent = await self._try_send(input_box, text)
                if not sent:
                    self._log("回车和发送按钮都未触发发送")
                    return False
            else:
                # textarea/input：用 fill + 回车
                await input_box.fill("")
                await asyncio.sleep(0.1)
                await input_box.fill(text)
                await asyncio.sleep(0.2)
                await input_box.press("Enter")
                await asyncio.sleep(0.5)

            self._last_send_time = asyncio.get_event_loop().time()
            self._comment_count += 1
            return True

        except Exception as e:
            self._log(f"发送评论错误: {e}")
            return False

    async def _try_send(self, input_box, expected_text: str = "") -> bool:
        """尝试多种发送方式：回车 → 兄弟节点发送按钮 → 全页面搜索发送按钮"""
        try:
            start_marker = await self.page.evaluate("() => performance.now()")
        except Exception:
            start_marker = 0

        # 方式1：回车
        try:
            await self.page.keyboard.press("Enter")
            await asyncio.sleep(0.8)
            # 检查输入框是否已清空（发送成功的标志）
            text = await input_box.evaluate('el => el.innerText || el.value || ""')
            if not text.strip():
                self._log("回车发送成功")
                return True
            if await self._saw_douyin_chat_request(start_marker, expected_text):
                self._log("检测到抖音评论请求，按发送成功处理")
                return True
        except Exception:
            pass

        # 方式1.5：部分 Slate 编辑器只响应聚焦页面上的真实 keydown/keyup。
        try:
            dispatched = await input_box.evaluate("""el => {
                const opts = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
                el.dispatchEvent(new KeyboardEvent('keydown', opts));
                el.dispatchEvent(new KeyboardEvent('keypress', opts));
                el.dispatchEvent(new KeyboardEvent('keyup', opts));
                return true;
            }""")
            if dispatched:
                await asyncio.sleep(0.8)
                text = await input_box.evaluate('el => el.innerText || el.value || ""')
                if not text.strip():
                    self._log("键盘事件发送成功")
                    return True
                if await self._saw_douyin_chat_request(start_marker, expected_text):
                    self._log("检测到抖音评论请求，按发送成功处理")
                    return True
        except Exception:
            pass

        # 方式2：父节点内找发送按钮
        try:
            sent = await input_box.evaluate("""el => {
                const parent = el.closest('[class*="chat"], [class*="input"], [class*="comment"], [data-e2e]') || el.parentElement;
                if (!parent) return false;
                const btns = parent.querySelectorAll('button, [class*="send"], [class*="btn"], [data-e2e*="send"]');
                for (const b of btns) {
                    const t = (b.innerText || b.textContent || '').trim();
                    if (t === '发送' || t === 'Send' || b.getAttribute('data-e2e') === 'chat-send' ||
                        b.className.toLowerCase().includes('send')) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            if sent:
                self._log("点击发送按钮成功")
                await asyncio.sleep(0.8)
                if await self._saw_douyin_chat_request(start_marker, expected_text):
                    self._log("检测到抖音评论请求，按发送成功处理")
                    return True
                return True
        except Exception:
            pass

        # 方式3：全页面找 data-e2e="chat-send" 或 class 含 send 的按钮
        try:
            btn = await self.page.query_selector(
                '[data-e2e="chat-send"], [data-e2e="send-btn"], '
                'button[class*="send"][class*="chat"], '
                'button[class*="send"]:not([class*="friend"]), '
                '[class*="chat-send"]'
            )
            if btn:
                visible = await btn.is_visible()
                if visible:
                    await btn.click()
                    self._log("点击页面发送按钮成功")
                    await asyncio.sleep(0.8)
                    if await self._saw_douyin_chat_request(start_marker, expected_text):
                        self._log("检测到抖音评论请求，按发送成功处理")
                        return True
                    return True
        except Exception:
            pass

        # 方式4：真实页面里发送按钮可能只有 svg，没有文字和稳定 class。
        try:
            sent = await self.page.evaluate("""() => {
                const editor = document.querySelector('[data-slate-editor="true"][contenteditable="true"]');
                if (!editor) return false;
                const er = editor.getBoundingClientRect();
                const nodes = Array.from(document.querySelectorAll('button, [role="button"], svg'));
                const candidates = nodes
                    .map(node => {
                        const rect = node.getBoundingClientRect();
                        return { node, rect, dx: rect.left - er.right, dy: Math.abs((rect.top + rect.bottom) / 2 - (er.top + er.bottom) / 2) };
                    })
                    .filter(item => item.rect.width > 0 && item.rect.height > 0)
                    .filter(item => item.dx > -20 && item.dx < 180 && item.dy < 80)
                    .sort((a, b) => (a.dy + Math.max(a.dx, 0)) - (b.dy + Math.max(b.dx, 0)));
                for (const item of candidates) {
                    const clickable = item.node.closest('button, [role="button"]') || item.node.parentElement;
                    if (clickable) {
                        clickable.click();
                        return true;
                    }
                }
                return false;
            }""")
            if sent:
                self._log("点击输入框附近发送控件")
                await asyncio.sleep(0.8)
                text = await input_box.evaluate('el => el.innerText || el.value || ""')
                if not text.strip():
                    return True
                if await self._saw_douyin_chat_request(start_marker, expected_text):
                    self._log("检测到抖音评论请求，按发送成功处理")
                    return True
        except Exception:
            pass

        return False

    async def _saw_douyin_chat_request(self, start_marker: float, expected_text: str = "") -> bool:
        """抖音 Slate 输入框可能不会马上清空，用真实评论请求作为成功信号。"""
        if not self.platform or getattr(self.platform, "name", "") != "douyin":
            return False
        try:
            return await self.page.evaluate("""({ since, text }) => {
                const entries = performance.getEntriesByType('resource') || [];
                const encoded = encodeURIComponent(text || '');
                return entries.some(entry => {
                    if (entry.startTime < since - 1000) return false;
                    if (!entry.name.includes('/webcast/room/chat/')) return false;
                    return true;
                });
            }""", {"since": start_marker, "text": expected_text})
        except Exception:
            return False

    async def _find_input_box(self):
        """查找评论输入框，多种策略尝试"""

        # 选择器由 platform 提供（快手/抖音 DOM 不同）
        if self.platform:
            input_selectors = self.platform.get_input_box_selectors()
        else:
            # 兜底：无 platform 时用通用选择器
            input_selectors = [
                'textarea[placeholder*="说"]',
                'textarea[placeholder*="弹幕"]',
                'textarea[placeholder*="评论"]',
                '[contenteditable="true"]',
                'textarea[placeholder]',
                'input[placeholder]',
            ]

        for selector in input_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for el in elements:
                    visible = await el.is_visible()
                    if visible:
                        self._log(f"找到输入框: {selector}")
                        return el
            except Exception:
                continue

        # 策略1.5：抖音聊天面板可能未展开，尝试点击展开
        if self.platform and self.platform.name == "douyin":
            try:
                clicked = await self.page.evaluate("""() => {
                    // 1. 精确：点击 data-e2e 属性的聊天入口（抖音最稳定的选择器）
                    const e2eTriggers = document.querySelectorAll(
                        '[data-e2e="chat-input"], [data-e2e="chatroom-input"], '
                        + '[data-e2e="chat-input-trigger"], [data-e2e="chat-input-placeholder"]'
                    );
                    for (const el of e2eTriggers) {
                        if (el.offsetParent !== null) { el.click(); return 'e2e'; }
                    }

                    // 2. 点击 placeholder 含"互动"/"说"的可点击区域（面板折叠时的提示条）
                    const phTriggers = document.querySelectorAll(
                        '[placeholder*="互动"], [placeholder*="说点"], '
                        + '[class*="chat-input"], [class*="chatroom-input"], '
                        + '[class*="input-placeholder"], [class*="editor-placeholder"]'
                    );
                    for (const el of phTriggers) {
                        if (el.offsetParent !== null) { el.click(); return 'placeholder'; }
                    }

                    // 3. 点击整个聊天区域（面板折叠态点击可展开）
                    const chatAreas = document.querySelectorAll(
                        '[class*="chatroom"], [class*="chat-room"], '
                        + '[data-e2e="chatroom"], [data-e2e="chatroom-container"]'
                    );
                    for (const el of chatAreas) {
                        if (el.offsetParent !== null) { el.click(); return 'chatroom'; }
                    }

                    // 4. 兜底：找页面右下角附近的可点击占位元素（折叠的聊天输入条）
                    const allDivs = document.querySelectorAll('div[placeholder], [data-placeholder]');
                    for (const el of allDivs) {
                        const rect = el.getBoundingClientRect();
                        // 聊天输入通常在页面右侧偏下方
                        if (rect.width > 100 && rect.height < 60
                            && rect.left > window.innerWidth * 0.5
                            && el.offsetParent !== null) {
                            el.click();
                            return 'fallback-placeholder';
                        }
                    }

                    return false;
                }""")
                if clicked:
                    self._log(f"点击展开抖音聊天面板（方式: {clicked}）...")
                    await asyncio.sleep(0.8)
                    # 重新查找输入框
                    for selector in input_selectors:
                        try:
                            elements = await self.page.query_selector_all(selector)
                            for el in elements:
                                visible = await el.is_visible()
                                if visible:
                                    self._log(f"展开后找到输入框: {selector}")
                                    return el
                        except Exception:
                            continue
            except Exception as e:
                self._log(f"展开聊天面板失败: {e}")

        # 策略2：调试模式 - 打印页面上所有可能的输入元素
        if not self._debug_logged:
            self._debug_logged = True
            await self._debug_print_inputs()

        return None

    async def _debug_print_inputs(self):
        """打印页面上所有输入元素，帮助确定正确的选择器"""
        self._log("===== 调试：页面输入元素 =====")
        try:
            info = await self.page.evaluate("""() => {
                const results = [];
                // 查找所有textarea/input/contenteditable
                const selectors = 'textarea, input[type="text"], input:not([type]), [contenteditable="true"], [contenteditable=""]';
                document.querySelectorAll(selectors).forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        index: i,
                        tag: el.tagName,
                        type: el.type || '',
                        class: (el.className || '').toString().slice(0, 100),
                        placeholder: el.placeholder || '',
                        contentEditable: el.contentEditable,
                        visible: rect.width > 0 && rect.height > 0,
                        id: el.id || '',
                        name: el.name || '',
                        dataE2e: el.getAttribute('data-e2e') || '',
                    });
                });
                return results;
            }""")

            for item in info:
                self._log(
                    f"  [{item['index']}] <{item['tag']}> type={item['type']} "
                    f"class={item['class'][:60]} placeholder={item['placeholder'][:30]} "
                    f"id={item['id']} data-e2e={item['dataE2e']} visible={item['visible']}"
                )

            if not info:
                self._log("页面上没有任何输入元素！可能弹幕区未展开。")
            self._log("===== 调试结束 =====")
        except Exception as e:
            self._log(f"调试打印失败: {e}")

    @property
    def comment_count(self) -> int:
        return self._comment_count
