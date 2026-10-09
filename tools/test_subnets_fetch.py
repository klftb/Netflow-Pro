import urllib.request, json, time, websocket, subprocess

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
cmd = [EDGE_PATH, "--headless", "--remote-debugging-port=9261", "--remote-allow-origins=*", "http://10.3.11.78:8080/"]
proc = subprocess.Popen(cmd)
time.sleep(2.0)

req = urllib.request.Request("http://127.0.0.1:9261/json")
with urllib.request.urlopen(req) as resp:
    targets = json.loads(resp.read().decode())
    ws_url = targets[0]["webSocketDebuggerUrl"]

ws = websocket.create_connection(ws_url)
def eval_js(expr, await_promise=False):
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True, "awaitPromise": await_promise}}))
    while True:
        raw = ws.recv()
        d = json.loads(raw)
        if d.get("id") == 1:
            return d.get("result", {}).get("result", {}).get("value")

time.sleep(3.0)
res = eval_js("fetch('http://10.3.11.78:8080/api/v1/config/subnets-summary').then(r => r.json())", await_promise=True)
print("Fetch result code:", res.get("code") if isinstance(res, dict) else res)
print("Fetch result data count:", len(res.get("data", [])) if isinstance(res, dict) else 0)

ws.close()
proc.kill()
