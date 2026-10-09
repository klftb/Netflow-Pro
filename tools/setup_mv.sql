-- ClickHouse Materialized View and Aggregation Table for Flow Analytics
CREATE TABLE IF NOT EXISTS ntopng.flows_5m_agg (
    time_bucket DateTime,
    src_ip String,
    dst_ip String,
    proto UInt8,
    dst_port UInt16,
    exporter_ip String,
    flows UInt64,
    bytes UInt64,
    pkts UInt64
) ENGINE = SummingMergeTree((flows, bytes, pkts))
PARTITION BY toYYYYMM(time_bucket)
ORDER BY (time_bucket, proto, exporter_ip, src_ip, dst_ip, dst_port);

CREATE MATERIALIZED VIEW IF NOT EXISTS ntopng.flows_5m_mv TO ntopng.flows_5m_agg AS
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
GROUP BY time_bucket, src_ip, dst_ip, proto, dst_port, exporter_ip;
