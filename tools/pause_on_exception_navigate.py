import urllib.request, json, websocket, time, subprocess

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
DEBUG_PORT = 9272

proc = subprocess.Popen([
    EDGE_PATH, "--headless", f"--remote-debugging-port={DEBUG_PORT}",
    "--remote-allow-origins=*", "about:blank"
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.0)

req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
targets = json.loads(urllib.request.urlopen(req).read().decode())
ws_url = [t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"][0]
ws = websocket.create_connection(ws_url)

def send(method, params=None):
    ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
    while True:
        res = json.loads(ws.recv())
        if res.get("id") == 1:
            return res

send("Page.enable")
send("Runtime.enable")
send("Debugger.enable")
send("Debugger.setPauseOnExceptions", {"state": "uncaught"})

# Now navigate to TARGET_URL
send("Page.navigate", {"url": TARGET_URL})

for _ in range(30):
    try:
        ws.settimeout(1.5)
        raw = ws.recv()
        msg = json.loads(raw)
        if msg.get("method") == "Debugger.paused":
            params = msg["params"]
            print("PAUSED ON EXCEPTION:", params.get("reason"), params.get("data"))
            callFrames = params["callFrames"]
            for f in callFrames:
                print(f"  at {f['functionName']} ({f.get('url')}:{f['location']['lineNumber']}:{f['location']['columnNumber']})")
            break
    except Exception:
        pass

ws.close()
proc.kill()
