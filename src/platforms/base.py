"""平台抽象基类：定义各平台（快手/抖音/...）需要实现的接口

平台专属逻辑（弹幕协议、直播流检测、登录流程、DOM 选择器）通过本接口抽象，
core/danmu/sender/gui 模块只依赖 Platform 接口，不直接耦合具体平台。
"""

from abc import ABC, abstractmethod
from typing import Optional


class Platform(ABC):
    """平台抽象基类"""

    # === 类属性：基础元数据 ===
    name: str = ""                  # 平台标识 "kuaishou" / "douyin"
    display_name: str = ""          # 中文显示名 "快手" / "抖音"
    home_url: str = ""              # 登录/首页 URL
    login_check_js: str = ""        # 检测已登录的 JS 表达式（返回 bool）
    room_url_pattern: str = ""      # 直播间 URL 匹配正则
    title_regex: str = ""           # 页面 title 提取主播名正则
    default_system_prompt: str = ""  # 默认系统提示词

    # === 抽象方法：平台专属逻辑 ===

    @abstractmethod
    def is_real_stream(self, url: str, content_type: str = "") -> bool:
        """判断 URL 是否是直播流

        Args:
            url: 请求/响应 URL
            content_type: Content-Type 头
        Returns:
            True 表示是直播流
        """
        ...

    @abstractmethod
    def match_danmu_ws_url(self, url: str) -> bool:
        """判断 WebSocket URL 是否是弹幕通道

        Args:
            url: WebSocket 连接 URL
        Returns:
            True 表示是弹幕 WebSocket
        """
        ...

    @abstractmethod
    def parse_danmu_payload(self, data: bytes) -> list[tuple[str, str]]:
        """解析 WebSocket payload，提取弹幕列表（同步方法，因为在 Playwright 回调线程中调用）

        Args:
            data: WebSocket 帧的二进制 payload
        Returns:
            [(username, content), ...] 弹幕列表
        """
        ...

    @abstractmethod
    def get_player_selectors(self) -> list[str]:
        """返回播放器截图 CSS 选择器列表（按优先级）"""
        ...

    @abstractmethod
    def get_streamer_selectors(self) -> list[str]:
        """返回主播名 DOM 选择器列表"""
        ...

    @abstractmethod
    def get_category_selectors(self) -> list[str]:
        """返回直播分类/标签 DOM 选择器列表"""
        ...

    @abstractmethod
    def get_input_box_selectors(self) -> list[str]:
        """返回评论输入框 CSS 选择器列表"""
        ...

    async def prepare_danmu_connection(self, page) -> dict:
        """建立弹幕连接前的准备工作（可选）

        快手无需准备，抖音需要通过浏览器执行 JS 获取 signature/ttwid/room_id。
        子类按需覆盖。

        Args:
            page: Playwright Page 实例
        Returns:
            连接参数 dict（如 {"signature": "...", "ttwid": "...", "room_id": "..."}）
        """
        return {}

    async def check_logged_in(self, page, context=None) -> bool:
        """检测登录态（默认用 login_check_js，子类可覆盖为 cookie 检测）

        抖音 sessionid 等关键 cookie 是 HttpOnly，JS 读不到，
        需要在子类用 Playwright 的 context.cookies() API 读取。

        Args:
            page: Playwright Page 实例
            context: Playwright BrowserContext 实例（用于读取 HttpOnly cookie）
        Returns:
            True 表示已登录
        """
        try:
            return bool(await page.evaluate(self.login_check_js))
        except Exception:
            return False

    async def build_auth_payload(self, conn_params: dict) -> Optional[bytes]:
        """构建 WebSocket 鉴权 payload（可选）

        抖音需要发送 auth 包，快手不需要。
        子类按需覆盖。

        Args:
            conn_params: prepare_danmu_connection 返回的参数
        Returns:
            auth payload bytes，None 表示不需要
        """
        return None

    async def build_ack_payload(self, payload: bytes) -> Optional[bytes]:
        """构建 ack 应答 payload（可选）

        抖音需要 ack，快手不需要。
        子类按需覆盖。

        Args:
            payload: 收到的 payload（用于提取 log_id 等字段）
        Returns:
            ack payload bytes，None 表示不需要
        """
        return None

    async def send_like(self, page, live_stream_id: str = "", count: int = 1) -> tuple[bool, dict]:
        """发送一次点赞（可选，子类按需覆盖）

        推荐实现方式：DOM 点击点赞按钮（让前端自己发带签名的请求）。
        不推荐 page.evaluate(fetch(...))，因为前端拦截器不会给脚本发起的
        fetch 请求加 __NS_hxfalcon 签名，导致服务端假成功。

        Args:
            page: Playwright Page 实例（必须已进入直播间）
            live_stream_id: 直播流 ID（部分平台可能不需要）
            count: 点赞次数（默认 1）
        Returns:
            (ok, detail) detail 含 status_code / error / debug_info 等字段
        """
        return False, {"error": "not_implemented"}
