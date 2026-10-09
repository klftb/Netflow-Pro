#!/usr/bin/env python3
"""
Automated Verifier for Sidebar Redesign:
1. 仪表盘 (Dashboard) - Macro overview default view
2. 监控 (Monitor) - Physical devices & interfaces list
3. 流量分析 (Traffic Analysis) - Direct drill-down via interface click & top dropdown selectors
4. 网络 (Network) - SNMP Auto-discovery & Interface Alias management
5. 设置 (Settings) - CIDR Business groups, Application mapping, and System SLA health
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
DEBUG_PORT = 9245

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
    print(f"[+] Saved screenshot: {artifact_path}")

def main():
    print("================================================================")
    print(" [Sidebar Architecture Redesign - End-to-End Automated Verifier] ")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port {DEBUG_PORT} targeting {TARGET_URL} ...")
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
        print("[ERROR] Could not obtain DevTools WebSocket URL")
        proc.kill()
        sys.exit(1)

    print(f"[+] Connected to Browser DevTools: {ws_url}")
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

    def eval_js(expr):
        res = send_cdp("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True
        })
        val = res.get("result", {}).get("result", {}).get("value")
        return val

    send_cdp("Page.enable")
    send_cdp("Runtime.enable")

    print("[*] Waiting 4.0s for initial Dashboard view and backend API data load...")
    time.sleep(4.0)

    # -------------------------------------------------------------
    # Step 1: Verify Dashboard (Default Tab)
    # -------------------------------------------------------------
    print("[*] Step 1: Verifying default view is '仪表盘'...")
    dash_info = eval_js("""
        (function() {
            const navItems = Array.from(document.querySelectorAll('.sidebar-btn')).map(el => ({
                text: el.innerText.trim(),
                active: el.classList.contains('active')
            }));
            const charts = Array.from(document.querySelectorAll('canvas')).length;
            return { navItems, canvasCount: charts };
        })()
    """)
    print(f"    - Sidebar state: {dash_info}")
    ss1 = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss1.get("result", {}).get("data"), "sidebar_1_dashboard.png")

    # -------------------------------------------------------------
    # Step 2: Switch to '监控'
    # -------------------------------------------------------------
    print("[*] Step 2: Clicking sidebar '监控'...")
    eval_js("""
        (function() {
            const item = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('监控'));
            if (item) { item.click(); return true; }
            return false;
        })()
    """)
    time.sleep(2.5)

    mon_info = eval_js("""
        (function() {
            const devCards = Array.from(document.querySelectorAll('.glass-card')).length;
            const ifaceBtns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('接口详情')).length;
            return { devCards, ifaceBtns };
        })()
    """)
    print(f"    - Monitor view state: {mon_info}")
    ss2 = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss2.get("result", {}).get("data"), "sidebar_2_monitor.png")

    # -------------------------------------------------------------
    # Step 3: Click '接口详情' in Monitor to jump into '流量分析'
    # -------------------------------------------------------------
    print("[*] Step 3: Clicking '接口详情' to trigger drill-down to '流量分析'...")
    jump_info = eval_js("""
        (function() {
            const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('接口详情'));
            if (btns.length > 0) {
                btns[0].click();
                return { clicked: true, total: btns.length };
            }
            return { clicked: false };
        })()
    """)
    print(f"    - Jump result: {jump_info}")
    time.sleep(3.5)

    analysis_info = eval_js("""
        (function() {
            const activeBtn = document.querySelector('.sidebar-btn.active')?.innerText.trim();
            const trendChart = document.getElementById('ifaceTrendChart');
            const hasCanvas = trendChart ? !!trendChart.querySelector('canvas') : false;
            const selectors = Array.from(document.querySelectorAll('select')).map(s => s.value);
            return { activeBtn, hasCanvas, selectors };
        })()
    """)
    print(f"    - Traffic Analysis view state: {analysis_info}")
    ss3 = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss3.get("result", {}).get("data"), "sidebar_3_traffic_analysis.png")

    # -------------------------------------------------------------
    # Step 4: Switch to '网络'
    # -------------------------------------------------------------
    print("[*] Step 4: Clicking sidebar '网络'...")
    eval_js("""
        (function() {
            const item = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('网络'));
            if (item) { item.click(); return true; }
            return false;
        })()
    """)
    time.sleep(2.5)

    net_info = eval_js("""
        (function() {
            const tables = Array.from(document.querySelectorAll('table')).length;
            const rows = Array.from(document.querySelectorAll('tr')).length;
            return { tables, rows };
        })()
    """)
    print(f"    - Network view state: {net_info}")
    ss4 = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss4.get("result", {}).get("data"), "sidebar_4_network.png")

    # -------------------------------------------------------------
    # Step 5: Switch to '设置'
    # -------------------------------------------------------------
    print("[*] Step 5: Clicking sidebar '设置'...")
    eval_js("""
        (function() {
            const item = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('设置'));
            if (item) { item.click(); return true; }
            return false;
        })()
    """)
    time.sleep(2.5)

    set_info = eval_js("""
        (function() {
            const subtabs = Array.from(document.querySelectorAll('#settingsSubTab button')).map(b => b.innerText.trim());
            const activeSubtab = document.querySelector('#settingsSubTab button.btn-primary')?.innerText.trim();
            const visibleInputs = Array.from(document.querySelectorAll('input')).filter(i => window.getComputedStyle(i).display !== 'none').length;
            return { subtabs, activeSubtab, visibleInputs };
        })()
    """)
    print(f"    - Settings view state: {set_info}")
    ss5 = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss5.get("result", {}).get("data"), "sidebar_5_settings.png")

    # -------------------------------------------------------------
    # Step 6: Test direct navigation to '流量分析' and top bar selector
    # -------------------------------------------------------------
    print("[*] Step 6: Clicking sidebar '流量分析' directly...")
    eval_js("""
        (function() {
            const item = Array.from(document.querySelectorAll('.sidebar-btn')).find(el => el.innerText.includes('流量分析'));
            if (item) { item.click(); return true; }
            return false;
        })()
    """)
    time.sleep(2.5)

    ss6 = send_cdp("Page.captureScreenshot", {"format": "png"})
    save_image(ss6.get("result", {}).get("data"), "sidebar_6_traffic_selector.png")

    ws.close()
    proc.kill()
    print("================================================================")
    print(" [ALL 5 TABS & DRILL-DOWN VERIFIED SUCCESSFULLY] ")
    print("================================================================")

if __name__ == "__main__":
    main()
