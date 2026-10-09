import requests
import json

def main():
    print("=== NetFlow Backend Verification Test ===")
    
    # 1. Login
    login_resp = requests.post("http://localhost:8080/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    print("Login status code:", login_resp.status_code)
    login_data = login_resp.json()
    token = login_data.get("data", {}).get("token", "")
    if not token:
        print("Login failed:", login_data)
        return
    print("Login successful! Token obtained.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 2. Test Traffic Trend (verify rx_bps and tx_bps are distinct)
    print("\n--- Testing /api/v1/traffic/trend ---")
    trend_resp = requests.post("http://localhost:8080/api/v1/traffic/trend", headers=headers, json={
        "start_time": "-1h",
        "end_time": "now",
        "direction": "all"
    })
    trend_json = trend_resp.json()
    points = trend_json.get("data", {}).get("points", [])
    print(f"Points returned: {len(points)}")
    if points:
        for p in points[-5:]:
            tx = p.get('tx_bps', 0)
            rx = p.get('rx_bps', 0)
            total = p.get('total_bps', 0)
            diff = abs(tx - rx)
            print(f"  Time: {p.get('timestamp')} | Tx: {tx:,.2f} bps | Rx: {rx:,.2f} bps | Total: {total:,.2f} bps | Diff: {diff:,.2f} bps")
        last = points[-1]
        assert last.get('tx_bps', 0) != last.get('rx_bps', 0) or len(points) == 0, "Tx and Rx should not be identical!"
        print(">> SUCCESS: Tx and Rx curves have distinct, real independent values!")

    # 3. Test TopN with IP dimension (verify NetBox enrichment)
    print("\n--- Testing /api/v1/traffic/topn (dimension=ip) ---")
    topn_resp = requests.post("http://localhost:8080/api/v1/traffic/topn", headers=headers, json={
        "start_time": "-1h",
        "end_time": "now",
        "dimension": "ip",
        "limit": 10
    })
    top_items = topn_resp.json().get("data", {}).get("items", [])
    print(f"Top items returned: {len(top_items)}")
    for i, it in enumerate(top_items):
        print(f"  #{i+1}: Key={it.get('key')} | Hostname={it.get('hostname')} | Label={it.get('label')}")

    # 4. Test Sankey (verify NetBox enrichment)
    print("\n--- Testing /api/v1/traffic/sankey ---")
    sankey_resp = requests.post("http://localhost:8080/api/v1/traffic/sankey", headers=headers, json={
        "start_time": "-1h",
        "end_time": "now",
        "limit": 10
    })
    sankey_data = sankey_resp.json().get("data", {})
    nodes = sankey_data.get("nodes", [])
    links = sankey_data.get("links", [])
    print(f"Sankey Nodes: {len(nodes)}, Links: {len(links)}")
    for n in nodes[:8]:
        print(f"  Node: {n.get('name')}")
    for l in links[:5]:
        print(f"  Link: {l.get('source')} -> {l.get('target')} (value: {l.get('value')})")

    print("\n=== Verification Complete ===")

if __name__ == "__main__":
    main()

