package alert

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

type AlertSeverity string

const (
	SeverityCritical AlertSeverity = "CRITICAL"
	SeverityHigh     AlertSeverity = "HIGH"
	SeverityMedium   AlertSeverity = "MEDIUM"
	SeverityLow      AlertSeverity = "LOW"
)

type AlertEvent struct {
	ID          string        `json:"id"`
	Type        string        `json:"type"` // "FLOW_SILENCE", "PORT_SCAN", "BANDWIDTH_THRESHOLD"
	Severity    AlertSeverity `json:"severity"`
	Title       string        `json:"title"`
	Description string        `json:"description"`
	Source      string        `json:"source"`
	Timestamp   string        `json:"timestamp"`
	Metrics     interface{}   `json:"metrics,omitempty"`
}

type Engine struct {
	conn              driver.Conn
	alerts            []AlertEvent
	mu                sync.RWMutex
	outputFile        string
	running           bool
	portScanThreshold uint64
	silenceMinutes    int
}

func NewEngine(conn driver.Conn, outputFile string) *Engine {
	return &Engine{
		conn:              conn,
		alerts:            make([]AlertEvent, 0),
		outputFile:        outputFile,
		running:           true,
		portScanThreshold: 100,
		silenceMinutes:    5,
	}
}

func (e *Engine) GetConfig() (uint64, int) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.portScanThreshold, e.silenceMinutes
}

func (e *Engine) SetConfig(portScan uint64, silenceMin int) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if portScan > 0 {
		e.portScanThreshold = portScan
	}
	if silenceMin > 0 {
		e.silenceMinutes = silenceMin
	}
}

func (e *Engine) Start() {
	log.Printf("[*] NBA Alert Engine started (Alert Output: %s, PortScanThreshold: %d, SilenceMinutes: %d)",
		e.outputFile, e.portScanThreshold, e.silenceMinutes)
	go e.runPortScanDetector()
	go e.runSilenceDetector()
}

func (e *Engine) recordAlert(a AlertEvent) {
	e.mu.Lock()
	defer e.mu.Unlock()

	// Dedup recently recorded alerts of same type and source within 1 minute
	now := time.Now()
	for _, exist := range e.alerts {
		if exist.Type == a.Type && exist.Source == a.Source {
			t, _ := time.Parse(time.RFC3339, exist.Timestamp)
			if now.Sub(t) < time.Minute {
				return // Skip duplicate
			}
		}
	}

	e.alerts = append([]AlertEvent{a}, e.alerts...)
	if len(e.alerts) > 100 {
		e.alerts = e.alerts[:100]
	}

	log.Printf("[ALERT][%s][%s] %s - %s", a.Severity, a.Type, a.Title, a.Description)

	// Persist to alert_output.json
	data, err := json.MarshalIndent(e.alerts, "", "  ")
	if err == nil {
		_ = os.WriteFile(e.outputFile, data, 0644)
	}
}

// 1. NBA Port Scan Detection: Single Source hitting > 100 destination ports within 1 minute
func (e *Engine) runPortScanDetector() {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for e.running {
		<-ticker.C
		ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
		e.mu.RLock()
		thresh := e.portScanThreshold
		e.mu.RUnlock()

		query := fmt.Sprintf(`
			SELECT
				src_ip,
				count(DISTINCT dst_port) AS scanned_ports,
				count() AS fl_count,
				sum(bytes) AS vol
			FROM ntopng.flows_raw
			WHERE first_switched >= now() - INTERVAL 2 MINUTE
			GROUP BY src_ip
			HAVING scanned_ports >= %d
		`, thresh)
		rows, err := e.conn.Query(ctx, query)
		if err == nil {
			for rows.Next() {
				var srcIP string
				var scannedPorts, flCount, vol uint64
				if err := rows.Scan(&srcIP, &scannedPorts, &flCount, &vol); err == nil {
					e.recordAlert(AlertEvent{
						ID:          fmt.Sprintf("SCAN-%d", time.Now().UnixNano()),
						Type:        "PORT_SCAN_ATTACK",
						Severity:    SeverityHigh,
						Title:       fmt.Sprintf("检测到源主机 %s 正在进行大范围端口扫描探测", srcIP),
						Description: fmt.Sprintf("单源 IP 在短时间内尝试连接了 %d 个不同的目标端口，具有强烈的网络攻击/渗透特征！", scannedPorts),
						Source:      srcIP,
						Timestamp:   time.Now().Format(time.RFC3339),
						Metrics: map[string]interface{}{
							"attacker_ip":   srcIP,
							"scanned_ports": scannedPorts,
							"total_packets": flCount,
							"total_bytes":   vol,
						},
					})
				}
			}
			rows.Close()
		}
		cancel()
	}
}

// 2. Flow Silence Detection: Alerts if no flow arrives in configured consecutive minutes
func (e *Engine) runSilenceDetector() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for e.running {
		<-ticker.C
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		var maxTime time.Time
		err := e.conn.QueryRow(ctx, "SELECT max(first_switched) FROM ntopng.flows_raw").Scan(&maxTime)
		if err == nil && !maxTime.IsZero() {
			silenceDuration := time.Since(maxTime)
			e.mu.RLock()
			silenceLimit := time.Duration(e.silenceMinutes) * time.Minute
			e.mu.RUnlock()
			if silenceDuration > silenceLimit {
				e.recordAlert(AlertEvent{
					ID:          fmt.Sprintf("SILENCE-%d", time.Now().UnixNano()),
					Type:        "FLOW_SILENCE",
					Severity:    SeverityCritical,
					Title:       "网络流上报中断静默告警 (Flow Silence)",
					Description: fmt.Sprintf("采集器已连续 %.1f 分钟未接收到新的 NetFlow 数据流，疑似核心交换机配置变更或网络故障！", silenceDuration.Minutes()),
					Source:      "Collector-Engine",
					Timestamp:   time.Now().Format(time.RFC3339),
					Metrics: map[string]interface{}{
						"last_seen":        maxTime.Format("2006-01-02 15:04:05"),
						"silence_duration": silenceDuration.String(),
					},
				})
			}
		}
		cancel()
	}
}

func (e *Engine) GetAlerts() []AlertEvent {
	e.mu.RLock()
	defer e.mu.RUnlock()
	res := make([]AlertEvent, len(e.alerts))
	copy(res, e.alerts)
	return res
}
