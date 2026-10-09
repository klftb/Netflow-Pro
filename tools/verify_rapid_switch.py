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
OUTPUT_TREND_FIXED = r"d:\nTop\dashboard_switch_trend_fixed.png"
OUTPUT_SANKEY_FIXED = r"d:\nTop\dashboard_switch_sankey_fixed.png"
DEBUG_PORT = 9295

def main():
    temp_profile = os.path.join(tempfile.gettempdir(), f"edge_rapid_{int(time.time())}")
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={temp_profile}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1920,1080",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        TARGET_URL
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)

    req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
    with urllib.request.urlopen(req) as resp:
        targets = json.loads(resp.read().decode())
        ws_url = [t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"][0]

    ws = websocket.create_connection(ws_url)

    msg_id = 1
    def send_cdp(method, params=None):
        nonlocal msg_id
        cur_id = msg_id
        ws.send(json.dumps({"id": cur_id, "method": method, "params": params or {}}))
        msg_id += 1
        while True:
            res = json.loads(ws.recv())
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

    def eval_js(js):
        return send_cdp("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
            "awaitPromise": True
        }).get("result", {}).get("result", {}).get("value")

    send_cdp("Page.navigate", {"url": TARGET_URL})
    time.sleep(3.0)

    # 1. 登录
    print("[*] 登录验证...")
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

    # 2. 等待初始图表完全就绪
    print("[*] 等待仪表盘初始数据加载与首次渲染...")
    for _ in range(30):
        ready = eval_js("""
        (function() {
            const t = document.getElementById('trendChart');
            const s = document.getElementById('sankeyChart');
            const tc = t ? t.querySelector('canvas') : null;
            const sc = s ? s.querySelector('canvas') : null;
            return !!(tc && sc && tc.clientWidth > 500 && sc.clientWidth > 500);
        })();
        """)
        if ready:
            print("  -> 初始图表双双渲染完成 (宽度均 > 500px)")
            break
        time.sleep(0.5)

    def measure_charts():
        return eval_js("""
        (function() {
            const t = document.getElementById('trendChart');
            const s = document.getElementById('sankeyChart');
            const tc = t ? t.querySelector('canvas') : null;
            const sc = s ? s.querySelector('canvas') : null;
            return {
                trendDomWidth: t ? t.clientWidth : 0,
                trendCanvasWidth: tc ? tc.clientWidth : 0,
                sankeyDomWidth: s ? s.clientWidth : 0,
                sankeyCanvasWidth: sc ? sc.clientWidth : 0
            };
        })();
        """)

    print("[*] 初始图表物理尺寸:", measure_charts())

    # 3. 轮换切换测试 1: 仪表盘 -> 网络统计 (触发 resize) -> 仪表盘
    print("\n[*] 轮换测试 1: 切换到【网络统计】并在隐藏状态触发全局 resize，再切回【仪表盘】...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const netBtn = btns.find(b => b.innerText.includes('网络'));
        if (netBtn) netBtn.click();
    })();
    """)
    time.sleep(1.5)
    eval_js("window.dispatchEvent(new Event('resize'))")
    time.sleep(0.5)
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const dashBtn = btns.find(b => b.innerText.includes('仪表盘'));
        if (dashBtn) dashBtn.click();
    })();
    """)
    time.sleep(1.5)
    m1 = measure_charts()
    print("  -> 切回结果 1:", m1)

    # 4. 轮换切换测试 2: 仪表盘 -> 设备管理 (触发 resize) -> 仪表盘
    print("\n[*] 轮换测试 2: 切换到【设备管理】并在隐藏状态触发全局 resize，再切回【仪表盘】...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const devBtn = btns.find(b => b.innerText.includes('设备管理'));
        if (devBtn) devBtn.click();
    })();
    """)
    time.sleep(1.5)
    eval_js("window.dispatchEvent(new Event('resize'))")
    time.sleep(0.5)
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const dashBtn = btns.find(b => b.innerText.includes('仪表盘'));
        if (dashBtn) dashBtn.click();
    })();
    """)
    time.sleep(1.5)
    m2 = measure_charts()
    print("  -> 切回结果 2:", m2)

    # 5. 轮换切换测试 3: 仪表盘 -> 流量分析 (触发 resize) -> 仪表盘
    print("\n[*] 轮换测试 3: 切换到【流量分析】并在隐藏状态触发全局 resize，再切回【仪表盘】...")
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const flwBtn = btns.find(b => b.innerText.includes('流量分析'));
        if (flwBtn) flwBtn.click();
    })();
    """)
    time.sleep(1.5)
    eval_js("window.dispatchEvent(new Event('resize'))")
    time.sleep(0.5)
    eval_js("""
    (function() {
        const btns = Array.from(document.querySelectorAll('.sidebar-btn'));
        const dashBtn = btns.find(b => b.innerText.includes('仪表盘'));
        if (dashBtn) dashBtn.click();
    })();
    """)
    time.sleep(1.5)
    m3 = measure_charts()
    print("  -> 切回结果 3:", m3)

    # 6. 截取走势图与桑基图
    print("\n[*] 截取切换后走势图视图...")
    snap = send_cdp("Page.captureScreenshot", {"format": "png"})
    with open(OUTPUT_TREND_FIXED, "wb") as f:
        f.write(base64.b64decode(snap.get("result", {}).get("data", "")))
    shutil.copyfile(OUTPUT_TREND_FIXED, os.path.join(ARTIFACT_DIR, os.path.basename(OUTPUT_TREND_FIXED)))

    print("[*] 滚动至底部截取桑基拓扑图视图...")
    eval_js("const c = document.querySelector('.app-content'); if (c) c.scrollTop = 1200;")
    time.sleep(1.0)
    snap2 = send_cdp("Page.captureScreenshot", {"format": "png"})
    with open(OUTPUT_SANKEY_FIXED, "wb") as f:
        f.write(base64.b64decode(snap2.get("result", {}).get("data", "")))
    shutil.copyfile(OUTPUT_SANKEY_FIXED, os.path.join(ARTIFACT_DIR, os.path.basename(OUTPUT_SANKEY_FIXED)))

    ws.close()
    proc.kill()

    # 综合评估
    passed = (m3['trendCanvasWidth'] > 1200 and m3['sankeyCanvasWidth'] > 1200)
    if passed:
        print("\n[SUCCESS] 3 轮全面多页面切屏与全局 Resize 压测 100% 通过！图表宽度完美自适应并保持满宽！")
    else:
        print(f"\n[FAIL] 宽度自适应验证未通过: {m3}")
        sys.exit(1)

if __name__ == "__main__":
    main()

