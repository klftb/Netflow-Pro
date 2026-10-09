import urllib.request
import json

def find_high_traffic():
    url = 'http://librenms.example.com/api/v0/ports?columns=device_id,ifIndex,ifName,ifAlias,ifInOctets_rate,ifOutOctets_rate'
    req = urllib.request.Request(url, headers={'X-Auth-Token': 'e77d2b54cef5356698d28b5dc3a8b524'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    
    ports = data.get('ports', [])
    print(f"Total ports scanned: {len(ports)}")
    for p in ports:
        in_m = (p.get('ifInOctets_rate') or 0) * 8 / 1e6
        out_m = (p.get('ifOutOctets_rate') or 0) * 8 / 1e6
        if in_m > 30 or out_m > 30:
            dev_id = p.get('device_id')
            print(f"Device ID {dev_id} - Port #{p.get('ifIndex')} {p.get('ifName')} [{p.get('ifAlias')}]: "
                  f"In={in_m:.2f} Mbps, Out={out_m:.2f} Mbps, Total={(in_m+out_m):.2f} Mbps")

if __name__ == '__main__':
    find_high_traffic()

