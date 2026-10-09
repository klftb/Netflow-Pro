-- ==============================================================================
-- Flow Analytics Platform - Full ClickHouse Initialization Schema
-- Target Database: ntopng
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS ntopng;

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

-- 3. Materialized View to feed flows_5m from flows_raw automatically
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

-- 4. app_mapping: Protocol & Port to Application Dictionary
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
    (6, 9000, 'ClickHouse-Native', 'Database'),
    (6, 9092, 'Kafka', 'Message Queue'),
    (17, 53, 'DNS', 'Network Infrastructure'),
    (17, 67, 'DHCP-Server', 'Network Infrastructure'),
    (17, 68, 'DHCP-Client', 'Network Infrastructure'),
    (17, 123, 'NTP', 'Network Infrastructure'),
    (17, 161, 'SNMP', 'Network Management'),
    (17, 162, 'SNMP-Trap', 'Network Management'),
    (17, 500, 'IPsec-ISAKMP', 'VPN'),
    (17, 4500, 'IPsec-NAT-T', 'VPN'),
    (17, 2055, 'NetFlow', 'Telemetry'),
    (17, 6343, 'sFlow', 'Telemetry'),
    (1, 0, 'ICMP', 'Network Diagnostic');

-- 5. business_groups: CIDR to Department/Business Unit Dictionary
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

-- 6. ip_hosts: 32-bit Host IP to Hostname/DNS Dictionary (Netbox & Local)
CREATE TABLE IF NOT EXISTS ntopng.ip_hosts (
    ip          String,
    hostname    String,
    dns_name    String,
    description String,
    source      LowCardinality(String), -- 'Netbox' or 'Local'
    updated_at  DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (ip);

-- 7. system_configs: Third-party integration configurations & NBA thresholds
CREATE TABLE IF NOT EXISTS ntopng.system_configs (
    config_key   String,
    config_value String,
    description  String,
    updated_at   DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY config_key;

INSERT INTO ntopng.system_configs (config_key, config_value, description) VALUES
    ('librenms_url', 'http://librenms.example.com/api/v0', 'LibreNMS API 基础服务地址'),
    ('librenms_token', '', 'LibreNMS API 访问令牌 Token'),
    ('netbox_url', 'http://netbox.example.com/api/', 'NetBox API 基础服务地址'),
    ('netbox_token', '', 'NetBox API 访问令牌 Token'),
    ('ldap_enabled', 'false', '是否开启 LDAP/AD 域用户认证'),
    ('ldap_url', 'ldap://ad.example.com:389', 'LDAP 服务器地址'),
    ('ldap_base_dn', 'dc=example,dc=com', 'LDAP 基础查询 Base DN'),
    ('ldap_bind_dn', '', 'LDAP 管理员或只读代理 Bind DN'),
    ('ldap_bind_password', '', 'LDAP 只读代理密码'),
    ('ldap_user_filter', '(&(objectClass=user)(sAMAccountName=%s))', '用户查找过滤规则表达式'),
    ('ldap_default_role', 'admin', 'LDAP 域用户登录后默认分配角色'),
    ('port_scan_threshold', '100', '单源端口扫描报警阈值 (端口数 / 2分钟)'),
    ('silence_minutes', '5', 'Flow 断流静默检测超时 (分钟)');

-- 8. system_users: System administrator & local users
CREATE TABLE IF NOT EXISTS ntopng.system_users (
    username      String,
    password_hash String,
    display_name  String,
    role          LowCardinality(String),
    auth_type     LowCardinality(String),
    created_at    DateTime DEFAULT now(),
    updated_at    DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY username;

-- Default Admin Account: admin / admin (bcrypt hash)
INSERT INTO ntopng.system_users (username, password_hash, display_name, role, auth_type, created_at, updated_at) VALUES
    ('admin', '$2a$10$R6hiSs2k2rXCIs5ZE/H6V..v548Joo6PiSWbG4syyw5mSdDw83JT.', '系统管理员', 'admin', 'local', now(), now());

-- 9. exporter_devices & device_interfaces: Exporter topology & SNMP metadata
CREATE TABLE IF NOT EXISTS ntopng.exporter_devices (
    exporter_ip    String,
    device_name    String,
    device_type    String,
    location       String,
    admin          String,
    description    String,
    snmp_version   String DEFAULT '2c',
    snmp_community String DEFAULT '',
    snmp_ver       String DEFAULT '',
    community      String DEFAULT '',
    is_discovered  UInt8 DEFAULT 0,
    created_at     DateTime DEFAULT now(),
    updated_at     DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY exporter_ip;

CREATE TABLE IF NOT EXISTS ntopng.device_interfaces (
    exporter_ip   String,
    if_index      UInt32,
    if_name       String,
    if_descr      String,
    if_alias      String,
    display_name  String,
    speed_mbps    UInt32,
    if_speed      UInt64 DEFAULT 0,
    if_type       String DEFAULT '',
    is_monitored  UInt8 DEFAULT 1,
    updated_at    DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (exporter_ip, if_index);
