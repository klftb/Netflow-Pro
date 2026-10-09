#!/usr/bin/env python3
"""
NBA Port Scan Attack Simulator
Simulates rapid multi-port probing from a single suspicious source IP to trigger NBA alerts.
"""

import sys
import time
import socket
import struct
import argparse

def ip_to_bytes(ip_str):
    return socket.inet_aton(ip_str)

def build_netflow_v9_packet(flows, seq_num=1):
    now_ts = int(time.time())
    record_len = 22
    template_id = 256
    fields = [
        (8, 4), (12, 4), (7, 2), (11, 2),
        (4, 1), (6, 1), (1, 4), (2, 4)
    ]
    template_payload = struct.pack("!HH", template_id, len(fields))
    for f_type, f_len in fields:
        template_payload += struct.pack("!HH", f_type, f_len)
    template_flowset = struct.pack("!HH", 0, 4 + len(template_payload)) + template_payload

    data_payload = bytearray()
    for f in flows:
        data_payload += struct.pack("!4s4sHHBBII",
            ip_to_bytes(f["src_ip"]),
            ip_to_bytes(f["dst_ip"]),
            f["src_port"],
            f["dst_port"],
            f["proto"],
            f["tcp_flags"],
            f["bytes"],
            f["pkts"]
        )
    pad_len = (4 - (len(data_payload) % 4)) % 4
    data_payload += b"\x00" * pad_len
    data_flowset = struct.pack("!HH", template_id, 4 + len(data_payload)) + data_payload

    header = struct.pack("!HHIIII", 9, 2, 3600000, now_ts, seq_num, 99999)
    return header + template_flowset + data_flowset

def main():
    parser = argparse.ArgumentParser(description="Port Scan Attack Injector")
    parser.add_argument("--target", default="127.0.0.1", help="Target Collector IP")
    parser.add_argument("--port", type=int, default=2055, help="Target Collector UDP Port")
    parser.add_argument("--attacker", default="198.51.100.99", help="Attacker Source IP")
    parser.add_argument("--victim", default="10.3.6.126", help="Victim Destination IP")
    parser.add_argument("--num-ports", type=int, default=120, help="Number of scanned ports (>100)")
    args = parser.parse_args()

    print(f"[*] Starting Port Scan Simulation: Attacker={args.attacker} -> Victim={args.victim}")
    print(f"[*] Probing {args.num_ports} unique ports to trigger NBA threshold (>100 ports/min)...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    batch = []
    seq = 1

    for p in range(1, args.num_ports + 1):
        batch.append({
            "src_ip": args.attacker,
            "dst_ip": args.victim,
            "src_port": 50000 + (p % 10000),
            "dst_port": 1000 + p, # 1001, 1002, ...
            "proto": 6,          # TCP
            "tcp_flags": 2,      # SYN flag only (Recon probe)
            "bytes": 64,
            "pkts": 1
        })
        if len(batch) >= 25:
            pkt = build_netflow_v9_packet(batch, seq_num=seq)
            sock.sendto(pkt, (args.target, args.port))
            batch = []
            seq += 1
            time.sleep(0.02)

    if batch:
        pkt = build_netflow_v9_packet(batch, seq_num=seq)
        sock.sendto(pkt, (args.target, args.port))

    sock.close()
    print(f"[+] Injected {args.num_ports} port probe flows successfully.")

if __name__ == "__main__":
    main()
