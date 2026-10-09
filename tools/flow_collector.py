#!/usr/bin/env python3
"""
NetFlow / IPFIX to ZeroMQ Collector Bridge for ntopng
Listens for NetFlow v5/v9 and IPFIX UDP packets and forwards parsed flows to ntopng over ZeroMQ.
"""

import sys
import os
import time
import struct
import socket
import json
import logging
import argparse
import signal
import queue
import threading
import urllib.request
import urllib.error
import zmq

# Field IDs for NetFlow v9 and IPFIX
NF9_IN_BYTES = 1
NF9_IN_PKTS = 2
NF9_PROTOCOL = 4
NF9_TCP_FLAGS = 6
NF9_L4_SRC_PORT = 7
NF9_IPV4_SRC_ADDR = 8
NF9_INPUT_SNMP = 10
NF9_L4_DST_PORT = 11
NF9_IPV4_DST_ADDR = 12
NF9_OUTPUT_SNMP = 14
NF9_LAST_SWITCHED = 21
NF9_FIRST_SWITCHED = 22
NF9_IPV6_SRC_ADDR = 27
NF9_IPV6_DST_ADDR = 28
NF9_IP_PROTOCOL_VERSION = 60
NF9_POST_NAT_SRC_IPV4 = 225
NF9_POST_NAT_DST_IPV4 = 226
NF9_POST_NAT_SRC_PORT = 227
NF9_POST_NAT_DST_PORT = 228

FIELD_NAMES = {
    NF9_IN_BYTES: "IN_BYTES",
    NF9_IN_PKTS: "IN_PKTS",
    NF9_PROTOCOL: "PROTOCOL",
    NF9_TCP_FLAGS: "TCP_FLAGS",
    NF9_L4_SRC_PORT: "L4_SRC_PORT",
    NF9_IPV4_SRC_ADDR: "IPV4_SRC_ADDR",
    NF9_INPUT_SNMP: "INPUT_SNMP",
    NF9_L4_DST_PORT: "L4_DST_PORT",
    NF9_IPV4_DST_ADDR: "IPV4_DST_ADDR",
    NF9_OUTPUT_SNMP: "OUTPUT_SNMP",
    NF9_LAST_SWITCHED: "LAST_SWITCHED",
    NF9_FIRST_SWITCHED: "FIRST_SWITCHED",
    NF9_IPV6_SRC_ADDR: "IPV6_SRC_ADDR",
    NF9_IPV6_DST_ADDR: "IPV6_DST_ADDR",
    NF9_POST_NAT_SRC_IPV4: "POST_NAT_SRC_IPV4_ADDR",
    NF9_POST_NAT_DST_IPV4: "POST_NAT_DST_IPV4_ADDR",
    NF9_POST_NAT_SRC_PORT: "POST_NAPT_SRC_TRANSPORT_PORT",
    NF9_POST_NAT_DST_PORT: "POST_NAPT_DST_TRANSPORT_PORT",
}
 
 
def flow_to_ch_row(f):
    src_ip = f.get("IPV4_SRC_ADDR") or f.get("IPV6_SRC_ADDR") or ""
    dst_ip = f.get("IPV4_DST_ADDR") or f.get("IPV6_DST_ADDR") or ""
    if not src_ip or not dst_ip:
        return None

    now_ts = int(time.time())
    first_sw = f.get("FIRST_SWITCHED")
    last_sw = f.get("LAST_SWITCHED")

    if not first_sw or first_sw <= 0:
        first_sw = now_ts
    if not last_sw or last_sw <= 0:
        last_sw = first_sw
    if last_sw < first_sw:
        last_sw = first_sw

    def to_dt(ts):
        try:
            if 1000000000 <= ts <= 2500000000:
                return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
        except Exception:
            pass
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts))

    return {
        "first_switched": to_dt(first_sw),
        "last_switched": to_dt(last_sw),
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": int(f.get("L4_SRC_PORT", 0)),
        "dst_port": int(f.get("L4_DST_PORT", 0)),
        "proto": int(f.get("PROTOCOL", 0)),
        "tcp_flags": int(f.get("TCP_FLAGS", 0)),
        "bytes": int(f.get("IN_BYTES", 0)),
        "pkts": int(f.get("IN_PKTS", 0)),
        "in_snmp": int(f.get("INPUT_SNMP", 0)),
        "out_snmp": int(f.get("OUTPUT_SNMP", 0)),
        "tos": int(f.get("SRC_TOS", f.get("TOS", 0))),
        "exporter_ip": f.get("EXPORTER_IPV4_ADDRESS", "")
    }


class ClickHouseWriter:
    def __init__(self, endpoint="http://127.0.0.1:8123/?query=INSERT+INTO+ntopng.flows_raw+FORMAT+JSONEachRow", max_batch=2000, flush_interval=2.0):
        self.endpoint = endpoint
        self.max_batch = max_batch
        self.flush_interval = flush_interval
        self.queue = queue.Queue(maxsize=100000)
        self.running = True
        self.total_inserted = 0
        self.worker = threading.Thread(target=self._run, daemon=True, name="ClickHouseWriter")
        self.worker.start()
        logging.info(f"ClickHouse batch writer started (endpoint: {self.endpoint})")

    def enqueue(self, flows):
        for f in flows:
            row = flow_to_ch_row(f)
            if row:
                try:
                    self.queue.put_nowait(row)
                except queue.Full:
                    pass

    def _flush_batch(self, batch):
        if not batch:
            return
        lines = [json.dumps(r) for r in batch]
        payload = "\n".join(lines).encode('utf-8')
        try:
            req = urllib.request.Request(self.endpoint, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    self.total_inserted += len(batch)
        except Exception as e:
            logging.error(f"ClickHouse insert error ({len(batch)} rows): {e}")

    def _run(self):
        batch = []
        last_flush = time.time()
        while self.running or not self.queue.empty():
            try:
                row = self.queue.get(timeout=0.5)
                batch.append(row)
            except queue.Empty:
                pass

            now = time.time()
            if len(batch) >= self.max_batch or (batch and (now - last_flush) >= self.flush_interval):
                self._flush_batch(batch)
                batch = []
                last_flush = now

    def stop(self):
        self.running = False
        if self.worker.is_alive():
            self.worker.join(timeout=2.0)


class FlowCollector:
    def __init__(self, udp_host="0.0.0.0", udp_port=2055, zmq_endpoint="tcp://127.0.0.1:5556", ch_endpoint=None):
        self.udp_host = udp_host
        self.udp_port = udp_port
        self.zmq_endpoint = zmq_endpoint
        self.ch_writer = ClickHouseWriter(ch_endpoint) if ch_endpoint else None
        self.running = True
        self.templates = {}  # (exporter_ip, source_id, template_id) -> [(type, len), ...]
        self.msg_id = 1
        self.total_pkts = 0
        self.total_flows = 0

        # Setup ZeroMQ PUB Socket
        self.context = zmq.Context()
        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.bind(self.zmq_endpoint)
        logging.info(f"ZeroMQ PUB bound to {self.zmq_endpoint}")

        # Setup UDP Socket
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind((self.udp_host, self.udp_port))
        self.udp_sock.settimeout(1.0)
        logging.info(f"UDP Flow listener bound to {self.udp_host}:{self.udp_port}")

    def stop(self):
        self.running = False
        if self.ch_writer:
            self.ch_writer.stop()

    def send_to_zmq(self, flows):
        if not flows:
            return
        payload = json.dumps(flows)
        payload_bytes = payload.encode('utf-8')

        # Frame 1: struct zmq_msg_hdr_v1 (24 bytes)
        # url: 16 bytes ("flow\0...")
        # version: 1 (uint8)
        # source_id: 0 (uint8)
        # size: uint16 (big-endian)
        # msg_id: uint32 (big-endian)
        url = b"flow\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        hdr = struct.pack("!16sBBHI", url, 1, 0, min(len(payload_bytes), 65535), self.msg_id)
        self.msg_id = (self.msg_id + 1) & 0xFFFFFFFF

        try:
            self.pub_socket.send_multipart([hdr, payload_bytes], zmq.NOBLOCK)
            self.total_flows += len(flows)
        except zmq.ZMQError as e:
            logging.warning(f"Failed to publish to ZMQ: {e}")

    def parse_v5(self, data, exporter_ip):
        if len(data) < 24:
            return []
        version, count, sys_uptime, unix_secs, unix_nsecs, flow_seq, engine_type, engine_id, sampling = struct.unpack(
            "!HHIIIIBBH", data[:24]
        )
        flows = []
        offset = 24
        for _ in range(count):
            if offset + 48 > len(data):
                break
            (
                src, dst, nexthop, in_snmp, out_snmp, pkts, octets,
                first, last, src_port, dst_port, pad, flags, proto,
                tos, src_as, dst_as, src_mask, dst_mask, pad2
            ) = struct.unpack("!4s4s4sHHIIIIHHBBBBHHBBH", data[offset:offset + 48])
            offset += 48

            src_ip = socket.inet_ntoa(src)
            dst_ip = socket.inet_ntoa(dst)

            first_switched = unix_secs - (sys_uptime - first) // 1000 if sys_uptime >= first else unix_secs
            last_switched = unix_secs - (sys_uptime - last) // 1000 if sys_uptime >= last else unix_secs
            if last_switched < first_switched:
                last_switched = first_switched

            flows.append({
                "IPV4_SRC_ADDR": src_ip,
                "IPV4_DST_ADDR": dst_ip,
                "L4_SRC_PORT": src_port,
                "L4_DST_PORT": dst_port,
                "PROTOCOL": proto,
                "IN_BYTES": octets,
                "IN_PKTS": pkts,
                "TCP_FLAGS": flags,
                "FIRST_SWITCHED": first_switched,
                "LAST_SWITCHED": last_switched,
                "INPUT_SNMP": in_snmp,
                "OUTPUT_SNMP": out_snmp,
                "EXPORTER_IPV4_ADDRESS": exporter_ip
            })
        return flows

    def _unpack_int(self, raw):
        length = len(raw)
        if length == 1:
            return raw[0]
        elif length == 2:
            return struct.unpack("!H", raw)[0]
        elif length == 4:
            return struct.unpack("!I", raw)[0]
        elif length == 8:
            return struct.unpack("!Q", raw)[0]
        return 0

    def _parse_flow_record(self, raw, template, base_time, sys_uptime, exporter_ip):
        offset = 0
        flow = {
            "EXPORTER_IPV4_ADDRESS": exporter_ip,
            "FIRST_SWITCHED": base_time,
            "LAST_SWITCHED": base_time,
            "IN_BYTES": 0,
            "IN_PKTS": 0
        }
        for f_type, f_len in template:
            if offset + f_len > len(raw):
                break
            val_bytes = raw[offset:offset + f_len]
            offset += f_len

            if f_type == NF9_IPV4_SRC_ADDR and f_len == 4:
                flow["IPV4_SRC_ADDR"] = socket.inet_ntoa(val_bytes)
            elif f_type == NF9_IPV4_DST_ADDR and f_len == 4:
                flow["IPV4_DST_ADDR"] = socket.inet_ntoa(val_bytes)
            elif f_type == NF9_IPV6_SRC_ADDR and f_len == 16:
                flow["IPV6_SRC_ADDR"] = socket.inet_ntop(socket.AF_INET6, val_bytes)
            elif f_type == NF9_IPV6_DST_ADDR and f_len == 16:
                flow["IPV6_DST_ADDR"] = socket.inet_ntop(socket.AF_INET6, val_bytes)
            elif f_type in (NF9_L4_SRC_PORT, NF9_L4_DST_PORT, NF9_PROTOCOL, NF9_IN_BYTES,
                            NF9_IN_PKTS, NF9_TCP_FLAGS, NF9_INPUT_SNMP, NF9_OUTPUT_SNMP,
                            NF9_POST_NAT_SRC_PORT, NF9_POST_NAT_DST_PORT):
                name = FIELD_NAMES.get(f_type)
                if name:
                    flow[name] = self._unpack_int(val_bytes)
            elif f_type == NF9_POST_NAT_SRC_IPV4 and f_len == 4:
                flow["POST_NAT_SRC_IPV4_ADDR"] = socket.inet_ntoa(val_bytes)
            elif f_type == NF9_POST_NAT_DST_IPV4 and f_len == 4:
                flow["POST_NAT_DST_IPV4_ADDR"] = socket.inet_ntoa(val_bytes)
            elif f_type in (NF9_FIRST_SWITCHED, NF9_LAST_SWITCHED):
                raw_time = self._unpack_int(val_bytes)
                if sys_uptime is not None and sys_uptime >= raw_time:
                    converted = base_time - (sys_uptime - raw_time) // 1000
                elif raw_time > 1000000000:  # Direct epoch timestamp (ms or s)
                    converted = raw_time // 1000 if raw_time > 20000000000 else raw_time
                else:
                    converted = base_time
                if f_type == NF9_FIRST_SWITCHED:
                    flow["FIRST_SWITCHED"] = converted
                else:
                    flow["LAST_SWITCHED"] = converted

        if "IPV4_SRC_ADDR" in flow or "IPV6_SRC_ADDR" in flow:
            return flow
        return None

    def parse_v9(self, data, exporter_ip):
        if len(data) < 20:
            return []
        version, count, sys_uptime, unix_secs, seq_num, source_id = struct.unpack("!HHIIII", data[:20])
        offset = 20
        flows = []
        while offset + 4 <= len(data):
            flowset_id, flowset_len = struct.unpack("!HH", data[offset:offset + 4])
            if flowset_len < 4 or offset + flowset_len > len(data):
                break
            fs_data = data[offset + 4:offset + flowset_len]
            offset += flowset_len

            if flowset_id == 0:  # Template FlowSet
                t_off = 0
                while t_off + 4 <= len(fs_data):
                    t_id, f_count = struct.unpack("!HH", fs_data[t_off:t_off + 4])
                    t_off += 4
                    t_fields = []
                    for _ in range(f_count):
                        if t_off + 4 > len(fs_data):
                            break
                        f_type, f_len = struct.unpack("!HH", fs_data[t_off:t_off + 4])
                        t_fields.append((f_type, f_len))
                        t_off += 4
                    self.templates[(exporter_ip, source_id, t_id)] = t_fields
            elif flowset_id >= 256:  # Data FlowSet
                tpl = self.templates.get((exporter_ip, source_id, flowset_id))
                if tpl:
                    rec_len = sum(f[1] for f in tpl)
                    if rec_len > 0:
                        d_off = 0
                        while d_off + rec_len <= len(fs_data):
                            f = self._parse_flow_record(fs_data[d_off:d_off + rec_len], tpl, unix_secs, sys_uptime, exporter_ip)
                            if f:
                                flows.append(f)
                            d_off += rec_len
        return flows

    def parse_ipfix(self, data, exporter_ip):
        if len(data) < 16:
            return []
        version, length, export_time, seq_num, obs_domain_id = struct.unpack("!HHIII", data[:16])
        offset = 16
        flows = []
        while offset + 4 <= len(data):
            set_id, set_len = struct.unpack("!HH", data[offset:offset + 4])
            if set_len < 4 or offset + set_len > len(data):
                break
            s_data = data[offset + 4:offset + set_len]
            offset += set_len

            if set_id == 2:  # Template Set
                t_off = 0
                while t_off + 4 <= len(s_data):
                    t_id, f_count = struct.unpack("!HH", s_data[t_off:t_off + 4])
                    t_off += 4
                    t_fields = []
                    for _ in range(f_count):
                        if t_off + 4 > len(s_data):
                            break
                        f_type, f_len = struct.unpack("!HH", s_data[t_off:t_off + 4])
                        t_off += 4
                        if f_type & 0x8000:  # Enterprise bit
                            f_type &= 0x7FFF
                            if t_off + 4 <= len(s_data):
                                t_off += 4
                        t_fields.append((f_type, f_len))
                    self.templates[(exporter_ip, obs_domain_id, t_id)] = t_fields
            elif set_id >= 256:  # Data Set
                tpl = self.templates.get((exporter_ip, obs_domain_id, set_id))
                if tpl:
                    rec_len = sum(f[1] for f in tpl)
                    if rec_len > 0:
                        d_off = 0
                        while d_off + rec_len <= len(s_data):
                            f = self._parse_flow_record(s_data[d_off:d_off + rec_len], tpl, export_time, None, exporter_ip)
                            if f:
                                flows.append(f)
                            d_off += rec_len
        return flows

    def run(self):
        logging.info("Starting Flow Collector loop...")
        last_stat_time = time.time()
        stat_flows = 0

        while self.running:
            try:
                data, addr = self.udp_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logging.error(f"Socket error: {e}")
                break

            exporter_ip = addr[0]
            self.total_pkts += 1

            if len(data) < 2:
                continue

            version = struct.unpack("!H", data[:2])[0]
            flows = []
            if version == 5:
                flows = self.parse_v5(data, exporter_ip)
            elif version == 9:
                flows = self.parse_v9(data, exporter_ip)
            elif version == 10:
                flows = self.parse_ipfix(data, exporter_ip)

            if flows:
                self.send_to_zmq(flows)
                if self.ch_writer:
                    self.ch_writer.enqueue(flows)
                stat_flows += len(flows)

            now = time.time()
            if now - last_stat_time >= 10.0:
                if stat_flows > 0:
                    ch_cnt = self.ch_writer.total_inserted if self.ch_writer else 0
                    logging.info(f"Stats: processed {stat_flows} flows in last 10s (total: {self.total_flows} ZMQ, {ch_cnt} ClickHouse, {self.total_pkts} pkts)")
                stat_flows = 0
                last_stat_time = now

        logging.info("Flow Collector shutting down...")
        self.pub_socket.close()
        self.context.term()
        self.udp_sock.close()


def send_test_flows(zmq_endpoint="tcp://127.0.0.1:5556", count=5):
    """Utility to inject synthetic flows for end-to-end dashboard verification"""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.connect(zmq_endpoint)
    logging.info(f"Connecting test sender to {zmq_endpoint}...")
    time.sleep(0.5)

    now = int(time.time())
    test_flows = [
        {
            "IPV4_SRC_ADDR": f"192.168.10.{10 + i}",
            "IPV4_DST_ADDR": "10.3.11.78" if i % 2 == 0 else "8.8.8.8",
            "L4_SRC_PORT": 40000 + i,
            "L4_DST_PORT": 443 if i % 2 == 0 else 53,
            "PROTOCOL": 6 if i % 2 == 0 else 17,
            "IN_BYTES": 1500 * (i + 1),
            "IN_PKTS": 10 * (i + 1),
            "TCP_FLAGS": 24,
            "FIRST_SWITCHED": now - 30,
            "LAST_SWITCHED": now,
            "INPUT_SNMP": 1,
            "OUTPUT_SNMP": 2,
            "EXPORTER_IPV4_ADDRESS": "10.3.11.1"  # Simulated Cisco Switch / FortiGate
        }
        for i in range(count)
    ]

    payload = json.dumps(test_flows).encode('utf-8')
    url = b"flow\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    hdr = struct.pack("!16sBBHI", url, 1, 0, min(len(payload), 65535), 1)

    sock.send_multipart([hdr, payload])
    logging.info(f"Successfully sent {len(test_flows)} synthetic test flows to ZMQ!")
    time.sleep(0.5)
    sock.close()
    ctx.term()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NetFlow/IPFIX to ZeroMQ bridge for ntopng")
    parser.add_argument("--udp-host", default="0.0.0.0", help="UDP listen IP (default: 0.0.0.0)")
    parser.add_argument("--udp-port", type=int, default=2055, help="UDP listen port (default: 2055)")
    parser.add_argument("--zmq-endpoint", default="tcp://127.0.0.1:5556", help="ZMQ PUB endpoint (default: tcp://127.0.0.1:5556)")
    parser.add_argument("--ch-endpoint", default="http://127.0.0.1:8123/?query=INSERT+INTO+ntopng.flows_raw+FORMAT+JSONEachRow", help="ClickHouse HTTP insert endpoint (default: http://127.0.0.1:8123/...)")
    parser.add_argument("--no-ch", action="store_true", help="Disable ClickHouse writer")
    parser.add_argument("--test", action="store_true", help="Send synthetic test flows and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.test:
        send_test_flows(args.zmq_endpoint)
        sys.exit(0)

    ch_ep = None if args.no_ch else args.ch_endpoint
    collector = FlowCollector(args.udp_host, args.udp_port, args.zmq_endpoint, ch_endpoint=ch_ep)

    def sig_handler(signum, frame):
        logging.info(f"Received signal {signum}, stopping...")
        collector.stop()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    collector.run()
