import urllib.request
import json
import time

def verify():
    base = "http://10.3.11.78:8080/api/v1"
    
    # 1. First get available exporters
    req = urllib.request.Request(f"{base}/devices/overview")
    with urllib.request.urlopen(req) as resp:
        devs = json.loads(resp.read().decode()).get("data", [])
        if not devs:
            print("No devices found!")
            return
        target_dev = devs[0]
        exp_ip = target_dev["exporter_ip"]
        if_index = 0
        for ifc in target_dev.get("interfaces", []):
            if ifc.get("has_flow"):
                if_index = ifc["if_index"]
                break
        print(f"Testing with device {exp_ip}, if_index {if_index}")

    # 2. Query sessions
    payload = {
        "exporter_ip": exp_ip,
        "if_index": if_index,
        "start_time": "2026-09-23 00:00:00",
        "end_time": "2026-09-23 23:59:59",
        "limit": 20
    }
    
    t0 = time.time()
    req = urllib.request.Request(
        f"{base}/traffic/sessions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
    elapsed = (time.time() - t0) * 1000
    
    items = res.get("data", {}).get("items", [])
    print(f"Fetched {len(items)} sessions in {elapsed:.1f}ms:")
    
    resolved_count = 0
    for idx, it in enumerate(items):
        src_ip = it.get("src_ip")
        src_host = it.get("src_hostname", "")
        dst_ip = it.get("dst_ip")
        dst_host = it.get("dst_hostname", "")
        
        if src_host or dst_host:
            resolved_count += 1
            print(f"[{idx+1}] RESOLVED: Src={src_host}({src_ip}) -> Dst={dst_host}({dst_ip}) [{it.get('app_name')}]")
        else:
            print(f"[{idx+1}] UNRESOLVED: Src={src_ip} -> Dst={dst_ip} [{it.get('app_name')}]")

    print(f"\nSummary: {resolved_count}/{len(items)} sessions have NetBox hostnames resolved.")

if __name__ == "__main__":
    verify()
