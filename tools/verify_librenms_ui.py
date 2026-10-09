import subprocess
import time
import json
import urllib.request
import os
import websocket
import sys
import base64

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
EDGE_PORT = 9298
TARGET_URL = "http://10.3.11.78:8080/#/snmp"

def capture_ui():
    print("=" * 64, flush=True)
    print(" [LibreNMS SNMP UI Browser Verification] ", flush=True)
    print("=" * 64, flush=True)

    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    print(f"[*] Launching Headless Edge on port {EDGE_PORT} ...", flush=True)
    edge_proc = subprocess.Popen([
        edge_path,
        "--headless",
        f"--remote-debugging-port={EDGE_PORT}",
        "--remote-allow-origins=*",
        "--no-sandbox",
        "--disable-gpu",
        "--window-size=1920,1080",
        "about:blank"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)

    try:
        ws_url = None
        for _ in range(15):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{EDGE_PORT}/json", timeout=2) as resp:
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
            print("[ERROR] Could not connect to DevTools WebSocket", flush=True)
            return False

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
                resp = json.loads(ws.recv())
                if resp.get("id") == cur_id:
                    return resp.get("result", {})

        def eval_js(expr):
            res = send_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return res.get("result", {}).get("value")

        def take_screenshot(name):
            res = send_cdp("Page.captureScreenshot", {"format": "png"})
            data = base64.b64decode(res["data"])
            path = os.path.join(ARTIFACT_DIR, f"{name}.png")
            with open(path, "wb") as f:
                f.write(data)
            print(f"[+] Screenshot captured: {path} ({len(data)} bytes)", flush=True)
            return path

        send_cdp("Page.enable")
        send_cdp("Runtime.enable")

        print(f"[*] Navigating to {TARGET_URL} ...", flush=True)
        send_cdp("Page.navigate", {"url": TARGET_URL})
        time.sleep(3.0)

        # 1. Verify SNMP hub UI
        body_text = eval_js("document.body.innerText")
        assert "LibreNMS API" in body_text, "LibreNMS API label not found in UI"
        assert "SHOffice" in body_text, "SHOffice location not rendered"
        assert "Ben Zhang" in body_text, "Ben Zhang contact not rendered"
        print("[+] PASS: SNMP Hub page shows LibreNMS API badge, SHOffice, and Ben Zhang!")
        take_screenshot("librenms_snmp_hub_verified")

        # 2. Navigate to FortiGate interface mapping sub-page
        print("[*] Navigating to #/snmp/interfaces?device=10.23.251.238 ...", flush=True)
        eval_js("window.location.hash = '#/snmp/interfaces?device=10.23.251.238'")
        time.sleep(3.0)

        sub_text = eval_js("document.body.innerText")
        assert "WAN1" in sub_text or "port1" in sub_text, "WAN1 / port1 not found in interface table"
        print("[+] PASS: FortiGate subpage shows LibreNMS synced ports (port1 / WAN1)!")
        take_screenshot("librenms_interfaces_subpage_verified")

        print("\n🎉 BROWSER CDP UI VERIFICATION COMPLETED SUCCESSFULLY!")
        return True

    finally:
        try:
            edge_proc.terminate()
            edge_proc.wait(timeout=2)
        except Exception:
            pass

if __name__ == '__main__':
    ok = capture_ui()
    sys.exit(0 if ok else 1)
