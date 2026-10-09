import subprocess, time, json, urllib.request, websocket

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
cmd = [EDGE_PATH, "--headless", "--remote-debugging-port=9249", "--remote-allow-origins=*", "--window-size=1920,1080", "about:blank"]
proc = subprocess.Popen(cmd)
time.sleep(2.0)

req = urllib.request.Request("http://127.0.0.1:9249/json")
with urllib.request.urlopen(req) as resp:
    targets = json.loads(resp.read().decode())
    ws_url = None
    for t in targets:
        if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
            ws_url = t["webSocketDebuggerUrl"]
            break

if not ws_url:
    print("NO WS URL")
    proc.kill()
    exit(1)

ws = websocket.create_connection(ws_url)
def send(method, params=None, id_val=1):
    ws.send(json.dumps({"id": id_val, "method": method, "params": params or {}}))
    while True:
        raw = ws.recv()
        d = json.loads(raw)
        if d.get("id") == id_val:
            return d

send("Console.enable", id_val=1)
send("Runtime.enable", id_val=2)
send("Page.enable", id_val=3)

# Navigate to target
print("Navigating to http://10.3.11.78:8080/ ...")
send("Page.navigate", {"url": "http://10.3.11.78:8080/"}, id_val=4)

ws.settimeout(1.0)
start_t = time.time()
while time.time() - start_t < 5.0:
    try:
        raw = ws.recv()
        d = json.loads(raw)
        method = d.get("method", "")
        if "console" in method.lower() or "exception" in method.lower():
            print(f"[{method}] {json.dumps(d.get('params', {}), ensure_ascii=False)}")
    except Exception:
        pass

# Check html content and Vue status
res = send("Runtime.evaluate", {"expression": "document.body.innerHTML", "returnByValue": True}, id_val=10)
body_html = res.get("result", {}).get("result", {}).get("value", "")
print(f"Body length: {len(body_html)}")
print(f"Body snippet: {body_html[:300]}")

res_vue = send("Runtime.evaluate", {"expression": "typeof Vue !== 'undefined' ? 'Vue OK' : 'No Vue'", "returnByValue": True}, id_val=11)
print("Vue check:", res_vue.get("result", {}).get("result", {}).get("value"))

ws.close()
proc.kill()
