INSERT INTO ntopng.business_groups (group_id, group_name, cidr, department) VALUES
    (1, '研发网段 (R&D)', '10.40.0.0/16', '研发中心'),
    (2, '办公OA网段 (Office)', '10.3.10.0/24', '综合行政'),
    (3, '核心数据中心 (DataCenter)', '10.3.6.0/24', 'IT运维部'),
    (4, '服务器生产集群 (Prod)', '10.3.11.0/24', '基础设施部'),
    (5, '网络设备管理段 (Network-Mgmt)', '10.3.251.0/24', '网络运维组'),
    (6, '出口防火墙互联段 (Firewall-Transit)', '10.3.255.0/24', '安全运营组'),
    (7, '远程分支互联 (Branch-VPN)', '10.23.251.0/24', '网络运维组');
