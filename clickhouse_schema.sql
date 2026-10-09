-- ==============================================================================
-- ClickHouse Schema for Flow Analytics Platform (Akvorado Architecture)
-- ==============================================================================

-- 1. flows_raw: Detailed flow records (30 Days TTL)
CREATE TABLE IF NOT EXISTS ntopng.flows_raw (
    first_switched DateTime,
    last_switched  DateTime,
    src_ip         String,
    dst_ip         String,
    src_port       UInt16,
    dst_port       UInt16,
    proto          UInt8,
    tcp_flags      UInt8,
    tos            UInt8,
    in_snmp        UInt32,
    out_snmp       UInt32,
    bytes          UInt64,
    pkts           UInt64,
    exporter_ip    String
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(first_switched)
ORDER BY (first_switched, proto, exporter_ip, in_snmp, out_snmp, src_ip, dst_ip, dst_port)
TTL first_switched + INTERVAL 30 DAY;

-- 2. flows_5m: 5-minute pre-aggregated rollup table (365 Days TTL)
CREATE TABLE IF NOT EXISTS ntopng.flows_5m (
    time_bucket    DateTime,
    exporter_ip    String,
    in_snmp        UInt32,
    out_snmp       UInt32,
    src_ip         String,
    dst_ip         String,
    proto          UInt8,
    dst_port       UInt16,
    flows          UInt64,
    bytes          UInt64,
    pkts           UInt64
) ENGINE = SummingMergeTree((flows, bytes, pkts))
PARTITION BY toYYYYMM(time_bucket)
ORDER BY (time_bucket, exporter_ip, in_snmp, out_snmp, proto, src_ip, dst_ip, dst_port)
TTL time_bucket + INTERVAL 365 DAY;

-- Materialized View to feed flows_5m from flows_raw automatically
CREATE MATERIALIZED VIEW IF NOT EXISTS ntopng.flows_5m_mv TO ntopng.flows_5m AS
SELECT
    toStartOfInterval(first_switched, INTERVAL 5 MINUTE) AS time_bucket,
    exporter_ip,
    in_snmp,
    out_snmp,
    src_ip,
    dst_ip,
    proto,
    dst_port,
    count() AS flows,
    sum(bytes) AS bytes,
    sum(pkts) AS pkts
FROM ntopng.flows_raw
GROUP BY time_bucket, exporter_ip, in_snmp, out_snmp, src_ip, dst_ip, proto, dst_port;

-- 3. app_mapping: Protocol & Port to Application Dictionary
CREATE TABLE IF NOT EXISTS ntopng.app_mapping (
    proto      UInt8,
    port       UInt16,
    app_name   String,
    category   String
) ENGINE = ReplacingMergeTree()
ORDER BY (proto, port);

-- Seed standard enterprise application mappings
INSERT INTO ntopng.app_mapping (proto, port, app_name, category) VALUES
    (6, 80, 'HTTP', 'Web'),
    (6, 443, 'HTTPS', 'Web / Encrypted'),
    (6, 22, 'SSH', 'Management'),
    (6, 23, 'Telnet', 'Management'),
    (6, 21, 'FTP', 'File Transfer'),
    (6, 25, 'SMTP', 'Mail'),
    (6, 110, 'POP3', 'Mail'),
    (6, 143, 'IMAP', 'Mail'),
    (6, 993, 'IMAPS', 'Mail'),
    (6, 995, 'POP3S', 'Mail'),
    (6, 3389, 'RDP', 'Remote Access'),
    (6, 1433, 'MSSQL', 'Database'),
    (6, 1521, 'Oracle', 'Database'),
    (6, 3306, 'MySQL', 'Database'),
    (6, 5432, 'PostgreSQL', 'Database'),
    (6, 6379, 'Redis', 'Database / Cache'),
    (6, 8080, 'HTTP-Alt', 'Web'),
    (6, 8443, 'HTTPS-Alt', 'Web'),
    (17, 53, 'DNS', 'Network Infrastructure'),
    (17, 123, 'NTP', 'Network Infrastructure'),
    (17, 161, 'SNMP', 'Network Management'),
    (17, 162, 'SNMP-Trap', 'Network Management'),
    (17, 500, 'IPsec-ISAKMP', 'VPN'),
    (17, 4500, 'IPsec-NAT-T', 'VPN'),
    (17, 2055, 'NetFlow', 'Telemetry'),
    (17, 6343, 'sFlow', 'Telemetry'),
    (1, 0, 'ICMP', 'Network Diagnostic');

-- 4. business_groups: CIDR to Department/Business Unit Dictionary
CREATE TABLE IF NOT EXISTS ntopng.business_groups (
    group_id    UInt32,
    group_name  String,
    cidr        String,
    department  String,
    source      LowCardinality(String) DEFAULT 'Local'
) ENGINE = ReplacingMergeTree()
ORDER BY group_id;

-- Seed enterprise business group CIDRs
INSERT INTO ntopng.business_groups (group_id, group_name, cidr, department, source) VALUES
    (1, '研发网段 (R&D)', '10.40.0.0/16', '研发中心', 'Local'),
    (2, '办公OA网段 (Office)', '10.3.10.0/24', '综合行政', 'Local'),
    (3, '核心数据中心 (DataCenter)', '10.3.6.0/24', 'IT运维部', 'Local'),
    (4, '服务器生产集群 (Prod)', '10.3.11.0/24', '基础设施部', 'Local'),
    (5, '网络设备管理段 (Network-Mgmt)', '10.3.251.0/24', '网络运维组', 'Local'),
    (6, '出口防火墙互联段 (Firewall-Transit)', '10.3.255.0/24', '安全运营组', 'Local');

-- 5. ip_hosts: 32-bit Host IP to Hostname/DNS Dictionary (Netbox & Local)
CREATE TABLE IF NOT EXISTS ntopng.ip_hosts (
    ip          String,
    hostname    String,
    dns_name    String,
    description String,
    source      LowCardinality(String), -- 'Netbox' or 'Local'
    updated_at  DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (ip);

