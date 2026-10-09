import urllib.request, json, websocket, time, subprocess

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
DEBUG_PORT = 9275

proc = subprocess.Popen([
    EDGE_PATH, "--headless", f"--remote-debugging-port={DEBUG_PORT}",
    "--remote-allow-origins=*", "about:blank"
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.0)

req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json")
targets = json.loads(urllib.request.urlopen(req).read().decode())
ws_url = [t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"][0]
ws = websocket.create_connection(ws_url)

msg_id = 1
def send(method, params=None):
    global msg_id
    cur_id = msg_id
    ws.send(json.dumps({"id": cur_id, "method": method, "params": params or {}}))
    msg_id += 1
    while True:
        res = json.loads(ws.recv())
        if res.get("id") == cur_id:
            return res

send("Page.enable")
send("Runtime.enable")
send("Debugger.enable")
send("Debugger.setPauseOnExceptions", {"state": "uncaught"})

send("Page.navigate", {"url": TARGET_URL})

while True:
    raw = ws.recv()
    msg = json.loads(raw)
    if msg.get("method") == "Debugger.paused":
        params = msg["params"]
        callFrames = params["callFrames"]
        topFrame = callFrames[0]
        callFrameId = topFrame["callFrameId"]
        
        # Evaluate code in topFrame
        eval_res = send("Debugger.evaluateOnCallFrame", {
            "callFrameId": callFrameId,
            "expression": "arguments[0]"
        })
        code_str = eval_res.get("result", {}).get("result", {}).get("value", "")
        print(f"Generated function code length: {len(code_str)}")
        with open("vue_generated_code.js", "w", encoding="utf-8") as f:
            f.write(code_str)
        print("[+] Saved vue_generated_code.js")

        # Let's also test running node -c on it
        import subprocess as sp
        r = sp.run(["node", "-c", "vue_generated_code.js"], capture_output=True, text=True)
        print("Node test on vue_generated_code.js:")
        print("Stdout:", r.stdout)
        print("Stderr:", r.stderr)
        break

ws.close()
proc.kill()
