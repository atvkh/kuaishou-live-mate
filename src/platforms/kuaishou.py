"""快手平台实现

把 src/danmu.py 的 _process_payload、src/core.py 的 is_real_stream/登录/DOM 选择器
等快手专属逻辑迁移到这里。
"""

import gzip
from google.protobuf.json_format import MessageToDict
from src.kuaishou_pb2 import SocketMessage, SCWebFeedPush
from src.platforms.base import Platform


class KuaishouPlatform(Platform):
    """快手直播间实现"""

    name = "kuaishou"
    display_name = "快手"
    home_url = "https://live.kuaishou.com"
    login_check_js = """
        () => {
            const avatar = document.querySelector('[class*="avatar"]');
            const loginBtn = document.querySelector('[class*="login-btn"], [class*="LoginBtn"]');
            if (avatar && avatar.offsetParent !== null) return true;
            if (loginBtn && loginBtn.offsetParent === null) return true;
            return document.cookie.includes('userId') || document.cookie.includes('kuaishou.live.web_st');
        }
    """
    room_url_pattern = r"live\.kuaishou\.com"
    title_regex = r"^(.+?)(?:的直播间|[-_|])"
    default_system_prompt = (
        "你是一名快手直播间观众，根据主播语音和弹幕实时生成简短接地气的评论。"
        "要求：口语化、像真人、5-15字、避免刷屏、贴合直播内容。"
    )

    def is_real_stream(self, url: str, content_type: str = "") -> bool:
        """准确判断是否是快手直播流（基于抓包测试确认）

        快手直播流特征：
          URL: https://tx-origin.pull.yximgs.com/gifshow/{streamId}_{quality}.flv?txSecret=xxx&txTime=6
          Content-Type: video/x-flv
          CDN域名: *.pull.yximgs.com
        排除非流：
          static.yximgs.com（封面截图）、ntp.nc.gifshow.com（NTP）
        """
        url_lower = url.lower()
        ctype_lower = content_type.lower() if content_type else ""

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

    def match_danmu_ws_url(self, url: str) -> bool:
        """快手弹幕 WebSocket 域名匹配

        快手弹幕 WS 域名：livejs-ws.kuaishou.cn 等
        放宽匹配：任何 kuaishou 域名或 /websocket 路径都尝试监听
        """
        url_lower = url.lower()
        return "kuaishou" in url_lower or "livejs" in url_lower or "/websocket" in url_lower

    def parse_danmu_payload(self, data: bytes) -> list[tuple[str, str]]:
        """解析快手 Protobuf 弹幕

        payloadType=310 对应 SCWebFeedPush，包含弹幕/礼物/点赞等信息
        compressionType=2 表示 GZIP 压缩
        """
        results: list[tuple[str, str]] = []
        try:
            msg = SocketMessage()
            msg.ParseFromString(data)

            # 检查是否需要解压
            if msg.compressionType == 2:  # GZIP
                msg.payload = gzip.decompress(msg.payload)
            elif msg.compressionType == 3:  # AES
                print("[KuaishouPlatform] 警告：检测到AES加密，暂不支持解密")
                return results

            if msg.payloadType == 310:
                # SCWebFeedPush - 弹幕推送
                feed = SCWebFeedPush()
                feed.ParseFromString(msg.payload)
                obj = MessageToDict(feed, preserving_proto_field_name=True)

                for comment in obj.get("commentFeeds", []):
                    user_info = comment.get("user", {})
                    username = user_info.get("userName", "匿名")
                    content = comment.get("content", "")
                    if content:
                        results.append((username, content))
            # 其他 payloadType（300=进入房间确认、101/1=心跳）不产生弹幕
        except Exception as e:
            print(f"[KuaishouPlatform] payload解析错误: {e}")

        return results

    def get_player_selectors(self) -> list[str]:
        """快手播放器截图选择器"""
        return [
            'video',                    # 原生video标签
            '#player video',            # 快手播放器
            '.live-player',             # 快手播放器容器
            '.player-container',        # 通用播放器容器
            '[class*="player"] video',  # player类下的video
            '[class*="video-wrap"] video',  # 视频包裹
            '[class*="player"]',        # 任何player类元素
            'canvas',                   # 部分直播用canvas渲染
        ]

    def get_streamer_selectors(self) -> list[str]:
        """快手主播名 DOM 选择器"""
        return [
            '.user-name', '.live-room-info-name', '.author-name',
            '[class*="anchor"] [class*="name"]', '[class*="streamer"] [class*="name"]',
            '.player-room-info .user-name', '.room-info-wrapper .user-name',
        ]

    def get_category_selectors(self) -> list[str]:
        """快手直播分类/标签 DOM 选择器"""
        return [
            '.live-room-info-tag', '.tag-item', '.category-name',
            '[class*="tag"] [class*="name"]', '[class*="category"]',
            '.player-room-info .tag', '.room-info-wrapper .tag',
        ]

    def get_input_box_selectors(self) -> list[str]:
        """快手评论输入框选择器（含通用选择器作为兜底）"""
        return [
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

    @staticmethod
    def extract_live_stream_id(stream_url: str) -> str:
        """从快手直播流 URL 提取 liveStreamId

        抓包确认流 URL 格式：
            https://tx-origin.pull.yximgs.com/gifshow/{liveStreamId}_{quality}.flv?txSecret=...
        例：/gifshow/SSvKPyY5DMM_GameAvcFhdL3.flv  ->  SSvKPyY5DMM
        """
        if not stream_url:
            return ""
        import re
        # 匹配 /gifshow/{id}_{quality}.flv
        m = re.search(r"/gifshow/([A-Za-z0-9_-]+?)_[A-Za-z0-9_-]+\.flv", stream_url)
        if m:
            return m.group(1)
        # 兜底：取 /gifshow/ 后第一段（截到 .flv 或 _）
        m = re.search(r"/gifshow/([A-Za-z0-9_-]+?)(?:\.flv|_)", stream_url)
        if m:
            return m.group(1)
        return ""

    async def send_like(self, page, live_stream_id: str = "", count: int = 1) -> tuple[bool, dict]:
        """快手点赞：双击 video 元素触发前端点赞流程

        实测方案（v9 测试 10/10 成功）：
        - page.dblclick('video') 模拟双击直播画面
        - 前端事件处理器自动发 POST /live_api/liveroom/like
        - 浏览器拦截器自动加 __NS_hxfalcon 签名（isTrusted=true）
        - 响应 {"data":true} 表示成功

        为什么不用 page.evaluate(fetch(...))：
        - 脚本发起的 fetch 不会被前端拦截器加签名
        - 服务端返回 200 {"data":true} 但实际不计数（假成功）

        Args:
            page: Playwright Page（必须已进入直播间）
            live_stream_id: 未使用（前端自己知道）
            count: 未使用（每次双击只发 1 次点赞请求）
        Returns:
            (ok, detail)
        """
        try:
            await page.dblclick('video', timeout=5000, force=True)
            return True, {"method": "dblclick", "debug_info": "video double-clicked"}
        except Exception as e:
            return False, {"error": f"exception:{e}"}
