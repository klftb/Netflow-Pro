import urllib.request, json, websocket, time, subprocess

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
DEBUG_PORT = 9265

proc = subprocess.Popen([
    EDGE_PATH, "--headless", f"--remote-debugging-port={DEBUG_PORT}",
    "--remote-allow-origins=*", TARGET_URL
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
targets = json.loads(urllib.request.urlopen(req).read().decode())
ws_url = [t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"][0]
ws = websocket.create_connection(ws_url)

ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
time.sleep(2.0)

# Hook into Vue compiler
res = ws.send(json.dumps({
    "id": 2,
    "method": "Runtime.evaluate",
    "params": {
        "expression": """
            (function() {
                const app = document.getElementById('app');
                const tpl = app.innerHTML;
                try {
                    const compiled = Vue.compile(tpl);
                    return { ok: true };
                } catch (e) {
                    return { ok: false, error: e.toString(), stack: e.stack };
                }
            })()
        """,
        "returnByValue": True
    }
}))

while True:
    raw = ws.recv()
    msg = json.loads(raw)
    if msg.get("id") == 2:
        print("Compile test:", json.dumps(msg.get("result", {}).get("result", {}).get("value"), indent=2))
        break

ws.close()
proc.kill()
