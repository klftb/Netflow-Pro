#!/usr/bin/env python3
import sys
import os
import time
import json
import subprocess
import urllib.request
import websocket
import tempfile

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/#/dashboard"
DEBUG_PORT = 9288

def main():
    temp_profile = os.path.join(tempfile.gettempdir(), f"edge_test_bug_{int(time.time())}")
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
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

    send_cdp("Page.navigate", {"url": TARGET_URL})
    time.sleep(3.0)

    # 登录
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
    time.sleep(4.0)

    def get_chart_widths():
        return eval_js("""
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

    print("[*] 等待桑基图和走势图数据请求与首次渲染完成...")
    for _ in range(25):
        w = get_chart_widths()
        if w['trendCanvasWidth'] > 0 and w['sankeyCanvasWidth'] > 0:
            break
        time.sleep(0.5)

    initial_widths = get_chart_widths()
    print("[1] 初始进入仪表盘页面图表宽度:", initial_widths)

    print("[*] 模拟用户点击切换到【网络统计】页面...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const netBtn = btns.find(b => b.innerText.includes('网络'));
        if (netBtn) netBtn.click();
    })();
    """)
    time.sleep(2.0)

    print("[*] 关键步骤：在网络统计页面触发全局 window resize 事件 (此时仪表盘为 display: none)...")
    eval_js("window.dispatchEvent(new Event('resize'))")
    time.sleep(0.5)

    print("[*] 模拟用户从【网络统计】切换回【仪表盘】页面...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const dashBtn = btns.find(b => b.innerText.includes('仪表盘'));
        if (dashBtn) dashBtn.click();
    })();
    """)
    time.sleep(1.0) # 等待 1 秒看图表是否已经恢复

    switched_widths = get_chart_widths()
    print("[2] 切换回仪表盘后图表宽度:", switched_widths)

    # 截取切换回仪表盘后的顶部视觉效果 (走势图与 Top 10)
    res = send_cdp("Page.captureScreenshot", {"format": "png"})
    b64 = res.get("result", {}).get("data", "")
    if b64:
        import base64
        with open(r"d:\nTop\switched_dashboard_trend_fixed.png", "wb") as f:
            f.write(base64.b64decode(b64))
        print("[+] 保存切换走势图截图至 d:\\nTop\\switched_dashboard_trend_fixed.png")

    # 滚动至底部截取桑基图拓扑
    print("[*] 滚动到底部截取桑基拓扑图...")
    eval_js("const appContent = document.querySelector('.app-content'); if (appContent) appContent.scrollTop = 1200; else window.scrollTo(0, 1200);")
    time.sleep(1.0)
    res2 = send_cdp("Page.captureScreenshot", {"format": "png"})
    b64_2 = res2.get("result", {}).get("data", "")
    if b64_2:
        import base64
        with open(r"d:\nTop\switched_dashboard_sankey_fixed.png", "wb") as f:
            f.write(base64.b64decode(b64_2))
        print("[+] 保存切换桑基图截图至 d:\\nTop\\switched_dashboard_sankey_fixed.png")

    ws.close()
    proc.kill()

    # 评估结果
    if switched_widths['trendCanvasWidth'] < 500 or switched_widths['sankeyCanvasWidth'] < 500:
        print("[!] 成功重现 BUG: 图表 canvas 宽度异常变窄 (小于 500px)！")
    else:
        print("[+] 图表 canvas 宽度正常，未能重现或已恢复！")

if __name__ == "__main__":
    main()

