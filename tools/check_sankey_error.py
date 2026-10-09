import subprocess
import time
import json
import urllib.request
import websocket

edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
proc = subprocess.Popen([edge_path, "--headless", "--remote-debugging-port=9292", "--remote-allow-origins=*", "--no-sandbox", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)

try:
    with urllib.request.urlopen("http://127.0.0.1:9292/json") as r:
        ws_url = [t["webSocketDebuggerUrl"] for t in json.loads(r.read().decode()) if t.get("type") == "page"][0]
    ws = websocket.create_connection(ws_url)

    msg_id = 1
    def cdp(m, params=None):
        global msg_id
        cid = msg_id
        msg_id += 1
        ws.send(json.dumps({"id": cid, "method": m, "params": params or {}}))
        while True:
            res = json.loads(ws.recv())
            if res.get("id") == cid:
                return res

    cdp("Page.enable")
    cdp("Runtime.enable")
    cdp("Log.enable")
    cdp("Page.navigate", {"url": "http://10.3.11.78:8080/#/dashboard"})
    time.sleep(3)

    # Trigger change on Vue model directly
    eval_res = cdp("Runtime.evaluate", {
        "expression": """
            (() => {
                const vueApp = document.querySelector('#app').__vue_app__;
                // Find exporter 10.4.1.254
                const sel = document.getElementById('exporterSelect');
                sel.value = '10.4.1.254';
                sel.dispatchEvent(new Event('change'));
                document.getElementById('queryBtn').click();
            })()
        """,
        "returnByValue": True
    })
    time.sleep(3)

    # Let's inspect console errors from window
    logs = cdp("Runtime.evaluate", {
        "expression": "window.__captured_errors || []",
        "returnByValue": True
    })
    print("Captured logs:", logs)

    check_errors = cdp("Runtime.evaluate", {
        "expression": """
            (() => {
                return {
                    sankeyNodes: (window.sankeyChartInstance ? window.sankeyChartInstance.getOption().series[0].data.length : 0),
                    sankeyLinks: (window.sankeyChartInstance ? window.sankeyChartInstance.getOption().series[0].links.length : 0),
                    topItemsCount: document.querySelectorAll('.top-table tbody tr').length
                };
            })()
        """,
        "returnByValue": True
    })
    print("DOM & Chart State:", json.dumps(check_errors, indent=2))

finally:
    if 'ws' in locals() and ws:
        try:
            ws.close()
        except:
            pass
    proc.terminate()
    proc.wait()
