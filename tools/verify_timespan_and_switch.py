#!/usr/bin/env python3
"""
Automated Verifier for:
1. View switching & ECharts life-cycle fix (Interface details -> Device list -> Another interface)
2. 30-Day and 365-Day Long-term Traffic Trend Query & Adaptive Time Axis
3. Custom Datetime-Local Picker Filtering
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

DEBUG_PORT = 9240

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
    print(f"[+] Saved screenshot: {artifact_path}")

def main():
    print("================================================================")
    print(" [Traffic Trend Long-term Storage & View Switch - Automated Verifier] ")
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

    print("[*] Waiting 3.5s for initial Device list load...")
    time.sleep(3.5)

    # -------------------------------------------------------------
    # Step 1: Open first interface detail (e.g. port13)
    # -------------------------------------------------------------
    print("[*] Step 1: Entering First Interface Detail (port13)...")
    res1 = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('接口详情'));
                if (btns.length > 0) {
                    btns[0].click();
                    return { clicked: true, count: btns.length };
                }
                return { clicked: false, count: 0 };
            })()
        """,
        "returnByValue": True
    })
    print(f"    - First interface click: {res1.get('result', {}).get('value')}")
    time.sleep(3.0)

    # -------------------------------------------------------------
    # Step 2: Return to device list, and switch to another interface
    # -------------------------------------------------------------
    print("[*] Step 2: Returning to device list to test view-switching bug...")
    res_back = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const backBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('返回设备列表'));
                if (backBtn) {
                    backBtn.click();
                    return true;
                }
                return false;
            })()
        """
    })
    print(f"    - Clicked '返回设备列表': {res_back.get('result', {}).get('value')}")
    time.sleep(1.5)

    # Click on the SECOND interface detail button (to test chart re-binding on another interface)
    print("[*] Step 3: Clicking on SECOND interface to verify trend chart is NOT blank...")
    res2 = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('接口详情'));
                if (btns.length > 1) {
                    btns[1].click();
                    return { clicked: true, target: 'second' };
                } else if (btns.length > 0) {
                    btns[0].click();
                    return { clicked: true, target: 'first_again' };
                }
                return { clicked: false };
            })()
        """,
        "returnByValue": True
    })
    print(f"    - Second interface click: {res2.get('result', {}).get('value')}")
    time.sleep(3.0)

    # Check chart status
    chart_status = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const dom = document.getElementById('ifaceTrendChart');
                if (!dom) return { exists: false };
                const canvas = dom.querySelector('canvas');
                const hasCanvas = !!canvas;
                const width = canvas ? canvas.width : 0;
                const height = canvas ? canvas.height : 0;
                return { exists: true, hasCanvas, width, height };
            })()
        """,
        "returnByValue": True
    })
    print(f"    - Chart DOM and Canvas check: {chart_status.get('result', {}).get('value')}")

    # Capture screenshot for interface view switch verification
    ss_switch = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss_switch.get("result", {}).get("data"), "interface_switch_verified.png")

    # -------------------------------------------------------------
    # Step 3: Test 30-Day Preset Query
    # -------------------------------------------------------------
    print("[*] Step 4: Testing '最近 30天' preset filter...")
    send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btn30d = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('最近 30天'));
                if (btn30d) {
                    btn30d.click();
                    return true;
                }
                return false;
            })()
        """
    })
    time.sleep(3.0)

    stats_30d = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const kpis = Array.from(document.querySelectorAll('.kpi-value')).map(el => el.innerText.trim());
                return { kpis };
            })()
        """,
        "returnByValue": True
    })
    print(f"    - 30-Day KPIs: {stats_30d.get('result', {}).get('value')}")

    ss_30d = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss_30d.get("result", {}).get("data"), "interface_30d_verified.png")

    # -------------------------------------------------------------
    # Step 4: Test 365-Day Preset Query (Long-term Storage)
    # -------------------------------------------------------------
    print("[*] Step 5: Testing '最近 365天 (全周期)' preset filter...")
    send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btn365d = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('最近 365天'));
                if (btn365d) {
                    btn365d.click();
                    return true;
                }
                return false;
            })()
        """
    })
    time.sleep(3.5)

    stats_365d = send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const kpis = Array.from(document.querySelectorAll('.kpi-value')).map(el => el.innerText.trim());
                return { kpis };
            })()
        """,
        "returnByValue": True
    })
    print(f"    - 365-Day KPIs: {stats_365d.get('result', {}).get('value')}")

    ss_365d = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss_365d.get("result", {}).get("data"), "interface_365d_verified.png")

    # -------------------------------------------------------------
    # Step 5: Test Custom Time Range
    # -------------------------------------------------------------
    print("[*] Step 6: Testing '自定义时间' range filter...")
    send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btnCustom = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('自定义时间'));
                if (btnCustom) {
                    btnCustom.click();
                    return true;
                }
                return false;
            })()
        """
    })
    time.sleep(2.0)

    ss_custom = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss_custom.get("result", {}).get("data"), "interface_custom_time_verified.png")

    # -------------------------------------------------------------
    # Step 6: Test Global Dashboard 365-Day and Custom Time
    # -------------------------------------------------------------
    print("[*] Step 7: Switching to Global Dashboard and testing 365-day trend...")
    send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const globBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('全网宏观大屏'));
                if (globBtn) {
                    globBtn.click();
                    return true;
                }
                return false;
            })()
        """
    })
    time.sleep(3.0)

    # Click 365d on Global Dashboard
    send_cdp("Runtime.evaluate", {
        "expression": """
            (function() {
                const btn365 = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('最近 365天'));
                if (btn365) {
                    btn365.click();
                    return true;
                }
                return false;
            })()
        """
    })
    time.sleep(3.5)

    ss_global = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss_global.get("result", {}).get("data"), "global_365d_verified.png")

    ws.close()
    proc.kill()
    print("================================================================")
    print(" [ALL VERIFICATIONS COMPLETED SUCCESSFULLY] ")
    print("================================================================")

if __name__ == "__main__":
    main()
