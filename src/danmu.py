"""弹幕采集模块：通过Playwright WebSocket拦截 + Protobuf解析读取快手直播间弹幕

参考项目: https://github.com/Superoff/kuaishou_websocket
核心原理: 快手直播间通过WebSocket推送Protobuf编码的弹幕数据，
         payloadType=310 对应 SCWebFeedPush，包含弹幕/礼物/点赞等信息
"""

import asyncio
import base64
import threading
import gzip
from google.protobuf.json_format import MessageToDict
from src.kuaishou_pb2 import SocketMessage, SCWebFeedPush

# 注入到页面的JS：hook WebSocket构造函数，捕获所有WebSocket消息
# 作为Playwright原生websocket事件的备选方案
WS_HOOK_JS = """
() => {
    if (window._ws_hooked) return;
    window._ws_hooked = true;
    window._ws_messages = [];
    window._ws_urls = [];

    const OriginalWebSocket = window.WebSocket;
    const HookedWebSocket = function(url, protocols) {
        console.log('[WS-Hook] WebSocket created: ' + url);
        window._ws_urls.push(url);

        let ws;
        if (protocols) {
            ws = new OriginalWebSocket(url, protocols);
        } else {
            ws = new OriginalWebSocket(url);
        }

        ws.addEventListener('message', function(event) {
            try {
                let data = event.data;
                if (data instanceof Blob) {
                    let reader = new FileReader();
                    reader.onload = function() {
                        let bytes = new Uint8Array(reader.result);
                        let binary = '';
                        let chunkSize = 8192;
                        for (let i = 0; i < bytes.length; i += chunkSize) {
                            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
                        }
                        window._ws_messages.push(btoa(binary));
                        if (window._ws_messages.length > 200) {
                            window._ws_messages = window._ws_messages.slice(-100);
                        }
                    };
                    reader.readAsArrayBuffer(data);
                } else if (data instanceof ArrayBuffer) {
                    let bytes = new Uint8Array(data);
                    let binary = '';
                    let chunkSize = 8192;
                    for (let i = 0; i < bytes.length; i += chunkSize) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
                    }
                    window._ws_messages.push(btoa(binary));
                    if (window._ws_messages.length > 200) {
                        window._ws_messages = window._ws_messages.slice(-100);
                    }
                }
            } catch(e) {
                console.log('[WS-Hook] Error: ' + e.message);
            }
        });

        return ws;
    };
    HookedWebSocket.prototype = OriginalWebSocket.prototype;
    HookedWebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
    HookedWebSocket.OPEN = OriginalWebSocket.OPEN;
    HookedWebSocket.CLOSING = OriginalWebSocket.CLOSING;
    HookedWebSocket.CLOSED = OriginalWebSocket.CLOSED;
    window.WebSocket = HookedWebSocket;
    console.log('[WS-Hook] WebSocket hook installed');
}
"""


class DanmuReader:
    """通过Playwright WebSocket拦截 + Protobuf解析读取弹幕"""

    def __init__(self, page):
        self.page = page
        self._running = False
        self._ws_connected = False
        self._raw_queue = []  # 线程安全的原始弹幕缓冲
        self._lock = threading.Lock()
        self._callback = None

        # 立即注册WebSocket监听器，必须在页面加载前注册
        self.page.on("websocket", self._on_websocket)

    async def start(self, callback):
        """开始监听弹幕

        Args:
            callback: 弹幕回调 async (username, content) -> None
        """
        self._running = True
        self._callback = callback

        # 弹幕去重：记录最近处理过的 (username, content) 指纹，避免双通道重复
        recent_fingerprints = []  # [(fingerprint, timestamp), ...]
        max_fingerprint_age = 10  # 10秒内的相同弹幕视为重复

        def is_duplicate(username: str, content: str) -> bool:
            """检查是否是近期已处理过的弹幕"""
            import time
            now = time.time()
            fp = f"{username}|{content}"
            # 清理过期指纹
            nonlocal recent_fingerprints
            recent_fingerprints = [(f, t) for f, t in recent_fingerprints if now - t < max_fingerprint_age]
            # 检查是否已存在
            for f, _ in recent_fingerprints:
                if f == fp:
                    return True
            # 记录新指纹
            recent_fingerprints.append((fp, now))
            return False

        if self._ws_connected:
            self._emit_log("WebSocket已连接，开始处理弹幕")
        else:
            self._emit_log("等待直播间WebSocket连接...")

        # 持续处理弹幕队列
        while self._running:
            try:
                # 方式1：从Playwright原生WebSocket事件缓冲区取弹幕
                with self._lock:
                    items = self._raw_queue[:]
                    self._raw_queue.clear()

                for username, content in items:
                    if content and self._callback:
                        if is_duplicate(username, content):
                            self._emit_log(f"跳过重复弹幕(原生): {username}: {content}")
                            continue
                        self._emit_log(f"弹出弹幕给callback: {username}: {content}")
                        await self._callback(username, content)

                # 方式2：从JS hook读取WebSocket消息（备选方案）
                try:
                    result = await self.page.evaluate(
                        "() => { const m = window._ws_messages || []; window._ws_messages = []; return m; }"
                    )
                    if result:
                        self._emit_log(f"从JS hook读取到 {len(result)} 条WebSocket消息")
                        for b64 in result:
                            try:
                                payload = base64.b64decode(b64)
                                self._process_payload(payload)
                            except Exception as e:
                                self._emit_log(f"JS hook消息解析错误: {e}")

                        # 处理完JS hook的消息后，再次取出新弹幕
                        with self._lock:
                            items = self._raw_queue[:]
                            self._raw_queue.clear()
                        for username, content in items:
                            if content and self._callback:
                                if is_duplicate(username, content):
                                    self._emit_log(f"跳过重复弹幕(JS-hook): {username}: {content}")
                                    continue
                                self._emit_log(f"JS-hook弹幕: {username}: {content}")
                                await self._callback(username, content)
                except Exception as e:
                    # JS evaluate可能失败（页面未就绪等），静默跳过
                    pass

                # 检查JS hook是否检测到WebSocket
                if not self._ws_connected:
                    try:
                        urls = await self.page.evaluate(
                            "() => window._ws_urls || []"
                        )
                        if urls:
                            self._ws_connected = True
                            self._emit_log(f"JS hook检测到WebSocket连接: {urls[-1]}")
                    except Exception:
                        pass

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._emit_log(f"弹幕处理错误: {e}")
                await asyncio.sleep(1)

    def _on_websocket(self, ws):
        """Playwright WebSocket事件回调"""
        url = ws.url
        self._emit_log(f"检测到WebSocket: {url}")

        # 快手弹幕WebSocket域名是 livejs-ws.kuaishou.cn
        # 放宽匹配：任何kuaishou域名的WebSocket都尝试监听
        if "kuaishou" in url or "livejs" in url or "/websocket" in url:
            self._emit_log("已连接到快手弹幕WebSocket!")
            self._ws_connected = True
            ws.on("framereceived", self._on_frame_received)
            ws.on("close", lambda: self._on_ws_close())
        else:
            self._emit_log(f"非弹幕WebSocket，跳过: {url}")

    def _on_frame_received(self, payload):
        """处理WebSocket收到的帧（在Playwright的线程中调用，不是asyncio线程）"""
        try:
            # Playwright异步API可能传递字典而非bytes
            if isinstance(payload, dict):
                self._emit_log(f"帧是字典，keys={list(payload.keys())}")
                payload = payload.get("data", payload.get("payload", b""))

            if isinstance(payload, str):
                self._emit_log("帧是文本，可能是JSON，跳过")
                return

            if not isinstance(payload, (bytes, bytearray)):
                self._emit_log(f"帧不是bytes类型: {type(payload)}")
                return

            self._process_payload(bytes(payload))

        except Exception as e:
            self._emit_log(f"帧解析错误: {e}")

    def _process_payload(self, payload: bytes):
        """解析Protobuf格式的WebSocket payload"""
        try:
            # 解析Protobuf消息
            msg = SocketMessage()
            msg.ParseFromString(payload)

            self._emit_log(f"收到帧 payloadType={msg.payloadType} compressionType={msg.compressionType} payload大小={len(msg.payload)}")

            # 检查是否需要解压
            if msg.compressionType == 2:  # GZIP
                msg.payload = gzip.decompress(msg.payload)
            elif msg.compressionType == 3:  # AES
                self._emit_log("警告：检测到AES加密，暂不支持解密")
                return

            if msg.payloadType == 310:
                # SCWebFeedPush - 弹幕推送
                feed = SCWebFeedPush()
                feed.ParseFromString(msg.payload)
                obj = MessageToDict(feed, preserving_proto_field_name=True)

                # 处理弹幕评论
                comments = obj.get("commentFeeds", [])
                if comments:
                    self._emit_log(f"解析到 {len(comments)} 条弹幕")

                for comment in comments:
                    user_info = comment.get("user", {})
                    username = user_info.get("userName", "匿名")
                    content = comment.get("content", "")
                    self._emit_log(f"弹幕详情: user={username} content={repr(content)}")
                    if content:
                        with self._lock:
                            self._raw_queue.append((username, content))

            elif msg.payloadType == 300:
                self._emit_log("收到进入房间确认(300)，等待弹幕推送...")
            elif msg.payloadType == 101:
                pass  # 心跳回复
            elif msg.payloadType == 1:
                pass  # 心跳
            else:
                self._emit_log(f"未处理的消息类型: {msg.payloadType}")

        except Exception as e:
            self._emit_log(f"payload解析错误: {e}")

    def _on_ws_close(self):
        """WebSocket关闭回调"""
        self._ws_connected = False
        self._emit_log("弹幕WebSocket已断开")

    def _emit_log(self, msg: str):
        print(f"[DanmuReader] {msg}")

    def stop(self):
        self._running = False
        self._ws_connected = False
