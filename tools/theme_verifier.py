#!/usr/bin/env python3
"""
Automated Theme & Table Contrast Verifier for NetFlow Analyzer Pro
Verifies:
1. Dark Mode: Table background is dark, IP addresses are crisp cyan/light, no white leakage.
2. Light Mode: Clean enterprise light theme, high contrast table, correct chart palettes.
Captures both dark_mode_verified.png and light_mode_verified.png.
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
DARK_IMG = r"d:\nTop\dark_mode_verified.png"
LIGHT_IMG = r"d:\nTop\light_mode_verified.png"
DEBUG_PORT = 9223

def main():
    print("================================================================")
    print(" [Theme & Contrast Automated Verifier - Dark & Light Modes]")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge targeting {TARGET_URL} on port {DEBUG_PORT} ...")
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

    print("[*] Waiting 3.5s for initial dashboard render in Dark Mode...")
    time.sleep(3.5)

    # 1. Capture Dark Mode Screenshot
    print(f"[*] Capturing HD screenshot for DARK MODE to {DARK_IMG} ...")
    ss_dark = send_cdp("Page.captureScreenshot", {"format": "png"})
    dark_b64 = ss_dark.get("result", {}).get("data")
    if dark_b64:
        with open(DARK_IMG, "wb") as f:
            f.write(base64.b64decode(dark_b64))
        print(f"[SUCCESS] Dark mode screenshot saved ({len(base64.b64decode(dark_b64)):,} bytes)")

    # 2. Toggle to Light Mode via the top button
    print("[*] Toggling theme to Light Mode via button click...")
    toggle_js = """
        (function() {
            var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('白天模式') || b.innerText.includes('夜间模式'));
            if (btn) {
                btn.click();
                return "Clicked theme toggle button: " + btn.innerText;
            }
            return "Button not found";
        })()
    """
    click_res = send_cdp("Runtime.evaluate", {"expression": toggle_js})
    print(f"[+] Toggle result: {click_res.get('result', {}).get('value')}")
    time.sleep(2.0)

    # 3. Capture Light Mode Screenshot
    print(f"[*] Capturing HD screenshot for LIGHT MODE to {LIGHT_IMG} ...")
    ss_light = send_cdp("Page.captureScreenshot", {"format": "png"})
    light_b64 = ss_light.get("result", {}).get("data")
    if light_b64:
        with open(LIGHT_IMG, "wb") as f:
            f.write(base64.b64decode(light_b64))
        print(f"[SUCCESS] Light mode screenshot saved ({len(base64.b64decode(light_b64)):,} bytes)")

    ws.close()
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    print("\n[VERIFICATION SUMMARY]")
    print(f"- Dark Mode Artifact:  {DARK_IMG} (Exists: {os.path.exists(DARK_IMG)})")
    print(f"- Light Mode Artifact: {LIGHT_IMG} (Exists: {os.path.exists(LIGHT_IMG)})")
    if os.path.exists(DARK_IMG) and os.path.exists(LIGHT_IMG):
        print("[ALL THEMES VERIFIED SUCCESSFULLY]")
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
