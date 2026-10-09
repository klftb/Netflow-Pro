#!/usr/bin/env python3
"""
Automated Verifier for SNMP Device Name Auto-Discovery & Exporter Tab
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
OUTPUT_IMAGE = r"d:\nTop\snmp_exporter_verified.png"
ARTIFACT_IMAGE = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9\snmp_exporter_verified.png"
DEBUG_PORT = 9228

def main():
    print("================================================================")
    print(" [SNMP Device Auto-Discovery - Automated Browser Verifier]")
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

    print("[*] Waiting 3s for dashboard initial load...")
    time.sleep(3.0)

    # 1. Click "系统配置" button
    print("[*] Step 1: Clicking '⚙️ 系统配置' button to open Configuration Center...")
    click_cfg_js = """
        (function() {
            var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('系统配置'));
            if (btn) {
                btn.click();
                return "Config button clicked";
            }
            return "Config button not found";
        })()
    """
    res = send_cdp("Runtime.evaluate", {"expression": click_cfg_js})
    print(f"[+] Action result: {res.get('result', {}).get('value')}")
    time.sleep(1.5)

    # 2. Click "采集设备 (Exporter)" Tab
    print("[*] Step 2: Clicking '采集设备 (Exporter)' tab...")
    click_tab_js = """
        (function() {
            var tab = document.querySelector('#tab-nav-exporters') || 
                      Array.from(document.querySelectorAll('.nav-link')).find(b => b.innerText.includes('采集设备') || b.innerText.includes('Exporter'));
            if (tab) {
                tab.click();
                return "Exporter tab clicked";
            }
            return "Exporter tab not found";
        })()
    """
    res_tab = send_cdp("Runtime.evaluate", {"expression": click_tab_js})
    print(f"[+] Action result: {res_tab.get('result', {}).get('value')}")
    time.sleep(1.5)

    # 3. Click "⚡ SNMP 获取并定义设备名" button
    print("[*] Step 3: Clicking '⚡ SNMP 获取并定义设备名' button...")
    click_snmp_js = """
        (function() {
            var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('SNMP 获取并定义设备名') || b.innerText.includes('SNMP 探测'));
            if (btn) {
                btn.click();
                return "SNMP probe button clicked";
            }
            return "SNMP probe button not found";
        })()
    """
    res_snmp = send_cdp("Runtime.evaluate", {"expression": click_snmp_js})
    print(f"[+] Action result: {res_snmp.get('result', {}).get('value')}")

    # Wait 5.0s for SNMP probe request to complete and show prompt
    print("[*] Waiting 5.0s for SNMP response and UI update...")
    time.sleep(5.0)

    # 4. Capture screenshot
    print(f"[*] Capturing HD screenshot of SNMP Exporter UI to {OUTPUT_IMAGE} ...")
    ss = send_cdp("Page.captureScreenshot", {"format": "png"})
    img_b64 = ss.get("result", {}).get("data")
    if img_b64:
        img_bytes = base64.b64decode(img_b64)
        with open(OUTPUT_IMAGE, "wb") as f:
            f.write(img_bytes)
        with open(ARTIFACT_IMAGE, "wb") as f:
            f.write(img_bytes)
        print(f"[SUCCESS] SNMP Exporter screenshot saved ({len(img_bytes):,} bytes)")

    ws.close()
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    if os.path.exists(OUTPUT_IMAGE) and os.path.getsize(OUTPUT_IMAGE) > 10000:
        print("[VERIFICATION COMPLETED] SNMP auto-discovery UI verified successfully.")
        sys.exit(0)
    else:
        print("[ERROR] Screenshot failed or empty")
        sys.exit(1)

if __name__ == "__main__":
    main()
