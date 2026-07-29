"""多引擎管理器：同进程运行多个账号，共用浏览器进程和 LLM，随机分配评论发送

架构：
  - 1 个 chromium.launch()  （浏览器进程只开 1 次）
  - N 个 browser.new_context()  （每个账号一个独立上下文，cookie/storage 完全隔离）
  - 主账号 context：进直播间采集弹幕+语音，LLM 生成评论
  - 副账号 context：进直播间只发评论（slave 模式，core.start 内已处理）
  - 评论由 EngineManager._distribute_comment 随机分配给已就绪的账号发送
"""

import asyncio
import random
from typing import Callable

import yaml

from src.core import LiveCompanionEngine
from src.llm_client import LLMClient


class EngineManager:
    """管理多个 LiveCompanionEngine 实例，共用 browser + LLM，分配评论发送"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
        self.engines: list[LiveCompanionEngine] = []
        self._llm: LLMClient = None
        self._playwright = None
        self._browser = None
        self._comment_lock = asyncio.Lock()
        self.is_running = False

        # GUI 回调（转发）
        self.on_status: Callable[[str], None] = None
        self.on_danmu: Callable = None
        self.on_transcription: Callable = None
        self.on_comment: Callable[[str], None] = None
        self.on_error: Callable[[str], None] = None
        self.on_room_switch: Callable = None

    def _load_config(self) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    async def start(self):
        """启动所有引擎：1 个浏览器 + N 个上下文"""
        if self.is_running:
            return
        self.is_running = True

        accounts = self.config.get("accounts", [])
        if not accounts:
            # 回退单账号模式（EngineManager 仍接管，但只跑一个 master）
            accounts = [{"name": "主账号", "cookie_file": "cookies.json", "role": "master"}]

        # 创建共用 LLM（主账号和副账号共用，节省 API 费用）
        llm_config = self.config.get("llm", {})
        self._llm = LLMClient(llm_config)

        # ===== 启动 1 个共享浏览器进程 =====
        # 先用主 engine 的 _ensure_chromium 检测/安装 chromium
        probe = LiveCompanionEngine(self.config_path)
        if not probe._ensure_chromium():
            self._emit_error("chromium 检测失败，无法启动多账号模式")
            self.is_running = False
            return

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # ===== 创建所有引擎（共享 browser） =====
        for acc in accounts:
            engine = LiveCompanionEngine(
                self.config_path,
                cookie_file=acc.get("cookie_file", "cookies.json"),
                role=acc.get("role", "slave"),
            )
            engine.engine_id = acc.get("name", "未命名")
            # 共用 LLM
            engine._llm = self._llm
            # 绑定回调（status/error 带账号名前缀，便于区分）
            engine.on_status = lambda msg, name=engine.engine_id: self._emit_status(f"[{name}] {msg}")
            engine.on_danmu = self._emit_danmu
            engine.on_transcription = self._emit_transcription
            engine.on_comment = self._emit_comment
            engine.on_error = lambda msg, name=engine.engine_id: self._emit_error(f"[{name}] {msg}")
            engine.on_room_switch = self._emit_room_switch
            self.engines.append(engine)

        # 主引擎的评论生成回调指向分配器
        master = next((e for e in self.engines if e.role == "master"), self.engines[0])
        master.on_comment_generated = self._distribute_comment

        # ===== 启动所有引擎（共享 browser 传入） =====
        tasks = [e.start(shared_browser=self._browser) for e in self.engines]
        await asyncio.gather(*tasks)

    async def _distribute_comment(self, comment: str):
        """主引擎生成评论后调用，随机选一个已就绪引擎发送"""
        async with self._comment_lock:
            ready = [e for e in self.engines if e.is_ready_to_send()]
            if not ready:
                self._emit_status("无就绪账号可发送，跳过")
                return False
            target = random.choice(ready)
            success = await target.send_comment_direct(comment)
            if not success:
                self._emit_error(f"[{target.engine_id}] 评论发送失败")
            return success

    async def stop(self):
        """停止所有引擎：并发关各 context，再关共享 browser"""
        self.is_running = False
        # 并发停所有 engine（各自关闭自己的 context），耗时从 N×单账号 降为 单账号
        if self.engines:
            await asyncio.gather(*[e.stop() for e in self.engines], return_exceptions=True)
        # 再关共享 browser 和 playwright（各加 3 秒超时保护）
        if self._browser:
            try:
                await asyncio.wait_for(self._browser.close(), timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass
        if self._playwright:
            try:
                await asyncio.wait_for(self._playwright.stop(), timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass

    # ===== 回调转发 =====
    def _emit_status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def _emit_danmu(self, username, content):
        if self.on_danmu:
            self.on_danmu(username, content)

    def _emit_transcription(self, text):
        if self.on_transcription:
            self.on_transcription(text)

    def _emit_comment(self, text):
        if self.on_comment:
            self.on_comment(text)

    def _emit_error(self, msg: str):
        if self.on_error:
            self.on_error(msg)

    def _emit_room_switch(self):
        if self.on_room_switch:
            self.on_room_switch()
