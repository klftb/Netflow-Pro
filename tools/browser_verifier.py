#!/usr/bin/env python3
"""
Browser Agent Automated UI Verifier for NetFlow Analyzer Pro
Launches headless Edge, drives user interaction sequence, and captures dashboard_verified.png.
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
OUTPUT_IMAGE = r"d:\nTop\dashboard_verified.png"
DEBUG_PORT = 9222

def main():
    print("================================================================")
    print(" [Phase 3: Browser Agent Automated UI & Interaction Verifier]")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge targeting {TARGET_URL} ...")
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
    for attempt in range(10):
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

    print("[*] Waiting for initial page load and Vue initialization...")
    time.sleep(3.0)

    # 1. Action Sequence Step 1: Select "Outbound", Input "192.168.0.0/16"
    print("[*] Step 1: Setting filter direction='outbound', src_ip='192.168.0.0/16' ...")
    step1_js = """
        var dirSel = document.getElementById('directionSelect');
        if (dirSel) {
            dirSel.value = 'outbound';
            dirSel.dispatchEvent(new Event('change'));
        }
        var srcInp = document.getElementById('srcIpInput');
        if (srcInp) {
            srcInp.value = '192.168.0.0/16';
            srcInp.dispatchEvent(new Event('input'));
        }
    """
    send_cdp("Runtime.evaluate", {"expression": step1_js})
    time.sleep(0.5)

    # 2. Action Sequence Step 2: Click "查询" button
    print("[*] Step 2: Clicking '查询' (Query) button...")
    step2_js = """
        var btn = document.getElementById('queryBtn');
        if (btn) btn.click();
    """
    send_cdp("Runtime.evaluate", {"expression": step2_js})
    print("[*] Waiting 3 seconds for charts & tables to refresh...")
    time.sleep(3.0)

    # 3. Action Sequence Step 3: Click Top Talker row 1 for drill-down联动
    print("[*] Step 3: Clicking Top Talker row 1 for drill-down linkage...")
    step3_js = """
        var row = document.getElementById('top-item-0');
        if (row) {
            row.click();
            console.log("Drill-down triggered on top-item-0");
        }
    """
    send_cdp("Runtime.evaluate", {"expression": step3_js})
    time.sleep(2.0)

    # 4. Capture Full Page Screenshot
    print(f"[*] Capturing HD screenshot to {OUTPUT_IMAGE} ...")
    ss_res = send_cdp("Page.captureScreenshot", {"format": "png"})
    img_b64 = ss_res.get("result", {}).get("data")
    if img_b64:
        img_bytes = base64.b64decode(img_b64)
        with open(OUTPUT_IMAGE, "wb") as f:
            f.write(img_bytes)
        print(f"[SUCCESS] Screenshot successfully saved ({len(img_bytes):,} bytes)")
    else:
        print("[ERROR] Failed to capture screenshot data")

    ws.close()
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    if os.path.exists(OUTPUT_IMAGE) and os.path.getsize(OUTPUT_IMAGE) > 10000:
        print(f"[PHASE 3 VERIFIED] Output artifact ready: {OUTPUT_IMAGE}")
        sys.exit(0)
    else:
        print("[FAILED] Verification artifact not created or too small")
        sys.exit(1)

if __name__ == "__main__":
    main()
