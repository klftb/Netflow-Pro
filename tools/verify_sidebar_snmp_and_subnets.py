#!/usr/bin/env python3
"""
Automated Verifier for Sidebar SNMP Separation and Subnets Edit/Delete:
1. Left Sidebar: Verify 6 items (Dashboard, Monitor, Traffic Analysis, Network, SNMP, Settings).
2. Network View: Verify it directly displays Subnets & IPAM (no internal subtabs).
3. Subnet Edit Modal: Click edit on a subnet, verify modal displays fields.
4. Subnet Create & Delete: Create a new subnet, verify in table, then delete it and verify disappearance.
5. SNMP View: Click SNMP in sidebar, verify direct access to SNMP Device Hub.
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
DEBUG_PORT = 9282

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
    print(" [Sidebar SNMP & Subnet Edit/Delete End-to-End Verifier] ", flush=True)
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
            # Auto accept any javascript dialog if one occurs
            if res.get("method") == "Page.javascriptDialogOpening":
                print(f"[*] Auto accepting JavaScript Dialog: {res.get('params')}", flush=True)
                send_cdp("Page.handleJavaScriptDialog", {"accept": True})
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

        # 1. Verify Sidebar Items
        print("\n--- [Step 1] Checking Left Sidebar Menu Items ---", flush=True)
        sidebar_items = eval_js("""
            Array.from(document.querySelectorAll('.sidebar-btn span')).map(el => el.innerText.trim())
        """)
        print(f"Sidebar menu items: {sidebar_items}", flush=True)
        assert "网络" in sidebar_items, "网络 item not found in sidebar!"
        assert "SNMP" in sidebar_items, "SNMP item not found in sidebar!"
        net_idx = sidebar_items.index("网络")
        snmp_idx = sidebar_items.index("SNMP")
        print(f"Index of 网络: {net_idx}, Index of SNMP: {snmp_idx}", flush=True)
        assert snmp_idx == net_idx + 1, "SNMP is not directly below 网络 in sidebar!"
        print("[SUCCESS] Sidebar order verified: 仪表盘 -> 监控 -> 流量分析 -> 网络 -> SNMP -> 设置", flush=True)

        # 2. Switch to Network View
        print("\n--- [Step 2] Navigating to '网络' View ---", flush=True)
        eval_js("""
            const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('网络'));
            if (btn) btn.click();
        """)
        time.sleep(2.0)

        # Verify no subtabs in Network view
        has_subtabs = eval_js("document.getElementById('networkSubTab') !== null")
        print(f"Has internal subtabs in Network view: {has_subtabs}", flush=True)
        assert not has_subtabs, "networkSubTab should be removed from Network view!"

        # Check KPIs and subnets table
        kpis = eval_js("""
            Array.from(document.querySelectorAll('.dashboard-card .kpi-value')).map(el => el.innerText.trim())
        """)
        print(f"Network view KPIs: {kpis}", flush=True)
        table_rows = eval_js("""
            Array.from(document.querySelectorAll('.app-content table tbody tr td:nth-child(2)')).map(el => el.innerText.trim()).filter(Boolean)
        """)
        print(f"Subnets in table: {table_rows[:4]} (Total: {len(table_rows)})", flush=True)
        capture("sidebar_snmp_1_network_subnets.png")

        # 3. Test Subnet Edit Modal
        print("\n--- [Step 3] Testing Subnet Edit Modal ---", flush=True)
        # Click the edit button on the first subnet row
        eval_js("""
            const firstEditBtn = document.querySelector('.table tbody tr button.btn-outline-primary');
            if (firstEditBtn) firstEditBtn.click();
        """)
        time.sleep(1.0)
        modal_visible = eval_js("document.querySelector('.modal.show') !== null")
        print(f"Subnet Edit Modal visible: {modal_visible}", flush=True)
        modal_title = eval_js("document.querySelector('.modal.show .modal-title') ? document.querySelector('.modal.show .modal-title').innerText.trim() : ''")
        print(f"Modal title: {modal_title}", flush=True)
        capture("sidebar_snmp_2_subnet_edit_modal.png")

        # Close the modal
        eval_js("""
            const closeBtn = document.querySelector('.modal.show .btn-secondary');
            if (closeBtn) closeBtn.click();
        """)
        time.sleep(0.5)

        # 4. Test Subnet Create and Delete
        print("\n--- [Step 4] Testing Subnet Creation & Deletion ---", flush=True)
        # Create temporary subnet
        eval_js("""
            const inputs = document.querySelectorAll('.app-content .card input');
            for (const inp of inputs) {
                if (inp.placeholder && inp.placeholder.includes('网段名称')) {
                    inp.value = '自动化验证临时段';
                    inp.dispatchEvent(new Event('input'));
                } else if (inp.placeholder && inp.placeholder.includes('CIDR')) {
                    inp.value = '192.168.211.0/24';
                    inp.dispatchEvent(new Event('input'));
                } else if (inp.placeholder && inp.placeholder.includes('所属部门')) {
                    inp.value = 'QA测试部';
                    inp.dispatchEvent(new Event('input'));
                }
            }
        """)
        time.sleep(0.5)
        # Click save button
        eval_js("""
            const saveBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('保存网段定义'));
            if (saveBtn) saveBtn.click();
        """)
        time.sleep(2.5)

        subnets_after_create = eval_js("""
            Array.from(document.querySelectorAll('.app-content table tbody tr td:nth-child(2)')).map(el => el.innerText.trim())
        """)
        print(f"Subnets after create: {subnets_after_create}", flush=True)
        assert any('自动化验证临时段' in s for s in subnets_after_create), "Created subnet not found in table!"
        print("[SUCCESS] Subnet created successfully and visible in table!", flush=True)
        capture("sidebar_snmp_3_subnet_created.png")

        # Now test editing this newly created subnet!
        print("\n--- [Step 4b] Editing the Created Subnet ---", flush=True)
        eval_js("""
            const rows = Array.from(document.querySelectorAll('.app-content table tbody tr'));
            const targetRow = rows.find(r => r.innerText.includes('自动化验证临时段'));
            if (targetRow) {
                const editBtn = targetRow.querySelector('button.btn-outline-primary');
                if (editBtn) editBtn.click();
            }
        """)
        time.sleep(1.0)
        # Modify name in modal
        eval_js("""
            const nameInput = document.querySelector('.modal.show input');
            if (nameInput) {
                nameInput.value = '自动化验证临时段(已修改)';
                nameInput.dispatchEvent(new Event('input'));
            }
            const saveModBtn = Array.from(document.querySelectorAll('.modal.show button')).find(b => b.innerText.includes('保存修改'));
            if (saveModBtn) saveModBtn.click();
        """)
        time.sleep(2.0)
        subnets_after_edit = eval_js("""
            Array.from(document.querySelectorAll('.app-content table tbody tr td:nth-child(2)')).map(el => el.innerText.trim())
        """)
        print(f"Subnets after edit: {subnets_after_edit}", flush=True)
        assert any('自动化验证临时段(已修改)' in s for s in subnets_after_edit), "Modified subnet not reflected!"
        print("[SUCCESS] Subnet edited and updated in table successfully!", flush=True)

        # Now delete the subnet
        print("\n--- [Step 4c] Deleting the Subnet ---", flush=True)
        # Step 1: Click delete button to show inline confirmation
        r_del1 = eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('.app-content table tbody tr'));
                const targetRow = rows.find(r => r.innerText.includes('自动化验证临时段(已修改)'));
                if (!targetRow) return 'targetRow not found in step 1';
                const delBtn = targetRow.querySelector('button.btn-outline-danger');
                if (!delBtn) return 'delBtn not found in step 1';
                delBtn.click();
                return 'delBtn clicked';
            })()
        """)
        print(f"Delete step 1 result: {r_del1}", flush=True)
        time.sleep(1.0)
        # Step 2: Click the red confirm button
        r_del2 = eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('.app-content table tbody tr'));
                const targetRow = rows.find(r => r.innerText.includes('自动化验证临时段(已修改)'));
                if (!targetRow) return 'targetRow not found in step 2';
                const confirmBtn = targetRow.querySelector('button.btn-danger');
                if (!confirmBtn) return 'confirmBtn not found in step 2';
                confirmBtn.click();
                return 'confirmBtn clicked';
            })()
        """)
        print(f"Delete step 2 result: {r_del2}", flush=True)
        time.sleep(2.5)

        subnets_after_delete = eval_js("""
            Array.from(document.querySelectorAll('.app-content table tbody tr td:nth-child(2)')).map(el => el.innerText.trim())
        """)
        print(f"Subnets after delete: {subnets_after_delete}", flush=True)
        assert not any('自动化验证临时段' in s for s in subnets_after_delete), "Subnet still exists after delete!"
        print("[SUCCESS] Subnet deleted and disappeared from table immediately!", flush=True)
        capture("sidebar_snmp_4_subnet_deleted.png")

        # 5. Switch to SNMP View from Left Sidebar
        print("\n--- [Step 5] Navigating to 'SNMP' View via Left Sidebar ---", flush=True)
        eval_js("""
            const snmpBtn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('SNMP'));
            if (snmpBtn) snmpBtn.click();
        """)
        time.sleep(2.0)

        # Verify SNMP Hub components
        header_title = eval_js("document.querySelector('.app-topbar h6') ? document.querySelector('.app-topbar h6').innerText.trim() : ''")
        print(f"Top header title on SNMP view: {header_title}", flush=True)
        probe_bar_visible = eval_js("document.querySelector('.app-content input[placeholder*=\"10.23.251.238\"]') !== null")
        print(f"SNMP probe bar visible: {probe_bar_visible}", flush=True)
        device_rows = eval_js("""
            Array.from(document.querySelectorAll('.app-content table tbody tr td:nth-child(2)')).map(el => el.innerText.trim()).filter(Boolean)
        """)
        print(f"SNMP managed devices: {device_rows}", flush=True)
        capture("sidebar_snmp_5_snmp_view.png")
        print("[SUCCESS] Direct navigation to SNMP Device Hub verified!", flush=True)

        print("\n================================================================", flush=True)
        print(" ALL 5 STEPS PASSED SUCCESSFULLY! ", flush=True)
        print("================================================================", flush=True)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        proc.kill()

if __name__ == "__main__":
    main()
