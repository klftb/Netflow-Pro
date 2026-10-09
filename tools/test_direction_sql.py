import subprocess

def query(q):
    cmd = [
        "ssh", "-i", "C:/Users/Ben/.ssh/id_ed25519", "ben@10.3.11.78",
        f"clickhouse-client --query \"{q}\""
    ]
    return subprocess.check_output(cmd).decode().strip()

sql = """
SELECT
    count() AS total_flows,
    formatReadableSize(sum(bytes)) AS total_vol,
    -- 入向：外部发往内部，或目的为内部
    formatReadableSize(sumIf(bytes, not (startsWith(src_ip, '10.') or startsWith(src_ip, '172.') or startsWith(src_ip, '192.168.')) and (startsWith(dst_ip, '10.') or startsWith(dst_ip, '172.') or startsWith(dst_ip, '192.168.')))) AS in_from_ext,
    -- 出向：内部发往外部
    formatReadableSize(sumIf(bytes, (startsWith(src_ip, '10.') or startsWith(src_ip, '172.') or startsWith(src_ip, '192.168.')) and not (startsWith(dst_ip, '10.') or startsWith(dst_ip, '172.') or startsWith(dst_ip, '192.168.')))) AS out_to_ext,
    -- 内部东西向互访
    formatReadableSize(sumIf(bytes, (startsWith(src_ip, '10.') or startsWith(src_ip, '172.') or startsWith(src_ip, '192.168.')) and (startsWith(dst_ip, '10.') or startsWith(dst_ip, '172.') or startsWith(dst_ip, '192.168.')))) AS internal_east_west
FROM ntopng.flows_raw
WHERE first_switched >= now() - INTERVAL 1 HOUR
"""

print("测算最近 1 小时真实流量方向分解:")
print(query(sql))
