package repository

import (
	"context"
	"fmt"
	"log"
	"math"
	"sort"
	"strings"
	"time"

	"flow-analytics-backend/internal/model"

	"golang.org/x/crypto/bcrypt"

	"github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

type ClickHouseRepo struct {
	conn driver.Conn
}

func NewClickHouseRepo(addr, db, user, pass string) (*ClickHouseRepo, error) {
	conn, err := clickhouse.Open(&clickhouse.Options{
		Addr: []string{addr},
		Auth: clickhouse.Auth{
			Database: db,
			Username: user,
			Password: pass,
		},
		Settings: clickhouse.Settings{
			"max_execution_time": 30,
		},
		DialTimeout:     5 * time.Second,
		MaxOpenConns:    25,
		MaxIdleConns:    5,
		ConnMaxLifetime: time.Hour,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to open clickhouse connection: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := conn.Ping(ctx); err != nil {
		return nil, fmt.Errorf("clickhouse ping failed: %w", err)
	}

	return &ClickHouseRepo{conn: conn}, nil
}

func (r *ClickHouseRepo) Ping(ctx context.Context) error {
	return r.conn.Ping(ctx)
}

func (r *ClickHouseRepo) GetConn() driver.Conn {
	return r.conn
}

func sanitize(s string) string {
	s = strings.ReplaceAll(s, "'", "\\'")
	s = strings.ReplaceAll(s, ";", "")
	return strings.TrimSpace(s)
}

func buildIPCondition(field, ipVal string) string {
	ipVal = sanitize(ipVal)
	if ipVal == "" {
		return ""
	}
	if strings.Contains(ipVal, "/") {
		return fmt.Sprintf("isIPAddressInRange(%s, '%s')", field, ipVal)
	}
	return fmt.Sprintf("%s = '%s'", field, ipVal)
}

func formatBytes(b uint64) string {
	if b < 1024 {
		return fmt.Sprintf("%d B", b)
	} else if b < 1024*1024 {
		return fmt.Sprintf("%.2f KB", float64(b)/1024.0)
	} else if b < 1024*1024*1024 {
		return fmt.Sprintf("%.2f MB", float64(b)/(1024.0*1024.0))
	} else if b < 1024*1024*1024*1024 {
		return fmt.Sprintf("%.2f GB", float64(b)/(1024.0*1024.0*1024.0))
	}
	return fmt.Sprintf("%.2f TB", float64(b)/(1024.0*1024.0*1024.0*1024.0))
}

func formatBps(bps float64) string {
	if bps < 1000 {
		return fmt.Sprintf("%.1f bps", bps)
	} else if bps < 1000*1000 {
		return fmt.Sprintf("%.2f Kbps", bps/1000.0)
	} else if bps < 1000*1000*1000 {
		return fmt.Sprintf("%.2f Mbps", bps/(1000.0*1000.0))
	}
	return fmt.Sprintf("%.2f Gbps", bps/(1000.0*1000.0*1000.0))
}

// QueryTrafficTrend handles intelligent routing based on time span
func (r *ClickHouseRepo) QueryTrafficTrend(ctx context.Context, req model.TrendRequest) (*model.TrendResponse, error) {
	startTime, endTime, duration := model.ParseTimeSpan(req.StartTime, req.EndTime)
	startStr := startTime.Format("2006-01-02 15:04:05")
	endStr := endTime.Format("2006-01-02 15:04:05")

	// Intelligent Query Routing:
	// If time range <= 24 hours: route to high-precision 'flows_raw'
	// If time range > 24 hours (e.g. 7 ~ 90 days): route to pre-aggregated 'flows_5m'
	useRaw := duration <= 24*time.Hour
	stepSec := 300 // default 5m

	if useRaw {
		if duration <= time.Hour {
			stepSec = 15 // 15 seconds
		} else if duration <= 6*time.Hour {
			stepSec = 60 // 1 minute
		} else {
			stepSec = 300 // 5 minutes
		}
	} else {
		if duration > 90*24*time.Hour {
			stepSec = 86400 // 1 day for 90d~365d
		} else if duration > 30*24*time.Hour {
			stepSec = 14400 // 4 hours for 30d~90d
		} else if duration > 7*24*time.Hour {
			stepSec = 3600 // 1 hour for 7d~30d
		} else {
			stepSec = 900 // 15 minutes for 1d~7d
		}
	}
	if req.StepSeconds > 0 {
		stepSec = req.StepSeconds
	}

	var filterConds []string

	if req.ExporterIP != "" {
		filterConds = append(filterConds, fmt.Sprintf("exporter_ip = '%s'", sanitize(req.ExporterIP)))
	}
	if req.IfIndex > 0 {
		if req.Direction == "inbound" {
			filterConds = append(filterConds, fmt.Sprintf("in_snmp = %d", req.IfIndex))
		} else if req.Direction == "outbound" {
			filterConds = append(filterConds, fmt.Sprintf("out_snmp = %d", req.IfIndex))
		} else {
			filterConds = append(filterConds, fmt.Sprintf("(in_snmp = %d OR out_snmp = %d)", req.IfIndex, req.IfIndex))
		}
	}
	if req.Port > 0 {
		filterConds = append(filterConds, fmt.Sprintf("dst_port = %d", req.Port))
	}
	if req.Proto != "" {
		p := strings.ToLower(req.Proto)
		switch p {
		case "tcp":
			filterConds = append(filterConds, "proto = 6")
		case "udp":
			filterConds = append(filterConds, "proto = 17")
		case "icmp":
			filterConds = append(filterConds, "proto = 1")
		}
	}

	// Direction & IP filtering
	srcCond := buildIPCondition("src_ip", req.SrcIP)
	dstCond := buildIPCondition("dst_ip", req.DstIP)

	if srcCond != "" && dstCond != "" {
		if req.Direction == "all" {
			filterConds = append(filterConds, fmt.Sprintf("((%s AND %s) OR (src_ip = '%s' AND dst_ip = '%s'))", srcCond, dstCond, sanitize(req.DstIP), sanitize(req.SrcIP)))
		} else {
			filterConds = append(filterConds, fmt.Sprintf("(%s AND %s)", srcCond, dstCond))
		}
	} else if srcCond != "" {
		if req.Direction == "all" {
			filterConds = append(filterConds, fmt.Sprintf("(%s OR %s)", srcCond, buildIPCondition("dst_ip", req.SrcIP)))
		} else {
			filterConds = append(filterConds, srcCond)
		}
	} else if dstCond != "" {
		if req.Direction == "all" {
			filterConds = append(filterConds, fmt.Sprintf("(%s OR %s)", dstCond, buildIPCondition("src_ip", req.DstIP)))
		} else {
			filterConds = append(filterConds, dstCond)
		}
	}

	var sql string
	if useRaw {
		// Timeline slot distribution for long-lived flows:
		// When FortiGate exports flows with long durations (e.g. 825s, 1800s),
		// timeSlots() and arrayJoin() expand and distribute the volume and packets
		// evenly across every time slot the flow was actively transmitting.
		var rawConds []string
		rawConds = append(rawConds, fmt.Sprintf("first_switched >= toDateTime('%s') - INTERVAL 24 HOUR AND first_switched <= '%s' AND last_switched >= '%s'", startStr, endStr, startStr))
		rawConds = append(rawConds, filterConds...)
		whereRaw := strings.Join(rawConds, " AND ")

		rxCol := "toFloat64(0) AS rx_rate"
		txCol := "toFloat64(0) AS tx_rate"
		if req.IfIndex > 0 {
			rxCol = fmt.Sprintf("toFloat64(round(sumIf(slot_bytes, in_snmp = %d) * 8 / %d, 2)) AS rx_rate", req.IfIndex, stepSec)
			txCol = fmt.Sprintf("toFloat64(round(sumIf(slot_bytes, out_snmp = %d) * 8 / %d, 2)) AS tx_rate", req.IfIndex, stepSec)
		} else {
			rxCol = fmt.Sprintf("toFloat64(round(sumIf(slot_bytes, startsWith(dst_ip, '10.') OR startsWith(dst_ip, '172.') OR startsWith(dst_ip, '192.168.')) * 8 / %d, 2)) AS rx_rate", stepSec)
			txCol = fmt.Sprintf("toFloat64(round(sumIf(slot_bytes, startsWith(src_ip, '10.') OR startsWith(src_ip, '172.') OR startsWith(src_ip, '192.168.')) * 8 / %d, 2)) AS tx_rate", stepSec)
		}
		bpsCol := fmt.Sprintf("toFloat64(round(sum(slot_bytes) * 8 / %d, 2)) AS bps_rate", stepSec)

		sql = fmt.Sprintf(`
			SELECT
				bucket,
				toUInt64(sum(slot_bytes)) AS total_bytes,
				toUInt64(sum(slot_pkts)) AS total_pkts,
				toUInt64(count()) AS flow_cnt,
				%s, %s, %s
			FROM (
				SELECT
					arrayJoin(timeSlots(first_switched, toUInt32(least(if(last_switched > first_switched, last_switched - first_switched, 1), 86400)), %d)) AS bucket,
					toUInt64(bytes / greatest(length(timeSlots(first_switched, toUInt32(least(if(last_switched > first_switched, last_switched - first_switched, 1), 86400)), %d)), 1)) AS slot_bytes,
					toUInt64(pkts / greatest(length(timeSlots(first_switched, toUInt32(least(if(last_switched > first_switched, last_switched - first_switched, 1), 86400)), %d)), 1)) AS slot_pkts,
					in_snmp,
					out_snmp,
					src_ip,
					dst_ip
				FROM ntopng.flows_raw
				WHERE %s
			)
			WHERE bucket >= '%s' AND bucket <= '%s'
			GROUP BY bucket
			ORDER BY bucket ASC
			LIMIT 1000
			SETTINGS max_threads = 8
		`, rxCol, txCol, bpsCol, stepSec, stepSec, stepSec, whereRaw, startStr, endStr)
	} else {
		var rollupConds []string
		rollupConds = append(rollupConds, fmt.Sprintf("time_bucket >= '%s' AND time_bucket <= '%s'", startStr, endStr))
		rollupConds = append(rollupConds, filterConds...)
		whereRollup := strings.Join(rollupConds, " AND ")

		rxCol := "toFloat64(0) AS rx_rate"
		txCol := "toFloat64(0) AS tx_rate"
		if req.IfIndex > 0 {
			rxCol = fmt.Sprintf("toFloat64(round(sumIf(bytes, in_snmp = %d) * 8 / %d, 2)) AS rx_rate", req.IfIndex, stepSec)
			txCol = fmt.Sprintf("toFloat64(round(sumIf(bytes, out_snmp = %d) * 8 / %d, 2)) AS tx_rate", req.IfIndex, stepSec)
		} else {
			rxCol = fmt.Sprintf("toFloat64(round(sumIf(bytes, startsWith(dst_ip, '10.') OR startsWith(dst_ip, '172.') OR startsWith(dst_ip, '192.168.')) * 8 / %d, 2)) AS rx_rate", stepSec)
			txCol = fmt.Sprintf("toFloat64(round(sumIf(bytes, startsWith(src_ip, '10.') OR startsWith(src_ip, '172.') OR startsWith(src_ip, '192.168.')) * 8 / %d, 2)) AS tx_rate", stepSec)
		}
		bpsCol := fmt.Sprintf("toFloat64(round(sum(bytes) * 8 / %d, 2)) AS bps_rate", stepSec)

		sql = fmt.Sprintf(`
			SELECT
				toStartOfInterval(time_bucket, INTERVAL %d SECOND) AS bucket,
				toUInt64(sum(bytes)) AS total_bytes,
				toUInt64(sum(pkts)) AS total_pkts,
				toUInt64(sum(flows)) AS flow_cnt,
				%s, %s, %s
			FROM ntopng.flows_5m
			WHERE %s
			GROUP BY bucket
			ORDER BY bucket ASC
			LIMIT 1000
			SETTINGS optimize_aggregation_in_order = 1, max_threads = 8
		`, stepSec, rxCol, txCol, bpsCol, whereRollup)
	}

	startQ := time.Now()
	rows, err := r.conn.Query(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("trend query error: %w", err)
	}
	defer rows.Close()

	var points []model.TrendPoint
	var bpsList []float64
	var totalBytesSum uint64
	var totalFlowsSum uint64
	var maxBps float64

	for rows.Next() {
		var bucket time.Time
		var b, p, f uint64
		var rxBps, txBps, bps float64
		if err := rows.Scan(&bucket, &b, &p, &f, &rxBps, &txBps, &bps); err != nil {
			continue
		}
		totalBytesSum += b
		totalFlowsSum += f

		pps := float64(p) / float64(stepSec)
		if bps > maxBps {
			maxBps = bps
		}
		bpsList = append(bpsList, bps)

		if rxBps == 0 && txBps == 0 && bps > 0 {
			rxBps = bps * 0.5
			txBps = bps * 0.5
		}

		points = append(points, model.TrendPoint{
			Timestamp: bucket.Format("2006-01-02 15:04:05"),
			TxBps:     txBps,
			RxBps:     rxBps,
			TotalBps:  bps,
			Pps:       pps,
			Flows:     f,
		})
	}

	queryDurMs := float64(time.Since(startQ).Microseconds()) / 1000.0

	// Calculate Dynamic P95 (95th Percentile Bandwidth)
	var p95Bps float64
	if len(bpsList) > 0 {
		sortedBps := make([]float64, len(bpsList))
		copy(sortedBps, bpsList)
		sort.Float64s(sortedBps)
		// 95th percentile index = math.Floor(N * 0.95)
		idx := int(math.Floor(float64(len(sortedBps)) * 0.95))
		if idx >= len(sortedBps) {
			idx = len(sortedBps) - 1
		}
		p95Bps = sortedBps[idx]
	}

	var avgBps float64
	if len(points) > 0 {
		avgBps = float64(totalBytesSum*8) / (float64(len(points) * stepSec))
	}

	ds := "flows_raw (High Precision)"
	if !useRaw {
		ds = "flows_5m (Pre-aggregated Rollup)"
	}

	return &model.TrendResponse{
		DataSource:  ds,
		Points:      points,
		TotalBytes:  totalBytesSum,
		TotalFlows:  totalFlowsSum,
		P95Bps:      p95Bps,
		MaxBps:      maxBps,
		AvgBps:      avgBps,
		QueryTimeMs: queryDurMs,
	}, nil
}

// QueryTopN aggregates top talkers by IP, Port, App, or Business Group
func (r *ClickHouseRepo) QueryTopN(ctx context.Context, req model.TopNRequest) (*model.TopNResponse, error) {
	startTime, endTime, duration := model.ParseTimeSpan(req.StartTime, req.EndTime)
	startStr := startTime.Format("2006-01-02 15:04:05")
	endStr := endTime.Format("2006-01-02 15:04:05")

	useRaw := duration <= 24*time.Hour
	tableName := "ntopng.flows_5m"
	if useRaw {
		tableName = "ntopng.flows_raw"
	}

	limit := req.Limit
	if limit <= 0 || limit > 100 {
		limit = 10
	}

	var conds []string
	if useRaw {
		conds = append(conds, fmt.Sprintf("f.first_switched >= toDateTime('%s') - INTERVAL 24 HOUR AND f.first_switched <= '%s' AND f.last_switched >= '%s'", startStr, endStr, startStr))
	} else {
		conds = append(conds, fmt.Sprintf("f.time_bucket >= '%s' AND f.time_bucket <= '%s'", startStr, endStr))
	}
	if req.ExporterIP != "" {
		conds = append(conds, fmt.Sprintf("f.exporter_ip = '%s'", sanitize(req.ExporterIP)))
	}
	if req.SrcIP != "" {
		conds = append(conds, buildIPCondition("f.src_ip", req.SrcIP))
	}
	if req.DstIP != "" {
		conds = append(conds, buildIPCondition("f.dst_ip", req.DstIP))
	}
	if req.Direction == "inbound" {
		conds = append(conds, "f.in_snmp > 0")
	} else if req.Direction == "outbound" {
		conds = append(conds, "f.out_snmp > 0")
	}
	whereClause := strings.Join(conds, " AND ")

	var sql string
	switch req.Dimension {
	case "port":
		sql = fmt.Sprintf(`
			SELECT
				toString(f.dst_port) AS k,
				concat(if(f.proto=6, 'TCP/', if(f.proto=17, 'UDP/', 'Proto/')), toString(f.dst_port)) AS lbl,
				sum(f.bytes) AS vol,
				count() AS fl
			FROM %s AS f
			WHERE %s
			GROUP BY f.proto, f.dst_port
			ORDER BY vol DESC
			LIMIT %d
			SETTINGS max_threads = 8
		`, tableName, whereClause, limit)

	case "app":
		sql = fmt.Sprintf(`
			SELECT
				toString(t.dst_port) AS k,
				if(m.app_name != '', concat(m.app_name, ' (', toString(t.dst_port), ')'), toString(t.dst_port)) AS lbl,
				t.vol,
				t.fl
			FROM (
				SELECT
					f.proto,
					f.dst_port,
					sum(f.bytes) AS vol,
					count() AS fl
				FROM %s AS f
				WHERE %s
				GROUP BY f.proto, f.dst_port
				ORDER BY vol DESC
				LIMIT %d
			) AS t
			LEFT JOIN ntopng.app_mapping AS m ON t.proto = m.proto AND t.dst_port = m.port
			ORDER BY t.vol DESC
			SETTINGS max_threads = 8
		`, tableName, whereClause, limit)

	case "business_group":
		sql = fmt.Sprintf(`
			SELECT
				g.group_name AS k,
				g.department AS lbl,
				sum(f.bytes) AS vol,
				sum(f.fl) AS fl
			FROM (
				SELECT
					f.src_ip,
					sum(f.bytes) AS bytes,
					count() AS fl
				FROM %s AS f
				WHERE %s
				GROUP BY f.src_ip
			) AS f
			CROSS JOIN (
				SELECT group_name, department, if(position(cidr, '/') > 0, cidr, concat(cidr, '/32')) AS safe_cidr
				FROM ntopng.business_groups FINAL
			) AS g
			WHERE isIPAddressInRange(f.src_ip, g.safe_cidr)
			GROUP BY g.group_name, g.department
			ORDER BY vol DESC
			LIMIT %d
			SETTINGS max_threads = 8
		`, tableName, whereClause, limit)

	case "interface":
		sql = fmt.Sprintf(`
			SELECT
				concat(t.exporter_ip, '#', toString(t.in_snmp)) AS k,
				concat(
					if(d.device_name != '', concat(d.device_name, ' '), concat(t.exporter_ip, ' ')),
					if(in_if.display_name != '', in_if.display_name, if(in_if.if_name != '', in_if.if_name, concat('接口 #', toString(t.in_snmp)))),
					' (In) → ',
					if(out_if.display_name != '', out_if.display_name, if(out_if.if_name != '', out_if.if_name, concat('#', toString(t.out_snmp)))),
					' (Out)'
				) AS lbl,
				t.vol,
				t.fl
			FROM (
				SELECT
					f.exporter_ip,
					f.in_snmp,
					f.out_snmp,
					sum(f.bytes) AS vol,
					count() AS fl
				FROM %s AS f
				WHERE %s
				GROUP BY f.exporter_ip, f.in_snmp, f.out_snmp
				ORDER BY vol DESC
				LIMIT %d
			) AS t
			LEFT JOIN (SELECT * FROM ntopng.exporter_devices FINAL) AS d ON t.exporter_ip = d.exporter_ip
			LEFT JOIN (SELECT * FROM ntopng.device_interfaces FINAL) AS in_if ON t.exporter_ip = in_if.exporter_ip AND t.in_snmp = in_if.if_index
			LEFT JOIN (SELECT * FROM ntopng.device_interfaces FINAL) AS out_if ON t.exporter_ip = out_if.exporter_ip AND t.out_snmp = out_if.if_index
			ORDER BY t.vol DESC
			SETTINGS max_threads = 8
		`, tableName, whereClause, limit)

	default: // "ip"
		sql = fmt.Sprintf(`
			SELECT
				t.src_ip AS k,
				concat(
					t.src_ip, ' [',
					if(d.device_name != '', d.device_name, t.exporter_ip),
					' | 接口: ',
					if(in_if.display_name != '', in_if.display_name, if(in_if.if_name != '', in_if.if_name, concat('#', toString(t.in_snmp)))),
					' → ',
					if(out_if.display_name != '', out_if.display_name, if(out_if.if_name != '', out_if.if_name, concat('#', toString(t.out_snmp)))),
					']'
				) AS lbl,
				t.vol,
				t.fl
			FROM (
				SELECT
					f.src_ip,
					any(f.exporter_ip) AS exporter_ip,
					any(f.in_snmp) AS in_snmp,
					any(f.out_snmp) AS out_snmp,
					sum(f.bytes) AS vol,
					count() AS fl
				FROM %s AS f
				WHERE %s
				GROUP BY f.src_ip
				ORDER BY vol DESC
				LIMIT %d
			) AS t
			LEFT JOIN (SELECT * FROM ntopng.exporter_devices FINAL) AS d ON t.exporter_ip = d.exporter_ip
			LEFT JOIN (SELECT * FROM ntopng.device_interfaces FINAL) AS in_if ON t.exporter_ip = in_if.exporter_ip AND t.in_snmp = in_if.if_index
			LEFT JOIN (SELECT * FROM ntopng.device_interfaces FINAL) AS out_if ON t.exporter_ip = out_if.exporter_ip AND t.out_snmp = out_if.if_index
			ORDER BY t.vol DESC
			SETTINGS max_threads = 8
		`, tableName, whereClause, limit)
	}

	startQ := time.Now()
	rows, err := r.conn.Query(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("topn query error: %w", err)
	}
	defer rows.Close()

	var items []model.TopNItem
	var totalBytes uint64

	for rows.Next() {
		var k, lbl string
		var vol, fl uint64
		if err := rows.Scan(&k, &lbl, &vol, &fl); err != nil {
			continue
		}
		totalBytes += vol
		items = append(items, model.TopNItem{
			Key:       k,
			Label:     lbl,
			Bytes:     vol,
			Formatted: formatBytes(vol),
			Flows:     fl,
		})
	}

	for i := range items {
		if totalBytes > 0 {
			items[i].Percentage = math.Round((float64(items[i].Bytes)/float64(totalBytes))*10000) / 100.0
		}
	}

	queryDurMs := float64(time.Since(startQ).Microseconds()) / 1000.0

	return &model.TopNResponse{
		DataSource:  tableName,
		Items:       items,
		TotalBytes:  totalBytes,
		QueryTimeMs: queryDurMs,
	}, nil
}

// QuerySankey returns source -> app/port -> target links for topological flow map
func (r *ClickHouseRepo) QuerySankey(ctx context.Context, req model.SankeyRequest) (*model.SankeyResponse, error) {
	startTime, endTime, duration := model.ParseTimeSpan(req.StartTime, req.EndTime)
	startStr := startTime.Format("2006-01-02 15:04:05")
	endStr := endTime.Format("2006-01-02 15:04:05")

	useRaw := duration <= 24*time.Hour
	tableName := "ntopng.flows_5m"
	timeCol := "time_bucket"
	if useRaw {
		tableName = "ntopng.flows_raw"
		timeCol = "first_switched"
	}

	limit := req.Limit
	if limit <= 0 || limit > 30 {
		limit = 15
	}

	conds := []string{fmt.Sprintf("%s >= '%s' AND %s <= '%s'", timeCol, startStr, timeCol, endStr)}
	if req.ExporterIP != "" {
		conds = append(conds, fmt.Sprintf("exporter_ip = '%s'", sanitize(req.ExporterIP)))
	}
	if req.Port > 0 {
		conds = append(conds, fmt.Sprintf("dst_port = %d", req.Port))
	}

	srcCond := buildIPCondition("src_ip", req.SrcIP)
	dstCond := buildIPCondition("dst_ip", req.DstIP)
	if srcCond != "" && dstCond != "" {
		if req.Direction == "all" {
			conds = append(conds, fmt.Sprintf("((%s AND %s) OR (src_ip = '%s' AND dst_ip = '%s'))", srcCond, dstCond, sanitize(req.DstIP), sanitize(req.SrcIP)))
		} else {
			conds = append(conds, fmt.Sprintf("(%s AND %s)", srcCond, dstCond))
		}
	} else if srcCond != "" {
		if req.Direction == "all" {
			conds = append(conds, fmt.Sprintf("(%s OR %s)", srcCond, buildIPCondition("dst_ip", req.SrcIP)))
		} else {
			conds = append(conds, srcCond)
		}
	} else if dstCond != "" {
		if req.Direction == "all" {
			conds = append(conds, fmt.Sprintf("(%s OR %s)", dstCond, buildIPCondition("src_ip", req.DstIP)))
		} else {
			conds = append(conds, dstCond)
		}
	}
	whereClause := strings.Join(conds, " AND ")

	var sql string
	if !useRaw {
		sql = fmt.Sprintf(`
			SELECT
				src_ip,
				dst_ip,
				dst_port,
				sum(bytes) AS vol
			FROM %s
			WHERE %s
			  AND src_ip IN (
				  SELECT src_ip
				  FROM %s
				  WHERE %s
				  GROUP BY src_ip
				  ORDER BY sum(bytes) DESC
				  LIMIT 25
			  )
			GROUP BY src_ip, dst_ip, dst_port
			ORDER BY vol DESC
			LIMIT %d
			SETTINGS max_threads = 8
		`, tableName, whereClause, tableName, whereClause, limit)
	} else {
		sql = fmt.Sprintf(`
			SELECT
				src_ip,
				dst_ip,
				dst_port,
				sum(bytes) AS vol
			FROM %s
			WHERE %s
			GROUP BY src_ip, dst_ip, dst_port
			ORDER BY vol DESC
			LIMIT %d
			SETTINGS max_threads = 8
		`, tableName, whereClause, limit)
	}

	startQ := time.Now()
	rows, err := r.conn.Query(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("sankey query error: %w", err)
	}
	defer rows.Close()

	type linkKey struct {
		source string
		target string
	}
	linkMap := make(map[linkKey]uint64)
	nodeMap := make(map[string]bool)

	for rows.Next() {
		var src, dst string
		var port uint16
		var vol uint64
		if err := rows.Scan(&src, &dst, &port, &vol); err != nil {
			continue
		}
		appLabel := fmt.Sprintf("Port:%d", port)
		if port == 443 {
			appLabel = "HTTPS (443)"
		} else if port == 80 {
			appLabel = "HTTP (80)"
		} else if port == 1433 {
			appLabel = "MSSQL (1433)"
		} else if port == 53 {
			appLabel = "DNS (53)"
		} else if port == 3389 {
			appLabel = "RDP (3389)"
		} else if port == 22 {
			appLabel = "SSH (22)"
		} else if port == 445 {
			appLabel = "SMB (445)"
		}

		srcNode := "源: " + src
		dstNode := "目: " + dst

		nodeMap[srcNode] = true
		nodeMap[appLabel] = true
		nodeMap[dstNode] = true

		// Link 1: src -> app
		linkMap[linkKey{source: srcNode, target: appLabel}] += vol
		// Link 2: app -> dst
		linkMap[linkKey{source: appLabel, target: dstNode}] += vol
	}

	var nodes []model.SankeyNode
	for k := range nodeMap {
		nodes = append(nodes, model.SankeyNode{Name: k})
	}

	var links []model.SankeyLink
	for k, v := range linkMap {
		links = append(links, model.SankeyLink{
			Source: k.source,
			Target: k.target,
			Value:  v,
		})
	}

	queryDurMs := float64(time.Since(startQ).Microseconds()) / 1000.0

	return &model.SankeyResponse{
		Nodes:       nodes,
		Links:       links,
		QueryTimeMs: queryDurMs,
	}, nil
}

// -------------------------------------------------------------
// Configuration Management Methods
// -------------------------------------------------------------

func (r *ClickHouseRepo) EnsureConfigTables(ctx context.Context) error {
	t1 := `
		CREATE TABLE IF NOT EXISTS ntopng.exporter_devices
		(
			exporter_ip String,
			device_name String,
			device_type String,
			description String
		)
		ENGINE = ReplacingMergeTree
		ORDER BY exporter_ip
	`
	if err := r.conn.Exec(ctx, t1); err != nil {
		return fmt.Errorf("failed to create exporter_devices table: %w", err)
	}
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.exporter_devices ADD COLUMN IF NOT EXISTS location String")
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.exporter_devices ADD COLUMN IF NOT EXISTS admin String")
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.exporter_devices ADD COLUMN IF NOT EXISTS snmp_community String")
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.exporter_devices ADD COLUMN IF NOT EXISTS snmp_version String DEFAULT '2c'")

	t2 := `
		CREATE TABLE IF NOT EXISTS ntopng.device_interfaces
		(
			exporter_ip String,
			if_index UInt32,
			if_name String,
			if_descr String,
			if_alias String,
			display_name String,
			speed_mbps UInt32,
			updated_at DateTime DEFAULT now()
		)
		ENGINE = ReplacingMergeTree(updated_at)
		ORDER BY (exporter_ip, if_index)
	`
	if err := r.conn.Exec(ctx, t2); err != nil {
		return fmt.Errorf("failed to create device_interfaces table: %w", err)
	}
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.device_interfaces ADD COLUMN IF NOT EXISTS display_name String")
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.device_interfaces ADD COLUMN IF NOT EXISTS speed_mbps UInt32")

	tDeleted := `
		CREATE TABLE IF NOT EXISTS ntopng.deleted_exporters
		(
			exporter_ip String,
			deleted_at DateTime DEFAULT now()
		)
		ENGINE = ReplacingMergeTree(deleted_at)
		ORDER BY exporter_ip
	`
	_ = r.conn.Exec(ctx, tDeleted)

	// Insert default seed devices if empty
	var count uint64
	_ = r.conn.QueryRow(ctx, "SELECT count() FROM ntopng.exporter_devices").Scan(&count)
	if count == 0 {
		_ = r.conn.Exec(ctx, `
			INSERT INTO ntopng.exporter_devices (exporter_ip, device_name, device_type, description) VALUES 
			('10.23.251.238', '核心业务防火墙 (10.23.251.238)', 'Firewall', '采集 10.23.x 业务网段流量与外部会话'),
			('10.3.251.1', 'Cisco Catalyst 9300 (核心交换机)', 'Switch', '办公及业务汇聚核心'),
			('10.3.255.225', 'FortiGate 200F (出口防火墙)', 'Firewall', '互联网边界防护与流镜像'),
			('10.3.11.251', '生产环境交换机 (10.3.11.251)', 'Switch', '基础设施生产网段汇聚')
		`)
	}

	// Insert default seed interfaces if empty
	var ifCount uint64
	_ = r.conn.QueryRow(ctx, "SELECT count() FROM ntopng.device_interfaces").Scan(&ifCount)
	if ifCount == 0 {
		_ = r.conn.Exec(ctx, `
			INSERT INTO ntopng.device_interfaces (exporter_ip, if_index, if_name, if_descr, if_alias, display_name, speed_mbps) VALUES
			('10.23.251.238', 1, 'port1', 'Internal LAN Interface', 'LAN-办公与内部网络', 'port1 (LAN-内部核心)', 1000),
			('10.23.251.238', 6, 'port6', 'WAN1 Telecom Uplink', 'WAN1-中国电信专线', 'port6 (WAN-电信专线)', 1000),
			('10.23.251.238', 7, 'port7', 'DMZ Service Zone', 'DMZ-外部业务发布区', 'port7 (DMZ-外部业务区)', 1000),
			('10.3.251.1', 9, 'Gi1/0/9', 'GigabitEthernet1/0/9', 'Uplink-汇聚上行', 'Gi1/0/9 (汇聚上行链路)', 1000),
			('10.3.251.1', 53, 'Te1/1/1', 'TenGigabitEthernet1/1/1', 'Core-10G-Trunk', 'Te1/1/1 (10G 核心骨干互联)', 10000),
			('10.3.255.225', 6, 'port6', 'Internet Egress WAN1', 'WAN1-联通主出口', 'port6 (WAN1-联通主出口)', 1000),
			('10.3.255.225', 9, 'port9', 'Internet Egress WAN2', 'WAN2-移动备用出口', 'port9 (WAN2-移动备用出口)', 1000),
			('10.3.255.225', 18, 'port18', 'Server Farm Trunk', 'Server-集群汇聚', 'port18 (Server-内部服务器集群)', 10000)
		`)
	}
	// Ensure app_mapping table and seed common protocols
	tAppMapping := `
		CREATE TABLE IF NOT EXISTS ntopng.app_mapping
		(
			proto UInt8,
			port UInt16,
			app_name String,
			category String
		)
		ENGINE = ReplacingMergeTree
		ORDER BY (proto, port)
	`
	_ = r.conn.Exec(ctx, tAppMapping)

	var appCount uint64
	_ = r.conn.QueryRow(ctx, "SELECT count() FROM ntopng.app_mapping FINAL").Scan(&appCount)
	if appCount < 40 {
		_ = r.conn.Exec(ctx, `
			INSERT INTO ntopng.app_mapping (proto, port, app_name, category) VALUES
			(1, 0, 'ICMP', 'Network Diagnostic'),
			(6, 20, 'FTP-Data', 'File Transfer'),
			(6, 21, 'FTP', 'File Transfer'),
			(6, 22, 'SSH', 'Management'),
			(6, 23, 'Telnet', 'Management'),
			(6, 25, 'SMTP', 'Mail'),
			(6, 53, 'DNS-TCP', 'Network Infrastructure'),
			(6, 80, 'HTTP', 'Web'),
			(6, 88, 'Kerberos', 'Authentication'),
			(6, 110, 'POP3', 'Mail'),
			(6, 111, 'RPC', 'Remote Procedure Call'),
			(6, 119, 'NNTP', 'News'),
			(6, 143, 'IMAP', 'Mail'),
			(6, 179, 'BGP', 'Routing'),
			(6, 389, 'LDAP', 'Directory Service'),
			(6, 443, 'HTTPS', 'Web / Encrypted'),
			(6, 445, 'SMB', 'File Sharing'),
			(6, 465, 'SMTPS', 'Mail'),
			(6, 636, 'LDAPS', 'Directory Service'),
			(6, 873, 'Rsync', 'File Transfer / Backup'),
			(6, 993, 'IMAPS', 'Mail'),
			(6, 995, 'POP3S', 'Mail'),
			(6, 1080, 'SOCKS-Proxy', 'Proxy / VPN'),
			(6, 1433, 'MSSQL', 'Database'),
			(6, 1521, 'Oracle', 'Database'),
			(6, 2049, 'NFS', 'Network File System'),
			(6, 2375, 'Docker-HTTP', 'DevOps / Containers'),
			(6, 2376, 'Docker-HTTPS', 'DevOps / Containers'),
			(6, 2379, 'etcd-Client', 'Cluster / Cloud'),
			(6, 3000, 'Grafana', 'Monitoring / Metrics'),
			(6, 3306, 'MySQL', 'Database'),
			(6, 3389, 'RDP', 'Remote Access'),
			(6, 5000, 'Docker-Registry', 'DevOps / Containers'),
			(6, 5432, 'PostgreSQL', 'Database'),
			(6, 5672, 'RabbitMQ', 'Message Queue'),
			(6, 5900, 'VNC', 'Remote Access'),
			(6, 6379, 'Redis', 'Database / Cache'),
			(6, 8000, 'Web-Service', 'Web'),
			(6, 8080, 'HTTP-Alt', 'Web'),
			(6, 8443, 'HTTPS-Alt', 'Web'),
			(6, 8888, 'Web-Console', 'Web'),
			(6, 9000, 'ClickHouse-Native', 'Database'),
			(6, 9090, 'Prometheus', 'Monitoring / Metrics'),
			(6, 9092, 'Kafka', 'Message Queue'),
			(6, 9200, 'Elasticsearch', 'Search / Analytics'),
			(6, 27017, 'MongoDB', 'Database'),
			(17, 53, 'DNS', 'Network Infrastructure'),
			(17, 67, 'DHCP-Server', 'Network Infrastructure'),
			(17, 68, 'DHCP-Client', 'Network Infrastructure'),
			(17, 69, 'TFTP', 'File Transfer'),
			(17, 88, 'Kerberos-UDP', 'Authentication'),
			(17, 123, 'NTP', 'Network Infrastructure'),
			(17, 161, 'SNMP', 'Network Management'),
			(17, 162, 'SNMP-Trap', 'Network Management'),
			(17, 500, 'IPsec-ISAKMP', 'VPN'),
			(17, 514, 'Syslog', 'Log Management'),
			(17, 1812, 'RADIUS-Auth', 'Authentication'),
			(17, 1813, 'RADIUS-Acct', 'Accounting'),
			(17, 2055, 'NetFlow', 'Telemetry'),
			(17, 4500, 'IPsec-NAT-T', 'VPN'),
			(17, 6343, 'sFlow', 'Telemetry')
		`)
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.app_mapping FINAL")
	}

	// Ensure system_configs table and seed initial configs
	tSysConfig := `
		CREATE TABLE IF NOT EXISTS ntopng.system_configs
		(
			config_key String,
			config_value String,
			description String,
			updated_at DateTime DEFAULT now()
		)
		ENGINE = ReplacingMergeTree(updated_at)
		ORDER BY config_key
	`
	_ = r.conn.Exec(ctx, tSysConfig)

	var sysCount uint64
	_ = r.conn.QueryRow(ctx, "SELECT count() FROM ntopng.system_configs").Scan(&sysCount)
	if sysCount == 0 {
		_ = r.conn.Exec(ctx, `
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
			('ldap_default_role', 'admin', 'LDAP 域用户登录后默认分配角色')
		`)
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.system_configs FINAL")
	}

	// Ensure system_users table
	tSysUsers := `
		CREATE TABLE IF NOT EXISTS ntopng.system_users
		(
			username String,
			password_hash String,
			display_name String,
			role LowCardinality(String),
			auth_type LowCardinality(String),
			created_at DateTime DEFAULT now(),
			updated_at DateTime DEFAULT now()
		)
		ENGINE = ReplacingMergeTree(updated_at)
		ORDER BY username
	`
	_ = r.conn.Exec(ctx, tSysUsers)

	var userCount uint64
	_ = r.conn.QueryRow(ctx, "SELECT count() FROM ntopng.system_users").Scan(&userCount)
	if userCount == 0 {
		// Default admin password: admin
		hashed, err := bcrypt.GenerateFromPassword([]byte("admin"), bcrypt.DefaultCost)
		if err == nil {
			_ = r.conn.Exec(ctx, `
				INSERT INTO ntopng.system_users (username, password_hash, display_name, role, auth_type, created_at, updated_at)
				VALUES ('admin', ?, '系统管理员', 'admin', 'local', now(), now())
			`, string(hashed))
			_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.system_users FINAL")
			log.Printf("[*] Initialized default admin account: admin / admin")
		}
	}

	// Ensure ip_hosts table
	tIPHosts := `
		CREATE TABLE IF NOT EXISTS ntopng.ip_hosts
		(
			ip String,
			hostname String,
			dns_name String,
			description String,
			source LowCardinality(String),
			updated_at DateTime DEFAULT now()
		)
		ENGINE = ReplacingMergeTree(updated_at)
		ORDER BY (ip)
	`
	_ = r.conn.Exec(ctx, tIPHosts)
	_ = r.conn.Exec(ctx, "ALTER TABLE ntopng.business_groups ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'Local'")

	return nil
}

func (r *ClickHouseRepo) GetSystemConfigs(ctx context.Context) (map[string]string, error) {
	configs := map[string]string{
		"librenms_url":       "http://librenms.example.com/api/v0",
		"librenms_token":     "",
		"netbox_url":         "http://netbox.example.com/api/",
		"netbox_token":       "",
		"ldap_enabled":       "false",
		"ldap_url":           "ldap://ad.example.com:389",
		"ldap_base_dn":       "dc=example,dc=com",
		"ldap_bind_dn":       "",
		"ldap_bind_password": "",
		"ldap_user_filter":   "(&(objectClass=user)(sAMAccountName=%s))",
		"ldap_default_role":  "admin",
	}

	rows, err := r.conn.Query(ctx, "SELECT config_key, config_value FROM ntopng.system_configs FINAL")
	if err != nil {
		return configs, nil
	}
	defer rows.Close()

	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err == nil && k != "" {
			configs[k] = v
		}
	}
	return configs, nil
}

func (r *ClickHouseRepo) SaveSystemConfigs(ctx context.Context, configs map[string]string) error {
	for k, v := range configs {
		if k == "" {
			continue
		}
		_ = r.conn.Exec(ctx, "INSERT INTO ntopng.system_configs (config_key, config_value, description, updated_at) VALUES (?, ?, '', now())", k, v)
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.system_configs FINAL")
	return nil
}

// GetUser fetches user by username from ntopng.system_users
func (r *ClickHouseRepo) GetUser(ctx context.Context, username string) (*model.SystemUser, error) {
	query := `SELECT username, password_hash, display_name, role, auth_type, created_at, updated_at 
	          FROM ntopng.system_users FINAL WHERE username = ? LIMIT 1`
	var u model.SystemUser
	err := r.conn.QueryRow(ctx, query, username).Scan(
		&u.Username,
		&u.PasswordHash,
		&u.DisplayName,
		&u.Role,
		&u.AuthType,
		&u.CreatedAt,
		&u.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return &u, nil
}

// SaveUser creates or updates a system user
func (r *ClickHouseRepo) SaveUser(ctx context.Context, u *model.SystemUser) error {
	query := `INSERT INTO ntopng.system_users (username, password_hash, display_name, role, auth_type, updated_at) 
	          VALUES (?, ?, ?, ?, ?, now())`
	err := r.conn.Exec(ctx, query, u.Username, u.PasswordHash, u.DisplayName, u.Role, u.AuthType)
	if err != nil {
		return err
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.system_users FINAL")
	return nil
}

// UpdateUserPassword updates the password hash for a local user
func (r *ClickHouseRepo) UpdateUserPassword(ctx context.Context, username string, newPasswordHash string) error {
	u, err := r.GetUser(ctx, username)
	if err != nil {
		return err
	}
	u.PasswordHash = newPasswordHash
	return r.SaveUser(ctx, u)
}

// GetAllUsers retrieves all system users from ntopng.system_users
func (r *ClickHouseRepo) GetAllUsers(ctx context.Context) ([]model.UserConfigItem, error) {
	rows, err := r.conn.Query(ctx, "SELECT username, password_hash, display_name, role, auth_type FROM ntopng.system_users FINAL ORDER BY username ASC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.UserConfigItem
	for rows.Next() {
		var u model.UserConfigItem
		if err := rows.Scan(&u.Username, &u.PasswordHash, &u.DisplayName, &u.Role, &u.AuthType); err == nil && u.Username != "" {
			list = append(list, u)
		}
	}
	return list, nil
}

// DeleteUser removes a user by username from ntopng.system_users
func (r *ClickHouseRepo) DeleteUser(ctx context.Context, username string) error {
	clean := sanitize(strings.TrimSpace(username))
	if clean == "" {
		return fmt.Errorf("username cannot be empty")
	}
	err := r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.system_users DELETE WHERE username = '%s' SETTINGS mutations_sync = 1", clean))
	if err != nil {
		err = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.system_users DELETE WHERE username = '%s'", clean))
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.system_users FINAL")
	return err
}

// GetAllDeviceInterfaces retrieves all stored device interfaces for configuration export
func (r *ClickHouseRepo) GetAllDeviceInterfaces(ctx context.Context) ([]model.DeviceInterface, error) {
	query := `
		SELECT 
			exporter_ip,
			if_index,
			ifNull(if_name, ''),
			ifNull(if_descr, ''),
			ifNull(if_alias, ''),
			ifNull(display_name, ''),
			ifNull(speed_mbps, 1000)
		FROM ntopng.device_interfaces FINAL
		ORDER BY exporter_ip ASC, if_index ASC
	`
	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.DeviceInterface
	for rows.Next() {
		var item model.DeviceInterface
		if err := rows.Scan(&item.ExporterIP, &item.IfIndex, &item.IfName, &item.IfDescr, &item.IfAlias, &item.DisplayName, &item.SpeedMbps); err == nil && item.ExporterIP != "" {
			list = append(list, item)
		}
	}
	return list, nil
}

// GetAllIPHostsForExport retrieves all 32-bit IP hosts for configuration export (Local prioritized, up to 10000 entries)
func (r *ClickHouseRepo) GetAllIPHostsForExport(ctx context.Context) ([]model.IPHost, error) {
	query := `
		SELECT ip, hostname, dns_name, description, if(source != '', source, 'Local'), updated_at
		FROM ntopng.ip_hosts FINAL
		ORDER BY if(source = 'Local', 0, 1) ASC, ip ASC
		LIMIT 10000
	`
	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.IPHost
	for rows.Next() {
		var item model.IPHost
		if err := rows.Scan(&item.IP, &item.Hostname, &item.DNSName, &item.Description, &item.Source, &item.UpdatedAt); err == nil && item.IP != "" {
			list = append(list, item)
		}
	}
	return list, nil
}


func (r *ClickHouseRepo) GetBusinessGroups(ctx context.Context) ([]model.BusinessGroup, error) {
	rows, err := r.conn.Query(ctx, "SELECT group_id, group_name, cidr, department, if(source != '', source, 'Local') FROM ntopng.business_groups FINAL ORDER BY group_id")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.BusinessGroup
	for rows.Next() {
		var item model.BusinessGroup
		if err := rows.Scan(&item.GroupID, &item.GroupName, &item.CIDR, &item.Department, &item.Source); err == nil {
			list = append(list, item)
		}
	}
	return list, nil
}

func (r *ClickHouseRepo) SaveBusinessGroup(ctx context.Context, bg model.BusinessGroup) error {
	bg.CIDR = strings.TrimSpace(bg.CIDR)
	if bg.CIDR != "" && !strings.Contains(bg.CIDR, "/") {
		bg.CIDR = bg.CIDR + "/32"
	}
	if bg.GroupID == 0 {
		var maxID uint32
		_ = r.conn.QueryRow(ctx, "SELECT ifNull(max(group_id), 0) FROM ntopng.business_groups").Scan(&maxID)
		bg.GroupID = maxID + 1
	}
	if bg.Source == "" {
		bg.Source = "Local"
	}
	err := r.conn.Exec(ctx, "INSERT INTO ntopng.business_groups (group_id, group_name, cidr, department, source) VALUES (?, ?, ?, ?, ?)",
		bg.GroupID, bg.GroupName, bg.CIDR, bg.Department, bg.Source)
	if err == nil {
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.business_groups FINAL")
	}
	return err
}

func (r *ClickHouseRepo) DeleteBusinessGroup(ctx context.Context, groupID uint32) error {
	err := r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.business_groups DELETE WHERE group_id = %d SETTINGS mutations_sync = 1", groupID))
	if err != nil {
		err = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.business_groups DELETE WHERE group_id = %d", groupID))
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.business_groups FINAL")
	return err
}

// GetIPHosts queries 32-bit hosts with filtering, search, and pagination
func (r *ClickHouseRepo) GetIPHosts(ctx context.Context, req model.IPHostQueryRequest) (*model.IPHostQueryResponse, error) {
	page := req.Page
	if page <= 0 {
		page = 1
	}
	pageSize := req.PageSize
	if pageSize <= 0 {
		pageSize = 50
	} else if pageSize > 500 {
		pageSize = 500
	}
	offset := (page - 1) * pageSize

	var conds []string
	if req.Keyword != "" {
		kw := sanitize(strings.TrimSpace(req.Keyword))
		conds = append(conds, fmt.Sprintf("(positionCaseInsensitive(ip, '%s') > 0 OR positionCaseInsensitive(hostname, '%s') > 0 OR positionCaseInsensitive(dns_name, '%s') > 0 OR positionCaseInsensitive(description, '%s') > 0)", kw, kw, kw, kw))
	}
	if req.Source != "" && req.Source != "all" {
		conds = append(conds, fmt.Sprintf("source = '%s'", sanitize(req.Source)))
	}

	whereClause := ""
	if len(conds) > 0 {
		whereClause = "WHERE " + strings.Join(conds, " AND ")
	}

	// 1. Count query
	countSQL := fmt.Sprintf("SELECT count() FROM ntopng.ip_hosts FINAL %s", whereClause)
	var total uint64
	if err := r.conn.QueryRow(ctx, countSQL).Scan(&total); err != nil {
		log.Printf("[GetIPHosts] count error: %v", err)
	}

	// 2. Data query
	dataSQL := fmt.Sprintf(`
		SELECT ip, hostname, dns_name, description, if(source != '', source, 'Netbox'), updated_at
		FROM ntopng.ip_hosts FINAL
		%s
		ORDER BY updated_at DESC, ip ASC
		LIMIT %d OFFSET %d
	`, whereClause, pageSize, offset)

	rows, err := r.conn.Query(ctx, dataSQL)
	if err != nil {
		return nil, fmt.Errorf("query ip_hosts failed: %w", err)
	}
	defer rows.Close()

	var items []model.IPHost
	for rows.Next() {
		var it model.IPHost
		if err := rows.Scan(&it.IP, &it.Hostname, &it.DNSName, &it.Description, &it.Source, &it.UpdatedAt); err == nil {
			items = append(items, it)
		}
	}

	// 3. Overall source counts
	var nbCount, locCount uint64
	if err := r.conn.QueryRow(ctx, "SELECT countIf(source = 'Netbox'), countIf(source = 'Local') FROM ntopng.ip_hosts FINAL").Scan(&nbCount, &locCount); err != nil {
		log.Printf("[GetIPHosts] source count error: %v", err)
	}

	return &model.IPHostQueryResponse{
		Total:          int64(total),
		Items:          items,
		TotalNetboxIPs: int64(nbCount),
		TotalLocalIPs:  int64(locCount),
	}, nil
}

// SaveIPHost creates or updates a single 32-bit host
func (r *ClickHouseRepo) SaveIPHost(ctx context.Context, host model.IPHost) error {
	host.IP = strings.TrimSpace(host.IP)
	if host.IP == "" {
		return fmt.Errorf("IP address cannot be empty")
	}
	if host.Source == "" {
		host.Source = "Local"
	}
	query := `INSERT INTO ntopng.ip_hosts (ip, hostname, dns_name, description, source, updated_at) VALUES (?, ?, ?, ?, ?, now())`
	err := r.conn.Exec(ctx, query, host.IP, host.Hostname, host.DNSName, host.Description, host.Source)
	if err == nil {
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.ip_hosts FINAL")
	}
	return err
}

// DeleteIPHost deletes a 32-bit host by IP
func (r *ClickHouseRepo) DeleteIPHost(ctx context.Context, ip string) error {
	ip = sanitize(strings.TrimSpace(ip))
	if ip == "" {
		return fmt.Errorf("IP address cannot be empty")
	}
	err := r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.ip_hosts DELETE WHERE ip = '%s' SETTINGS mutations_sync = 1", ip))
	if err != nil {
		err = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.ip_hosts DELETE WHERE ip = '%s'", ip))
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.ip_hosts FINAL")
	return err
}

// BatchSaveIPHosts batch inserts IP hosts into ntopng.ip_hosts
func (r *ClickHouseRepo) BatchSaveIPHosts(ctx context.Context, hosts []model.IPHost) error {
	if len(hosts) == 0 {
		return nil
	}
	batch, err := r.conn.PrepareBatch(ctx, "INSERT INTO ntopng.ip_hosts (ip, hostname, dns_name, description, source, updated_at)")
	if err != nil {
		return fmt.Errorf("prepare batch failed: %w", err)
	}

	for _, h := range hosts {
		src := h.Source
		if src == "" {
			src = "Netbox"
		}
		if err := batch.Append(h.IP, h.Hostname, h.DNSName, h.Description, src, h.UpdatedAt); err != nil {
			return fmt.Errorf("batch append failed: %w", err)
		}
	}
	if err := batch.Send(); err != nil {
		return fmt.Errorf("batch send failed: %w", err)
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.ip_hosts FINAL")
	return nil
}

// GetAllIPHostsMap loads all IP host mappings into memory separated by source
func (r *ClickHouseRepo) GetAllIPHostsMap(ctx context.Context) (map[string]string, map[string]string, error) {
	query := `
		SELECT ip, if(hostname != '', hostname, if(dns_name != '', dns_name, description)), if(source != '', source, 'Netbox')
		FROM ntopng.ip_hosts FINAL
		WHERE hostname != '' OR dns_name != '' OR (description != '' AND position(description, ' ') = 0)
	`
	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()

	netboxMap := make(map[string]string)
	localMap := make(map[string]string)

	for rows.Next() {
		var ip, name, src string
		if err := rows.Scan(&ip, &name, &src); err == nil && ip != "" && name != "" {
			if strings.EqualFold(src, "Local") {
				localMap[ip] = name
			} else {
				netboxMap[ip] = name
			}
		}
	}
	return netboxMap, localMap, nil
}

// GetLocalIPHostSet returns a set of IP addresses that have been customized as 'Local'
func (r *ClickHouseRepo) GetLocalIPHostSet(ctx context.Context) (map[string]bool, error) {
	rows, err := r.conn.Query(ctx, "SELECT ip FROM ntopng.ip_hosts FINAL WHERE source = 'Local'")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	localSet := make(map[string]bool)
	for rows.Next() {
		var ip string
		if err := rows.Scan(&ip); err == nil && ip != "" {
			localSet[ip] = true
		}
	}
	return localSet, nil
}

func (r *ClickHouseRepo) GetAppMappings(ctx context.Context) ([]model.AppMappingItem, error) {
	rows, err := r.conn.Query(ctx, "SELECT proto, port, app_name, category FROM ntopng.app_mapping FINAL ORDER BY port ASC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.AppMappingItem
	for rows.Next() {
		var item model.AppMappingItem
		if err := rows.Scan(&item.Proto, &item.Port, &item.AppName, &item.Category); err == nil {
			list = append(list, item)
		}
	}
	return list, nil
}

func (r *ClickHouseRepo) SaveAppMapping(ctx context.Context, app model.AppMappingItem) error {
	err := r.conn.Exec(ctx, "INSERT INTO ntopng.app_mapping (proto, port, app_name, category) VALUES (?, ?, ?, ?)",
		app.Proto, app.Port, app.AppName, app.Category)
	if err == nil {
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.app_mapping FINAL")
	}
	return err
}

func (r *ClickHouseRepo) DeleteAppMapping(ctx context.Context, proto uint8, port uint16) error {
	err := r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.app_mapping DELETE WHERE proto = %d AND port = %d SETTINGS mutations_sync = 1", proto, port))
	if err != nil {
		err = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.app_mapping DELETE WHERE proto = %d AND port = %d", proto, port))
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.app_mapping FINAL")
	return err
}

func (r *ClickHouseRepo) GetExporterDevices(ctx context.Context) ([]model.ExporterDevice, error) {
	query := `
		SELECT 
			exporter_ip,
			device_name,
			device_type,
			description,
			ifNull(location, ''),
			ifNull(admin, ''),
			ifNull(snmp_community, ''),
			ifNull(snmp_version, '2c')
		FROM ntopng.exporter_devices FINAL
		ORDER BY exporter_ip ASC
	`
	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.ExporterDevice
	for rows.Next() {
		var item model.ExporterDevice
		if err := rows.Scan(&item.ExporterIP, &item.DeviceName, &item.DeviceType, &item.Description, &item.Location, &item.Admin, &item.SNMPCommunity, &item.SNMPVersion); err == nil {
			list = append(list, item)
		}
	}
	return list, nil
}

func (r *ClickHouseRepo) SaveExporterDevice(ctx context.Context, dev model.ExporterDevice) error {
	if dev.SNMPVersion == "" {
		dev.SNMPVersion = "2c"
	}
	err := r.conn.Exec(ctx, "INSERT INTO ntopng.exporter_devices (exporter_ip, device_name, device_type, description, location, admin, snmp_community, snmp_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
		dev.ExporterIP, dev.DeviceName, dev.DeviceType, dev.Description, dev.Location, dev.Admin, dev.SNMPCommunity, dev.SNMPVersion)
	if err == nil {
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.exporter_devices FINAL")
		// Clear tombstone if previously deleted
		_ = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.deleted_exporters DELETE WHERE exporter_ip = '%s'", sanitize(dev.ExporterIP)))
	}
	return err
}

func (r *ClickHouseRepo) DeleteExporterDevice(ctx context.Context, exporterIP string) error {
	cleanIP := sanitize(exporterIP)
	err := r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.exporter_devices DELETE WHERE exporter_ip = '%s' SETTINGS mutations_sync = 1", cleanIP))
	if err != nil {
		err = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.exporter_devices DELETE WHERE exporter_ip = '%s'", cleanIP))
	}
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.exporter_devices FINAL")

	// Also clean up any interface definitions for this device
	_ = r.conn.Exec(ctx, fmt.Sprintf("ALTER TABLE ntopng.device_interfaces DELETE WHERE exporter_ip = '%s'", cleanIP))
	_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.device_interfaces FINAL")

	// Insert tombstone so autodiscover won't immediately resurrect this deleted exporter
	_ = r.conn.Exec(ctx, fmt.Sprintf("INSERT INTO ntopng.deleted_exporters (exporter_ip, deleted_at) VALUES ('%s', now())", cleanIP))

	return err
}

func (r *ClickHouseRepo) FindUnregisteredExporters(ctx context.Context, lookbackMinutes int) ([]string, error) {
	if lookbackMinutes <= 0 {
		lookbackMinutes = 10
	}
	query := fmt.Sprintf(`
		SELECT DISTINCT exporter_ip 
		FROM ntopng.flows_raw 
		WHERE first_switched >= now() - INTERVAL %d MINUTE 
		  AND exporter_ip != ''
		  AND exporter_ip != '0.0.0.0'
		  AND exporter_ip NOT IN (SELECT exporter_ip FROM ntopng.exporter_devices FINAL)
		  AND exporter_ip NOT IN (SELECT exporter_ip FROM ntopng.deleted_exporters FINAL WHERE deleted_at >= now() - INTERVAL 7 DAY)
	`, lookbackMinutes)

	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query unregistered exporters: %w", err)
	}
	defer rows.Close()

	var ips []string
	for rows.Next() {
		var ip string
		if err := rows.Scan(&ip); err == nil && ip != "" {
			ips = append(ips, ip)
		}
	}
	return ips, nil
}

func (r *ClickHouseRepo) GetActiveInterfacesForExporter(ctx context.Context, ip string) ([]uint32, error) {
	cleanIP := sanitize(ip)
	query := fmt.Sprintf(`
		SELECT DISTINCT if_index 
		FROM (
			SELECT in_snmp AS if_index FROM ntopng.flows_raw WHERE exporter_ip = '%s' AND in_snmp > 0 AND first_switched >= now() - INTERVAL 24 HOUR
			UNION ALL
			SELECT out_snmp AS if_index FROM ntopng.flows_raw WHERE exporter_ip = '%s' AND out_snmp > 0 AND first_switched >= now() - INTERVAL 24 HOUR
		)
		ORDER BY if_index ASC
	`, cleanIP, cleanIP)

	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query active interfaces for exporter: %w", err)
	}
	defer rows.Close()

	var ifIndices []uint32
	for rows.Next() {
		var ifIdx uint32
		if err := rows.Scan(&ifIdx); err == nil && ifIdx > 0 {
			ifIndices = append(ifIndices, ifIdx)
		}
	}
	return ifIndices, nil
}

func (r *ClickHouseRepo) GetSubnetsSummary(ctx context.Context) ([]model.SubnetSummaryItem, error) {
	groups, err := r.GetBusinessGroups(ctx)
	if err != nil {
		return nil, err
	}

	startTime := time.Now().Add(-24 * time.Hour).Format("2006-01-02 15:04:05")
	query := fmt.Sprintf(`
		SELECT
			g.group_id,
			g.group_name,
			g.cidr,
			g.department,
			sum(f.bytes) AS total_bytes,
			sum(f.flows) AS total_flows,
			uniqExact(multiIf(isIPAddressInRange(f.src_ip, g.safe_cidr), f.src_ip, f.dst_ip)) AS active_ips
		FROM ntopng.flows_5m AS f
		CROSS JOIN (
			SELECT
				group_id,
				group_name,
				cidr,
				if(position(cidr, '/') > 0, cidr, concat(cidr, '/32')) AS safe_cidr,
				department
			FROM ntopng.business_groups FINAL
		) AS g
		WHERE f.time_bucket >= '%s' AND (isIPAddressInRange(f.src_ip, g.safe_cidr) OR isIPAddressInRange(f.dst_ip, g.safe_cidr))
		GROUP BY g.group_id, g.group_name, g.cidr, g.department
	`, startTime)

	statsMap := make(map[uint32]struct {
		bytes     uint64
		flows     uint64
		activeIPs uint32
	})

	var grandTotalBytes uint64 = 0
	rows, err := r.conn.Query(ctx, query)
	if err != nil {
		log.Printf("[GetSubnetsSummary] query error: %v", err)
	} else {
		defer rows.Close()
		for rows.Next() {
			var gid uint32
			var gname, cidr, dept string
			var b, fl, ips uint64
			if err := rows.Scan(&gid, &gname, &cidr, &dept, &b, &fl, &ips); err == nil {
				statsMap[gid] = struct {
					bytes     uint64
					flows     uint64
					activeIPs uint32
				}{bytes: b, flows: fl, activeIPs: uint32(ips)}
				grandTotalBytes += b
			}
		}
	}

	res := make([]model.SubnetSummaryItem, 0, len(groups))
	for _, g := range groups {
		item := model.SubnetSummaryItem{
			GroupID:    g.GroupID,
			GroupName:  g.GroupName,
			CIDR:       g.CIDR,
			Department: g.Department,
		}
		if s, ok := statsMap[g.GroupID]; ok {
			item.Bytes = s.bytes
			item.Flows = s.flows
			item.ActiveIPCount = s.activeIPs
			item.FormattedBytes = formatBytes(s.bytes)
			if grandTotalBytes > 0 {
				item.Percentage = math.Round((float64(s.bytes)/float64(grandTotalBytes))*10000) / 100.0
			}
		} else {
			item.FormattedBytes = "0 B"
		}
		res = append(res, item)
	}

	return res, nil
}

func (r *ClickHouseRepo) GetDeviceInterfaces(ctx context.Context, exporterIP string) ([]model.DeviceInterface, error) {
	query := `
		SELECT 
			t.exporter_ip,
			t.if_index,
			ifNull(i.if_name, concat('Port', toString(t.if_index))),
			ifNull(i.if_descr, 'Network Interface'),
			ifNull(i.if_alias, ''),
			ifNull(i.display_name, if(i.if_name != '', i.if_name, concat('接口 #', toString(t.if_index)))),
			ifNull(i.speed_mbps, 1000),
			toString(ifNull(i.updated_at, now()))
		FROM (
			SELECT exporter_ip, in_snmp AS if_index FROM ntopng.flows_raw WHERE exporter_ip = ? AND in_snmp > 0
			UNION DISTINCT
			SELECT exporter_ip, out_snmp AS if_index FROM ntopng.flows_raw WHERE exporter_ip = ? AND out_snmp > 0
			UNION DISTINCT
			SELECT exporter_ip, if_index FROM ntopng.device_interfaces WHERE exporter_ip = ?
		) AS t
		LEFT JOIN (SELECT * FROM ntopng.device_interfaces FINAL) AS i 
			ON t.exporter_ip = i.exporter_ip AND t.if_index = i.if_index
		ORDER BY t.if_index ASC
	`
	rows, err := r.conn.Query(ctx, query, exporterIP, exporterIP, exporterIP)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []model.DeviceInterface
	for rows.Next() {
		var item model.DeviceInterface
		if err := rows.Scan(&item.ExporterIP, &item.IfIndex, &item.IfName, &item.IfDescr, &item.IfAlias, &item.DisplayName, &item.SpeedMbps, &item.UpdatedAt); err == nil {
			list = append(list, item)
		}
	}
	return list, nil
}

func (r *ClickHouseRepo) SaveDeviceInterface(ctx context.Context, item model.DeviceInterface) error {
	if item.DisplayName == "" {
		if item.IfAlias != "" {
			item.DisplayName = fmt.Sprintf("%s (%s)", item.IfName, item.IfAlias)
		} else {
			item.DisplayName = item.IfName
		}
	}
	query := `
		INSERT INTO ntopng.device_interfaces 
		(exporter_ip, if_index, if_name, if_descr, if_alias, display_name, speed_mbps, updated_at) 
		VALUES (?, ?, ?, ?, ?, ?, ?, now())
	`
	err := r.conn.Exec(ctx, query, item.ExporterIP, item.IfIndex, item.IfName, item.IfDescr, item.IfAlias, item.DisplayName, item.SpeedMbps)
	if err == nil {
		_ = r.conn.Exec(ctx, "OPTIMIZE TABLE ntopng.device_interfaces FINAL")
	}
	return err
}

func (r *ClickHouseRepo) QueryDeviceOverview(ctx context.Context) ([]model.DeviceOverviewItem, error) {
	devQuery := `SELECT exporter_ip, device_name, device_type, description, ifNull(location, ''), ifNull(admin, '') FROM ntopng.exporter_devices FINAL ORDER BY exporter_ip ASC`
	rows, err := r.conn.Query(ctx, devQuery)
	if err != nil {
		return nil, fmt.Errorf("failed to query exporter devices: %w", err)
	}
	defer rows.Close()

	var devices []model.DeviceOverviewItem
	devMap := make(map[string]*model.DeviceOverviewItem)
	for rows.Next() {
		var d model.DeviceOverviewItem
		if err := rows.Scan(&d.ExporterIP, &d.DeviceName, &d.DeviceType, &d.Description, &d.Location, &d.Admin); err == nil {
			d.Status = "online"
			d.Interfaces = []model.DeviceInterfaceStat{}
			devices = append(devices, d)
		}
	}
	for i := range devices {
		devMap[devices[i].ExporterIP] = &devices[i]
	}

	flowQuery := `
		SELECT 
			exporter_ip, 
			if_index, 
			sum(bytes) AS total_bytes,
			sumIf(bytes, dir = 1) AS rx_bytes,
			sumIf(bytes, dir = 2) AS tx_bytes,
			count() AS flows,
			max(last_switched) AS last_seen,
			toUnixTimestamp(now()) - toUnixTimestamp(max(last_switched)) AS last_seen_age_sec,
			sumIf(effective_bytes, dir = 1) AS rx_bytes_5m,
			sumIf(effective_bytes, dir = 2) AS tx_bytes_5m
		FROM (
			SELECT 
				exporter_ip, 
				in_snmp AS if_index, 
				bytes, 
				toUInt64(
					if(last_switched >= now() - INTERVAL 5 MINUTE AND first_switched <= now(),
					   bytes * least(toUnixTimestamp(least(last_switched, now())) - toUnixTimestamp(greatest(first_switched, toDateTime(now() - INTERVAL 5 MINUTE))), 300) / greatest(toUnixTimestamp(last_switched) - toUnixTimestamp(first_switched), 1),
					   0
					)
				) AS effective_bytes,
				first_switched, 
				last_switched, 
				1 AS dir 
			FROM ntopng.flows_raw 
			WHERE first_switched >= now() - INTERVAL 24 HOUR AND in_snmp > 0
			UNION ALL
			SELECT 
				exporter_ip, 
				out_snmp AS if_index, 
				bytes, 
				toUInt64(
					if(last_switched >= now() - INTERVAL 5 MINUTE AND first_switched <= now(),
					   bytes * least(toUnixTimestamp(least(last_switched, now())) - toUnixTimestamp(greatest(first_switched, toDateTime(now() - INTERVAL 5 MINUTE))), 300) / greatest(toUnixTimestamp(last_switched) - toUnixTimestamp(first_switched), 1),
					   0
					)
				) AS effective_bytes,
				first_switched, 
				last_switched, 
				2 AS dir 
			FROM ntopng.flows_raw 
			WHERE first_switched >= now() - INTERVAL 24 HOUR AND out_snmp > 0
		)
		GROUP BY exporter_ip, if_index
	`
	flowRows, err := r.conn.Query(ctx, flowQuery)
	if err != nil {
		return nil, fmt.Errorf("failed to query flow interface aggregation: %w", err)
	}
	defer flowRows.Close()

	type ifFlowStat struct {
		totalBytes  uint64
		rxBytes     uint64
		txBytes     uint64
		flows       uint64
		lastSeen    time.Time
		lastSeenSec int64
		rxBytes5m   uint64
		txBytes5m   uint64
	}
	flowStats := make(map[string]map[uint32]ifFlowStat)
	for flowRows.Next() {
		var expIP string
		var ifIdx uint32
		var tb, rb, xb, fl, rb5, xb5 uint64
		var ls time.Time
		var ageSec int64
		if err := flowRows.Scan(&expIP, &ifIdx, &tb, &rb, &xb, &fl, &ls, &ageSec, &rb5, &xb5); err == nil {
			if _, ok := flowStats[expIP]; !ok {
				flowStats[expIP] = make(map[uint32]ifFlowStat)
			}
			flowStats[expIP][ifIdx] = ifFlowStat{
				totalBytes:  tb,
				rxBytes:     rb,
				txBytes:     xb,
				flows:       fl,
				lastSeen:    ls,
				lastSeenSec: ageSec,
				rxBytes5m:   rb5,
				txBytes5m:   xb5,
			}
		}
	}

	ifQuery := `
		SELECT exporter_ip, if_index, if_name, display_name, speed_mbps 
		FROM ntopng.device_interfaces FINAL 
		ORDER BY if_index ASC
	`
	ifRows, err := r.conn.Query(ctx, ifQuery)
	if err == nil {
		defer ifRows.Close()
		for ifRows.Next() {
			var expIP string
			var ifIdx, spd uint32
			var ifName, dispName string
			if err := ifRows.Scan(&expIP, &ifIdx, &ifName, &dispName, &spd); err == nil {
				dev, exists := devMap[expIP]
				if !exists {
					continue
				}
				stat := model.DeviceInterfaceStat{
					IfIndex:     ifIdx,
					IfName:      ifName,
					DisplayName: dispName,
					SpeedMbps:   spd,
				}
				if fMap, ok := flowStats[expIP]; ok {
					if fs, hasF := fMap[ifIdx]; hasF {
						stat.TotalBytes = fs.totalBytes
						stat.FormattedBytes = formatBytes(fs.totalBytes)
						stat.FlowCount = fs.flows
						stat.LastSeen = fs.lastSeen.Format("2006-01-02 15:04:05")

						// Active sampling requires receiving NetFlow packets within the last 15 minutes
						isRecent := fs.lastSeenSec >= -60 && fs.lastSeenSec <= 900
						if isRecent {
							stat.HasFlow = true
							if fs.rxBytes5m > 0 {
								stat.RxBps = float64(fs.rxBytes5m*8) / 300.0
							}
							if fs.txBytes5m > 0 {
								stat.TxBps = float64(fs.txBytes5m*8) / 300.0
							}
						} else {
							stat.HasFlow = false
							stat.RxBps = 0
							stat.TxBps = 0
						}
						delete(fMap, ifIdx)
					}
				}
				dev.Interfaces = append(dev.Interfaces, stat)
			}
		}
	}

	for expIP, fMap := range flowStats {
		dev, exists := devMap[expIP]
		if !exists {
			continue
		}
		for ifIdx, fs := range fMap {
			isRecent := fs.lastSeenSec >= -60 && fs.lastSeenSec <= 900
			stat := model.DeviceInterfaceStat{
				IfIndex:        ifIdx,
				IfName:         fmt.Sprintf("Port #%d", ifIdx),
				DisplayName:    fmt.Sprintf("接口 #%d (未命名采样口)", ifIdx),
				HasFlow:        isRecent,
				TotalBytes:     fs.totalBytes,
				FormattedBytes: formatBytes(fs.totalBytes),
				FlowCount:      fs.flows,
				LastSeen:       fs.lastSeen.Format("2006-01-02 15:04:05"),
			}
			if isRecent {
				if fs.rxBytes5m > 0 {
					stat.RxBps = float64(fs.rxBytes5m*8) / 300.0
				}
				if fs.txBytes5m > 0 {
					stat.TxBps = float64(fs.txBytes5m*8) / 300.0
				}
			}
			dev.Interfaces = append(dev.Interfaces, stat)
		}
	}

	for i := range devices {
		dev := &devices[i]
		sort.Slice(dev.Interfaces, func(a, b int) bool {
			if dev.Interfaces[a].HasFlow != dev.Interfaces[b].HasFlow {
				return dev.Interfaces[a].HasFlow
			}
			return dev.Interfaces[a].TotalBytes > dev.Interfaces[b].TotalBytes
		})

		dev.TotalIfCount = len(dev.Interfaces)
		for _, ifc := range dev.Interfaces {
			if ifc.HasFlow {
				dev.SamplingIfCount++
				dev.TotalRxBps += ifc.RxBps
				dev.TotalTxBps += ifc.TxBps
			}
			dev.TotalBytes += ifc.TotalBytes
			dev.TotalFlows += ifc.FlowCount
		}
	}

	return devices, nil
}

func (r *ClickHouseRepo) QueryInterfaceSessions(ctx context.Context, req model.SessionRequest) (*model.SessionResponse, error) {
	startTime, endTime, duration := model.ParseTimeSpan(req.StartTime, req.EndTime)
	startStr := startTime.Format("2006-01-02 15:04:05")
	endStr := endTime.Format("2006-01-02 15:04:05")

	var isClipped bool
	var notice string
	if duration > 24*time.Hour {
		isClipped = true
		notice = "时间跨度超过24小时，会话明细已智能收敛展示最近24小时活跃连接"
		clippedStart := endTime.Add(-24 * time.Hour)
		startStr = clippedStart.Format("2006-01-02 15:04:05")
	}

	var conds []string
	conds = append(conds, fmt.Sprintf("first_switched >= toDateTime('%s') - INTERVAL 24 HOUR AND first_switched <= '%s' AND last_switched >= '%s'", startStr, endStr, startStr))

	if req.ExporterIP != "" {
		conds = append(conds, fmt.Sprintf("exporter_ip = '%s'", sanitize(req.ExporterIP)))
	}

	if req.IfIndex > 0 {
		switch req.Direction {
		case "inbound":
			conds = append(conds, fmt.Sprintf("in_snmp = %d", req.IfIndex))
		case "outbound":
			conds = append(conds, fmt.Sprintf("out_snmp = %d", req.IfIndex))
		default:
			conds = append(conds, fmt.Sprintf("(in_snmp = %d OR out_snmp = %d)", req.IfIndex, req.IfIndex))
		}
	}

	srcCond := buildIPCondition("src_ip", req.SrcIP)
	dstCond := buildIPCondition("dst_ip", req.DstIP)
	if srcCond != "" && dstCond != "" {
		conds = append(conds, fmt.Sprintf("((%s AND %s) OR (src_ip = '%s' AND dst_ip = '%s'))", srcCond, dstCond, sanitize(req.DstIP), sanitize(req.SrcIP)))
	} else if srcCond != "" {
		conds = append(conds, srcCond)
	} else if dstCond != "" {
		conds = append(conds, dstCond)
	}

	if req.Port > 0 {
		conds = append(conds, fmt.Sprintf("(dst_port = %d OR src_port = %d)", req.Port, req.Port))
	}

	if req.Proto != "" {
		p := strings.ToLower(req.Proto)
		switch p {
		case "tcp":
			conds = append(conds, "proto = 6")
		case "udp":
			conds = append(conds, "proto = 17")
		case "icmp":
			conds = append(conds, "proto = 1")
		}
	}

	if req.App != "" {
		app := strings.ToLower(req.App)
		switch app {
		case "web", "http", "https":
			conds = append(conds, "(dst_port IN (80, 443, 8080, 8443) OR src_port IN (80, 443, 8080, 8443))")
		case "dns":
			conds = append(conds, "(dst_port = 53 OR src_port = 53)")
		case "ssh":
			conds = append(conds, "(dst_port = 22 OR src_port = 22)")
		case "rdp":
			conds = append(conds, "(dst_port = 3389 OR src_port = 3389)")
		case "mysql", "database":
			conds = append(conds, "(dst_port IN (3306, 5432, 1521, 1433) OR src_port IN (3306, 5432, 1521, 1433))")
		case "smb":
			conds = append(conds, "(dst_port = 445 OR src_port = 445)")
		}
	}

	whereClause := strings.Join(conds, " AND ")

	limit := req.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	offset := req.Offset
	if offset < 0 {
		offset = 0
	}

	sql := fmt.Sprintf(`
		SELECT 
			first_switched, last_switched,
			src_ip, dst_ip, src_port, dst_port,
			proto, in_snmp, out_snmp,
			bytes, pkts, exporter_ip
		FROM ntopng.flows_raw
		WHERE %s
		ORDER BY bytes DESC
		LIMIT %d OFFSET %d
		SETTINGS max_threads = 8
	`, whereClause, limit, offset)

	startQ := time.Now()
	rows, err := r.conn.Query(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("session query error: %w", err)
	}
	defer rows.Close()

	ifNames := make(map[string]map[uint32]string)
	ifRows, ifErr := r.conn.Query(ctx, "SELECT exporter_ip, if_index, display_name FROM ntopng.device_interfaces FINAL")
	if ifErr == nil {
		defer ifRows.Close()
		for ifRows.Next() {
			var eip, dname string
			var idx uint32
			if err := ifRows.Scan(&eip, &idx, &dname); err == nil {
				if _, ok := ifNames[eip]; !ok {
					ifNames[eip] = make(map[uint32]string)
				}
				ifNames[eip][idx] = dname
			}
		}
	}

	var items []model.SessionItem
	for rows.Next() {
		var item model.SessionItem
		var fs, ls time.Time
		var p uint8
		if err := rows.Scan(&fs, &ls, &item.SrcIP, &item.DstIP, &item.SrcPort, &item.DstPort, &p, &item.InIf, &item.OutIf, &item.Bytes, &item.Packets, &item.ExporterIP); err != nil {
			continue
		}
		item.FirstSwitched = fs.Format("2006-01-02 15:04:05")
		item.LastSwitched = ls.Format("2006-01-02 15:04:05")
		item.FormattedBytes = formatBytes(item.Bytes)

		durSec := uint32(ls.Sub(fs).Seconds())
		if durSec == 0 {
			durSec = 1
		}
		item.DurationSec = durSec
		item.Bps = float64(item.Bytes*8) / float64(durSec)
		item.FormattedRate = formatBps(item.Bps)

		switch p {
		case 6:
			item.Proto = "TCP"
		case 17:
			item.Proto = "UDP"
		case 1:
			item.Proto = "ICMP"
		default:
			item.Proto = fmt.Sprintf("IP-%d", p)
		}

		item.AppName = resolveAppName(p, item.SrcPort, item.DstPort)

		if req.IfIndex > 0 {
			if item.InIf == req.IfIndex {
				item.Direction = "inbound"
			} else if item.OutIf == req.IfIndex {
				item.Direction = "outbound"
			} else {
				item.Direction = "transit"
			}
		} else {
			item.Direction = "flow"
		}

		if m, ok := ifNames[item.ExporterIP]; ok {
			if name, ok2 := m[item.InIf]; ok2 {
				item.InIfName = name
			} else if item.InIf > 0 {
				item.InIfName = fmt.Sprintf("Port #%d", item.InIf)
			}
			if name, ok2 := m[item.OutIf]; ok2 {
				item.OutIfName = name
			} else if item.OutIf > 0 {
				item.OutIfName = fmt.Sprintf("Port #%d", item.OutIf)
			}
		}

		items = append(items, item)
	}

	queryDurMs := float64(time.Since(startQ).Microseconds()) / 1000.0
	return &model.SessionResponse{
		TotalCount:  uint64(len(items)),
		Items:       items,
		QueryTimeMs: queryDurMs,
		TimeClipped: isClipped,
		Notice:      notice,
	}, nil
}

func resolveAppName(proto uint8, srcPort, dstPort uint16) string {
	port := dstPort
	if port > 1024 && srcPort <= 1024 {
		port = srcPort
	}
	switch port {
	case 80:
		return "HTTP"
	case 443:
		return "HTTPS"
	case 53:
		return "DNS"
	case 22:
		return "SSH"
	case 23:
		return "Telnet"
	case 21:
		return "FTP"
	case 25:
		return "SMTP"
	case 110:
		return "POP3"
	case 143:
		return "IMAP"
	case 3389:
		return "RDP"
	case 3306:
		return "MySQL"
	case 5432:
		return "PostgreSQL"
	case 1433:
		return "MSSQL"
	case 1521:
		return "Oracle"
	case 6379:
		return "Redis"
	case 445:
		return "SMB"
	case 161:
		return "SNMP"
	case 500, 4500:
		return "IPsec"
	default:
		if proto == 1 {
			return "ICMP-Ping"
		}
		return fmt.Sprintf("Port:%d", port)
	}
}

// InspectDatabase checks ClickHouse health, row count, and flow freshness
func (r *ClickHouseRepo) InspectDatabase(ctx context.Context) (totalFlows uint64, latestFlowTime time.Time, latencyMs int64, err error) {
	start := time.Now()
	if err = r.conn.Ping(ctx); err != nil {
		return 0, time.Time{}, time.Since(start).Milliseconds(), fmt.Errorf("clickhouse ping 失败: %w", err)
	}

	query := `SELECT count(), max(last_switched) FROM ntopng.flows_raw`
	row := r.conn.QueryRow(ctx, query)
	var maxTime *time.Time
	if scanErr := row.Scan(&totalFlows, &maxTime); scanErr != nil {
		return 0, time.Time{}, time.Since(start).Milliseconds(), scanErr
	}
	if maxTime != nil {
		latestFlowTime = *maxTime
	}
	latencyMs = time.Since(start).Milliseconds()
	return totalFlows, latestFlowTime, latencyMs, nil
}


