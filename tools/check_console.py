import subprocess, time, json, urllib.request, websocket

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
cmd = [EDGE_PATH, "--headless", "--remote-debugging-port=9248", "--remote-allow-origins=*", "http://10.3.11.78:8080/"]
proc = subprocess.Popen(cmd)
time.sleep(2.5)

req = urllib.request.Request("http://127.0.0.1:9248/json")
with urllib.request.urlopen(req) as resp:
    targets = json.loads(resp.read().decode())
    ws_url = targets[0]["webSocketDebuggerUrl"]

ws = websocket.create_connection(ws_url)
ws.send(json.dumps({"id": 1, "method": "Console.enable"}))
ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
ws.send(json.dumps({"id": 3, "method": "Page.enable"}))

# reload page so Console.enable captures startup errors
ws.send(json.dumps({"id": 4, "method": "Page.reload"}))

time.sleep(3.0)
ws.settimeout(2.0)
logs = []
try:
    while True:
        msg = ws.recv()
        d = json.loads(msg)
        m = d.get("method", "")
        if "console" in m.lower() or "exception" in m.lower() or "log" in m.lower():
            logs.append(d)
except Exception:
    pass

print(f"Captured {len(logs)} log entries:")
for l in logs:
    print(json.dumps(l, ensure_ascii=False))

# check #app
ws.send(json.dumps({"id": 99, "method": "Runtime.evaluate", "params": {"expression": "document.getElementById('app') ? document.getElementById('app').innerHTML.substring(0, 300) : 'NO APP'"}}))
res = json.loads(ws.recv())
print("App preview:", res.get("result", {}).get("result", {}).get("value"))

ws.close()
proc.kill()
