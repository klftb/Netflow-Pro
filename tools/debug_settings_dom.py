import urllib.request, json, websocket, time

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET_URL = "http://10.3.11.78:8080/"
DEBUG_PORT = 9248
import subprocess

proc = subprocess.Popen([
    EDGE_PATH, "--headless", f"--remote-debugging-port={DEBUG_PORT}",
    "--remote-allow-origins=*", "--window-size=1920,1080", "--no-sandbox", TARGET_URL
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)

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
        raw = ws.recv()
        res = json.loads(raw)
        if res.get("id") == cur_id:
            return res

send("Page.enable")
send("Runtime.enable")
time.sleep(3.0)

# Switch to settings
send("Runtime.evaluate", {
    "expression": """
        const btn = Array.from(document.querySelectorAll('.sidebar-btn')).find(b => b.innerText.includes('设置'));
        btn.click();
    """
})
time.sleep(1.0)

res = send("Runtime.evaluate", {
    "expression": """
        (function() {
            const el = Array.from(document.querySelectorAll('div')).find(d => d.getAttribute('v-show') === "activeNav === 'settings'" || (d.style && d.style.display !== 'none' && d.innerHTML.includes('业务组与 CIDR 网段')));
            const app = document.getElementById('app');
            const pills = document.querySelectorAll('#settingsSubTab');
            const appContent = document.querySelector('.app-content');
            return {
                appContentChildren: Array.from(appContent.children).map(c => ({
                    tag: c.tagName,
                    display: window.getComputedStyle(c).display,
                    offsetHeight: c.offsetHeight,
                    innerHTMLPreview: c.innerHTML.substring(0, 100)
                })),
                pillsFound: pills.length
            };
        })()
    """,
    "returnByValue": True
})
print("Result:", json.dumps(res.get("result", {}).get("result", {}).get("value"), indent=2, ensure_ascii=False))

ws.close()
proc.kill()
