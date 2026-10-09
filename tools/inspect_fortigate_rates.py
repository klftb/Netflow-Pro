import urllib.request
import json
import subprocess

def check_librenms():
    print("=== [1] LibreNMS Device 123 (10.23.251.238) Port Rates ===")
    url = 'http://librenms.example.com/api/v0/devices/123/ports?columns=port_id,ifIndex,ifName,ifAlias,ifSpeed,ifInOctets_rate,ifOutOctets_rate,poll_period'
    req = urllib.request.Request(url, headers={'X-Auth-Token': 'e77d2b54cef5356698d28b5dc3a8b524'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    for p in data.get('ports', []):
        in_bps = (p.get('ifInOctets_rate') or 0) * 8
        out_bps = (p.get('ifOutOctets_rate') or 0) * 8
        if in_bps > 100000 or out_bps > 100000:
            print(f"  Interface #{p.get('ifIndex')} {p.get('ifName')} ({p.get('ifAlias')}): "
                  f"In={in_bps/1000000:.2f} Mbps, Out={out_bps/1000000:.2f} Mbps, Total={(in_bps+out_bps)/1000000:.2f} Mbps")

def check_clickhouse_trend():
    print("\n=== [2] ClickHouse NetFlow 1-minute Buckets for 10.23.251.238 (Last 30 min) ===")
    sql = """
    SELECT 
        toStartOfInterval(first_switched, INTERVAL 60 SECOND) AS bucket,
        count() AS flows,
        sum(bytes) AS bytes,
        round(sum(bytes)*8 / 60 / 1000000, 2) AS mbps,
        round(sumIf(bytes, in_snmp = 1)*8 / 60 / 1000000, 2) AS port1_in_mbps,
        round(sumIf(bytes, out_snmp = 1)*8 / 60 / 1000000, 2) AS port1_out_mbps
    FROM ntopng.flows_raw
    WHERE exporter_ip = '10.23.251.238' AND first_switched >= now() - INTERVAL 30 MINUTE
    GROUP BY bucket
    ORDER BY bucket DESC
    LIMIT 20;
    """
    cmd = ['ssh', '-i', r'C:\Users\Ben\.ssh\id_ed25519', '-o', 'StrictHostKeyChecking=no', 'ben@10.3.11.78', f'clickhouse-client --format PrettyCompact -q "{sql}"']
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout)

def check_clickhouse_flows():
    print("\n=== [3] Inspect Top Flows from 10.23.251.238 ===")
    sql = """
    SELECT 
        first_switched, last_switched, last_switched - first_switched AS dur,
        src_ip, dst_ip, src_port, dst_port, in_snmp, out_snmp, bytes,
        round(bytes*8 / 1000000, 2) AS mbits,
        round(bytes*8 / greatest(last_switched - first_switched, 1) / 1000000, 2) AS flow_mbps
    FROM ntopng.flows_raw
    WHERE exporter_ip = '10.23.251.238' AND first_switched >= now() - INTERVAL 10 MINUTE
    ORDER BY bytes DESC
    LIMIT 10;
    """
    cmd = ['ssh', '-i', r'C:\Users\Ben\.ssh\id_ed25519', '-o', 'StrictHostKeyChecking=no', 'ben@10.3.11.78', f'clickhouse-client --format PrettyCompact -q "{sql}"']
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout)

if __name__ == '__main__':
    check_librenms()
    check_clickhouse_trend()
    check_clickhouse_flows()

