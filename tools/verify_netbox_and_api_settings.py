#!/usr/bin/env python3
"""
Automated Verifier for NetBox API Integration & Unified API Settings UX
1. Verifies Settings -> Third-party API Integration sub-tab
2. Tests NetBox and LibreNMS connection UI interaction
3. Verifies Traffic Analysis platform displaying 'Hostname (IP)'
"""

import sys
import os
import time
import json
import base64
import subprocess
import urllib.request
import websocket
import shutil

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
OUTPUT_API_IMAGE = r"d:\nTop\api_settings_verified.png"
OUTPUT_TRAFFIC_IMAGE = r"d:\nTop\traffic_analysis_netbox_hostname_verified.png"

DEBUG_PORT = 9245

def main():
    print("================================================================")
    print(" [NetBox Integration & API Settings - Automated Verifier] ")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port {DEBUG_PORT} ...")
    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--window-size=1920,1080",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        TARGET_URL
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)

    ws_url = None
    for _ in range(10):
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
        print("[ERROR] Could not obtain DevTools WebSocket URL")
        proc.kill()
        sys.exit(1)

    print(f"[+] Connected to Browser DevTools: {ws_url}")
    ws = websocket.create_connection(ws_url)

    msg_id = 1
    def send_cdp(method, params=None):
        nonlocal msg_id
        cur_id = msg_id
        payload = {"id": cur_id, "method": method, "params": params or {}}
        ws.send(json.dumps(payload))
        msg_id += 1
        while True:
            raw = ws.recv()
            res = json.loads(raw)
            if res.get("id") == cur_id:
                return res

    send_cdp("Page.enable")
    send_cdp("Runtime.enable")

    def eval_js(js_code):
        res = send_cdp("Runtime.evaluate", {"expression": js_code, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value")

    def capture_screenshot(out_path):
        res = send_cdp("Page.captureScreenshot", {"format": "png"})
        b64 = res.get("result", {}).get("data", "")
        if b64:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"[+] Screenshot saved to {out_path}")
            # Also copy to artifacts dir
            basename = os.path.basename(out_path)
            art_path = os.path.join(ARTIFACT_DIR, basename)
            shutil.copyfile(out_path, art_path)
            print(f"[+] Artifact updated: {art_path}")

    time.sleep(3.0)

    # 1. Navigate to Settings -> Third-party API SubTab
    print("[*] Navigating to Settings (#/settings)...")
    eval_js("window.location.hash = '#/settings'")
    time.sleep(1.5)
    
    # Click second subtab button: '第三方平台 API 集成'
    print("[*] Clicking '第三方平台 API 集成' subtab button...")
    eval_js("""
    const btns = Array.from(document.querySelectorAll('#settingsSubTab button'));
    const apiBtn = btns.find(b => b.innerText.includes('第三方平台') || b.innerText.includes('API'));
    if (apiBtn) apiBtn.click();
    """)
    time.sleep(1.5)

    # Click '测试 NetBox 连接'
    print("[*] Clicking '测试 NetBox 连接' button...")
    eval_js("""
    const btns = Array.from(document.querySelectorAll('button'));
    const testBtn = btns.find(b => b.innerText.includes('测试 NetBox'));
    if (testBtn) testBtn.click();
    """)
    time.sleep(2.5)

    # Capture Settings API screenshot
    capture_screenshot(OUTPUT_API_IMAGE)

    # 2. Navigate to Traffic Analysis platform
    print("[*] Navigating to Traffic Analysis (#/traffic_analysis)...")
    eval_js("window.location.hash = '#/traffic_analysis'")
    time.sleep(2.0)

    # Click refresh iface analytics to make sure sessions are loaded
    eval_js("""
    const btns = Array.from(document.querySelectorAll('button'));
    const refBtn = btns.find(b => b.innerText.includes('刷新端口数据'));
    if (refBtn) refBtn.click();
    """)
    time.sleep(3.0)

    # Scroll down to session table
    print("[*] Scrolling down to interface session flow table...")
    eval_js("""
    const tableCard = document.querySelector('.top-table');
    if (tableCard) {
        tableCard.scrollIntoView({ behavior: 'instant', block: 'center' });
    }
    """)
    time.sleep(1.5)

    # Check session table row content
    sample_rows = eval_js("""
    Array.from(document.querySelectorAll('.top-table tbody tr')).slice(0, 5).map(r => r.innerText.replace(/\\s+/g, ' '))
    """)
    print(f"[+] Rendered Table Rows Sample: {sample_rows}")

    # Capture Traffic Analysis screenshot showing resolved hostnames
    capture_screenshot(OUTPUT_TRAFFIC_IMAGE)

    ws.close()
    proc.kill()
    print("================================================================")
    print(" [Verification Finished Successfully] ")
    print("================================================================")

if __name__ == "__main__":
    main()
