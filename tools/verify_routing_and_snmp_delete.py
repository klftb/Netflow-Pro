import subprocess
import time
import json
import urllib.request
import os
import websocket
import sys

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
EDGE_PORT = 9299
TARGET_URL = "http://10.3.11.78:8080/"

def run_test():
    print("=" * 64, flush=True)
    print(" [Hash Router & SNMP Delete Verification Suite] ", flush=True)
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
            import base64
            buf = base64.b64decode(data)
            path1 = os.path.join(ARTIFACT_DIR, filename)
            with open(path1, "wb") as f:
                f.write(buf)
            with open(filename, "wb") as f:
                f.write(buf)
            print(f"[+] Saved screenshot: {path1}", flush=True)

        send_cdp("Page.enable")
        send_cdp("Runtime.enable")

        print(f"[*] Navigating to {TARGET_URL} ...", flush=True)
        send_cdp("Page.navigate", {"url": TARGET_URL})
        time.sleep(4.0)

        # 1. Check initial hash
        init_hash = eval_js("window.location.hash")
        print(f"[+] Initial URL Hash: {init_hash}", flush=True)
        assert init_hash in ["#/dashboard", ""], f"Unexpected initial hash: {init_hash}"

        # 2. Test navigation to #/monitor
        print("\n--- [Step 1] Navigating to Monitor via Hash Router ---", flush=True)
        eval_js("""
            const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('监控'));
            if (btn) btn.click();
        """)
        time.sleep(2.0)
        nav_hash = eval_js("window.location.hash")
        print(f"[+] Monitor URL Hash: {nav_hash}", flush=True)
        assert nav_hash == "#/monitor", f"Hash not updated to #/monitor: {nav_hash}"

        nav_active = eval_js("document.querySelector('.sidebar-btn.active span')?.innerText")
        print(f"[+] Active sidebar button: {nav_active}", flush=True)
        assert "监控" in nav_active

        # 3. Test jumping into dedicated subpage for device
        print("\n--- [Step 2] Clicking Device Interface Management (Subpage Jump) ---", flush=True)
        eval_js("""
            const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('端口管理'));
            if (btns.length > 0) btns[0].click();
        """)
        time.sleep(2.0)

        sub_hash = eval_js("window.location.hash")
        print(f"[+] Subpage URL Hash after click: {sub_hash}", flush=True)
        assert "monitor/interfaces" in sub_hash, f"Hash did not update: {sub_hash}"

        subpage_info = eval_js("""({
            hasBreadcrumb: !!document.querySelector('.badge.bg-primary-subtle'),
            breadcrumbText: document.querySelector('.badge.bg-primary-subtle')?.innerText || '',
            hasBackBtn: Array.from(document.querySelectorAll('button')).some(b => b.innerText.includes('返回设备列表')),
            rows: document.querySelectorAll('table tbody tr').length
        })""")
        print(f"[+] Monitor Subpage Info: {subpage_info}", flush=True)
        assert subpage_info["hasBackBtn"] is True, "Back button missing in monitor subpage!"
        assert subpage_info["rows"] > 0, "No interface rows in monitor subpage!"
        capture_screenshot("route_1_hash_monitor_subpage_verified.png")

        # 4. Test clicking back button
        print("\n--- [Step 3] Returning to Monitor Device List ---", flush=True)
        eval_js("""
            const backBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('返回设备列表'));
            if (backBtn) backBtn.click();
        """)
        time.sleep(2.0)
        back_hash = eval_js("window.location.hash")
        print(f"[+] URL Hash after clicking back: {back_hash}", flush=True)
        assert back_hash == "#/monitor"

        # 5. Test SNMP Navigation & Subpage Jump
        print("\n--- [Step 4] Navigating to SNMP Hub ---", flush=True)
        snmp_click_res = eval_js("""(() => {
            const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('SNMP'));
            if (!btn) return { found: false, all: Array.from(document.querySelectorAll('.sidebar-btn')).map(b => b.innerText) };
            btn.click();
            return { found: true, text: btn.innerText, newHash: window.location.hash };
        })()""")
        print(f"[DEBUG CLICK SNMP]: {snmp_click_res}", flush=True)
        time.sleep(2.0)
        snmp_hash = eval_js("window.location.hash")
        print(f"[+] SNMP URL Hash: {snmp_hash}", flush=True)
        assert snmp_hash == "#/snmp"

        # Check delete button presence in SNMP table
        snmp_table_info = eval_js("""({
            hasDeleteBtn: !!document.querySelector('button[title=\"删除此 SNMP 设备配置\"]'),
            deviceCount: document.querySelectorAll('.app-content table tbody tr').length
        })""")
        print(f"[+] SNMP Hub Info: {snmp_table_info}", flush=True)
        assert snmp_table_info['hasDeleteBtn'] is True, "Delete button missing in SNMP table!"
        capture_screenshot("route_3_snmp_delete_button_verified.png")

        # Click SNMP Interface Subpage
        print("\n--- [Step 5] Clicking SNMP Interface Mapping Subpage ---", flush=True)
        eval_js("""
            const mapBtns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('端口映射与描述'));
            if (mapBtns.length > 0) mapBtns[0].click();
        """)
        time.sleep(2.0)
        snmp_sub_hash = eval_js("window.location.hash")
        print(f"[+] SNMP Subpage URL Hash: {snmp_sub_hash}", flush=True)
        assert "snmp/interfaces" in snmp_sub_hash

        snmp_subpage_info = eval_js("""({
            breadcrumbText: document.querySelector('.badge.bg-primary-subtle')?.innerText || '',
            hasBackBtn: Array.from(document.querySelectorAll('button')).some(b => b.innerText.includes('返回托管设备清单')),
            ifRows: document.querySelectorAll('table tbody tr').length
        })""")
        print(f"[+] SNMP Subpage Info: {snmp_subpage_info}", flush=True)
        assert snmp_subpage_info["hasBackBtn"] is True, "Back button missing in SNMP subpage!"
        assert snmp_subpage_info["ifRows"] > 0, "No interfaces in SNMP subpage!"
        capture_screenshot("route_2_hash_snmp_subpage_verified.png")

        # 6. Test Browser History Back (history.back())
        print("\n--- [Step 6] Testing Browser Native History Back ---", flush=True)
        eval_js("history.back()")
        time.sleep(2.0)
        hist_back_hash = eval_js("window.location.hash")
        print(f"[+] URL Hash after history.back(): {hist_back_hash}", flush=True)
        assert hist_back_hash == "#/snmp"

        # 7. Test SNMP Device Deletion End-to-End
        print("\n--- [Step 7] Testing SNMP Device Add & Delete Flow ---", flush=True)
        # Add a temporary device 10.99.88.77 via backend API
        add_payload = json.dumps({
            "exporter_ip": "10.99.88.77",
            "device_name": "TEST_SW_TEMP (10.99.88.77)",
            "device_type": "Switch",
            "description": "自动化删除测试临时设备",
            "location": "测试机架",
            "admin": "AutoTester",
            "snmp_community": "public",
            "snmp_version": "2c"
        }).encode('utf-8')
        req = urllib.request.Request("http://10.3.11.78:8080/api/v1/config/exporters", data=add_payload, headers={'Content-Type': 'application/json'}, method='POST')
        add_res = json.loads(urllib.request.urlopen(req).read().decode())
        print(f"[+] Added temporary SNMP device 10.99.88.77: {add_res}", flush=True)

        # Refresh configs in Vue
        eval_js("window.__fetchConfigs && window.__fetchConfigs()")
        found = False
        for _ in range(15):
            if eval_js("document.body.innerText.includes('10.99.88.77')"):
                found = True
                break
            eval_js("window.__fetchConfigs && window.__fetchConfigs()")
            time.sleep(1.0)
        print(f"[+] 10.99.88.77 appears in table: {found}", flush=True)
        assert found is True, "Temporary device not visible in table!"

        # Click delete on 10.99.88.77
        del_click = eval_js("""(() => {
            const rows = Array.from(document.querySelectorAll('table tbody tr'));
            const targetRow = rows.find(r => r.innerText.includes('10.99.88.77'));
            if (!targetRow) return { error: 'row not found' };
            const delBtn = targetRow.querySelector('button[title=\"删除此 SNMP 设备配置\"]');
            if (!delBtn) return { error: 'delBtn not found', html: targetRow.innerHTML };
            delBtn.click();
            return { clicked: true };
        })()""")
        print(f"[DEBUG DEL CLICK]: {del_click}", flush=True)
        time.sleep(1.0)

        # Confirm delete
        confirm_click = eval_js("""(() => {
            const rows = Array.from(document.querySelectorAll('table tbody tr'));
            const targetRow = rows.find(r => r.innerText.includes('10.99.88.77'));
            if (!targetRow) return { error: 'row not found for confirm' };
            const confirmBtn = targetRow.querySelector('button[title=\"确认永久移除此设备配置\"]');
            if (!confirmBtn) return { error: 'confirmBtn not found', html: targetRow.innerHTML };
            confirmBtn.click();
            return { clicked: true };
        })()""")
        print(f"[DEBUG CONFIRM CLICK]: {confirm_click}", flush=True)
        time.sleep(1.0)

        # Wait until deleted
        deleted = False
        for _ in range(15):
            if not eval_js("document.body.innerText.includes('10.99.88.77')"):
                deleted = True
                break
            time.sleep(1.0)
        print(f"[+] 10.99.88.77 gone after delete: {deleted}", flush=True)
        assert deleted is True, "Device 10.99.88.77 was not deleted!"
        capture_screenshot("route_4_snmp_deleted_success_verified.png")

        print("\n[SUCCESS] All Hash Routing, Subpage Jump, and SNMP Delete tests passed 100%!", flush=True)

    finally:
        try: ws.close()
        except: pass
        edge_proc.terminate()

if __name__ == "__main__":
    run_test()
