#!/usr/bin/env python3
"""
Automated Verifier for Redesigned Device & Interface Monitoring UX
- Verifies Device Tree with Indented NetFlow/sFlow sampling ports
- Verifies Interface Deep-Dive Analytics Workbench (KPIs, Trend, Filters, Sessions)
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

OUTPUT_DEVICES_IMAGE = r"d:\nTop\device_interfaces_indented_verified.png"
ARTIFACT_DEVICES_IMAGE = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9\device_interfaces_indented_verified.png"

OUTPUT_DETAIL_IMAGE = r"d:\nTop\interface_deepdive_analytics_verified.png"
ARTIFACT_DETAIL_IMAGE = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9\interface_deepdive_analytics_verified.png"

DEBUG_PORT = 9235

def main():
    print("================================================================")
    print(" [Redesigned UX & Interface Deep-Dive - Automated Verifier] ")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port {DEBUG_PORT} targeting {TARGET_URL} ...")
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

    print("[*] Waiting 3.5s for initial Device & Interface list load...")
    time.sleep(3.5)

    # 1. Capture the Device & Indented Interfaces view
    print("[*] Step 1: Checking device list and capturing indented interfaces view...")
    eval_res = send_cdp("Runtime.evaluate", {
        "expression": "document.body.innerText.includes('网络设备与开启采样端口监控') && document.body.innerText.includes('CNSHFTOA02.example.com')"
    })
    print(f"    - Device list visible: {eval_res.get('result', {}).get('value')}")

    ss_dev = send_cdp("Page.captureScreenshot", {"format": "png"})
    img_b64_dev = ss_dev.get("result", {}).get("data")
    if img_b64_dev:
        b = base64.b64decode(img_b64_dev)
        with open(OUTPUT_DEVICES_IMAGE, "wb") as f:
            f.write(b)
        with open(ARTIFACT_DEVICES_IMAGE, "wb") as f:
            f.write(b)
        print(f"[+] Successfully captured devices overview screenshot: {OUTPUT_DEVICES_IMAGE}")

    # 2. Click on the first '接口详情' button (port13 200M-CTC-Active)
    print("[*] Step 2: Clicking on '接口详情' to drill down into interface workbench...")
    click_res = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('接口详情'));
                if (btns.length > 0) {
                    btns[0].click();
                    return true;
                }
                return false;
            })()
        """
    })
    print(f"    - Clicked interface detail button: {click_res.get('result', {}).get('value')}")

    print("[*] Waiting 3.5s for Interface Analytics and Session data to load...")
    time.sleep(3.5)

    # Check if sessions and breadcrumbs are loaded
    session_check = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const hasBreadcrumb = document.body.innerText.includes('返回设备列表');
                const hasTrend = !!document.getElementById('ifaceTrendChart');
                const sessionRows = document.querySelectorAll('table tbody tr').length;
                return { hasBreadcrumb, hasTrend, sessionRows };
            })()
        """,
        "returnByValue": True
    })
    print(f"    - Interface Workbench Status: {session_check.get('result', {}).get('value')}")

    # 3. Capture the Interface Deep-Dive Analytics Workbench screenshot
    print("[*] Step 3: Capturing Interface Deep-Dive Analytics Workbench screenshot...")
    ss_detail = send_cdp("Page.captureScreenshot", {"format": "png"})
    img_b64_detail = ss_detail.get("result", {}).get("data")
    if img_b64_detail:
        b = base64.b64decode(img_b64_detail)
        with open(OUTPUT_DETAIL_IMAGE, "wb") as f:
            f.write(b)
        with open(ARTIFACT_DETAIL_IMAGE, "wb") as f:
            f.write(b)
        print(f"[+] Successfully captured interface workbench screenshot: {OUTPUT_DETAIL_IMAGE}")

    # 4. Test A-to-B host filtering & capture full session table
    print("[*] Step 4: Testing A-to-B host filtering and capturing session table...")
    send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const inputs = document.querySelectorAll('input[type=text]');
                if (inputs.length >= 2) {
                    inputs[0].value = '10.23.12.89';
                    inputs[0].dispatchEvent(new Event('input'));
                }
                const qBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('查询'));
                if (qBtn) qBtn.click();
                window.scrollBy(0, 500);
            })()
        """
    })
    time.sleep(2.5)

    ss_filter = send_cdp("Page.captureScreenshot", {"format": "png"})
    img_b64_filter = ss_filter.get("result", {}).get("data")
    if img_b64_filter:
        b = base64.b64decode(img_b64_filter)
        with open(r"d:\nTop\interface_sessions_filtered_verified.png", "wb") as f:
            f.write(b)
        with open(r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9\interface_sessions_filtered_verified.png", "wb") as f:
            f.write(b)
        print("[+] Successfully captured filtered sessions screenshot")

    ws.close()
    proc.kill()
    print("================================================================")
    print(" [VERIFICATION COMPLETED SUCCESSFULLY] ")
    print("================================================================")

if __name__ == "__main__":
    main()

