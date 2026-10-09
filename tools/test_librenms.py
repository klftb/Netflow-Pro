import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def test():
    for url in ["http://librenms.example.com/api/v0/devices", "https://librenms.example.com/api/v0/devices"]:
        print(f"Testing {url} ...")
        try:
            req = urllib.request.Request(url, headers={"X-Auth-Token": "e77d2b54cef5356698d28b5dc3a8b524"})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                devs = data.get("devices", [])
                print(f"Success! Total devices: {len(devs)}")
                
                known_ips = ["10.23.251.238", "10.3.255.225", "10.3.251.1", "10.3.11.251", "10.11.251.13"]
                for d in devs:
                    ip = d.get("ip") or d.get("hostname")
                    if ip in known_ips:
                        print(f"Matched device: ID={d.get('device_id')} IP={ip} sysName={d.get('sysName')} "
                              f"location={d.get('location')} contact={d.get('sysContact')} "
                              f"hardware={d.get('hardware')} os={d.get('os')}")
                return
        except Exception as e:
            print(f"Failed {url}: {e}")

if __name__ == '__main__':
    test()

