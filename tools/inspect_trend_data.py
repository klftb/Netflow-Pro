import subprocess
import json

def query(q):
    cmd = [
        "ssh", "-i", "C:/Users/Ben/.ssh/id_ed25519", "ben@10.3.11.78",
        f"clickhouse-client --query \"{q}\""
    ]
    return subprocess.check_output(cmd).decode().strip()

print("1. flows_raw 总体流量方向分布 (最近 1 小时):")
res = query("SELECT count(), sum(bytes), countIf(in_snmp > 0), countIf(out_snmp > 0), sumIf(bytes, in_snmp > 0), sumIf(bytes, out_snmp > 0) FROM ntopng.flows_raw WHERE first_switched >= now() - INTERVAL 1 HOUR")
print("  count, total_bytes, in_snmp>0_cnt, out_snmp>0_cnt, in_bytes, out_bytes:")
print(" ", res)

print("\n2. flows_raw 样例字段:")
sample = query("SELECT first_switched, src_ip, dst_ip, in_snmp, out_snmp, bytes, pkts FROM ntopng.flows_raw WHERE first_switched >= now() - INTERVAL 10 MINUTE LIMIT 5 FORMAT TabSeparatedWithNames")
print(sample)

print("\n3. 网段内外流向判断 (内部网段 vs 外部):")
subnets = query("SELECT cidr FROM ntopng.business_groups")
print("  已配置网段:", subnets.splitlines())
