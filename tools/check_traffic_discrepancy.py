import subprocess

sql = """
SELECT 
    if(src_ip <= dst_ip, concat(src_ip, ':', toString(src_port), ' <-> ', dst_ip, ':', toString(dst_port)), concat(dst_ip, ':', toString(dst_port), ' <-> ', src_ip, ':', toString(src_port))) AS session_pair,
    proto,
    sum(bytes) AS total_bytes,
    sum(pkts) AS total_pkts,
    count() AS segments,
    min(first_switched) AS s_start,
    max(last_switched) AS s_end,
    max(last_switched) - min(first_switched) AS dur_s,
    round(sum(bytes)*8 / greatest(max(last_switched) - min(first_switched), 1) / 1000000, 2) AS avg_mbps
FROM ntopng.flows_raw
WHERE first_switched >= now() - INTERVAL 10 MINUTE
GROUP BY session_pair, proto
HAVING total_bytes > 5000000
ORDER BY total_bytes DESC
LIMIT 8;
"""

def main():
    cmd = ['ssh', '-i', r'C:\Users\Ben\.ssh\id_ed25519', '-o', 'StrictHostKeyChecking=no', 'ben@10.3.11.78', f'clickhouse-client --format PrettyCompact -q "{sql}"']
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("=== Bidirectional Session Aggregation Test ===")
    print(res.stdout)
    if res.stderr:
        print("Stderr:", res.stderr)

if __name__ == '__main__':
    main()
