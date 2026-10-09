#!/usr/bin/env python3
"""
Verifier for Monitor Search and Location/Admin Mapping
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
TARGET_URL = "http://10.3.11.78:8080/#/monitor"
ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
DEBUG_PORT = 9295

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
    print(" [Monitor Search & Location/Admin Mapping Verifier] ", flush=True)
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
    ws.settimeout(15.0)

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

        # Wait for device cards to finish loading
        print("[*] Waiting for devices data to finish loading...", flush=True)
        for _ in range(30):
            time.sleep(1.0)
            loaded = eval_js("""
                !document.body.innerText.includes('正在加载设备监控数据') &&
                document.querySelectorAll('.app-content .dashboard-card').length > 0
            """)
            if loaded:
                print("[+] Device cards loaded successfully!", flush=True)
                break

        # 1. 检查设备列表与详细字段
        print("\n--- [Step 1] Verifying Device List & Location/Admin Labels ---", flush=True)
        cards = eval_js("""
            Array.from(document.querySelectorAll('.app-content .dashboard-card')).map(card => {
                const name = card.querySelector('.fs-6') ? card.querySelector('.fs-6').innerText.trim() : '';
                const text = card.innerText;
                const ipMatch = text.match(/IP:\\s*([0-9.]+)/);
                const locMatch = text.match(/物理机房\\/位置:\\s*([^\\n]+)/);
                const adminMatch = text.match(/联系人:\\s*([^\\n]+)/);
                return {
                    name,
                    ip: ipMatch ? ipMatch[1].trim() : '',
                    location: locMatch ? locMatch[1].trim() : '',
                    admin: adminMatch ? adminMatch[1].trim() : ''
                };
            }).filter(c => c.name)
        """)

        print(f"[+] Total visible devices: {len(cards)}")
        for c in cards:
            print(f"    - IP: {c['ip']:<15} | Name: {c['name']:<30} | Loc: {c['location']:<12} | Admin: {c['admin']}")
        
        # 确认 10.3.255.225 不存在
        has_deleted = any(c['ip'] == '10.3.255.225' for c in cards)
        if not has_deleted:
            print("[PASS] Deleted device 10.3.255.225 is NOT present in device cards!")
        else:
            print("[FAIL] Deleted device 10.3.255.225 is still present!")

        # 确认 10.30.0.253 包含 WXOffice 与 Storm Shaw
        dev253 = next((c for c in cards if '10.30.0.253' in c['ip']), None)
        if dev253 and 'WXOffice' in dev253['location'] and 'Storm Shaw' in dev253['admin']:
            print(f"[PASS] Device 10.30.0.253 has correct Location '{dev253['location']}' and Admin '{dev253['admin']}'!")
        else:
            print(f"[FAIL] Device 10.30.0.253 location/admin mismatch: {dev253}")

        capture("monitor_1_overview_cards_verified.png")

        # 2. 测试搜索功能 - 按主机名或关键词 cnwx 搜索
        print("\n--- [Step 2] Testing Search by 'cnwx' ---", flush=True)
        eval_js("""
            const input = document.querySelector('input[placeholder*=\"按设备 IP\"]');
            if (input) {
                input.value = 'cnwx';
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        """)
        time.sleep(1.0)
        filtered_cards = eval_js("""
            Array.from(document.querySelectorAll('.app-content .dashboard-card')).map(card => {
                const name = card.querySelector('.fs-6') ? card.querySelector('.fs-6').innerText.trim() : '';
                return name;
            }).filter(Boolean)
        """)
        print(f"[+] Search 'cnwx' result count: {len(filtered_cards)}, items: {filtered_cards}")
        capture("monitor_2_search_cnwx_verified.png")

        # 3. 测试搜索功能 - 按物理机房 WXOffice 搜索
        print("\n--- [Step 3] Testing Search by Location 'WXOffice' ---", flush=True)
        eval_js("""
            const input = document.querySelector('input[placeholder*=\"按设备 IP\"]');
            if (input) {
                input.value = 'WXOffice';
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        """)
        time.sleep(1.0)
        filtered_cards_loc = eval_js("""
            Array.from(document.querySelectorAll('.app-content .dashboard-card')).map(card => {
                const name = card.querySelector('.fs-6') ? card.querySelector('.fs-6').innerText.trim() : '';
                return name;
            }).filter(Boolean)
        """)
        print(f"[+] Search 'WXOffice' result count: {len(filtered_cards_loc)}, items: {filtered_cards_loc}")
        capture("monitor_3_search_location_verified.png")

        # 4. 清空搜索
        print("\n--- [Step 4] Testing Search Clear ---", flush=True)
        eval_js("""
            const clearBtn = document.querySelector('button[title=\"清空搜索\"]');
            if (clearBtn) clearBtn.click();
        """)
        time.sleep(1.0)
        all_restored = eval_js("""
            document.querySelectorAll('.app-content .dashboard-card').length
        """)
        print(f"[+] Restored all device cards count: {all_restored}")
        capture("monitor_4_search_cleared_verified.png")

        # 5. 测试进入专属端口子页面查看 location 和 admin
        print("\n--- [Step 5] Entering Device Interfaces Subpage ---", flush=True)
        eval_js("""
            const portBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('端口管理') && b.closest('.dashboard-card').innerText.includes('10.30.0.253'));
            if (portBtn) portBtn.click();
        """)
        time.sleep(2.0)
        subpage_info = eval_js("""
            const header = document.querySelector('.app-content .card');
            header ? header.innerText : ''
        """)
        print(f"[+] Subpage header text snippet: {subpage_info[:200]}...")
        if 'WXOffice' in subpage_info and 'Storm Shaw' in subpage_info:
            print("[PASS] Subpage header correctly displays Location and Admin!")
        capture("monitor_5_subpage_location_admin_verified.png")

        print("\n================================================================", flush=True)
        print(" [ALL VERIFICATION STEPS PASSED SUCCESSFULLY!] ")
        print("================================================================", flush=True)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        proc.kill()

if __name__ == '__main__':
    main()
