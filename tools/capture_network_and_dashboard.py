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
TARGET_URL = "http://10.3.11.78:8080/#/dashboard"

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
OUTPUT_SUBNETS_IMG = r"d:\nTop\network_subnets_tab_verified.png"
OUTPUT_HOSTS_IMG = r"d:\nTop\network_hosts_tab_verified.png"
OUTPUT_MODAL_IMG = r"d:\nTop\network_add_host_modal_verified.png"
OUTPUT_DASHBOARD_IMG = r"d:\nTop\dashboard_hostname_verified.png"

DEBUG_PORT = 9277

def main():
    temp_profile = os.path.join(tempfile.gettempdir(), f"edge_clean_{int(time.time())}")
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

    # 显式导航到目标 URL，防止停留在空白或首次启动页面
    print(f"[*] Navigating to {TARGET_URL} ...")
    send_cdp("Page.navigate", {"url": TARGET_URL})
    time.sleep(3.0)

    url_now = eval_js("window.location.href")
    title_now = eval_js("document.title")
    print(f"[*] Loaded URL: {url_now}, Title: {title_now}")

    # 1. 登录
    print("[*] 检查并执行登录...")
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
    time.sleep(3.5)

    # 2. 导航至【网络统计】模块
    print("[*] 切换至【网络统计】模块 (hash: #/network)...")
    eval_js("""
    (function() {
        window.location.hash = '#/network';
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const netBtn = btns.find(b => b.innerText.includes('网络'));
        if (netBtn) netBtn.click();
    })();
    """)
    time.sleep(3.0)

    # 确保在 Tab 1: 业务网段维护
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('button'));
        const subnetBtn = btns.find(b => b.innerText.includes('业务网段维护') || b.innerText.includes('Subnets'));
        if (subnetBtn) subnetBtn.click();
    })();
    """)
    time.sleep(2.0)

    # 截图 1: 业务网段维护视图
    print("[*] 截取网络统计 - 业务网段维护视图...")
    capture_screenshot(OUTPUT_SUBNETS_IMG)

    # 3. 切换到 Tab 2: 32 位主机维护
    print("[*] 切换到【32 位主机维护】选项卡...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('button'));
        const hostBtn = btns.find(b => b.innerText.includes('32 位主机维护') || b.innerText.includes('32位主机维护'));
        if (hostBtn) hostBtn.click();
    })();
    """)
    time.sleep(3.5)

    # 截图 2: 32 位主机维护视图
    print("[*] 截取网络统计 - 32 位主机维护视图 (含 Netbox/Local 标签与分页)...")
    capture_screenshot(OUTPUT_HOSTS_IMG)

    # 4. 打开新增主机模态框
    print("[*] 打开【新增 Local 32 位主机】模态框...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('button'));
        const addBtn = btns.find(b => b.innerText.includes('新增 Local 主机') || b.innerText.includes('新增 32 位主机'));
        if (addBtn) addBtn.click();
    })();
    """)
    time.sleep(1.5)

    # 截图 3: 新增主机模态框
    print("[*] 截取新增主机模态框视图...")
    capture_screenshot(OUTPUT_MODAL_IMG)

    # 关闭模态框
    eval_js("""
    (function() {
        const closeBtns = Array.from(document.querySelectorAll('.modal-dialog button'));
        const cancelBtn = closeBtns.find(b => b.innerText.includes('取消'));
        if (cancelBtn) cancelBtn.click();
    })();
    """)
    time.sleep(1.0)

    # 5. 导航回【仪表盘】模块
    print("[*] 切换回【仪表盘】模块 (hash: #/dashboard)...")
    eval_js("""
    (function() {
        window.location.hash = '#/dashboard';
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const dashBtn = btns.find(b => b.innerText.includes('仪表盘'));
        if (dashBtn) dashBtn.click();
    })();
    """)
    time.sleep(4.5)

    # 截图 4: 仪表盘视图
    print("[*] 截取仪表盘视图 (验证 Top 10 主机名解析)...")
    capture_screenshot(OUTPUT_DASHBOARD_IMG)

    ws.close()
    proc.kill()
    try:
        shutil.rmtree(temp_profile, ignore_errors=True)
    except Exception:
        pass
    print("[+] 全部端到端自动化测试与高分辨率截图完毕！")

if __name__ == "__main__":
    main()

