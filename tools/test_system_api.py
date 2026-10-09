import json
import urllib.request

BASE_URL = "http://10.3.11.78:8080"

def test_system():
    # 1. Login
    login_data = json.dumps({"username": "admin", "password": "admin"}).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/api/v1/auth/login", data=login_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        token = res["data"]["token"]
        print("[+] Login Success, Token:", token[:20], "...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 2. Get Core Services Status
    print("\n[+] 1. Testing GET /api/v1/system/services ...")
    req = urllib.request.Request(f"{BASE_URL}/api/v1/system/services", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print(f"Code: {res['code']}, Message: {res['message']}")
        services = res.get("data", [])
        print(f"Total Services Managed: {len(services)}")
        for s in services:
            print(f"  - [{s.get('status').upper()}] {s.get('name')} | PID: {s.get('pid')} | Mem: {s.get('memory')} | Port: {s.get('port')} | Uptime: {s.get('uptime')}")

    # 3. System One-Click Inspection
    print("\n[+] 2. Testing POST /api/v1/system/inspect ...")
    req = urllib.request.Request(f"{BASE_URL}/api/v1/system/inspect", data=b"{}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print(f"Code: {res['code']}, Message: {res['message']}")
        report = res.get("data", {})
        print(f"Report Overall Status: {report.get('overall_status')}, Score: {report.get('score')}/100, InspectedAt: {report.get('inspected_at')}, TotalDuration: {report.get('duration_ms')}ms")
        print(f"Summary: Total: {report.get('total_checks')}, Passed: {report.get('passed_checks')}, Warn: {report.get('warning_checks')}, Failed: {report.get('failed_checks')}")
        print("Check Items:")
        for item in report.get("items", []):
            print(f"  [{item.get('status').upper()}] {item.get('name')}: {item.get('message')} (Latency: {item.get('latency_ms')}ms)")
            print(f"       Details: {item.get('details')}")
            if item.get("suggestion"):
                print(f"       Suggestion: {item.get('suggestion')}")

if __name__ == "__main__":
    test_system()

