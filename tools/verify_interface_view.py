import urllib.request, json, time, websocket, base64, subprocess, os

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
OUT_IP = r"d:\nTop\ip_with_interface_verified.png"
OUT_IF = r"d:\nTop\interface_tab_verified.png"

cmd = [EDGE_PATH, "--headless", "--remote-debugging-port=9226", "--remote-allow-origins=*", "--window-size=1920,1080", "--disable-gpu", TARGET_URL]
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

res = json.loads(urllib.request.urlopen("http://127.0.0.1:9226/json").read().decode())
ws_url = [t["webSocketDebuggerUrl"] for t in res if t.get("type") == "page"][0]
ws = websocket.create_connection(ws_url)

msg_id = 1
def send(m, p=None):
    global msg_id
    cur_id = msg_id
    ws.send(json.dumps({"id": cur_id, "method": m, "params": p or {}}))
    msg_id += 1
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == cur_id:
            return r

send("Page.enable")
time.sleep(3.5)

# 1. Capture IP view (with device and interface)
ss1 = send("Page.captureScreenshot", {"format": "png"})
with open(OUT_IP, "wb") as f:
    f.write(base64.b64decode(ss1["result"]["data"]))

# 2. Click "采集接口" Tab
send("Runtime.evaluate", {"expression": "var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('采集接口')); if (btn) btn.click();"})
time.sleep(2.0)

# 3. Capture Interface Tab view
ss2 = send("Page.captureScreenshot", {"format": "png"})
with open(OUT_IF, "wb") as f:
    f.write(base64.b64decode(ss2["result"]["data"]))

ws.close()
proc.kill()
print("IP_IMG_SAVED:", os.path.exists(OUT_IP))
print("IF_IMG_SAVED:", os.path.exists(OUT_IF))
