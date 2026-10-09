import urllib.request
import json

def check_all_ports():
    url = 'http://librenms.example.com/api/v0/devices/123/ports?columns=port_id,ifIndex,ifName,ifDescr,ifAlias,ifSpeed,ifInOctets_rate,ifOutOctets_rate,ifInOctets,ifOutOctets,ifInOctets_prev,ifOutOctets_prev,poll_time,poll_period'
    req = urllib.request.Request(url, headers={'X-Auth-Token': 'e77d2b54cef5356698d28b5dc3a8b524'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    for p in data.get('ports', []):
        in_rate = p.get('ifInOctets_rate') or 0
        out_rate = p.get('ifOutOctets_rate') or 0
        in_oct = p.get('ifInOctets') or 0
        out_oct = p.get('ifOutOctets') or 0
        print(f"Port {p.get('port_id')} (ifIndex {p.get('ifIndex')}) {p.get('ifName')} [{p.get('ifAlias')}]: "
              f"InRate={in_rate*8/1e6:.2f} Mbps, OutRate={out_rate*8/1e6:.2f} Mbps | "
              f"InBytes={in_oct:,}, OutBytes={out_oct:,} | PollTime={p.get('poll_time')}")

if __name__ == '__main__':
    check_all_ports()

