"""抖音平台实现

抖音直播间技术栈：
- 弹幕：WebSocket + Protobuf（pushFrame/Response/Message 结构）
- 直播流：FLV/m3u8 @ *.pull-flv.com 等 CDN
- 签名：signature（基于 room_id + ttwid + 时间戳，算法在 webmssdk.js）
- 登录：扫码 + sessionid cookie

签名方案：通过 Playwright 在浏览器执行 JS 调用 webmssdk.js 的 sign 函数，
天然规避算法更新（浏览器加载的 webmssdk.js 永远是最新版）。

参考：DouyinLiveWebFetcher 项目、CSDN 抖音逆向系列文章
"""

import gzip
import struct
import time
from typing import Optional

from src.platforms.base import Platform


# === 抖音 Protobuf 定义（简化版，手工编写）===
# 实际生产环境建议用 protoc 从 douyin.proto 重新生成
try:
    from google.protobuf.runtime_version import domain as _protobuf_runtime
    from google.protobuf import descriptor as _descriptor
    from google.protobuf import descriptor_pool as _descriptor_pool
    from google.protobuf import symbol_database as _symbol_database
    from google.protobuf.internal import builder as _builder

    # 动态构建 protobuf descriptor（避免依赖外部 .proto 文件）
    # 这里采用纯 bytes 解析的兜底方案，因为抖音 schema 经常变化
    _HAS_PROTOBUF = True
except ImportError:
    _HAS_PROTOBUF = False


class DouyinPlatform(Platform):
    """抖音直播间实现"""

    name = "douyin"
    display_name = "抖音"
    home_url = "https://live.douyin.com"
    login_check_js = """
        () => {
            // 抖音登录态通过 sessionid / PASSID cookie 判断
            return document.cookie.includes('sessionid') ||
                   document.cookie.includes('sessionid_ss') ||
                   document.cookie.includes('PASSID');
        }
    """
    # 抖音直播间 URL：live.douyin.com/{数字ID}，精确匹配避免误判首页
    room_url_pattern = r"live\.douyin\.com/\d+"
    title_regex = r"^(.+?)(?:的.*?直播间|的直播|[-_|]直播|[-_|]\s*抖音)"
    default_system_prompt = (
        "你是一名抖音直播间观众，根据主播语音和弹幕实时生成简短接地气的评论。"
        "要求：口语化、像真人、5-15字、避免刷屏、贴合直播内容。"
    )

    def is_real_stream(self, url: str, content_type: str = "") -> bool:
        """判断是否是抖音直播流（基于真实抓包数据 2026-07-26）

        真实抓包结果：
          - FLV 流：https://pull-flv-l26.douyincdn.com/third/stream-xxx.flv
          - Content-Type: video/x-flv
          - 排除：lf-douyin-pc-web.douyinstatic.com（预览视频 mp4，不是直播流）
        """
        url_lower = url.lower()
        ctype_lower = content_type.lower() if content_type else ""

        # 先命中确定的直播流，避免后面的通用排除词误杀。
        if "video/x-flv" in ctype_lower:
            return True
        if "application/vnd.apple.mpegurl" in ctype_lower:
            return True
        if ("pull-flv-" in url_lower and "douyincdn.com" in url_lower
                and ".flv" in url_lower):
            return True
        if ("pull-hls-" in url_lower and "douyincdn.com" in url_lower
                and ".m3u8" in url_lower):
            return True
        if ("douyincdn.com" in url_lower and any(ext in url_lower for ext in [".flv", ".m3u8"])):
            return True

        # 排除非流请求（静态资源、API、预览视频）
        if any(kw in url_lower for kw in [
            ".js", ".css", ".png", ".jpg", ".webp", ".woff", ".svg", ".gif",
            ".json", "/api/", "/webcast/", "im-front", "rtc",
            "douyinstatic.com",  # 静态资源 CDN（含预览 mp4）
            "bytetos.com",       # 静态资源
            "bytetcc.com",       # 配置 CDN
        ]):
            return False

        return False

    def match_danmu_ws_url(self, url: str) -> bool:
        """抖音弹幕 WebSocket 域名匹配（基于真实抓包数据 2026-07-26）

        真实抓包结果：
          - 弹幕 WS：wss://webcast100-ws-web-hl.douyin.com/webcast/im/push/v2/?...
          - 含 /webcast/im/push/ 路径，signature 参数由服务端返回
          - 注意：frontier-pc.douyin.com 和 frontier-im.douyin.com 是其他业务 WS，不是弹幕
        """
        url_lower = url.lower()
        # 精确匹配弹幕 WS 路径
        if "/webcast/im/push/" in url_lower and "douyin.com" in url_lower:
            return True
        # 兜底：webcast*-ws-web-*.douyin.com 域名模式
        if "webcast" in url_lower and "-ws-web-" in url_lower and "douyin.com" in url_lower:
            return True
        return False

    async def check_logged_in(self, page, context=None) -> bool:
        """检测抖音登录态

        抖音 sessionid / sessionid_ss / PASSID 等关键 cookie 都是 HttpOnly，
        document.cookie 读不到，必须用 Playwright 的 context.cookies() API 读取。
        同时结合 DOM 检测作为兜底（登录后右上角显示头像）。
        """
        # 方式1：用 context.cookies() 读取 HttpOnly cookie（最可靠）
        if context is not None:
            try:
                cookies = await context.cookies()
                cookie_names = {c.get("name", "") for c in cookies}
                # 抖音登录态关键 cookie（HttpOnly，JS 读不到）
                if any(name in cookie_names for name in (
                    "sessionid", "sessionid_ss", "PASSID",
                    "sid_guard", "sid_tt", "uid_tt",
                )):
                    return True
            except Exception as e:
                print(f"[DouyinPlatform] check_logged_in cookie 读取失败: {e}")

        # 方式2：DOM 兜底检测（登录后右上角有头像，未登录显示"登录"按钮）
        try:
            return await page.evaluate("""
                () => {
                    // 已登录：右上角有头像元素
                    const avatar = document.querySelector(
                        '[data-e2e="login-avatar"], [class*="avatar"][class*="user"], '
                        '[class*="user-info"] [class*="avatar"], '
                        'header [class*="avatar"]'
                    );
                    if (avatar && avatar.offsetParent !== null) return true;
                    // 未登录：有"登录"按钮
                    const loginBtn = document.querySelector(
                        '[data-e2e="login"], [class*="login-button"], [class*="loginBtn"]'
                    );
                    if (loginBtn && loginBtn.offsetParent !== null) return false;
                    // 兜底：检查 cookie 中是否有非 HttpOnly 的登录态字段
                    return document.cookie.includes('LOGIN_STATUS') ||
                           document.cookie.includes('passport_csrf_token');
                }
            """)
        except Exception:
            return False

    def parse_danmu_payload(self, data: bytes) -> list[tuple[str, str]]:
        """解析抖音 Protobuf 弹幕（基于真实抓包数据 2026-07-26）

        真实 PushFrame 结构（抓包确认）：
          field 1 (varint): log_id
          field 2 (varint): timestamp（非 payload！之前的代码这里错了）
          field 3 (varint): ?
          field 4 (varint): ?
          field 5 (repeated bytes): headers（key-value 对，含 compress_type=gzip）
          field 7 (bytes): "hb" 心跳标识（仅心跳包）
          field 8 (bytes): payload（gzip 压缩，弹幕数据在这里！）

        Response（payload 解压后）{
          field 1 (repeated bytes): messages
          field 2 (string): internalExt
        }
        Message {
          field 1 (string): method  ("WebcastChatMessage"=弹幕)
          field 2 (bytes): payload  (ChatMessage 序列化)
        }
        ChatMessage {
          field 1 (bytes): user { field 1 (string): nickname }
          field 2 (string): content
        }
        """
        results: list[tuple[str, str]] = []
        try:
            # Step 1: 解析 PushFrame（外层）
            push_frame_fields = self._parse_protobuf_fields(data)

            # ★ 关键修正：payload 在 field 8，不是 field 2
            # field 2 是 timestamp（varint），field 8 才是 payload（bytes）
            payload_data = b""
            # 优先用 field 8（抓包确认）
            if 8 in push_frame_fields:
                payload_data = push_frame_fields[8]
            elif 2 in push_frame_fields:
                # 回退：旧版可能用 field 2（兼容）
                val = push_frame_fields[2]
                if isinstance(val, bytes):
                    payload_data = val

            if not payload_data:
                return results  # 心跳包没有 payload

            # Step 2: GZIP 解压 payload
            try:
                payload_data = gzip.decompress(payload_data)
            except Exception:
                pass  # 可能未压缩

            # Step 3: 解析 Response，提取 messages
            response_fields = self._parse_protobuf_fields(payload_data)
            messages_data = response_fields.get(1, b"")  # messages 字段（repeated）

            if not messages_data:
                return results

            # Step 4: 遍历 messages，提取弹幕
            # messages 是 repeated Message，每个 Message 是一个 length-delimited 字段
            messages = self._split_repeated_messages(messages_data)
            for msg_bytes in messages:
                msg_fields = self._parse_protobuf_fields(msg_bytes)
                method_bytes = msg_fields.get(1, b"")  # method
                inner_payload = msg_fields.get(2, b"")  # payload

                try:
                    method = method_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    method = ""

                if method != "WebcastChatMessage":
                    continue

                # 解析 ChatMessage
                chat_fields = self._parse_protobuf_fields(inner_payload)
                user_bytes = chat_fields.get(1, b"")  # user
                content = ""
                try:
                    content_raw = chat_fields.get(2, b"")  # content
                    content = content_raw.decode("utf-8", errors="ignore")
                except Exception:
                    pass

                # 解析 User.nickname
                username = "匿名"
                if user_bytes:
                    user_fields = self._parse_protobuf_fields(user_bytes)
                    try:
                        nickname = user_fields.get(1, b"").decode("utf-8", errors="ignore")
                        if nickname:
                            username = nickname
                    except Exception:
                        pass

                if content:
                    results.append((username, content))

        except Exception as e:
            print(f"[DouyinPlatform] payload解析错误: {e}")

        return results

    @staticmethod
    def _parse_protobuf_fields(data: bytes) -> dict:
        """轻量解析 protobuf wire format，提取字段号 -> 值的映射

        只解析 wire type 0 (varint)、2 (length-delimited)，
        跳过 1 (64-bit) 和 5 (32-bit)。
        对于 repeated 字段，返回最后一次出现的值（够用）。

        注意：这是兜底方案，对 schema 变化鲁棒但精度不如 protoc 生成的代码。
        """
        fields = {}
        i = 0
        while i < len(data):
            try:
                # 读 tag
                tag, i = DouyinPlatform._read_varint(data, i)
                field_number = tag >> 3
                wire_type = tag & 0x07

                if wire_type == 0:  # varint
                    value, i = DouyinPlatform._read_varint(data, i)
                    fields[field_number] = value
                elif wire_type == 2:  # length-delimited
                    length, i = DouyinPlatform._read_varint(data, i)
                    if i + length > len(data):
                        break
                    fields[field_number] = data[i:i + length]
                    i += length
                elif wire_type == 1:  # 64-bit
                    i += 8
                elif wire_type == 5:  # 32-bit
                    i += 4
                else:
                    break
            except Exception:
                break
        return fields

    @staticmethod
    def _read_varint(data: bytes, i: int) -> tuple[int, int]:
        """读取 protobuf varint 编码"""
        result = 0
        shift = 0
        while i < len(data):
            b = data[i]
            result |= (b & 0x7F) << shift
            i += 1
            if (b & 0x80) == 0:
                break
            shift += 7
        return result, i

    @staticmethod
    def _split_repeated_messages(data: bytes) -> list[bytes]:
        """把 repeated length-delimited 字段拆分成多个 message bytes"""
        messages = []
        i = 0
        while i < len(data):
            try:
                # 每个元素是 tag(1) + length + bytes
                tag, i = DouyinPlatform._read_varint(data, i)
                wire_type = tag & 0x07
                if wire_type != 2:
                    break
                length, i = DouyinPlatform._read_varint(data, i)
                if i + length > len(data):
                    break
                messages.append(data[i:i + length])
                i += length
            except Exception:
                break
        return messages

    async def prepare_danmu_connection(self, page) -> dict:
        """通过浏览器执行 JS 获取抖音弹幕连接参数

        在浏览器里调用 webmssdk.js 的 sign 函数，天然规避算法更新。
        """
        try:
            result = await page.evaluate("""
                async () => {
                    // 获取 room_id
                    const roomId = window.localStorage.getItem('roomId') ||
                                   (location.pathname.match(/(\\d+)/) || [,''])[1] ||
                                   '';

                    // 获取 ttwid
                    const ttwid = document.cookie.split('ttwid=')[1]?.split(';')[0] || '';

                    // signature：通过浏览器执行 webmssdk.js
                    let signature = '';
                    try {
                        // webmssdk.js 暴露的 sign 函数（不同版本可能不同）
                        if (typeof window.byted_acrawler === 'object' && window.byted_acrawler.frontierSign) {
                            const params = {
                                roomId: roomId,
                                ttwid: ttwid,
                            };
                            const signed = window.byted_acrawler.frontierSign(params);
                            signature = signed.signature || '';
                        }
                    } catch (e) {
                        console.log('sign error: ' + e.message);
                    }

                    return { roomId, ttwid, signature };
                }
            """)
            return result or {}
        except Exception as e:
            print(f"[DouyinPlatform] prepare_danmu_connection 失败: {e}")
            return {}

    async def build_auth_payload(self, conn_params: dict) -> Optional[bytes]:
        """构建抖音 WebSocket 鉴权 payload

        抖音需要发送 auth 包才能开始接收弹幕。
        """
        try:
            room_id = conn_params.get("roomId", "")
            ttwid = conn_params.get("ttwid", "")
            if not room_id:
                return None

            # 构建 auth JSON
            import json
            auth_data = {
                "common": {
                    "room_id": int(room_id) if room_id.isdigit() else 0,
                    "web_rid": room_id,
                },
                "fetch_schema": 1,
            }
            auth_json = json.dumps(auth_data, separators=(',', ':'))

            # 构建 PushFrame（外层 protobuf）
            # PushFrame {
            #   payloadType: string  = "proto"
            #   payload: bytes       = gzip(auth_json)
            # }
            payload_gzipped = gzip.compress(auth_json.encode("utf-8"))

            # 序列化 PushFrame
            auth_payload = self._encode_push_frame(payload_type="proto", payload=payload_gzipped)
            return auth_payload
        except Exception as e:
            print(f"[DouyinPlatform] build_auth_payload 失败: {e}")
            return None

    @staticmethod
    def _encode_push_frame(payload_type: str, payload: bytes) -> bytes:
        """编码 PushFrame protobuf"""
        result = b""
        # field 1: payloadType (string, wire type 2)
        pt_bytes = payload_type.encode("utf-8")
        result += DouyinPlatform._encode_varint((1 << 3) | 2)
        result += DouyinPlatform._encode_varint(len(pt_bytes))
        result += pt_bytes
        # field 2: payload (bytes, wire type 2)
        result += DouyinPlatform._encode_varint((2 << 3) | 2)
        result += DouyinPlatform._encode_varint(len(payload))
        result += payload
        return result

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        """编码 protobuf varint"""
        result = b""
        while value > 0x7F:
            result += bytes([0x80 | (value & 0x7F)])
            value >>= 7
        result += bytes([value & 0x7F])
        return result

    async def build_ack_payload(self, payload: bytes) -> Optional[bytes]:
        """构建 ack 应答 payload"""
        try:
            # 解析收到的 PushFrame，提取 log_id
            push_frame_fields = self._parse_protobuf_fields(payload)
            # log_id 在 field 3（参考调研文章）
            log_id = push_frame_fields.get(3, 0)
            if not log_id:
                return None

            # 构建 ack 响应
            # Response { internalExt: string, messages: [], cursor: string }
            # ack 内容：return log_id
            import json
            ack_data = json.dumps({"log_id": str(log_id)}, separators=(',', ':'))
            ack_gzipped = gzip.compress(ack_data.encode("utf-8"))
            return self._encode_push_frame(payload_type="ack", payload=ack_gzipped)
        except Exception as e:
            print(f"[DouyinPlatform] build_ack_payload 失败: {e}")
            return None

    def get_player_selectors(self) -> list[str]:
        """抖音播放器截图选择器

        抖音直播间 DOM 结构（基于调研，需实际抓包确认）：
          - video 标签是核心
          - .xgplayer 容器（西瓜播放器）
          - [data-e2e="player"] 抖音专属
        """
        return [
            'video',                            # 原生 video 标签
            '.xgplayer video',                  # 西瓜播放器
            '.xgplayer',                        # 西瓜播放器容器
            '[data-e2e="player"] video',        # 抖音播放器
            '[data-e2e="player"]',              # 抖音播放器容器
            '.player-container',                # 通用播放器容器
            '[class*="player"] video',          # player 类下的 video
            '[class*="player"]',                # 任何 player 类元素
            'canvas',                           # 兜底
        ]

    def get_streamer_selectors(self) -> list[str]:
        """抖音主播名 DOM 选择器"""
        return [
            '[data-e2e="anchor-name"]',                 # 抖音专属
            '[data-e2e="living-info-nickname"]',
            '.webcast-chatroom .anchor-name',
            '[class*="anchor"] [class*="name"]',
            '[class*="streamer"] [class*="name"]',
            '.user-name',
            '.author-name',
        ]

    def get_category_selectors(self) -> list[str]:
        """抖音直播分类/标签 DOM 选择器"""
        return [
            '[data-e2e="live-category"]',
            '[data-e2e="living-info-tag"]',
            '[class*="tag"] [class*="name"]',
            '[class*="category"]',
            '.tag-item',
            '.category-name',
        ]

    def get_input_box_selectors(self) -> list[str]:
        """抖音评论输入框选择器（基于真实抓包 DOM 2026-07-26）

        真实 DOM 结构：
          <div class="zone-container editor-kit-container GK5HNaLy notranslate chrome window chrome88"
               data-zone-id="0" data-zone-container="*"
               data-slate-editor="true" contenteditable="true"
               spellcheck="false" placeholder="与大家互动一下...">

        是 Slate.js 编辑器（contenteditable div），不是 textarea/input。
        """
        return [
            # 精确匹配（抓包确认）
            '[data-slate-editor="true"][contenteditable="true"]',
            'div.editor-kit-container[contenteditable="true"]',
            'div.zone-container[contenteditable="true"]',
            # 通配匹配
            '[contenteditable="true"][data-zone-id]',
            '[contenteditable="true"][placeholder*="互动"]',
            '[contenteditable="true"][placeholder*="说"]',
            # 兜底
            '.webcast-chatroom [contenteditable="true"]',
            '[class*="chatroom"] [contenteditable="true"]',
            '[class*="chat-input"] [contenteditable="true"]',
        ]

    async def send_comment_via_fetch(self, page, content: str) -> bool:
        """抖音专属评论发送：通过浏览器执行 fetch（基于真实抓包 2026-07-26）

        抓包确认：
          - 接口：GET https://live.douyin.com/webcast/room/chat/
          - 关键参数：content, room_id, type=0, rtf_content="", paste_edit_method=non_paste
          - 签名：msToken + a_bogus（由前端 webmssdk.js 自动拦截 fetch 添加）

        优势：
          - 不依赖 contenteditable div 的 DOM 操作（Slate.js 事件复杂，type+Enter 不稳定）
          - 浏览器自动处理 a_bogus 反爬签名（无法 Python 端生成）
          - 直接走真实 API，最稳定

        :param page: Playwright Page 实例
        :param content: 评论文本
        :return: 是否发送成功
        """
        try:
            result = await page.evaluate("""
                async (content) => {
                    try {
                        // 抖音页面路径上的数字是 web_rid，真正评论接口需要长 room_id。
                        // 优先从 SSR 数据和已加载资源里取长 room_id，最后才用路径兜底。
                        const pickRoomId = () => {
                            const candidates = [];
                            const addNum = (value) => {
                                const s = String(value || '').trim();
                                if (s && /^\\d{6,}$/.test(s)) candidates.push(s);
                            };

                            // 1. URL search params
                            try { addNum(new URLSearchParams(location.search).get('room_id')); } catch (_) {}

                            // 2. SSR 数据：__RENDER_DATA__ 和 __NEXT_DATA__（最可靠）
                            try {
                                for (const id of ['__RENDER_DATA__', '__NEXT_DATA__']) {
                                    const el = document.getElementById(id);
                                    if (!el) continue;
                                    const text = el.textContent || '';
                                    const matches = text.matchAll(/"room_?id"\\s*[:=]\\s*"?(\d{10,})"?/g);
                                    for (const m of matches) addNum(m[1]);
                                }
                            } catch (_) {}

                            // 3. localStorage
                            try { addNum(localStorage.getItem('roomId')); } catch (_) {}
                            try { addNum(localStorage.getItem('room_id')); } catch (_) {}

                            // 4. Performance API：/webcast/ 请求的 URL 参数
                            try {
                                const urls = performance.getEntriesByType('resource')
                                    .map(entry => entry.name)
                                    .filter(Boolean)
                                    .reverse();
                                for (const rawUrl of urls) {
                                    if (!rawUrl.includes('/webcast/')) continue;
                                    try {
                                        const u2 = new URL(rawUrl, location.origin);
                                        addNum(u2.searchParams.get('room_id'));
                                        const internalExt = u2.searchParams.get('internal_ext') || '';
                                        const extMatch = internalExt.match(/wss_push_room_id:(\\d+)/);
                                        if (extMatch) addNum(extMatch[1]);
                                    } catch(_) {}
                                }
                            } catch (_) {}

                            // 5. HTML 里所有 room_id 附近的10位+数字
                            try {
                                const html = document.documentElement.innerHTML;
                                const roomMatches = html.matchAll(/"room_?id"\\s*[:=]\\s*"?(\d{10,})"?/g);
                                for (const m of roomMatches) addNum(m[1]);
                            } catch (_) {}

                            // 6. 全局变量
                            try { addNum(window.__NEXT_DATA__?.props?.pageProps?.room?.room_id); } catch(_) {}

                            // 7. 路径兜底（web_rid，比长ID短）
                            const pathMatch = location.pathname.match(/\\/(\\d+)/);
                            if (pathMatch) addNum(pathMatch[1]);

                            // 优先返回最长的（长 room_id > 短 web_rid）
                            candidates.sort((a, b) => b.length - a.length);
                            return candidates[0] || '';
                        };

                        const roomId = pickRoomId();
                        if (!roomId) return { ok: false, error: '未找到 room_id' };

                        const chromePart = navigator.userAgent.split('Chrome/')[1] || '';
                        const browserVersion = chromePart.split(' ')[0] || '125.0.0.0';

                        // 构造请求参数（基于真实抓包 2026-07-26）
                        // 关键：enter_from 必须是 web_live（抓包确认），不能用 link_share
                        const params = new URLSearchParams({
                            aid: '6383',
                            app_name: 'douyin_web',
                            live_id: '1',
                            device_platform: 'web',
                            language: 'zh-CN',
                            enter_from: 'web_live',
                            cookie_enabled: 'true',
                            screen_width: String(window.screen.width),
                            screen_height: String(window.screen.height),
                            browser_language: navigator.language,
                            browser_platform: navigator.platform,
                            browser_name: 'Chrome',
                            browser_version: browserVersion,
                            os_name: 'Windows',
                            os_version: '10',
                            room_id: roomId,
                            content: content,
                            type: '0',
                            rtf_content: '',
                            paste_edit_method: 'non_paste',
                        });

                        const url = '/webcast/room/chat/?' + params.toString();

                        // 用 fetch 发送，credentials:'include' 确保带 cookie
                        // webmssdk.js 会自动拦截 fetch 并添加 msToken + a_bogus + bd-ticket-guard-* headers
                        // 不要手动设置 msToken/a_bogus（会被覆盖或冲突）
                        const resp = await fetch(url, {
                            method: 'GET',
                            credentials: 'include',
                            headers: {
                                'accept': 'application/json, text/plain, */*',
                            },
                        });

                        // 返回完整响应体，让 Python 侧根据真实结构判断
                        let body = null;
                        let bodyStr = '';
                        try {
                            bodyStr = await resp.text();
                            try { body = JSON.parse(bodyStr); } catch(_) {}
                        } catch (_) {}

                        return { ok: resp.ok, status: resp.status, roomId, body, bodyStr: bodyStr.slice(0, 500) };
                    } catch (e) {
                        return { ok: false, error: String(e) };
                    }
                }
            """, content)

            # 打印完整响应供调试（不再猜字段名）
            status = result.get('status')
            room_id = result.get('roomId')
            body_str = result.get('bodyStr', '')
            # 同时输出到 print（终端）和通过返回值让 sender 输出到 GUI
            print(f"[DouyinPlatform] fetch 响应: HTTP {status}, roomId={room_id}, bodyStr={body_str!r}")

            body = result.get("body") or {}

            # 根据真实响应结构判断成功：尝试多种常见字段名
            ok = False
            fail_reason = ""
            for code_field in ("status_code", "code", "err_code", "statusCode", "error_code"):
                if code_field in body:
                    code_val = body[code_field]
                    ok = (code_val == 0)
                    fail_reason = f"{code_field}={code_val}"
                    print(f"[DouyinPlatform] 判断字段: {code_field}={code_val} → {'成功' if ok else '失败'}")
                    break
            else:
                # 没找到任何状态码字段
                if result.get("ok") and body:
                    fail_reason = f"无状态码字段, body keys={list(body.keys())}"
                    print(f"[DouyinPlatform] 响应体无状态码字段，body keys={list(body.keys())}")
                    ok = False
                elif result.get("ok") and not body:
                    fail_reason = "无响应体"
                    ok = False
                else:
                    fail_reason = f"HTTP {status}"
                    ok = False

            # 把调试信息塞进 result，让 sender 能输出到 GUI
            result["debug_info"] = f"HTTP {status}, roomId={room_id}, body={body_str[:200]}, {fail_reason}"

            if ok:
                print(f"[DouyinPlatform] fetch 发送成功: {content[:20]}")
                return True, result
            else:
                print(f"[DouyinPlatform] fetch 发送失败: {result}")
                return False, result
        except Exception as e:
            print(f"[DouyinPlatform] send_comment_via_fetch 异常: {e}")
            return False

    async def send_like(self, page, live_stream_id: str = "", count: int = 1) -> tuple[bool, dict]:
        """抖音点赞：双击 video 元素触发前端点赞流程

        实测方案（douyin_like_verify_report.txt 验证 10/10 成功）：
        - page.dblclick('video') 模拟双击直播画面
        - 前端事件处理器自动发 POST /webcast/room/like/
        - 浏览器拦截器自动加 msToken + a_bogus 签名
        - 响应 {"status_code":0} 表示成功

        改进：页面可能有多个 video（广告/预览），选择面积最大的直播 video。
        备选：双击失败时尝试点击点赞按钮（心形图标）。

        Args:
            page: Playwright Page（必须已进入直播间）
            live_stream_id: 未使用（前端自己知道 room_id）
            count: 未使用（每次双击只发 1 次点赞请求）
        Returns:
            (ok, detail)
        """
        try:
            # 先检查页面是否有 video 元素及其状态
            video_info = await page.evaluate("""() => {
                const videos = Array.from(document.querySelectorAll('video'));
                if (videos.length === 0) return {count: 0, msg: '无 video 元素'};
                // 选择面积最大的 video（直播画面通常是最大的）
                let best = null, bestArea = 0;
                for (const v of videos) {
                    const rect = v.getBoundingClientRect();
                    const area = rect.width * rect.height;
                    if (area > bestArea) { bestArea = area; best = v; }
                }
                const r = best.getBoundingClientRect();
                return {
                    count: videos.length,
                    bestRect: {x: r.x, y: r.y, w: r.width, h: r.height},
                    bestSrc: (best.currentSrc || best.src || '').slice(0, 80),
                    readyState: best.readyState,
                };
            }""")
            print(f"[DouyinLike] video 状态: {video_info}")

            if not video_info or video_info.get("count", 0) == 0:
                return False, {"error": "页面无 video 元素"}

            # 双击面积最大的 video 的中心点（更精确）
            rect = video_info.get("bestRect", {})
            if rect and rect.get("w", 0) > 0:
                cx = rect["x"] + rect["w"] / 2
                cy = rect["y"] + rect["h"] / 2
                await page.mouse.dblclick(cx, cy, timeout=5000)
                return True, {"method": "mouse.dblclick", "debug_info": f"video@({cx:.0f},{cy:.0f})"}
            # 回退：直接 dblclick 选择器
            await page.dblclick('video', timeout=5000, force=True)
            return True, {"method": "dblclick", "debug_info": "video double-clicked (fallback)"}
        except Exception as e:
            err = str(e)
            print(f"[DouyinLike] 点赞异常: {err}")
            return False, {"error": f"exception:{err}"}
