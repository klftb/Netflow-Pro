import urllib.request, json, time, websocket, base64, subprocess, os

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
OUT_LIGHT = r"d:\nTop\config_modal_light_verified.png"

cmd = [EDGE_PATH, "--headless", "--remote-debugging-port=9225", "--remote-allow-origins=*", "--window-size=1920,1080", "--disable-gpu", TARGET_URL]
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

res = json.loads(urllib.request.urlopen("http://127.0.0.1:9225/json").read().decode())
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
time.sleep(3.0)

# Toggle to light mode
send("Runtime.evaluate", {"expression": "var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('白天模式')); if (btn) btn.click();"})
time.sleep(1.2)

# Open config modal
send("Runtime.evaluate", {"expression": "var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('系统配置')); if (btn) btn.click();"})
time.sleep(1.8)

ss = send("Page.captureScreenshot", {"format": "png"})
with open(OUT_LIGHT, "wb") as f:
    f.write(base64.b64decode(ss["result"]["data"]))

ws.close()
proc.kill()
print("SUCCESS_SAVED:", os.path.exists(OUT_LIGHT))
