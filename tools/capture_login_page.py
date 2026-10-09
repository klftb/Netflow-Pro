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
import tempfile

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/#/dashboard"

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
OUTPUT_IMG = r"d:\nTop\login_card_cleaned_verified.png"

DEBUG_PORT = 9266

def main():
    temp_profile = os.path.join(tempfile.gettempdir(), f"edge_login_{int(time.time())}")
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--remote-allow-origins=*",
        "--window-size=1920,1080",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        TARGET_URL
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)

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
        print("[!] Failed to get DevTools URL")
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
    send_cdp("Network.enable")
    send_cdp("Network.setCacheDisabled", {"cacheDisabled": True})
    send_cdp("Emulation.setDeviceMetricsOverride", {
        "width": 1920,
        "height": 1080,
        "deviceScaleFactor": 1,
        "mobile": False
    })

    def capture_screenshot(out_path):
        res = send_cdp("Page.captureScreenshot", {"format": "png", "quality": 100})
        b64 = res.get("result", {}).get("data", "")
        if b64:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"[+] Saved: {out_path}")
            art_path = os.path.join(ARTIFACT_DIR, os.path.basename(out_path))
            shutil.copyfile(out_path, art_path)
            print(f"[+] Copied to artifact: {art_path}")

    # 清空可能存在的 localStorage token 以展示干净的登录界面
    send_cdp("Page.navigate", {"url": TARGET_URL})
    time.sleep(3.0)

    send_cdp("Runtime.evaluate", {
        "expression": "localStorage.removeItem('flow_auth_token'); window.location.reload();",
        "awaitPromise": True
    })
    time.sleep(3.0)

    print("[*] 正在截取登录卡片视图...")
    capture_screenshot(OUTPUT_IMG)

    ws.close()
    proc.kill()

if __name__ == "__main__":
    main()
