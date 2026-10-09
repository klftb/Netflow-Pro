import urllib.request
import json
import time
import subprocess
import os

API_BASE = "http://10.3.11.78:8080/api/v1"

def api_get(endpoint):
    req = urllib.request.Request(f"{API_BASE}{endpoint}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))

def api_post(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(f"{API_BASE}{endpoint}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    print("=== [STEP 1] Testing LibreNMS Connection Status ===")
    status = api_get("/config/librenms/status")
    print("LibreNMS Status Response:", json.dumps(status, ensure_ascii=False))
    assert status.get("code") == 0, f"Status check failed: {status}"
    assert status.get("data", {}).get("connected") is True, "LibreNMS not connected!"
    print(">>> PASS: LibreNMS API is CONNECTED and HEALTHY!\n")

    print("=== [STEP 2] Testing SNMP/LibreNMS Probe for 10.3.251.1 (Switch) ===")
    probe1 = api_post("/config/exporters/snmp-probe", {"exporter_ip": "10.3.251.1"})
    print("Probe 10.3.251.1 Response:", json.dumps(probe1, ensure_ascii=False))
    assert probe1.get("code") == 0, f"Probe failed: {probe1}"
    d1 = probe1.get("data", {})
    assert d1.get("sys_name") == "cnshc93oa01", f"Unexpected sys_name: {d1.get('sys_name')}"
    assert d1.get("sys_location") == "SHOffice", f"Unexpected location: {d1.get('sys_location')}"
    assert d1.get("sys_contact") == "Ben Zhang", f"Unexpected contact: {d1.get('sys_contact')}"
    assert d1.get("device_type") == "Switch", f"Unexpected device_type: {d1.get('device_type')}"
    print(">>> PASS: 10.3.251.1 successfully probed & synced from LibreNMS!\n")

    print("=== [STEP 3] Testing SNMP/LibreNMS Probe for 10.23.251.238 (Firewall) ===")
    probe2 = api_post("/config/exporters/snmp-probe", {"exporter_ip": "10.23.251.238"})
    print("Probe 10.23.251.238 Response:", json.dumps(probe2, ensure_ascii=False))
    assert probe2.get("code") == 0, f"Probe failed: {probe2}"
    d2 = probe2.get("data", {})
    assert d2.get("sys_name") == "auw2ftvm04", f"Unexpected sys_name: {d2.get('sys_name')}"
    assert d2.get("sys_location") == "AWS_US2", f"Unexpected location: {d2.get('sys_location')}"
    assert d2.get("sys_contact") == "Ben_Zhang", f"Unexpected contact: {d2.get('sys_contact')}"
    assert d2.get("device_type") == "Firewall", f"Unexpected device_type: {d2.get('device_type')}"
    print(">>> PASS: 10.23.251.238 successfully probed & synced from LibreNMS!\n")

    print("=== [STEP 4] Verifying Exporters List in API ===")
    exporters = api_get("/config/exporters")
    exp_list = exporters.get("data", [])
    print(f"Total Exporters returned: {len(exp_list)}")
    matched = 0
    for exp in exp_list:
        ip = exp.get("exporter_ip")
        if ip == "10.3.251.1":
            print(f"  - 10.3.251.1: name='{exp.get('device_name')}', loc='{exp.get('location')}', admin='{exp.get('admin')}'")
            assert exp.get("location") == "SHOffice"
            assert exp.get("admin") == "Ben Zhang"
            matched += 1
        elif ip == "10.23.251.238":
            print(f"  - 10.23.251.238: name='{exp.get('device_name')}', loc='{exp.get('location')}', admin='{exp.get('admin')}'")
            assert exp.get("location") == "AWS_US2"
            assert exp.get("admin") == "Ben_Zhang"
            matched += 1
    assert matched >= 2, f"Could not match expected exporters (matched={matched})"
    print(">>> PASS: Exporters list correctly reflects LibreNMS location & admin!\n")

    print("=== [STEP 5] Verifying 10.23.251.238 Ports in API ===")
    ifaces = api_get("/config/exporters/10.23.251.238/interfaces")
    if_list = ifaces.get("data", [])
    print(f"Total Interfaces for 10.23.251.238: {len(if_list)}")
    wan1_found = False
    for ifc in if_list:
        if ifc.get("if_index") == 1:
            print(f"  - IfIndex 1: if_name='{ifc.get('if_name')}', alias='{ifc.get('if_alias')}', display='{ifc.get('display_name')}', speed={ifc.get('speed_mbps')}M")
            assert "WAN1" in ifc.get("display_name") or "WAN1" in ifc.get("if_alias")
            wan1_found = True
    assert wan1_found, "WAN1 interface not found!"
    print(">>> PASS: Interfaces correctly populated with LibreNMS ifAlias & speed!\n")

    print("==================================================")
    print("🎉 ALL 5 BACKEND & INTEGRATION TESTS PASSED 100%!")
    print("==================================================")

if __name__ == '__main__':
    main()
