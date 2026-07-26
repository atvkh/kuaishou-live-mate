"""抖音评论发送抓包测试（在真实浏览器里测试 fetch 评论 + 打印完整响应）

用法：在直播伴侣运行期间，打开抖音直播间后执行：
    python scripts/douyin_chat_test.py

脚本会在浏览器控制台里执行 fetch 评论请求，并打印完整响应体。
不修改任何项目代码，纯诊断工具。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"))

from playwright.async_api import async_playwright

DOUYIN_HOME = "https://live.douyin.com"
DOUIN_HOME = DOUYIN_HOME  # alias

# 找 cookie
COOKIE_FILES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "旁白" / "cookies_douyin_main.json",
    PROJECT_ROOT / "cookies_douyin_main.json",
    PROJECT_ROOT / "cookies.json",
]
COOKIE_FILE = next((f for f in COOKIE_FILES if f.exists()), None)


async def main():
    print("=== 抖音评论 fetch 诊断工具 ===")
    print(f"Cookie: {COOKIE_FILE}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.add_init_script('Object.defineProperties(navigator, {webdriver:{get:()=>undefined}})')

        if COOKIE_FILE:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            print(f"已加载 {len(cookies)} 条 cookie")

        print(f"导航到: {DOUYIN_HOME}")
        await page.goto(DOUIN_HOME, wait_until="domcontentloaded", timeout=15000)

        print("\n请在浏览器中进入抖音直播间，然后按回车继续...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        url = page.url
        print(f"当前页面: {url}")

        # ── 1. 诊断 room_id 来源 ──
        print("\n" + "="*60)
        print("【1】room_id 来源诊断")
        print("="*60)

        room_info = await page.evaluate("""() => {
            const result = {};

            // pathname
            const pathMatch = location.pathname.match(/\\/(\\d+)/);
            result.pathname_id = pathMatch ? pathMatch[1] : '';

            // localStorage
            result.localStorage_roomId = localStorage.getItem('roomId') || '';
            result.localStorage_room_id = localStorage.getItem('room_id') || '';

            // performance entries 里的 room_id
            try {
                const entries = performance.getEntriesByType('resource') || [];
                const roomIds = new Set();
                for (const entry of entries) {
                    if (!entry.name.includes('/webcast/')) continue;
                    try {
                        const u = new URL(entry.name, location.origin);
                        const rid = u.searchParams.get('room_id');
                        if (rid) roomIds.add(rid);
                        // internal_ext 里也可能有
                        const ext = u.searchParams.get('internal_ext') || '';
                        const m = ext.match(/wss_push_room_id:(\\d+)/);
                        if (m) roomIds.add(m[1]);
                    } catch(_) {}
                }
                result.performance_room_ids = Array.from(roomIds);
            } catch(_) { result.performance_room_ids = []; }

            // __NEXT_DATA__ / __RENDER_DATA__
            result.next_data_room_id = '';
            result.render_data_room_id = '';
            try {
                const nd = document.getElementById('__NEXT_DATA__');
                if (nd) {
                    const text = nd.textContent || '';
                    const m = text.match(/"room_?id"\\s*:?\\s*"?([0-9]{10,})"?/);
                    if (m) result.next_data_room_id = m[1];
                }
                const rd = document.getElementById('__RENDER_DATA__');
                if (rd) {
                    const text = rd.textContent || '';
                    const m = text.match(/"room_?id"\\s*:?\\s*"?([0-9]{10,})"?/);
                    if (m) result.render_data_room_id = m[1];
                }
            } catch(_) {}

            // 页面 HTML 里所有长数字 ID
            try {
                const html = document.documentElement.innerHTML;
                const ids = new Set();
                const matches = html.match(/"room_?id"\\s*:?\\s*"?(\\d{10,})"?/g) || [];
                for (const m of matches) {
                    const idMatch = m.match(/(\\d{10,})/);
                    if (idMatch) ids.add(idMatch[1]);
                }
                result.html_room_ids = Array.from(ids).slice(0, 5);
            } catch(_) { result.html_room_ids = []; }

            // 全局变量
            result.global_roomId = '';
            try { result.global_roomId = String(window.__NEXT_DATA__?.props?.pageProps?.room?.room_id || ''); } catch(_) {}

            return result;
        }""")

        for k, v in room_info.items():
            print(f"  {k}: {v}")

        # 选最长的 room_id
        all_ids = []
        for v in room_info.values():
            if isinstance(v, str) and v and v.isdigit() and len(v) >= 6:
                all_ids.append(v)
            elif isinstance(v, list):
                all_ids.extend(v)
        all_ids.sort(key=len, reverse=True)
        best_room_id = all_ids[0] if all_ids else ""
        print(f"\n  → 最佳 room_id: {best_room_id} (长度={len(best_room_id)})")

        # ── 2. 测试 fetch 评论 + 打印完整响应 ──
        print("\n" + "="*60)
        print("【2】fetch 评论 API 测试（打印完整响应）")
        print("="*60)

        test_content = "测试123"
        fetch_result = await page.evaluate("""async ({roomId, content}) => {
            try {
                if (!roomId) return { error: 'no room_id' };

                const chromePart = navigator.userAgent.split('Chrome/')[1] || '';
                const browserVersion = chromePart.split(' ')[0] || '125.0.0.0';

                const params = new URLSearchParams({
                    aid: '6383',
                    app_name: 'douyin_web',
                    live_id: '1',
                    device_platform: 'web',
                    language: 'zh-CN',
                    enter_from: 'link_share',
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
                console.log('[TEST] fetch URL:', url);

                const resp = await fetch(url, {
                    method: 'GET',
                    credentials: 'include',
                    headers: { 'accept': 'application/json, text/plain, */*' },
                });

                const bodyText = await resp.text();
                return {
                    httpStatus: resp.status,
                    httpOk: resp.ok,
                    headers: Object.fromEntries(resp.headers.entries()),
                    bodyText: bodyText.slice(0, 2000),
                    bodyLength: bodyText.length,
                };
            } catch (e) {
                return { error: String(e) };
            }
        }""", {"roomId": best_room_id, "content": test_content})

        print(f"  HTTP 状态: {fetch_result.get('httpStatus')}")
        print(f"  HTTP OK: {fetch_result.get('httpOk')}")
        print(f"  响应头:")
        for k, v in (fetch_result.get("headers") or {}).items():
            print(f"    {k}: {v}")
        print(f"  响应体 (前2000字):")
        print(f"    {fetch_result.get('bodyText', '')}")

        # 尝试解析 JSON
        try:
            body_json = json.loads(fetch_result.get("bodyText", ""))
            print(f"\n  JSON 解析成功，顶层 keys: {list(body_json.keys())}")
            # 打印前2层结构
            import pprint
            pprint.pprint(body_json, width=120, depth=3)
        except Exception:
            print("  JSON 解析失败")

        # ── 3. DOM 信息 ──
        print("\n" + "="*60)
        print("【3】主播名 + 输入框 DOM")
        print("="*60)

        dom_info = await page.evaluate("""() => {
            const result = {};
            result.title = document.title;

            // 主播名
            const nameEls = document.querySelectorAll(
                '[data-e2e="anchor-nickname"], [data-e2e="anchor-name"], ' +
                '[data-e2e="living-info-nickname"], ' +
                '[class*="anchor"] [class*="name"], [class*="streamer"] [class*="name"], ' +
                '.user-name, .author-name'
            );
            result.name_candidates = [];
            nameEls.forEach(el => {
                result.name_candidates.push({
                    tag: el.tagName,
                    text: (el.innerText || '').trim().slice(0, 50),
                    class: (el.className || '').toString().slice(0, 100),
                    dataE2e: el.getAttribute('data-e2e') || '',
                    visible: el.offsetParent !== null,
                });
            });

            // 输入框
            const inputEls = document.querySelectorAll(
                'textarea, input[type="text"], input:not([type]), [contenteditable="true"]'
            );
            result.inputs = [];
            inputEls.forEach(el => {
                const rect = el.getBoundingClientRect();
                result.inputs.push({
                    tag: el.tagName,
                    placeholder: el.placeholder || el.getAttribute('placeholder') || '',
                    contentEditable: el.contentEditable,
                    dataSlateEditor: el.getAttribute('data-slate-editor') || '',
                    class: (el.className || '').toString().slice(0, 100),
                    visible: rect.width > 0 && rect.height > 0,
                    width: rect.width,
                    height: rect.height,
                });
            });

            return result;
        }""")

        print(f"  页面标题: {dom_info.get('title')}")
        print(f"  主播名候选:")
        for c in dom_info.get("name_candidates", []):
            print(f"    <{c['tag']}> text={c['text']!r} class={c['class'][:60]} data-e2e={c['dataE2e']} visible={c['visible']}")
        print(f"  输入框:")
        for inp in dom_info.get("inputs", []):
            print(f"    <{inp['tag']}> placeholder={inp['placeholder']!r} contentEditable={inp['contentEditable']} "
                  f"slate={inp['dataSlateEditor']} visible={inp['visible']} size={inp['width']:.0f}x{inp['height']:.0f}")

        print("\n=== 诊断完成 ===")
        print("请将以上输出发给开发者")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
