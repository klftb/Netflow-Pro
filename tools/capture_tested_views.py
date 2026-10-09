#!/usr/bin/env python3
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
OUTPUT_API_IMAGE = r"d:\nTop\api_settings_tested_verified.png"
OUTPUT_TRAFFIC_IMAGE = r"d:\nTop\traffic_sessions_hostname_table_verified.png"

DEBUG_PORT = 9255

def main():
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
        print("Failed to get DevTools URL")
        proc.kill()
        sys.exit(1)

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
            print(f"[+] Saved: {out_path}")
            art_path = os.path.join(ARTIFACT_DIR, os.path.basename(out_path))
            shutil.copyfile(out_path, art_path)

    time.sleep(3.0)

    # 1. Test Settings -> API Tab and click test buttons
    print("[*] Navigating to Settings (#/settings)...")
    eval_js("window.location.hash = '#/settings'")
    time.sleep(1.0)
    
    # Click API tab and invoke testNetBox directly via Vue instance
    eval_js("""
    const app = document.querySelector('#app');
    const vm = app.__vue_app__._instance.proxy;
    vm.settingsSubTab = 'api';
    vm.testNetBox();
    """)
    print("[*] Waiting for NetBox test result...")
    time.sleep(2.5)

    capture_screenshot(OUTPUT_API_IMAGE)

    # 2. Test Traffic Analysis and scroll to table
    print("[*] Navigating to Traffic Analysis (#/traffic_analysis)...")
    eval_js("window.location.hash = '#/traffic_analysis'")
    time.sleep(2.0)

    # Refresh analytics and scroll .app-content to bottom
    eval_js("""
    const app = document.querySelector('#app');
    const vm = app.__vue_app__._instance.proxy;
    vm.fetchInterfaceAnalytics();
    """)
    time.sleep(2.0)

    eval_js("""
    const scrollContainer = document.querySelector('.app-content');
    if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }
    """)
    time.sleep(1.0)

    capture_screenshot(OUTPUT_TRAFFIC_IMAGE)

    ws.close()
    proc.kill()
    print("[+] Done!")

if __name__ == "__main__":
    main()
