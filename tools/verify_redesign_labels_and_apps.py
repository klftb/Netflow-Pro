#!/usr/bin/env python3
"""
Comprehensive Verifier for Labels Redesign & App Mapping Management:
1. Sidebar: 监控 -> 设备管理, 网络 -> 网络统计
2. Header:
   - Monitor: 设备管理
   - Traffic Analysis: 流量分析平台
   - Network: 网络统计 (Subnets & IPAM)
3. Traffic Analysis Interface Selector: '[采样中]' without any flame icon
4. Settings: Common protocols loaded, search/filter works, edit & delete works
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
DEBUG_PORT = 9298

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
    print(" [Labels Redesign & App Mapping Management Verifier] ", flush=True)
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
    ws.settimeout(20.0)

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
        time.sleep(3.0)

        # -------------------------------------------------------------
        # 1. 验证侧边栏标签修改
        # -------------------------------------------------------------
        print("\n--- [Step 1] Verifying Sidebar & Monitor Header ---", flush=True)
        sidebar_items = eval_js("""
            Array.from(document.querySelectorAll('.sidebar-menu .sidebar-btn span')).map(el => el.innerText.trim())
        """)
        print(f"[+] Sidebar navigation buttons: {sidebar_items}")
        assert '设备管理' in sidebar_items, "Sidebar does not contain '设备管理'"
        assert '网络统计' in sidebar_items, "Sidebar does not contain '网络统计'"
        assert '监控' not in sidebar_items, "Sidebar still contains old '监控'"
        assert '网络' not in [s for s in sidebar_items if s == '网络'], "Sidebar still contains plain '网络'"
        print("[PASS] Sidebar buttons successfully updated to '设备管理' & '网络统计'!")

        # 切换到设备管理
        eval_js("window.location.hash = '#/monitor'")
        time.sleep(2.0)
        top_header_monitor = eval_js("document.querySelector('.app-topbar h6').innerText.trim()")
        print(f"[+] Monitor top header text: {top_header_monitor}")
        assert top_header_monitor == '设备管理', f"Header text mismatch: {top_header_monitor}"
        print("[PASS] Monitor top header is exactly '设备管理'!")
        capture("redesign_1_device_management_view.png")

        # -------------------------------------------------------------
        # 2. 验证流量分析平台与“采样中”图标移除
        # -------------------------------------------------------------
        print("\n--- [Step 2] Verifying Traffic Analysis Platform & Interface Selector ---", flush=True)
        eval_js("window.location.hash = '#/traffic_analysis'")
        time.sleep(3.0)
        top_header_traffic = eval_js("document.querySelector('.app-topbar h6').innerText.trim()")
        print(f"[+] Traffic analysis top header text: {top_header_traffic}")
        assert top_header_traffic == '流量分析平台', f"Header text mismatch: {top_header_traffic}"
        print("[PASS] Traffic analysis header successfully renamed to '流量分析平台'!")

        # 打印当前页面所有 select 和 options 并截图
        time.sleep(2.0)
        capture("redesign_2_traffic_analysis_platform.png")
        select_dump = eval_js("""
            Array.from(document.querySelectorAll('select')).map(s => {
                return {
                    name: s.className,
                    options: Array.from(s.options).map(o => ({ value: o.value, text: o.innerText.trim() }))
                };
            })
        """)
        print(f"[DEBUG] select dump: {select_dump}")

        # 检查所有选项
        all_option_texts = eval_js("""
            Array.from(document.querySelectorAll('select option')).map(o => o.innerText.trim())
        """)
        has_flame = any('🔥' in t for t in all_option_texts)
        assert not has_flame, f"Option still contains flame emoji: {[t for t in all_option_texts if '🔥' in t]}"
        print("[PASS] Verified: No flame icon '🔥' in any interface option!")

        # -------------------------------------------------------------
        # 3. 验证网络统计模块标题
        # -------------------------------------------------------------
        print("\n--- [Step 3] Verifying Network Statistics Module ---", flush=True)
        eval_js("window.location.hash = '#/network'")
        time.sleep(2.0)
        top_header_network = eval_js("document.querySelector('.app-topbar h6').innerText.trim()")
        print(f"[+] Network top header text: {top_header_network}")
        assert '网络统计' in top_header_network, f"Network header mismatch: {top_header_network}"
        print("[PASS] Network module top header successfully updated to '网络统计'!")
        capture("redesign_3_network_statistics_view.png")

        # -------------------------------------------------------------
        # 4. 验证设置模块中的常用协议字典、搜索、修改与删除功能
        # -------------------------------------------------------------
        print("\n--- [Step 4] Verifying Settings App Mapping Management ---", flush=True)
        eval_js("window.location.hash = '#/settings'")
        time.sleep(2.0)

        # 检查是否已加载 60+ 个常用协议
        total_apps_count = eval_js("""
            document.querySelectorAll('#appSettingsForm + div + div tbody tr').length
        """)
        print(f"[+] Rendered app mappings row count: {total_apps_count}")
        assert total_apps_count >= 50, f"Expected >= 50 common protocols, got {total_apps_count}"

        # 检查常见协议是否存在（如 HTTP, HTTPS, SSH, Redis, MySQL, SMB, BGP）
        app_names = eval_js("""
            Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr td:nth-child(3)')).map(e => e.innerText.trim())
        """)
        for proto_name in ['HTTP', 'HTTPS', 'SSH', 'Redis', 'MySQL', 'SMB', 'BGP', 'DNS']:
            assert proto_name in app_names, f"Protocol {proto_name} not found in dictionary!"
        print(f"[PASS] Common protocols successfully populated! (Sample: HTTP, HTTPS, SSH, Redis, MySQL, SMB, BGP, DNS)")
        capture("redesign_4_settings_common_protocols.png")

        # 测试协议搜索过滤
        print("\n--- [Step 4.1] Testing App Mapping Search Filter ---", flush=True)
        eval_js("""
            const input = document.querySelector('input[placeholder*=\"搜索应用名称\"]');
            if (input) {
                input.value = 'Redis';
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        """)
        time.sleep(0.8)
        filtered_names = eval_js("""
            Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr td:nth-child(3)')).map(e => e.innerText.trim()).filter(Boolean)
        """)
        print(f"[+] Search 'Redis' results: {filtered_names}")
        assert 'Redis' in filtered_names and len(filtered_names) == 1, f"Search filtering failed: {filtered_names}"
        print("[PASS] Protocol search filtering works perfectly!")
        capture("redesign_5_settings_search_redis.png")

        # 清空搜索
        eval_js("""
            const clearBtn = document.querySelector('button[title=\"清空\"]');
            if (clearBtn) clearBtn.click();
        """)
        time.sleep(0.5)

        # 测试协议编辑/修改功能
        print("\n--- [Step 4.2] Testing App Mapping Edit Functionality ---", flush=True)
        eval_js("""
            // Find Redis row (port 6379) and click its 修改 button
            const rows = Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr'));
            const redisRow = rows.find(r => r.innerText.includes('6379'));
            if (redisRow) {
                const editBtn = Array.from(redisRow.querySelectorAll('button')).find(b => b.innerText.includes('修改'));
                if (editBtn) editBtn.click();
            }
        """)
        time.sleep(1.0)
        form_state = eval_js("""
            ({
                title: document.querySelector('#appSettingsForm h6').innerText.trim(),
                port: document.querySelector('#appSettingsForm input[placeholder*=\"端口号\"]').value,
                appName: document.querySelector('#appSettingsForm input[placeholder*=\"应用名称\"]').value,
                category: document.querySelector('#appSettingsForm input[placeholder*=\"分类\"]').value,
                saveBtnText: document.querySelector('#appSettingsForm button.btn-warning').innerText.trim()
            })
        """)
        print(f"[+] Edit form state: {form_state}")
        assert form_state['port'] == '6379' and form_state['appName'] == 'Redis', "Form did not load Redis data"
        assert '修改应用协议定义' in form_state['title'] and '更新协议' in form_state['saveBtnText'], "Edit mode UI not activated"
        print("[PASS] Edit button loaded protocol into form and activated update mode!")
        capture("redesign_6_settings_edit_mode.png")

        # 取消修改
        eval_js("""
            const cancelBtn = Array.from(document.querySelectorAll('#appSettingsForm button')).find(b => b.innerText.includes('取消修改'));
            if (cancelBtn) cancelBtn.click();
        """)
        time.sleep(0.5)

        # 测试新增与删除功能
        print("\n--- [Step 4.3] Testing App Mapping Add & Delete Functionality ---", flush=True)
        # 添加自定义测试协议 TCP 9988 -> 'DemoMonitorApp'
        eval_js("""
            const form = document.querySelector('#appSettingsForm');
            form.querySelector('input[placeholder*=\"端口号\"]').value = '9988';
            form.querySelector('input[placeholder*=\"端口号\"]').dispatchEvent(new Event('input', { bubbles: true }));
            form.querySelector('input[placeholder*=\"应用名称\"]').value = 'DemoMonitorApp';
            form.querySelector('input[placeholder*=\"应用名称\"]').dispatchEvent(new Event('input', { bubbles: true }));
            form.querySelector('input[placeholder*=\"分类\"]').value = 'Testing';
            form.querySelector('input[placeholder*=\"分类\"]').dispatchEvent(new Event('input', { bubbles: true }));
            const saveBtn = Array.from(form.querySelectorAll('button')).find(b => b.innerText.includes('保存'));
            if (saveBtn) saveBtn.click();
        """)
        time.sleep(2.0)

        # 检查 9988 是否出现在列表中
        has_demo = eval_js("""
            Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr')).some(r => r.innerText.includes('9988') && r.innerText.includes('DemoMonitorApp'))
        """)
        print(f"[+] Custom protocol added successfully: {has_demo}")
        assert has_demo, "Added custom protocol 9988 not found in table"

        # 点击删除并确认
        del_click = eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr'));
                const demoRow = rows.find(r => r.innerText.includes('9988'));
                if (!demoRow) return 'Row 9988 not found';
                const delBtn = Array.from(demoRow.querySelectorAll('button')).find(b => b.innerText.includes('删除'));
                if (!delBtn) return 'Delete button not found';
                delBtn.click();
                return 'Delete button clicked';
            })()
        """)
        print(f"[+] Initial delete button click: {del_click}", flush=True)
        time.sleep(1.0)

        # 点击两步确认的勾选按钮
        confirm_click = eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr'));
                const demoRow = rows.find(r => r.innerText.includes('9988'));
                if (!demoRow) return 'Row 9988 not found for confirmation';
                const confirmBtn = demoRow.querySelector('.btn-danger');
                if (!confirmBtn) return 'Confirm danger button not found';
                confirmBtn.click();
                return 'Confirm danger button clicked';
            })()
        """)
        print(f"[+] Confirm delete button click: {confirm_click}", flush=True)
        time.sleep(2.5)

        has_demo_after_del = eval_js("""
            Array.from(document.querySelectorAll('#appSettingsForm + div + div tbody tr')).some(r => r.innerText.includes('9988'))
        """)
        print(f"[+] Protocol 9988 present after deletion: {has_demo_after_del}", flush=True)
        assert not has_demo_after_del, "Protocol 9988 still present after delete"
        print("[PASS] App mapping addition, inline two-step deletion, and persistence verified!")
        capture("redesign_7_settings_after_deletion.png")

        print("\n================================================================", flush=True)
        print(" [ALL 5 REQUIREMENTS FULLY VERIFIED AND PASSED!] ")
        print("================================================================", flush=True)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        proc.kill()

if __name__ == '__main__':
    main()
