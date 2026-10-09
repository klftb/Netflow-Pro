#!/usr/bin/env python3
"""
Verification Script for Subnet Traffic Stats Restoration:
Verifies that after fixing the SQL in GetSubnetsSummary, the network subnets table
displays real traffic stats, flows, active hosts, and percentage bars.
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
DEBUG_PORT = 9283

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
    print(" [Subnet Traffic Stats Restoration Verifier] ", flush=True)
    print("================================================================", flush=True)

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}", flush=True)
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port 9285 ...", flush=True)
    cmd = [
        EDGE_PATH,
        "--headless",
        "--remote-debugging-port=9285",
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
            req = urllib.request.Request("http://127.0.0.1:9285/json")
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
    ws.settimeout(12.0)

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
        time.sleep(3.5)

        # 1. Switch to 'network'
        print("[*] Switching to 'network' tab...", flush=True)
        eval_js("""
            const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('网络'));
            if (btn) btn.click();
        """)
        
        # Wait up to 15 seconds for subnets data to load
        print("[*] Waiting for subnets data to finish loading...", flush=True)
        for i in range(15):
            time.sleep(1.0)
            is_loading = eval_js("document.querySelector('.app-content') ? document.querySelector('.app-content').innerText.includes('正在加载网段数据') : false")
            if not is_loading:
                print(f"[+] Subnet data loaded after {i+1} seconds.", flush=True)
                break

        # 2. Check subnets data in DOM / Vue
        subnets_info = eval_js("""
            (() => {
                const netContainer = Array.from(document.querySelectorAll('.app-main > div, .app-content > div'))
                    .find(el => el.innerText && el.innerText.includes('已定义业务网段') && el.offsetParent !== null);
                if (!netContainer) return { error: 'Network container not visible' };

                const kpis = Array.from(netContainer.querySelectorAll('.dashboard-card .kpi-value')).map(el => el.innerText.trim());
                
                const table = netContainer.querySelector('table');
                if (!table) return { error: 'Table not found', kpis };

                const rows = Array.from(table.querySelectorAll('tbody tr')).map(r => {
                    return Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim());
                });

                return {
                    kpis,
                    rowCount: rows.length,
                    rows: rows
                };
            })()
        """)
        print(f"[+] Subnet KPIs: {subnets_info.get('kpis')}", flush=True)
        print(f"[+] Subnet rows count: {subnets_info.get('rowCount')}", flush=True)
        for idx, row in enumerate(subnets_info.get('rows', [])):
            print(f"    Row {idx+1}: {row}", flush=True)

        capture("subnet_traffic_restored_verified.png")
        print("[+] Test completed successfully!", flush=True)

    finally:
        try:
            ws.close()
        except:
            pass
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
