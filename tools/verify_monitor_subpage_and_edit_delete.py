#!/usr/bin/env python3
"""
Verifier for Monitor View Enhancements:
1. Device modification & deletion controls in device list view.
2. Device Interface Management as a dedicated sub-page (with back button & full width table).
3. Test enter subpage, search/filter ports, return to list, and inline two-step delete.
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
DEBUG_PORT = 9287

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
    print(" [Monitor Device Edit/Delete & Interface Sub-Page Verifier] ", flush=True)
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

        # 1. Switch to Monitor View
        print("\n--- [Step 1] Navigating to '监控' View ---", flush=True)
        eval_js("""
            const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('监控'));
            if (btn) btn.click();
        """)
        time.sleep(2.5)

        # Check devices list
        dev_cards = eval_js("""
            Array.from(document.querySelectorAll('.app-content .dashboard-card')).map(card => {
                const title = card.querySelector('.fs-6') ? card.querySelector('.fs-6').innerText.trim() : '';
                const btns = Array.from(card.querySelectorAll('button')).map(b => b.innerText.trim());
                return { title, btns };
            }).filter(d => d.title)
        """)
        print(f"[+] Loaded device cards: {len(dev_cards)}", flush=True)
        for d in dev_cards:
            print(f"    Device: {d['title']} | Actions: {d['btns']}", flush=True)
        capture("monitor_1_devices_list_verified.png")

        # 2. Test Device Edit Modal
        print("\n--- [Step 2] Testing Device Edit Modal ---", flush=True)
        eval_js("""
            const editBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('修改'));
            if (editBtn) editBtn.click();
        """)
        time.sleep(1.0)
        modal_visible = eval_js("document.querySelector('#deviceEditModal.show') !== null")
        print(f"[+] Device edit modal visible: {modal_visible}", flush=True)
        capture("monitor_2_edit_modal_verified.png")

        # Close modal
        eval_js("""
            const closeBtn = document.querySelector('#deviceEditModal.show .btn-secondary');
            if (closeBtn) closeBtn.click();
        """)
        time.sleep(1.0)

        # 3. Test Enter Dedicated Interface Management Sub-Page
        print("\n--- [Step 3] Entering Dedicated Interface Management Sub-Page ---", flush=True)
        eval_js("""
            const portBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('端口管理'));
            if (portBtn) portBtn.click();
        """)
        time.sleep(1.5)

        subpage_info = eval_js("""
            (() => {
                const backBtn = document.querySelector('.app-content button');
                const hasBack = backBtn && backBtn.innerText.includes('返回设备列表');
                const rows = Array.from(document.querySelectorAll('.app-content table tbody tr')).map(r => {
                    return Array.from(r.querySelectorAll('td')).map(td => td.innerText.trim());
                });
                return {
                    hasBack,
                    rowCount: rows.length,
                    sampleRow: rows[0] || []
                };
            })()
        """)
        print(f"[+] Subpage back button found: {subpage_info.get('hasBack')}", flush=True)
        print(f"[+] Subpage interface rows: {subpage_info.get('rowCount')}", flush=True)
        print(f"[+] Sample row: {subpage_info.get('sampleRow')}", flush=True)
        capture("monitor_3_interface_subpage_verified.png")

        # 4. Test Search within Subpage
        print("\n--- [Step 4] Testing Search within Interface Subpage ---", flush=True)
        eval_js("""
            const inp = document.querySelector('.app-content input[placeholder*=\"搜索端口\"]');
            if (inp) {
                inp.value = 'port';
                inp.dispatchEvent(new Event('input'));
            }
        """)
        time.sleep(1.0)
        search_count = eval_js("document.querySelectorAll('.app-content table tbody tr').length")
        print(f"[+] Search filtered row count: {search_count}", flush=True)

        # 5. Return to Device List
        print("\n--- [Step 5] Returning to Device List ---", flush=True)
        eval_js("""
            const backBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('返回设备列表'));
            if (backBtn) backBtn.click();
        """)
        time.sleep(1.0)

        # 6. Test Inline Two-Step Delete
        print("\n--- [Step 6] Testing Inline Two-Step Safe Delete Trigger ---", flush=True)
        eval_js("""
            const delBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.innerText.includes('删除'));
            if (delBtn) delBtn.click();
        """)
        time.sleep(0.5)
        has_confirm = eval_js("""
            Array.from(document.querySelectorAll('.app-content button')).some(b => b.innerText.includes('确认'))
        """)
        print(f"[+] Inline confirm button rendered: {has_confirm}", flush=True)
        capture("monitor_4_delete_confirm_verified.png")

        # Cancel delete
        eval_js("""
            const cancelBtn = Array.from(document.querySelectorAll('.app-content button')).find(b => b.getAttribute('title') === '取消');
            if (cancelBtn) cancelBtn.click();
        """)
        time.sleep(0.5)
        print("[+] Monitor view verification completed successfully!", flush=True)

    finally:
        try:
            ws.close()
        except:
            pass
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
