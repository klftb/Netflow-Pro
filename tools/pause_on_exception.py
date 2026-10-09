import urllib.request, json, websocket, time, subprocess

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
DEBUG_PORT = 9268

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
ws.send(json.dumps({"id": 2, "method": "Debugger.setPauseOnExceptions", "params": {"state": "uncaught"}}))

while True:
    try:
        raw = ws.recv()
        msg = json.loads(raw)
        if msg.get("method") == "Debugger.paused":
            callFrames = msg["params"]["callFrames"]
            print("PAUSED ON EXCEPTION!")
            for f in callFrames:
                print(f"  at {f['functionName']} ({f.get('url')}:{f['location']['lineNumber']}:{f['location']['columnNumber']})")
                print(f"     scope: {f.get('scopeChain')}")
            break
    except Exception as e:
        print("Exception:", e)
        break

ws.close()
proc.kill()
