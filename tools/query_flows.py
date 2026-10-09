#!/usr/bin/env python3
"""
CLI Tool for querying historical NetFlow traffic from ClickHouse
Supports filtering by Source IP, Destination IP, bidirectional IP pair, ports, protocols, and time ranges.
"""

import sys
import os
import argparse
import datetime
import json
import urllib.request
import urllib.parse

CH_URL = "http://127.0.0.1:8123/"

PROTO_NAMES = {
    1: "ICMP",
    6: "TCP",
    17: "UDP",
    47: "GRE",
    50: "ESP",
    89: "OSPF",
}

def human_bytes(b):
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.2f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    else:
        return f"{b / (1024 * 1024 * 1024):.2f} GB"

def parse_time_delta(s):
    s = s.strip().lower()
    num = int("".join([c for c in s if c.isdigit()]))
    unit = "".join([c for c in s if c.isalpha()])
    if unit in ("m", "min", "minute", "minutes"):
        return datetime.timedelta(minutes=num)
    elif unit in ("h", "hr", "hour", "hours"):
        return datetime.timedelta(hours=num)
    elif unit in ("d", "day", "days"):
        return datetime.timedelta(days=num)
    elif unit in ("w", "week", "weeks"):
        return datetime.timedelta(weeks=num)
    else:
        return datetime.timedelta(hours=num)

def ch_query(sql):
    url = CH_URL + "?default_format=JSON"
    req = urllib.request.Request(url, data=sql.encode('utf-8'))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode('utf-8')
            return json.loads(data)
    except Exception as e:
        print(f"ClickHouse Query Error: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Query historical flow traffic from ClickHouse")
    parser.add_argument("--src", help="Source IP address (Sender)")
    parser.add_argument("--dst", help="Destination IP address (Receiver)")
    parser.add_argument("--bi", "--bidirectional", action="store_true", help="Enable bidirectional traffic matching between --src and --dst")
    parser.add_argument("--ip", help="Match IP either as source or destination")
    parser.add_argument("--ip2", help="Match second IP (bidirectional pair with --ip)")
    parser.add_argument("--port", type=int, help="Source or destination L4 port")
    parser.add_argument("--proto", help="Protocol (e.g. tcp, udp, icmp, 6, 17)")
    parser.add_argument("--exporter", help="Exporter device IP (e.g. 10.3.251.1)")
    parser.add_argument("--last", default="1h", help="Time window relative to now (e.g. 15m, 1h, 6h, 24h, 7d). Default: 1h")
    parser.add_argument("--from", dest="from_time", help="Start time (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--to", dest="to_time", help="End time (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--limit", type=int, default=50, help="Max flow records to show (default: 50)")
    parser.add_argument("--summary", action="store_true", help="Only show summary totals without flow list")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    conditions = []

    # Time filters
    now = datetime.datetime.now()
    if args.from_time:
        conditions.append(f"first_switched >= '{args.from_time}'")
    elif args.last:
        delta = parse_time_delta(args.last)
        start_t = (now - delta).strftime('%Y-%m-%d %H:%M:%S')
        conditions.append(f"first_switched >= '{start_t}'")

    if args.to_time:
        conditions.append(f"first_switched <= '{args.to_time}'")

    # IP filters (Strict by default, bidirectional when requested)
    if args.ip and args.ip2:
        conditions.append(f"((src_ip = '{args.ip}' AND dst_ip = '{args.ip2}') OR (src_ip = '{args.ip2}' AND dst_ip = '{args.ip}'))")
    elif args.ip:
        conditions.append(f"(src_ip = '{args.ip}' OR dst_ip = '{args.ip}')")
    else:
        if args.src and args.dst:
            if args.bi:
                conditions.append(f"((src_ip = '{args.src}' AND dst_ip = '{args.dst}') OR (src_ip = '{args.dst}' AND dst_ip = '{args.src}'))")
            else:
                conditions.append(f"(src_ip = '{args.src}' AND dst_ip = '{args.dst}')")
        else:
            if args.src:
                if args.bi:
                    conditions.append(f"(src_ip = '{args.src}' OR dst_ip = '{args.src}')")
                else:
                    conditions.append(f"src_ip = '{args.src}'")
            if args.dst:
                if args.bi:
                    conditions.append(f"(src_ip = '{args.dst}' OR dst_ip = '{args.dst}')")
                else:
                    conditions.append(f"dst_ip = '{args.dst}'")

    if args.port:
        conditions.append(f"(src_port = {args.port} OR dst_port = {args.port})")

    if args.proto:
        p = args.proto.strip().lower()
        if p == "tcp":
            conditions.append("proto = 6")
        elif p == "udp":
            conditions.append("proto = 17")
        elif p == "icmp":
            conditions.append("proto = 1")
        elif p.isdigit():
            conditions.append(f"proto = {p}")

    if args.exporter:
        conditions.append(f"exporter_ip = '{args.exporter}'")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Aggregation Summary Query
    sum_sql = f"""
    SELECT
        count() AS total_flows,
        sum(bytes) AS total_bytes,
        sum(pkts) AS total_pkts,
        min(first_switched) AS min_time,
        max(last_switched) AS max_time
    FROM ntopng.flows
    WHERE {where_clause}
    """
    sum_res = ch_query(sum_sql)
    sum_data = sum_res["data"][0] if sum_res.get("data") else {}

    total_flows = int(sum_data.get("total_flows") or 0)
    total_bytes = int(sum_data.get("total_bytes") or 0)
    total_pkts = int(sum_data.get("total_pkts") or 0)
    min_time = sum_data.get("min_time") or "N/A"
    max_time = sum_data.get("max_time") or "N/A"

    if args.json:
        detail_sql = f"""
        SELECT first_switched, last_switched, src_ip, src_port, dst_ip, dst_port, proto, bytes, pkts, exporter_ip
        FROM ntopng.flows
        WHERE {where_clause}
        ORDER BY first_switched DESC
        LIMIT {args.limit}
        """
        detail_res = ch_query(detail_sql) if not args.summary else {"data": []}
        out = {
            "summary": {
                "total_flows": total_flows,
                "total_bytes": total_bytes,
                "total_bytes_human": human_bytes(total_bytes),
                "total_pkts": total_pkts,
                "time_span": f"{min_time} ~ {max_time}"
            },
            "flows": detail_res.get("data", [])
        }
        print(json.dumps(out, indent=2))
        return

    # Text / Table Output
    mode_str = "双向关联 (Bidirectional)" if args.bi else "严格单向 (Strict Directional)"
    print("=" * 78)
    print(f" 历史流量查询结果 (Historical Flow Query: {mode_str})")
    print("=" * 78)
    print(f" 查询过滤: {where_clause}")
    print(f" 时间跨度: {min_time}  至  {max_time}")
    print(f" 流记录数: {total_flows:,} 条")
    print(f" 传输流量: {human_bytes(total_bytes)} ({total_bytes:,} 字节)")
    print(f" 数据包数: {total_pkts:,} 个包")
    print("=" * 78)

    if args.summary or total_flows == 0:
        return

    # Flow Detail List
    detail_sql = f"""
    SELECT first_switched, src_ip, src_port, dst_ip, dst_port, proto, bytes, pkts, exporter_ip
    FROM ntopng.flows
    WHERE {where_clause}
    ORDER BY first_switched DESC
    LIMIT {args.limit}
    """
    detail_res = ch_query(detail_sql)
    rows = detail_res.get("data", [])

    print(f"\n最近流明细 (展示前 {min(len(rows), args.limit)} 条):")
    hdr = f"{'开始时间':<20} {'源地址(发送):端口':<24} {'目标地址(接收):端口':<24} {'协议':<6} {'流量':<12} {'包数':<8} {'采集器'}"
    print("-" * len(hdr))
    print(hdr)
    print("-" * len(hdr))

    for r in rows:
        t = r.get("first_switched", "")
        src = f"{r.get('src_ip')}:{r.get('src_port')}"
        dst = f"{r.get('dst_ip')}:{r.get('dst_port')}"
        proto_num = int(r.get("proto", 0))
        proto_str = PROTO_NAMES.get(proto_num, str(proto_num))
        b_str = human_bytes(int(r.get("bytes", 0)))
        p_str = str(r.get("pkts", 0))
        exp = r.get("exporter_ip", "")
        print(f"{t:<20} {src:<24} {dst:<24} {proto_str:<6} {b_str:<12} {p_str:<8} {exp}")
    print("-" * len(hdr))

if __name__ == "__main__":
    main()