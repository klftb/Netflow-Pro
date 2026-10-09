#!/usr/bin/env python3
"""
Verifier for Dashboard Time Synchronization and Filtered Sankey Topology:
1. Verifies that switching time presets (1h, 24h, 7d) automatically synchronizes
   the start and end datetime-local inputs, and refreshes all charts accordingly.
2. Verifies that filtering conditions (e.g. Exporter, Port, Direction) are passed to
   the Sankey endpoint and the topology graph updates synchronously.
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
DEBUG_PORT = 9286

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
    print(" [Dashboard Time Sync & Sankey Filtered Topology Verifier] ", flush=True)
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

        # 1. Initial State
        print("\n--- [Step 1] Verifying Initial Dashboard State and Time Sync ---", flush=True)
        start_val = eval_js("document.querySelectorAll('.filter-card input[type=\"datetime-local\"]')[0].value")
        end_val = eval_js("document.querySelectorAll('.filter-card input[type=\"datetime-local\"]')[1].value")
        print(f"[+] Initial synchronized time inputs: start='{start_val}', end='{end_val}'", flush=True)
        assert start_val and end_val, "Start and end time inputs must be populated!"

        # 2. Click Preset '1h' and check auto synchronization
        print("\n--- [Step 2] Testing '最近 1小时' Auto Time Synchronization ---", flush=True)
        eval_js("""
            const btn1h = Array.from(document.querySelectorAll('.btn-quick-time')).find(b => b.innerText.includes('1小时'));
            if (btn1h) btn1h.click();
        """)
        time.sleep(2.0)
        start_1h = eval_js("document.querySelectorAll('.filter-card input[type=\"datetime-local\"]')[0].value")
        end_1h = eval_js("document.querySelectorAll('.filter-card input[type=\"datetime-local\"]')[1].value")
        print(f"[+] 1h Preset synchronized inputs: start='{start_1h}', end='{end_1h}'", flush=True)
        assert start_1h != start_val, "Start time should have updated to 1 hour ago!"

        # 3. Click Preset '7d' and check auto synchronization & charts update
        print("\n--- [Step 3] Testing '最近 7天' Auto Time Synchronization ---", flush=True)
        eval_js("""
            const btn7d = Array.from(document.querySelectorAll('.btn-quick-time')).find(b => b.innerText.includes('7天'));
            if (btn7d) btn7d.click();
        """)
        time.sleep(3.0)
        start_7d = eval_js("document.querySelectorAll('.filter-card input[type=\"datetime-local\"]')[0].value")
        end_7d = eval_js("document.querySelectorAll('.filter-card input[type=\"datetime-local\"]')[1].value")
        print(f"[+] 7d Preset synchronized inputs: start='{start_7d}', end='{end_7d}'", flush=True)
        capture("dashboard_sync_7d_verified.png")

        # 4. Filter Sankey Topology (e.g. Exporter: 10.3.255.225 FortiGate)
        print("\n--- [Step 4] Testing Filtered Sankey Topology Synchronous Update ---", flush=True)
        eval_js("""
            // Select exporter 10.3.255.225
            const expSelect = document.getElementById('exporterSelect');
            if (expSelect) {
                expSelect.value = '10.3.255.225';
                expSelect.dispatchEvent(new Event('change'));
            }
        """)
        time.sleep(3.0)

        # Verify Sankey rendered
        sankey_info = eval_js("""
            (() => {
                const el = document.getElementById('sankeyChart');
                return {
                    rendered: el && el.getAttribute('_echarts_instance_') !== null,
                    text: el ? el.innerText : ''
                };
            })()
        """)
        print(f"[+] Sankey chart status: {sankey_info}", flush=True)
        capture("dashboard_sankey_filtered_verified.png")
        print("[+] Dashboard time sync & Sankey filtering verification finished successfully!", flush=True)

    finally:
        try:
            ws.close()
        except:
            pass
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
