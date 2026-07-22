"""评论发送模块：通过Playwright自动化在快手直播间发送评论"""

import asyncio


class CommentSender:
    """通过Playwright模拟用户操作发送直播间评论"""

    def __init__(self, page, config: dict):
        self.page = page
        self.min_interval = config.get("min_interval", 20)
        self.max_interval = config.get("max_interval", 50)
        self.max_length = config.get("max_length", 20)
        self._last_send_time = 0
        self._comment_count = 0
        self._debug_logged = False  # 只打印一次调试信息

    async def send_comment(self, text: str) -> bool:
        """发送评论到直播间

        Args:
            text: 评论文本

        Returns:
            是否发送成功
        """
        if len(text) > self.max_length:
            text = text[: self.max_length]

        try:
            input_box = await self._find_input_box()
            if not input_box:
                print("[CommentSender] 未找到评论输入框")
                return False

            # 点击输入框使其获得焦点
            await input_box.click()
            await asyncio.sleep(0.3)

            # 清空已有内容并输入新文本
            await input_box.fill("")
            await asyncio.sleep(0.1)
            await input_box.fill(text)
            await asyncio.sleep(0.2)

            # 尝试按回车发送
            await input_box.press("Enter")
            await asyncio.sleep(0.5)

            self._last_send_time = asyncio.get_event_loop().time()
            self._comment_count += 1
            return True

        except Exception as e:
            print(f"[CommentSender] 发送评论错误: {e}")
            return False

    async def _find_input_box(self):
        """查找评论输入框，多种策略尝试"""

        # 策略1：按常见选择器查找
        input_selectors = [
            # 快手直播间常见选择器
            'textarea[placeholder*="说"]',
            'textarea[placeholder*="弹幕"]',
            'textarea[placeholder*="评论"]',
            'textarea[placeholder*="聊天"]',
            'input[placeholder*="说"]',
            'input[placeholder*="弹幕"]',
            'input[placeholder*="评论"]',
            # 按class查找
            'textarea[class*="chat"]',
            'textarea[class*="input"]',
            'textarea[class*="comment"]',
            'textarea[class*="danmu"]',
            'input[class*="chat"]',
            'input[class*="comment"]',
            # 按容器查找
            '.chat-input textarea',
            '.chat-input input',
            '.comment-input textarea',
            '.comment-input input',
            '.danmu-input textarea',
            '.danmu-input input',
            # 兜底
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
                        print(f"[CommentSender] 找到输入框: selector={selector}")
                        return el
            except Exception:
                continue

        # 策略2：调试模式 - 打印页面上所有可能的输入元素
        if not self._debug_logged:
            self._debug_logged = True
            await self._debug_print_inputs()

        return None

    async def _debug_print_inputs(self):
        """打印页面上所有输入元素，帮助确定正确的选择器"""
        print("[CommentSender] ===== 调试：页面输入元素 =====")
        try:
            info = await self.page.evaluate("""() => {
                const results = [];
                // 查找所有textarea/input/contenteditable
                const selectors = 'textarea, input[type="text"], input:not([type]), [contenteditable="true"]';
                document.querySelectorAll(selectors).forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        index: i,
                        tag: el.tagName,
                        type: el.type || '',
                        class: el.className || '',
                        placeholder: el.placeholder || '',
                        contentEditable: el.contentEditable,
                        visible: rect.width > 0 && rect.height > 0,
                        id: el.id || '',
                        name: el.name || '',
                    });
                });
                return results;
            }""")

            for item in info:
                print(f"  [{item['index']}] <{item['tag']}> type={item['type']} class={item['class'][:80]} placeholder={item['placeholder'][:30]} id={item['id']} visible={item['visible']}")

            if not info:
                print("[CommentSender] 页面上没有任何输入元素！可能弹幕区未展开。")
            print("[CommentSender] ===== 调试结束 =====")
        except Exception as e:
            print(f"[CommentSender] 调试打印失败: {e}")

    @property
    def comment_count(self) -> int:
        return self._comment_count
