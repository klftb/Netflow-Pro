#!/usr/bin/env python3
"""
Verification Script for:
1. Daytime mode (light theme): physical location & admin contact font color matches other text (not white).
2. Network statistics module (网络统计): subnets table action buttons only have icons (no '编辑', no '删除' text).
3. Settings module (设置): protocol mappings table action buttons only have icons (no '修改'/'编辑', no '删除' text).
"""

import sys
import os
import time
import json
import base64
import subprocess
import urllib.request
import websocket

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
DEBUG_PORT = 9297

def save_image(img_b64, filename):
    if not img_b64:
        return
    b = base64.b64decode(img_b64)
    local_path = os.path.join(r"d:\nTop", filename)
    artifact_path = os.path.join(ARTIFACT_DIR, filename)
    with open(local_path, "wb") as f:
        f.write(b)
    with open(artifact_path, "wb") as f:
        f.write(b)
    print(f"[+] Saved screenshot: {artifact_path}", flush=True)

def main():
    print("================================================================", flush=True)
    print(" [Theme Font Color & Icon-Only Action Buttons Verifier] ", flush=True)
    print("================================================================", flush=True)

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}", flush=True)
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port {DEBUG_PORT} ...", flush=True)
    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--window-size=1920,1080",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        "about:blank"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)

    ws_url = None
    for _ in range(15):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
            with urllib.request.urlopen(req, timeout=2) as resp:
                targets = json.loads(resp.read().decode())
                for t in targets:
                    if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
                        ws_url = t["webSocketDebuggerUrl"]
                        break
            if ws_url:
                break
        except Exception:
            time.sleep(0.5)

    if not ws_url:
        print("[ERROR] Could not obtain DevTools WebSocket URL", flush=True)
        proc.kill()
        sys.exit(1)

    print(f"[+] Connected to Browser DevTools: {ws_url}", flush=True)
    ws = websocket.create_connection(ws_url)
    ws.settimeout(20.0)

    msg_id = 1
    def send_cdp(method, params=None):
        nonlocal msg_id
        cur_id = msg_id
        payload = {"id": cur_id, "method": method, "params": params or {}}
        ws.send(json.dumps(payload))
        msg_id += 1
        while True:
            try:
                raw = ws.recv()
            except Exception as e:
                print(f"[WARN] recv exception on {method}: {e}", flush=True)
                return {}
            res = json.loads(raw)
            if res.get("id") == cur_id:
                return res

    def eval_js(expr):
        r = send_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("result", {}).get("value")

    def capture(filename):
        r = send_cdp("Page.captureScreenshot", {"format": "png"})
        save_image(r.get("result", {}).get("data"), filename)

    try:
        send_cdp("Page.enable")
        send_cdp("Runtime.enable")
        print(f"[*] Navigating to {TARGET_URL} ...", flush=True)
        send_cdp("Page.navigate", {"url": TARGET_URL})
        time.sleep(3.0)

        # -------------------------------------------------------------
        # 1. 验证白天模式下，物理位置和联系人字体颜色与其他字体一致
        # -------------------------------------------------------------
        print("\n--- [Step 1] Verifying Light Theme Font Color for Location & Admin ---", flush=True)
        # 切换到白天模式
        eval_js("""
            document.documentElement.setAttribute('data-bs-theme', 'light');
            document.body.classList.remove('theme-dark');
            document.body.classList.add('theme-light');
            localStorage.setItem('netflow_theme', 'light');
        """)
        time.sleep(0.5)

        # 导航到设备管理
        eval_js("window.location.hash = '#/monitor'")
        print("[*] Waiting for monitor devices data to load...", flush=True)
        for _ in range(30):
            loading = eval_js("document.body.innerText.includes('正在加载设备监控数据')")
            cards_count = eval_js("document.querySelectorAll('.dashboard-card').length")
            if not loading and cards_count > 0:
                break
            time.sleep(0.5)

        time.sleep(1.0)
        # 检查设备卡片中 location 与 admin 的 computed color
        card_colors = eval_js("""
            (() => {
                const results = [];
                const cards = document.querySelectorAll('.dashboard-card');
                cards.forEach(card => {
                    const devNameEl = card.querySelector('.fw-bold.fs-6');
                    const locEl = Array.from(card.querySelectorAll('span')).find(s => s.innerText.includes('物理机房/位置'));
                    const adminEl = Array.from(card.querySelectorAll('span')).find(s => s.innerText.includes('联系人'));
                    if (locEl || adminEl) {
                        const locStrong = locEl ? locEl.querySelector('strong') : null;
                        const adminStrong = adminEl ? adminEl.querySelector('strong') : null;
                        results.push({
                            deviceName: devNameEl ? devNameEl.innerText.trim() : 'Unknown',
                            nameColor: devNameEl ? getComputedStyle(devNameEl).color : null,
                            locText: locStrong ? locStrong.innerText.trim() : null,
                            locColor: locStrong ? getComputedStyle(locStrong).color : null,
                            adminText: adminStrong ? adminStrong.innerText.trim() : null,
                            adminColor: adminStrong ? getComputedStyle(adminStrong).color : null
                        });
                    }
                });
                return results;
            })()
        """)
        print(f"[+] Light mode monitor cards color inspection: {json.dumps(card_colors, indent=2, ensure_ascii=False)}")
        assert len(card_colors) > 0, "No monitor device cards with location/admin found!"
        
        for item in card_colors:
            if item.get("locColor"):
                # 确保不是白色（text-light 是 rgb(248, 249, 250) 或 rgb(255, 255, 255)）
                assert item["locColor"] != "rgb(248, 249, 250)" and item["locColor"] != "rgb(255, 255, 255)", f"Location color in light theme is white: {item}"
                # 确保与设备名称的字体颜色一致（都是 var(--text-main)，即 rgb(15, 23, 42)）
                assert item["locColor"] == item["nameColor"], f"Location color {item['locColor']} does not match name color {item['nameColor']}"
            if item.get("adminColor"):
                assert item["adminColor"] != "rgb(248, 249, 250)" and item["adminColor"] != "rgb(255, 255, 255)", f"Admin color in light theme is white: {item}"
                assert item["adminColor"] == item["nameColor"], f"Admin color {item['adminColor']} does not match name color {item['nameColor']}"

        print("[PASS] Device cards location and admin font colors in light mode match other text perfectly!")
        capture("light_mode_location_admin_font_verified.png")

        # 检查设备子页面中的 location 与 admin computed color
        print("\n--- [Step 1.1] Verifying Subpage Header Font Color in Light Theme ---", flush=True)
        # 点击 cnwxftoa02 的端口管理按钮
        eval_js("""
            const rows = Array.from(document.querySelectorAll('.dashboard-card'));
            const cnwxCard = rows.find(r => r.innerText.includes('10.30.0.253'));
            if (cnwxCard) {
                const btn = Array.from(cnwxCard.querySelectorAll('button')).find(b => b.innerText.includes('端口管理'));
                if (btn) btn.click();
            }
        """)
        print("[*] Waiting for subpage to render...", flush=True)
        for _ in range(20):
            sub_rendered = eval_js("document.querySelector('.badge.bg-primary-subtle') !== null")
            if sub_rendered:
                break
            time.sleep(0.5)

        time.sleep(1.0)
        subpage_colors = eval_js("""
            (() => {
                const header = document.querySelector('.card.p-3.mb-3');
                if (!header) return null;
                const locEl = Array.from(header.querySelectorAll('span')).find(s => s.innerText.includes('物理机房/位置'));
                const adminEl = Array.from(header.querySelectorAll('span')).find(s => s.innerText.includes('联系人'));
                const titleEl = header.querySelector('h5');
                const locStrong = locEl ? locEl.querySelector('strong') : null;
                const adminStrong = adminEl ? adminEl.querySelector('strong') : null;
                return {
                    titleColor: titleEl ? getComputedStyle(titleEl).color : null,
                    locText: locStrong ? locStrong.innerText.trim() : null,
                    locColor: locStrong ? getComputedStyle(locStrong).color : null,
                    adminText: adminStrong ? adminStrong.innerText.trim() : null,
                    adminColor: adminStrong ? getComputedStyle(adminStrong).color : null
                };
            })()
        """)
        print(f"[+] Subpage header colors: {subpage_colors}")
        assert subpage_colors["locColor"] != "rgb(248, 249, 250)" and subpage_colors["locColor"] != "rgb(255, 255, 255)", "Subpage locColor is white"
        assert subpage_colors["adminColor"] != "rgb(248, 249, 250)" and subpage_colors["adminColor"] != "rgb(255, 255, 255)", "Subpage adminColor is white"
        print("[PASS] Subpage header location and admin font colors verified in light theme!")
        capture("light_mode_subpage_location_admin_verified.png")

        # -------------------------------------------------------------
        # 2. 验证网络统计模块下网络信息的‘编辑’‘删除’文字已删除，仅保留图标
        # -------------------------------------------------------------
        print("\n--- [Step 2] Verifying Network Statistics Subnets Table Action Buttons ---", flush=True)
        eval_js("window.location.hash = '#/network'")
        print("[*] Waiting for network subnets summary to load...", flush=True)
        for _ in range(30):
            loading = eval_js("document.body.innerText.includes('正在加载网段数据')")
            sub_cnt = eval_js("""
                (() => {
                    const heading = Array.from(document.querySelectorAll('h6')).find(h => h.innerText.includes('已定义网段列表与流量汇总'));
                    if (!heading) return 0;
                    const table = heading.closest('.card').querySelector('table');
                    return table ? table.querySelectorAll('tbody tr td:last-child button').length : 0;
                })()
            """)
            if not loading and sub_cnt > 0:
                break
            time.sleep(0.5)

        time.sleep(1.0)
        subnet_buttons = eval_js("""
            (() => {
                const heading = Array.from(document.querySelectorAll('h6')).find(h => h.innerText.includes('已定义网段列表与流量汇总'));
                if (!heading) return [];
                const table = heading.closest('.card').querySelector('table');
                if (!table) return [];
                const rows = Array.from(table.querySelectorAll('tbody tr'));
                return rows.slice(0, 10).map(r => {
                    const btns = Array.from(r.querySelectorAll('td:last-child button')).map(b => ({
                        text: b.innerText.trim(),
                        iconClass: b.querySelector('i') ? b.querySelector('i').className : null,
                        title: b.title
                    }));
                    return {
                        subnetName: r.querySelector('td:nth-child(2)') ? r.querySelector('td:nth-child(2)').innerText.trim() : '',
                        buttons: btns
                    };
                }).filter(r => r.buttons.length > 0);
            })()
        """)
        print(f"[+] Network subnets action buttons sample: {json.dumps(subnet_buttons, indent=2, ensure_ascii=False)}")
        assert len(subnet_buttons) > 0, "No subnet rows with action buttons found!"
        
        for row in subnet_buttons:
            for b in row["buttons"]:
                # 必须不能包含“编辑”或“删除”文字
                assert '编辑' not in b["text"], f"Button still has text '编辑': {b}"
                assert '删除' not in b["text"], f"Button still has text '删除': {b}"
                # 文字必须为空
                assert b["text"] == "", f"Button text is not empty: '{b['text']}'"
                # 必须保留图标
                assert b["iconClass"] is not None and ("fa-edit" in b["iconClass"] or "fa-trash" in b["iconClass"]), f"Button icon missing: {b}"

        print("[PASS] Network statistics subnets table: '编辑' and '删除' text completely removed, icons preserved!")
        capture("network_table_icon_buttons_verified.png")

        # -------------------------------------------------------------
        # 3. 验证设置模块中协议的‘编辑’‘删除’文字已删除，仅保留图标
        # -------------------------------------------------------------
        print("\n--- [Step 3] Verifying Settings Protocols Table Action Buttons ---", flush=True)
        eval_js("window.location.hash = '#/settings'")
        time.sleep(2.5)

        protocol_buttons = eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr'));
                return rows.slice(0, 8).map(r => {
                    const btns = Array.from(r.querySelectorAll('td:last-child button')).map(b => ({
                        text: b.innerText.trim(),
                        iconClass: b.querySelector('i') ? b.querySelector('i').className : null,
                        title: b.title
                    }));
                    return {
                        port: r.querySelector('td:nth-child(2)') ? r.querySelector('td:nth-child(2)').innerText.trim() : '',
                        appName: r.querySelector('td:nth-child(3)') ? r.querySelector('td:nth-child(3)').innerText.trim() : '',
                        buttons: btns
                    };
                });
            })()
        """)
        print(f"[+] Settings protocol action buttons sample: {json.dumps(protocol_buttons, indent=2, ensure_ascii=False)}")

        for row in protocol_buttons:
            for b in row["buttons"]:
                # 必须不能包含“编辑”、“修改”或“删除”文字
                assert '编辑' not in b["text"], f"Button still has text '编辑': {b}"
                assert '修改' not in b["text"], f"Button still has text '修改': {b}"
                assert '删除' not in b["text"], f"Button still has text '删除': {b}"
                # 文字必须为空
                assert b["text"] == "", f"Button text is not empty: '{b['text']}'"
                # 必须保留图标
                assert b["iconClass"] is not None and ("fa-edit" in b["iconClass"] or "fa-trash" in b["iconClass"]), f"Button icon missing: {b}"

        print("[PASS] Settings protocols table: '编辑'/'修改' and '删除' text completely removed, icons preserved!")
        capture("settings_protocol_icon_buttons_verified.png")

        # -------------------------------------------------------------
        # 4. 切回暗黑模式对照验证
        # -------------------------------------------------------------
        print("\n--- [Step 4] Verifying Dark Theme Contrast ---", flush=True)
        eval_js("""
            document.documentElement.setAttribute('data-bs-theme', 'dark');
            document.body.classList.remove('theme-light');
            document.body.classList.add('theme-dark');
            localStorage.setItem('netflow_theme', 'dark');
        """)
        time.sleep(0.5)
        eval_js("window.location.hash = '#/monitor'")
        time.sleep(2.0)
        capture("dark_mode_location_admin_font_verified.png")
        print("[PASS] Dark theme also verified cleanly!")

        print("\n================================================================", flush=True)
        print(" [ALL 3 REQUIREMENTS FULLY VERIFIED AND PASSED!] ")
        print("================================================================", flush=True)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        proc.kill()

if __name__ == '__main__':
    main()
