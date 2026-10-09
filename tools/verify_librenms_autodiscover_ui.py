import subprocess
import time
import json
import urllib.request
import os
import websocket
import sys
import base64

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
EDGE_PORT = 9295
TARGET_URL = "http://10.3.11.78:8080/#/dashboard"

def run_test():
    print("=" * 64, flush=True)
    print(" [LibreNMS Sync & NetFlow Auto-Discovery Verification] ", flush=True)
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
                raw = ws.recv()
                res = json.loads(raw)
                if res.get("id") == cur_id:
                    return res

        def eval_js(expr):
            r = send_cdp("Runtime.evaluate", {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": True
            })
            return r.get("result", {}).get("result", {}).get("value")

        def capture_screenshot(filename):
            res = send_cdp("Page.captureScreenshot", {"format": "png"})
            data = res.get("result", {}).get("data")
            buf = base64.b64decode(data)
            path1 = os.path.join(ARTIFACT_DIR, filename)
            with open(path1, "wb") as f:
                f.write(buf)
            print(f"[+] Saved screenshot: {path1}", flush=True)

        send_cdp("Page.enable")
        send_cdp("Runtime.enable")

        print(f"[*] Navigating to {TARGET_URL} ...", flush=True)
        send_cdp("Page.navigate", {"url": TARGET_URL})
        time.sleep(3.0)

        # 1. Verify Sidebar buttons
        sidebar_buttons = eval_js("""
            Array.from(document.querySelectorAll('.sidebar-btn span')).map(el => el.innerText.trim()).filter(Boolean)
        """)
        print("[+] Sidebar buttons detected:", sidebar_buttons, flush=True)
        assert "SNMP" not in sidebar_buttons, f"SNMP button still exists in sidebar: {sidebar_buttons}"
        assert "监控" in sidebar_buttons, "Monitor button missing in sidebar"
        assert "网络" in sidebar_buttons, "Network button missing in sidebar"
        capture_screenshot("librenms_1_sidebar_no_snmp.png")

        # 2. Test accessing #/snmp redirects to #/monitor
        print("[*] Navigating to http://10.3.11.78:8080/#/snmp ...", flush=True)
        send_cdp("Page.navigate", {"url": "http://10.3.11.78:8080/#/snmp"})
        time.sleep(2.0)
        current_hash = eval_js("window.location.hash")
        print(f"[+] Current hash after navigating to #/snmp: {current_hash}", flush=True)
        assert "#/monitor" in current_hash, f"Expected #/monitor, got {current_hash}"

        # 3. Check Monitor view has LibreNMS sync button & auto-discovered 10.4.1.254
        sync_button_text = eval_js("""
            (() => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('从 LibreNMS 同步所有设备与端口'));
                return btn ? btn.innerText.trim() : null;
            })()
        """)
        print(f"[+] Found Sync Button: {sync_button_text}", flush=True)
        assert sync_button_text is not None, "LibreNMS sync button missing on Monitor page"

        # Check devices rendered on page
        devices = eval_js("""
            Array.from(document.querySelectorAll('.dashboard-card .ip-address-text')).map(el => el.innerText.trim())
        """)
        print(f"[+] Rendered Devices in Monitor: {devices}", flush=True)
        assert "10.4.1.254" in devices, f"10.4.1.254 missing from Monitor page: {devices}"
        print("[+] Auto-discovered device 10.4.1.254 verified in monitor device list!", flush=True)
        capture_screenshot("librenms_2_monitor_sync_button.png")

        # 4. Open edit modal on a device and verify NO SNMP inputs
        print("[*] Opening device edit modal ...", flush=True)
        eval_js("""
            (() => {
                const editBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('修改'));
                if (editBtn) editBtn.click();
            })()
        """)
        time.sleep(1.0)
        modal_html = eval_js("document.getElementById('deviceEditModal').innerHTML")
        assert "Community" not in modal_html, "SNMP Community input still found in deviceEditModal!"
        assert "SNMP 版本" not in modal_html, "SNMP Version select still found in deviceEditModal!"
        print("[+] Verified deviceEditModal has NO SNMP credential inputs!", flush=True)
        capture_screenshot("librenms_3_edit_modal_no_snmp.png")

        # Close modal
        eval_js("""
            (() => {
                const cancelBtn = document.querySelector('#deviceEditModal button.btn-secondary');
                if (cancelBtn) cancelBtn.click();
            })()
        """)
        time.sleep(1.0)

        # 5. Open interface subpage for 10.4.1.254
        print("[*] Entering interface subpage for 10.4.1.254 ...", flush=True)
        eval_js("""
            (() => {
                const card = Array.from(document.querySelectorAll('.dashboard-card')).find(c => c.innerText.includes('10.4.1.254'));
                if (card) {
                    const ifBtn = Array.from(card.querySelectorAll('button')).find(b => b.innerText.includes('端口管理'));
                    if (ifBtn) ifBtn.click();
                }
            })()
        """)
        time.sleep(2.0)

        iface_subpage_hash = eval_js("window.location.hash")
        print(f"[+] Interface subpage URL hash: {iface_subpage_hash}", flush=True)

        iface_sync_btn = eval_js("""
            (() => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('LibreNMS 同步该设备'));
                return btn ? btn.innerText.trim() : null;
            })()
        """)
        print(f"[+] Found Interface Sync Button: {iface_sync_btn}", flush=True)
        assert iface_sync_btn is not None, "LibreNMS sync single device button missing"

        # Check interfaces rendered
        rendered_ifaces = eval_js("""
            Array.from(document.querySelectorAll('tr td .ip-address-text')).map(el => el.innerText.trim())
        """)
        print(f"[+] First 5 interfaces: {rendered_ifaces[:5]}", flush=True)

        capture_screenshot("librenms_4_interface_subpage_sync.png")

        print("=" * 64, flush=True)
        print(" [SUCCESS] All LibreNMS sync & Auto-discovery tests passed! ", flush=True)
        print("=" * 64, flush=True)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        edge_proc.terminate()
        edge_proc.wait()

if __name__ == "__main__":
    run_test()
