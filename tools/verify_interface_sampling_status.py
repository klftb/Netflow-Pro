import subprocess
import time
import json
import urllib.request
import os
import websocket
import sys

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
EDGE_PORT = 9298
TARGET_URL = "http://10.3.11.78:8080/#/monitor"

def run_test():
    print("=" * 64, flush=True)
    print(" [Interface Sampling Status Sync Verification Suite] ", flush=True)
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
            print(f"[+] Saved screenshot: {path1}", flush=True)

        send_cdp("Page.enable")
        send_cdp("Runtime.enable")

        print(f"[*] Navigating to {TARGET_URL} ...", flush=True)
        send_cdp("Page.navigate", {"url": TARGET_URL})
        time.sleep(4.0)

        # 1. Verify Monitor subpage device cards
        devices_info = eval_js("""
            Array.from(document.querySelectorAll('.dashboard-card')).filter(c => c.innerText.includes('IP:')).map(card => {
                const title = card.querySelector('.fw-bold.fs-6')?.innerText || '';
                const cardText = card.innerText;
                return { title, cardText };
            })
        """)
        print(f"[+] Found {len(devices_info or [])} device cards on Monitor page", flush=True)

        # 2. Check Cisco 9300 specifically
        cisco_card = eval_js("""
            (() => {
                const cards = Array.from(document.querySelectorAll('.dashboard-card')).filter(c => c.innerText.includes('IP:'));
                for (let c of cards) {
                    if (c.innerText.includes('10.3.251.1')) {
                        const portBtn = c.querySelector('button[title*="端口管理"]')?.innerText || '';
                        const cardText = c.innerText;
                        return { portBtn, cardText };
                    }
                }
                return null;
            })()
        """)
        print(f"[+] Cisco 9300 card info: {cisco_card}", flush=True)
        assert cisco_card is not None, "Cisco 9300 card not found!"
        assert "端口管理 (1/" in cisco_card['portBtn'], f"Expected '端口管理 (1/...', got: {cisco_card['portBtn']}"

        # 3. Open Cisco 9300 Interface Subview
        print("[*] Opening Cisco 9300 interface management subpage...", flush=True)
        opened = eval_js("""
            (() => {
                const cards = Array.from(document.querySelectorAll('.dashboard-card')).filter(c => c.innerText.includes('IP:'));
                for (let c of cards) {
                    if (c.innerText.includes('10.3.251.1')) {
                        const btn = c.querySelector('button[title*="端口管理"]');
                        if (btn) { btn.click(); return true; }
                    }
                }
                return false;
            })()
        """)
        assert opened, "Failed to click 端口管理 button"
        time.sleep(2.0)

        # 4. Verify 仅采样端口 (1)
        time.sleep(2.0)
        subpage_info = eval_js("""
            (() => {
                const btnGroup = Array.from(document.querySelectorAll('.btn-group button'));
                const samplingBtn = btnGroup.find(b => b.innerText.includes('采样端口'));
                const tables = Array.from(document.querySelectorAll('table'));
                const matchingTables = tables.filter(t => t.innerText.includes('采样状态') || t.innerText.includes('接口名称'));
                const table = matchingTables[matchingTables.length - 1]; // take the active one
                const rows = table ? Array.from(table.querySelectorAll('tbody tr')).map(r => {
                    return r.innerText.replace(/\\s+/g, ' ');
                }) : [];
                return {
                    activeFilter: samplingBtn?.innerText || '',
                    matchingTablesCount: matchingTables.length,
                    tableFound: !!table,
                    tableText: table ? table.innerText.substring(0, 200) : '',
                    rowCount: rows.length,
                    firstRow: rows[0] || ''
                };
            })()
        """)
        print(f"[+] Subpage default filter state: {subpage_info}", flush=True)
        assert "仅采样端口 (1)" in subpage_info['activeFilter'], f"Expected '仅采样端口 (1)', got: {subpage_info['activeFilter']}"
        assert "129" in subpage_info['firstRow'] and "Vlan901" in subpage_info['firstRow'], f"Expected Vlan901 row, got: {subpage_info['firstRow']}"

        # 5. Switch to 全部端口 to inspect Gi1/0/1 and Gi2/0/1 badges
        print("[*] Switching to 全部端口 filter...", flush=True)
        eval_js("""
            (() => {
                const btns = Array.from(document.querySelectorAll('.btn-group button'));
                for (let b of btns) {
                    if (b.innerText.includes('全部端口')) { b.click(); break; }
                }
            })()
        """)
        time.sleep(1.0)

        # Search for Gi1/0/1 to see its status badge
        eval_js("""
            (() => {
                const input = document.querySelector('input[placeholder*="搜索端口"]');
                if (input) {
                    input.value = 'Gi1/0/1';
                    input.dispatchEvent(new Event('input'));
                }
            })()
        """)
        time.sleep(1.0)

        gi_status = eval_js("""
            (() => {
                const tables = Array.from(document.querySelectorAll('table'));
                const matchingTables = tables.filter(t => t.innerText.includes('采样状态') || t.innerText.includes('接口名称'));
                const table = matchingTables[matchingTables.length - 1];
                const rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
                return rows.map(r => r.innerText.replace(/\\s+/g, ' '));
            })()
        """)
        print(f"[+] Gi1/0/1 status in interface list: {gi_status}", flush=True)
        assert any("已停止采样" in s for s in gi_status), f"Expected '已停止采样' badge for Gi1/0/1, got: {gi_status}"

        # Clear search to take full subpage screenshot
        eval_js("""
            (() => {
                const input = document.querySelector('input[placeholder*="搜索端口"]');
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('input'));
                }
            })()
        """)
        time.sleep(1.0)
        capture_screenshot("cisco_interface_sampling_status_verified.png")

        # 6. Verify Traffic Analysis Module
        print("[*] Navigating to 流量分析 (Traffic Analysis) ...", flush=True)
        eval_js("window.location.hash = '#/traffic_analysis'")
        time.sleep(3.0)

        # Select Cisco 9300 in Device dropdown
        eval_js("""
            (() => {
                const labels = Array.from(document.querySelectorAll('label'));
                const devLabel = labels.find(l => l.innerText.includes('分析设备'));
                const devSelect = devLabel?.parentElement.querySelector('select');
                if (devSelect) {
                    for (let opt of devSelect.options) {
                        if (opt.value === '10.3.251.1') {
                            devSelect.value = '10.3.251.1';
                            devSelect.dispatchEvent(new Event('change'));
                            break;
                        }
                    }
                }
            })()
        """)
        time.sleep(2.0)

        analysis_state = eval_js("""
            (() => {
                const labels = Array.from(document.querySelectorAll('label'));
                const ifLabel = labels.find(l => l.innerText.includes('分析接口'));
                const ifSelect = ifLabel?.parentElement.querySelector('select');
                const options = ifSelect ? Array.from(ifSelect.options).map(o => ({
                    value: o.value,
                    text: o.text,
                    selected: o.selected
                })) : [];
                return {
                    selectedIfVal: ifSelect?.value,
                    options: options.filter(o => o.value == '129' || o.value == '9' || o.value == '53')
                };
            })()
        """)
        print(f"[+] Traffic Analysis interface dropdown for Cisco 9300: {analysis_state}", flush=True)
        assert analysis_state['selectedIfVal'] == '129', f"Expected selected interface to be 129 (Vlan901), got: {analysis_state['selectedIfVal']}"
        vlan_opt = next((o for o in analysis_state['options'] if o['value'] == '129'), None)
        gi9_opt = next((o for o in analysis_state['options'] if o['value'] == '9'), None)
        gi53_opt = next((o for o in analysis_state['options'] if o['value'] == '53'), None)

        assert vlan_opt and "🔥 [采样中]" in vlan_opt['text'], f"Expected '🔥 [采样中]' on Vlan901, got: {vlan_opt}"
        assert gi9_opt and "⏸️ [已停止]" in gi9_opt['text'], f"Expected '⏸️ [已停止]' on Gi1/0/1, got: {gi9_opt}"
        assert gi53_opt and "⏸️ [已停止]" in gi53_opt['text'], f"Expected '⏸️ [已停止]' on Gi2/0/1, got: {gi53_opt}"

        capture_screenshot("cisco_traffic_analysis_dropdown_verified.png")

        print("=" * 64, flush=True)
        print(" [SUCCESS] All interface sampling status checks passed cleanly! ", flush=True)
        print("=" * 64, flush=True)

    finally:
        try:
            edge_proc.terminate()
            edge_proc.wait(timeout=3)
        except Exception:
            pass

if __name__ == "__main__":
    run_test()
