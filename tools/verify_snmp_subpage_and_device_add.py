#!/usr/bin/env python3
"""
Verifier for SNMP Page Requirements:
1. Verifies that the top card is renamed to 'SNMP设备添加' with appropriate add actions.
2. Verifies that Interface Mapping is no longer flattened, but accessed via a dedicated sub-page
   from the Managed Devices Hub with a clear '← 返回托管设备清单' button.
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
DEBUG_PORT = 9288

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
    print(" [SNMP Device Add & Interface Sub-Page Verifier] ", flush=True)
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
        time.sleep(4.0)

        # 1. Switch to SNMP View
        print("\n--- [Step 1] Navigating to 'SNMP' View ---", flush=True)
        eval_js("""
            const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('SNMP'));
            if (btn) btn.click();
        """)
        time.sleep(2.0)

        # 2. Verify 'SNMP设备添加' card title and button
        print("\n--- [Step 2] Verifying 'SNMP设备添加' Card ---", flush=True)
        add_card_info = eval_js("""
            (() => {
                const h6 = Array.from(document.querySelectorAll('.app-content h6')).find(el => el.innerText.includes('SNMP设备添加'));
                const btn = Array.from(document.querySelectorAll('.app-content button')).find(el => el.innerText.includes('探测并添加设备'));
                return {
                    hasCardTitle: h6 !== undefined,
                    titleText: h6 ? h6.innerText.trim() : '',
                    hasAddButton: btn !== undefined,
                    buttonText: btn ? btn.innerText.trim() : ''
                };
            })()
        """)
        print(f"[+] SNMP Device Add card info: {add_card_info}", flush=True)
        assert add_card_info.get("hasCardTitle"), "Card title 'SNMP设备添加' not found!"
        assert add_card_info.get("hasAddButton"), "Button '探测并添加设备' not found!"
        capture("snmp_1_device_add_and_hub_verified.png")

        # 3. Enter Interface Mapping Sub-Page
        print("\n--- [Step 3] Entering Dedicated Interface Mapping Sub-Page ---", flush=True)
        eval_js("""
            const portBtn = Array.from(document.querySelectorAll('.app-content table tbody tr button')).find(b => b.innerText.includes('端口映射与描述'));
            if (portBtn) portBtn.click();
        """)
        time.sleep(2.0)

        subpage_info = eval_js("""
            (() => {
                const backBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('返回托管设备清单'));
                const title = Array.from(document.querySelectorAll('.app-content h5')).find(el => el.innerText.includes('设备接口定义与 SNMP 端口描述管理'));
                const rows = Array.from(document.querySelectorAll('.app-content table tbody tr')).map(r => {
                    return Array.from(r.querySelectorAll('td')).map(td => td.innerText.trim());
                });
                return {
                    hasBackBtn: backBtn !== undefined,
                    hasTitle: title !== undefined,
                    titleText: title ? title.innerText.trim() : '',
                    rowCount: rows.length,
                    sampleRow: rows[0] || []
                };
            })()
        """)
        print(f"[+] Subpage back button exists: {subpage_info.get('hasBackBtn')}", flush=True)
        print(f"[+] Subpage title: {subpage_info.get('titleText')}", flush=True)
        print(f"[+] Subpage interface rows: {subpage_info.get('rowCount')}", flush=True)
        print(f"[+] Sample row: {subpage_info.get('sampleRow')}", flush=True)
        assert subpage_info.get("hasBackBtn"), "Back button to devices list must exist in interface subpage!"
        capture("snmp_2_interface_subpage_verified.png")

        # 4. Return to Devices Hub
        print("\n--- [Step 4] Returning to Managed Devices Hub ---", flush=True)
        eval_js("""
            const backBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('返回托管设备清单'));
            if (backBtn) backBtn.click();
        """)
        time.sleep(1.0)

        devices_rendered = eval_js("""
            (() => {
                const h6 = Array.from(document.querySelectorAll('.app-content h6')).find(el => el.innerText.includes('托管网络设备清单与自定义属性中心'));
                return h6 !== undefined;
            })()
        """)
        print(f"[+] Successfully returned to devices hub: {devices_rendered}", flush=True)
        assert devices_rendered, "Should return to devices hub!"
        capture("snmp_3_return_devices_verified.png")

        print("[+] SNMP view requirements verification finished successfully!", flush=True)

    finally:
        try:
            ws.close()
        except:
            pass
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
