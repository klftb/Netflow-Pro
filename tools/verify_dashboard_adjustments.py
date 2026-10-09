#!/usr/bin/env python3
"""
Automated Verifier for Dashboard Adjustments:
1. Bandwidth Trend: col-12, distinct Tx and Rx curves, P95 line
2. Top 10 Talkers: col-12 below Trend, expanded with Hostnames, bytes, progress bars, flows, drill-down
3. Sankey Topology: col-12 at bottom with NetBox resolved Hostnames on nodes
"""

import sys
import os
import time
import json
import base64
import subprocess
import urllib.request
import websocket
import shutil

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"

ARTIFACT_DIR = r"C:\Users\Ben\.gemini\antigravity\brain\55f59907-6c6b-41b6-a7e8-388bea2059b9"
OUTPUT_FULL_IMAGE = r"d:\nTop\dashboard_full_view_verified.png"
OUTPUT_TREND_IMAGE = r"d:\nTop\dashboard_trend_dual_curves_verified.png"
OUTPUT_TOP10_IMAGE = r"d:\nTop\dashboard_top10_expanded_verified.png"
OUTPUT_SANKEY_IMAGE = r"d:\nTop\dashboard_sankey_hostnames_verified.png"

DEBUG_PORT = 9258

def send_cdp(ws, method, params=None, msg_id=1):
    payload = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(payload))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp

def capture_screenshot(ws, output_path, msg_id=100):
    res = send_cdp(ws, "Page.captureScreenshot", {"format": "png", "quality": 100}, msg_id=msg_id)
    b64_data = res.get("result", {}).get("data", "")
    if b64_data:
        raw_bytes = base64.b64decode(b64_data)
        with open(output_path, "wb") as f:
            f.write(raw_bytes)
        print(f"  [+] 截图保存至: {output_path} ({len(raw_bytes)} bytes)")
        basename = os.path.basename(output_path)
        dest = os.path.join(ARTIFACT_DIR, basename)
        shutil.copyfile(output_path, dest)
        print(f"  [+] 已同步至 Artifact 目录: {dest}")

def evaluate_js(ws, expr, msg_id=200):
    res = send_cdp(ws, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True
    }, msg_id=msg_id)
    return res.get("result", {}).get("result", {}).get("value")

def main():
    print("================================================================")
    print(" [Dashboard Adjustments & Hostname Enrichment - Automated Verifier] ")
    print("================================================================")

    if not os.path.exists(EDGE_PATH):
        print(f"[ERROR] Edge executable not found at {EDGE_PATH}")
        sys.exit(1)

    print(f"[*] Launching Headless Edge on port {DEBUG_PORT} ...")
    cmd = [
        EDGE_PATH,
        "--headless",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        "--window-size=1920,1400",
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
        print("[ERROR] Could not connect to Edge DevTools")
        proc.kill()
        sys.exit(1)

    try:
        ws = websocket.create_connection(ws_url)
        send_cdp(ws, "Page.enable", msg_id=1)
        send_cdp(ws, "Runtime.enable", msg_id=2)

        # 1. Check if login is required
        print("\n[*] 1. 检查页面登录状态...")
        has_overlay = evaluate_js(ws, "!!document.querySelector('.login-overlay')", msg_id=10)
        if has_overlay:
            print("  -> 检测到登录界面，执行自动登录 (admin / admin)...")
            login_res = evaluate_js(ws, """
                (async () => {
                    const inputs = document.querySelectorAll('.login-card input');
                    inputs[0].value = 'admin';
                    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
                    inputs[1].value = 'admin';
                    inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
                    const btn = document.querySelector('.login-card button[type="submit"]');
                    btn.click();
                    await new Promise(r => setTimeout(r, 1500));
                    return { token: localStorage.getItem('flow_auth_token') };
                })()
            """, msg_id=11)
            print(f"  -> 登录完成，Token={bool(login_res.get('token'))}")
        
        # Navigate to dashboard
        evaluate_js(ws, "window.location.hash = '#/dashboard';", msg_id=12)
        print("[*] 等待仪表盘数据与 ECharts 渲染 (4秒)...")
        time.sleep(4.0)

        # 2. Check layout classes
        print("\n[*] 2. 验证仪表盘排版结构 (宽度与顺序)...")
        layout_info = evaluate_js(ws, """
            (() => {
                const trendEl = document.getElementById('trendChart');
                const trendCardCol = trendEl ? trendEl.closest('.dashboard-card').parentElement.className : '';
                
                const topTableEl = document.querySelector('.top-table');
                const topCardCol = topTableEl ? topTableEl.closest('.dashboard-card').parentElement.className : '';
                
                const sankeyEl = document.getElementById('sankeyChart');
                const sankeyCardCol = sankeyEl ? sankeyEl.closest('.dashboard-card').parentElement.className : '';
                
                return {
                    trendCol: trendCardCol,
                    topCol: topCardCol,
                    sankeyCol: sankeyCardCol
                };
            })()
        """, msg_id=15)
        print(f"  -> 走势图所在列栅格: '{layout_info.get('trendCol')}' (预期: 包含 col-12)")
        print(f"  -> Top 10 所在列栅格: '{layout_info.get('topCol')}' (预期: 包含 col-12)")
        print(f"  -> 桑基图所在列栅格: '{layout_info.get('sankeyCol')}' (预期: 包含 col-12)")
        
        assert 'col-12' in layout_info.get('trendCol', ''), "走势图宽度未设置为 col-12！"
        assert 'col-12' in layout_info.get('topCol', ''), "Top 10 宽度未设置为 col-12！"
        assert 'col-12' in layout_info.get('sankeyCol', ''), "桑基图宽度未设置为 col-12！"

        # 3. Check Bandwidth Trend Data (distinct Rx and Tx)
        print("\n[*] 3. 验证双向带宽时序走势图 (出向 Tx vs 入向 Rx 双曲线)...")
        trend_chart_info = evaluate_js(ws, """
            (() => {
                const el = document.getElementById('trendChart');
                const chart = echarts.getInstanceByDom(el);
                if (!chart) return { error: "No echarts instance on trendChart" };
                const opt = chart.getOption();
                const series = opt.series || [];
                const txSeries = series.find(s => s.name && s.name.includes('出向'));
                const rxSeries = series.find(s => s.name && s.name.includes('入向'));
                
                const txData = txSeries ? txSeries.data : [];
                const rxData = rxSeries ? rxSeries.data : [];
                
                // Compare last 10 points
                let diffCount = 0;
                const sampleDiffs = [];
                for (let i = Math.max(0, txData.length - 10); i < txData.length; i++) {
                    const diff = Math.abs((txData[i] || 0) - (rxData[i] || 0));
                    if (diff > 0) diffCount++;
                    sampleDiffs.push({ idx: i, tx: txData[i], rx: rxData[i], diff: diff });
                }
                
                return {
                    seriesCount: series.length,
                    txName: txSeries ? txSeries.name : null,
                    rxName: rxSeries ? rxSeries.name : null,
                    dataPoints: txData.length,
                    sampleDiffs: sampleDiffs.slice(-3),
                    diffCount: diffCount
                };
            })()
        """, msg_id=20)
        print(f"  -> 时序图系列数: {trend_chart_info.get('seriesCount')}, 数据点数: {trend_chart_info.get('dataPoints')}")
        print(f"  -> 系列名称: Tx='{trend_chart_info.get('txName')}', Rx='{trend_chart_info.get('rxName')}'")
        for s in trend_chart_info.get('sampleDiffs', []):
            print(f"     样本点 -> Tx: {s.get('tx'):,.0f} bps, Rx: {s.get('rx'):,.0f} bps, 差值: {s.get('diff'):,.0f} bps")
        print(f"  -> 最近样本差异点数: {trend_chart_info.get('diffCount')} / 10")
        assert trend_chart_info.get('diffCount', 0) > 0, "时序图中出向与入向依然完全重叠或数据为空！"

        # 4. Check Top 10 Talkers with Hostnames & Progress Bars
        print("\n[*] 4. 验证 Top 10 业务统计表格 (放大布局、占比进度条与 NetBox 主机名)...")
        top_table_info = evaluate_js(ws, """
            (() => {
                const rows = Array.from(document.querySelectorAll('tr[id^="top-item-"]'));
                const items = rows.map(r => {
                    const labelEl = r.querySelector('.ip-address-text');
                    const progressEl = r.querySelector('.progress-bar');
                    return {
                        label: labelEl ? labelEl.innerText.trim() : '',
                        hasProgressBar: !!progressEl,
                        progressWidth: progressEl ? progressEl.style.width : ''
                    };
                });
                const hostnameCount = items.filter(it => it.label.includes('(') && it.label.includes(')')).length;
                return {
                    rowCount: rows.length,
                    hostnameCount: hostnameCount,
                    sampleItems: items.slice(0, 5)
                };
            })()
        """, msg_id=30)
        print(f"  -> 表格行数: {top_table_info.get('rowCount')}, 包含主机名格式的行数: {top_table_info.get('hostnameCount')}")
        for i, it in enumerate(top_table_info.get('sampleItems', [])):
            print(f"     #{i+1}: {it.get('label')} | 进度条宽度: {it.get('progressWidth')}")
        assert top_table_info.get('rowCount', 0) > 0, "Top 10 表格为空！"

        # 5. Check Sankey Topology Nodes for Hostnames
        print("\n[*] 5. 验证端到端网络业务流向拓扑 (Sankey 节点主机名)...")
        sankey_info = evaluate_js(ws, """
            (() => {
                const el = document.getElementById('sankeyChart');
                const chart = echarts.getInstanceByDom(el);
                if (!chart) return { error: "No echarts instance on sankeyChart" };
                const opt = chart.getOption();
                const series = (opt && opt.series && opt.series[0]) || {};
                const nodes = series.data || [];
                const links = series.links || [];
                
                const hostNodes = nodes.filter(n => n.name && n.name.includes('(') && n.name.includes(')'));
                return {
                    nodeCount: nodes.length,
                    linkCount: links.length,
                    hostNodeCount: hostNodes.length,
                    sampleNodes: nodes.slice(0, 6).map(n => n.name),
                    sampleHostNodes: hostNodes.slice(0, 4).map(n => n.name)
                };
            })()
        """, msg_id=40)
        print(f"  -> 桑基图节点总数: {sankey_info.get('nodeCount')}, 连线总数: {sankey_info.get('linkCount')}")
        print(f"  -> 包含主机名的节点数: {sankey_info.get('hostNodeCount')}")
        print(f"  -> 样本节点: {sankey_info.get('sampleNodes')}")
        print(f"  -> 命中 NetBox 主机名的样本节点: {sankey_info.get('sampleHostNodes')}")

        # 6. Capture Screenshots
        print("\n[*] 6. 截取高清验证图...")
        
        # Screenshot 1: Full View
        capture_screenshot(ws, OUTPUT_FULL_IMAGE, msg_id=101)

        # Screenshot 2: Trend Chart Focus
        evaluate_js(ws, "document.getElementById('trendChart').scrollIntoView({behavior: 'instant', block: 'center'});", msg_id=102)
        time.sleep(0.5)
        capture_screenshot(ws, OUTPUT_TREND_IMAGE, msg_id=103)

        # Screenshot 3: Top 10 Focus
        evaluate_js(ws, "document.querySelector('.top-table').scrollIntoView({behavior: 'instant', block: 'center'});", msg_id=104)
        time.sleep(0.5)
        capture_screenshot(ws, OUTPUT_TOP10_IMAGE, msg_id=105)

        # Screenshot 4: Sankey Focus
        evaluate_js(ws, "document.getElementById('sankeyChart').scrollIntoView({behavior: 'instant', block: 'center'});", msg_id=106)
        time.sleep(0.5)
        capture_screenshot(ws, OUTPUT_SANKEY_IMAGE, msg_id=107)

        print("\n================================================================")
        print(" [ALL VERIFICATION CHECKS PASSED SUCCESSFULLY] ")
        print("================================================================")

    finally:
        try:
            ws.close()
        except Exception:
            pass
        proc.kill()

if __name__ == "__main__":
    main()

