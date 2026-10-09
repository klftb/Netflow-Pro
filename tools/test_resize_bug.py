import sys
import os
import time
import json
import subprocess
import urllib.request
import websocket
import base64
import tempfile

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/#/dashboard"
DEBUG_PORT = 9291

def main():
    temp_profile = os.path.join(tempfile.gettempdir(), f"edge_test_res_{int(time.time())}")
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        EDGE_PATH, "--headless", f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={temp_profile}",
        "--remote-allow-origins=*",
        "--no-first-run", "--no-default-browser-check", "--window-size=1920,1080",
        "--disable-gpu", "--hide-scrollbars", "--no-sandbox", TARGET_URL
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)

    req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
    with urllib.request.urlopen(req) as resp:
        ws_url = json.loads(resp.read().decode())[0]["webSocketDebuggerUrl"]

    ws = websocket.create_connection(ws_url, origin=f"http://127.0.0.1:{DEBUG_PORT}")
    msg_id = 1
    def send_cdp(method, params=None):
        nonlocal msg_id
        cur = msg_id
        ws.send(json.dumps({"id": cur, "method": method, "params": params or {}}))
        msg_id += 1
        while True:
            res = json.loads(ws.recv())
            if res.get("id") == cur:
                return res

    def eval_js(js):
        return send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True}).get("result", {}).get("result", {}).get("value")

    send_cdp("Page.enable")
    send_cdp("Runtime.enable")
    send_cdp("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False})

    send_cdp("Page.navigate", {"url": TARGET_URL})
    time.sleep(3.0)

    # 登录
    eval_js("""
    (function() {
        const inputs = document.querySelectorAll('.login-card input');
        if (inputs.length >= 2) {
            inputs[0].value = 'admin';
            inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
            inputs[1].value = 'admin';
            inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
            const btn = document.querySelector('.login-card button[type="submit"]');
            if (btn) btn.click();
        }
    })();
    """)
    time.sleep(4.0)

    # 1. 切换到网络统计
    print("[*] 切换到网络统计页面...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const netBtn = btns.find(b => b.innerText.includes('网络'));
        if (netBtn) netBtn.click();
    })();
    """)
    time.sleep(2.0)

    # 2. 在网络统计页面触发一次 window resize（模拟用户改变窗口大小或切出切入）
    print("[*] 触发 window resize 事件 (此时仪表盘为 display:none)...")
    eval_js("window.dispatchEvent(new Event('resize'))")
    time.sleep(0.5)

    # 3. 切换回仪表盘
    print("[*] 切换回仪表盘页面...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const dashBtn = btns.find(b => b.innerText.includes('仪表盘'));
        if (dashBtn) dashBtn.click();
    })();
    """)
    time.sleep(1.0)

    res = eval_js("""
    (function() {
        const trendDom = document.getElementById('trendChart');
        const trendCanvas = trendDom ? trendDom.querySelector('canvas') : null;
        const sankeyDom = document.getElementById('sankeyChart');
        const sankeyCanvas = sankeyDom ? sankeyDom.querySelector('canvas') : null;
        return {
            trendDomWidth: trendDom ? trendDom.clientWidth : 0,
            trendCanvasWidth: trendCanvas ? trendCanvas.clientWidth : 0,
            sankeyDomWidth: sankeyDom ? sankeyDom.clientWidth : 0,
            sankeyCanvasWidth: sankeyCanvas ? sankeyCanvas.clientWidth : 0
        };
    })();
    """)
    print("[!] 切换回仪表盘后的图表尺寸:", res)

    # 截图看实际视觉效果
    snap = send_cdp("Page.captureScreenshot", {"format": "png"})
    b64 = snap.get("result", {}).get("data", "")
    with open(r"d:\nTop\test_resize_shrink.png", "wb") as f:
        f.write(base64.b64decode(b64))
    print("[+] 保存截图至 d:\\nTop\\test_resize_shrink.png")

    ws.close()
    proc.kill()

if __name__ == "__main__":
    main()

