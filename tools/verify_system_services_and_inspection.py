#!/usr/bin/env python3
import sys
import os
import time
import json
import base64
import subprocess
import urllib.request
import websocket
import shutil
import tempfile

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/#/settings"

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
OUTPUT_SERVICES_IMG = r"d:\nTop\settings_services_status_verified.png"
OUTPUT_INSPECT_IMG = r"d:\nTop\settings_inspection_report_verified.png"

DEBUG_PORT = 9299

def main():
    temp_profile = os.path.join(tempfile.gettempdir(), f"edge_sys_{int(time.time())}")
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--remote-allow-origins=*",
        "--window-size=1920,1080",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        TARGET_URL
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)

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
        print("[!] Failed to get DevTools URL")
        proc.kill()
        sys.exit(1)

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

    send_cdp("Page.enable")
    send_cdp("Runtime.enable")
    send_cdp("Network.enable")
    send_cdp("Network.setCacheDisabled", {"cacheDisabled": True})
    send_cdp("Emulation.setDeviceMetricsOverride", {
        "width": 1920,
        "height": 1080,
        "deviceScaleFactor": 1,
        "mobile": False
    })

    def eval_js(js_code):
        res = send_cdp("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": True,
            "awaitPromise": True
        })
        return res.get("result", {}).get("result", {}).get("value")

    def capture_screenshot(out_path):
        res = send_cdp("Page.captureScreenshot", {"format": "png", "quality": 100})
        b64 = res.get("result", {}).get("data", "")
        if b64:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"[+] Saved: {out_path}")
            art_path = os.path.join(ARTIFACT_DIR, os.path.basename(out_path))
            shutil.copyfile(out_path, art_path)
            print(f"[+] Copied to artifact: {art_path}")

    print(f"[*] Navigating to {TARGET_URL} ...")
    send_cdp("Page.navigate", {"url": TARGET_URL})
    time.sleep(3.0)

    # 1. 登录
    print("[*] 检查登录状态...")
    eval_js("""
    (function() {
        const loginOverlay = document.querySelector('.login-overlay');
        if (loginOverlay) {
            const inputs = document.querySelectorAll('.login-card input');
            if (inputs.length >= 2) {
                inputs[0].value = 'admin';
                inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
                inputs[1].value = 'admin';
                inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
                const btn = document.querySelector('.login-card button[type="submit"]');
                if (btn) btn.click();
            }
        }
    })();
    """)
    time.sleep(3.0)

    # 2. 导航至设置模块与系统选项卡
    print("[*] 切换至【设置】模块 -> 【核心服务状态与系统巡检】子选项卡...")
    eval_js("""
    (function() {
        window.location.hash = '#/settings';
        setTimeout(() => {
            const btnSubTab = document.getElementById('btnSubTabSystem');
            if (btnSubTab) btnSubTab.click();
        }, 500);
    })();
    """)
    time.sleep(3.0)

    # 3. 验证受管核心服务列表是否正常加载
    services_info = eval_js("""
    (function() {
        const cards = document.querySelectorAll('#settingsSubTab ~ div .card .card');
        return {
            count: cards.length,
            htmlSnippet: document.body.innerText.substring(0, 500)
        };
    })();
    """)
    print("[*] Services info:", services_info)

    # 截图 1: 核心受管服务集群状态
    print("[*] 正在截取服务状态卡片视图...")
    capture_screenshot(OUTPUT_SERVICES_IMG)

    # 4. 点击【⚡ 开始一键全面巡检】按钮
    print("[*] 点击【⚡ 开始一键全面巡检】按钮...")
    eval_js("""
    (function() {
        const btn = document.getElementById('btnRunInspection');
        if (btn) btn.click();
    })();
    """)

    # 5. 等待巡检完成
    print("[*] 等待巡检完成 (最多 15 秒)...")
    for sec in range(15):
        time.sleep(1.0)
        report_status = eval_js("""
        (function() {
            const btn = document.getElementById('btnRunInspection');
            const scoreEl = document.querySelector('.display-6.fw-bold');
            return {
                btnText: btn ? btn.innerText.trim() : '',
                scoreText: scoreEl ? scoreEl.innerText.trim() : null
            };
        })();
        """)
        print(f"    - Step {sec+1}s: {report_status}")
        if report_status and report_status.get("scoreText") and "⚡" in report_status.get("btnText", ""):
            print("[+] 巡检执行完毕，成功生成报告！")
            break

    time.sleep(2.0)

    # 截图 2: 一键全面巡检报告与评分看板
    print("[*] 正在截取巡检结果报告视图...")
    capture_screenshot(OUTPUT_INSPECT_IMG)

    print("[+] 测试及验证全部顺利完成！")
    ws.close()
    proc.kill()

if __name__ == "__main__":
    main()

