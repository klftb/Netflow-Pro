import urllib.request, json, websocket, time, subprocess

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
DEBUG_PORT = 9260

proc = subprocess.Popen([
    EDGE_PATH, "--headless", f"--remote-debugging-port={DEBUG_PORT}",
    "--remote-allow-origins=*", TARGET_URL
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
targets = json.loads(urllib.request.urlopen(req).read().decode())
ws_url = [t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"][0]
ws = websocket.create_connection(ws_url)

ws.send(json.dumps({"id": 1, "method": "Debugger.enable"}))
time.sleep(2.0)

scripts = []
while True:
    try:
        ws.settimeout(0.5)
        msg = json.loads(ws.recv())
        if msg.get("method") == "Debugger.scriptParsed":
            scripts.append(msg["params"])
    except Exception:
        break

for s in scripts:
    print(f"ID: {s['scriptId']}, url: {s.get('url')}, startLine: {s.get('startLine')}, endLine: {s.get('endLine')}")

ws.close()
proc.kill()
