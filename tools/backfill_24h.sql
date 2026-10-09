INSERT INTO ntopng.flows_5m_agg
SELECT
    toStartOfInterval(first_switched, INTERVAL 5 MINUTE) AS time_bucket,
    src_ip,
    dst_ip,
    proto,
    dst_port,
    exporter_ip,
    count() AS flows,
    sum(bytes) AS bytes,
    sum(pkts) AS pkts
FROM ntopng.flows
WHERE first_switched >= now() - INTERVAL 24 HOUR
GROUP BY time_bucket, src_ip, dst_ip, proto, dst_port, exporter_ip;
