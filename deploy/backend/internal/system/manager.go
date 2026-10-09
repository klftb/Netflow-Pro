package system

import (
	"context"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"flow-analytics-backend/internal/auth"
	"flow-analytics-backend/internal/librenms"
	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/netbox"
	"flow-analytics-backend/internal/repository"
)

type Manager struct {
	repo         *repository.ClickHouseRepo
	libreClient  *librenms.Client
	netboxClient *netbox.Client
	ldapClient   *auth.LDAPClient
}

func NewManager(
	repo *repository.ClickHouseRepo,
	libreClient *librenms.Client,
	netboxClient *netbox.Client,
	ldapClient *auth.LDAPClient,
) *Manager {
	return &Manager{
		repo:         repo,
		libreClient:  libreClient,
		netboxClient: netboxClient,
		ldapClient:   ldapClient,
	}
}

// 1. GetServicesStatus retrieves real-time execution states of core platform services
func (m *Manager) GetServicesStatus(ctx context.Context) ([]model.ManagedService, error) {
	services := []model.ManagedService{
		{
			ID:          "flow-backend",
			Name:        "Akvorado 流分析与后端 API",
			Type:        "systemd",
			ServiceName: "flow-backend.service",
			Port:        "8080 (RESTful API / Web)",
			Description: "提供 NetFlow 汇聚统计、NetBox 每日同步引擎、LDAP 认证与系统编排 API",
		},
		{
			ID:          "clickhouse-server",
			Name:        "ClickHouse 列式高性能时序数据库",
			Type:        "systemd",
			ServiceName: "clickhouse-server.service",
			Port:        "9000 (Native) / 8123 (HTTP)",
			Description: "分布式高性能时序存储，持久化亿级 NetFlow 原始流明细与资产元数据",
		},
		{
			ID:          "flow-collector",
			Name:        "NetFlow / sFlow 采集网桥服务",
			Type:        "systemd",
			ServiceName: "flow-collector.service",
			Port:        "2055 (UDP 采集) / 5556 (IPC)",
			Description: "全天候监听 UDP 2055 接收全网交换机与防火墙 NetFlow/IPFIX 报文并清洗分发",
		},
		{
			ID:          "flow-kafka",
			Name:        "Kafka 流消息削峰缓冲集群",
			Type:        "docker",
			ServiceName: "flow-kafka",
			Port:        "9092 (KRaft Broker)",
			Description: "高性能流数据消息中继队列，支撑突发流量洪峰削峰填谷，保障数据零丢包",
		},
	}

	for i := range services {
		s := &services[i]
		if s.Type == "systemd" {
			out, err := exec.CommandContext(ctx, "systemctl", "show", s.ServiceName, "--property=MainPID,MemoryCurrent,ActiveState,SubState,ActiveEnterTimestamp").CombinedOutput()
			if err != nil {
				s.Status = "error"
				s.SubState = "unknown"
				s.Uptime = "获取失败"
				s.Memory = "--"
				continue
			}
			lines := strings.Split(string(out), "\n")
			props := make(map[string]string)
			for _, line := range lines {
				parts := strings.SplitN(line, "=", 2)
				if len(parts) == 2 {
					props[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
				}
			}

			s.Status = props["ActiveState"]
			s.SubState = props["SubState"]
			if pid, err := strconv.Atoi(props["MainPID"]); err == nil {
				s.PID = pid
			}
			if memBytes, err := strconv.ParseUint(props["MemoryCurrent"], 10, 64); err == nil && memBytes > 0 {
				s.Memory = formatBytes(memBytes)
			} else {
				s.Memory = "--"
			}
			if ts := props["ActiveEnterTimestamp"]; ts != "" {
				s.Uptime = ts
			} else {
				s.Uptime = "--"
			}
		} else if s.Type == "docker" {
			out, err := exec.CommandContext(ctx, "sudo", "docker", "inspect", s.ServiceName, "--format", "{{.State.Status}}|{{.State.Pid}}|{{.State.StartedAt}}").Output()
			if err != nil {
				s.Status = "stopped"
				s.SubState = "not found"
				s.Uptime = "--"
				s.Memory = "--"
				continue
			}
			cleanOut := strings.TrimSpace(string(out))
			lines := strings.Split(cleanOut, "\n")
			targetLine := lines[len(lines)-1]
			parts := strings.Split(strings.TrimSpace(targetLine), "|")
			if len(parts) >= 3 {
				s.SubState = strings.TrimSpace(parts[0])
				if s.SubState == "running" {
					s.Status = "active"
				} else {
					s.Status = "inactive"
				}
				if pid, err := strconv.Atoi(strings.TrimSpace(parts[1])); err == nil {
					s.PID = pid
				}
				s.Uptime = formatDockerTimestamp(strings.TrimSpace(parts[2]))
				s.Memory = "JVM (Kafka)"
			}
		}
		s.UpdatedAt = time.Now()
	}

	return services, nil
}

// 2. RestartService safely restarts the targeted service
func (m *Manager) RestartService(ctx context.Context, serviceID string) (string, error) {
	switch serviceID {
	case "flow-backend":
		// Asynchronous restart to allow immediate response delivery to caller
		go func() {
			time.Sleep(600 * time.Millisecond)
			exec.Command("sudo", "systemctl", "restart", "flow-backend.service").Run()
		}()
		return "flow-backend 核心服务重启指令已下发，服务正在重启中，系统将在 3 秒内恢复并自动刷新", nil

	case "clickhouse-server":
		cmdCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
		defer cancel()
		out, err := exec.CommandContext(cmdCtx, "sudo", "systemctl", "restart", "clickhouse-server.service").CombinedOutput()
		if err != nil {
			return "", fmt.Errorf("重启 ClickHouse 失败: %s (%v)", string(out), err)
		}
		return "ClickHouse 数据库服务已成功重启并恢复在线", nil

	case "flow-collector":
		cmdCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
		defer cancel()
		out, err := exec.CommandContext(cmdCtx, "sudo", "systemctl", "restart", "flow-collector.service").CombinedOutput()
		if err != nil {
			return "", fmt.Errorf("重启采集器服务失败: %s (%v)", string(out), err)
		}
		return "NetFlow / sFlow 采集网桥服务已成功重启并就绪", nil

	case "flow-kafka":
		cmdCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
		defer cancel()
		out, err := exec.CommandContext(cmdCtx, "sudo", "docker", "restart", "flow-kafka").CombinedOutput()
		if err != nil {
			return "", fmt.Errorf("重启 Kafka 容器失败: %s (%v)", string(out), err)
		}
		return "Kafka 流消息缓冲容器已成功重启并恢复服务", nil

	default:
		return "", fmt.Errorf("不支持或非法的服务标识: %s", serviceID)
	}
}

// 3. RunInspection performs full-spectrum system health check and returns a detailed diagnostic report
func (m *Manager) RunInspection(ctx context.Context) (*model.InspectionReport, error) {
	start := time.Now()
	report := &model.InspectionReport{
		InspectedAt: time.Now().Format("2006-01-02 15:04:05"),
		Score:       100,
		Items:       make([]model.InspectionItem, 0),
	}

	// [Check 1-4]: Core Platform Services Status
	services, err := m.GetServicesStatus(ctx)
	if err == nil {
		for _, s := range services {
			item := model.InspectionItem{
				ID:       "service_" + s.ID,
				Category: "service",
				Name:     s.Name + " (" + s.ServiceName + ")",
			}
			if s.Status == "active" && s.SubState == "running" {
				item.Status = "pass"
				item.Message = fmt.Sprintf("运行正常 (PID: %d)", s.PID)
				item.Details = fmt.Sprintf("内存: %s | 端口: %s | 启动时间: %s", s.Memory, s.Port, s.Uptime)
			} else {
				item.Status = "fail"
				item.Message = fmt.Sprintf("服务异常停止 (状态: %s / %s)", s.Status, s.SubState)
				item.Details = fmt.Sprintf("请在服务列表点击【重启服务】或通过 systemctl/docker 查看日志")
				item.Suggestion = fmt.Sprintf("执行 'sudo systemctl restart %s' 尝试拉起服务", s.ServiceName)
				report.Score -= 20
			}
			report.Items = append(report.Items, item)
		}
	}

	// [Check 5]: ClickHouse Database Query & Flow Freshness
	chStart := time.Now()
	totalFlows, latestTime, _, chErr := m.repo.InspectDatabase(ctx)
	chDuration := time.Since(chStart).Milliseconds()
	chItem := model.InspectionItem{
		ID:        "database_clickhouse",
		Category:  "database",
		Name:      "ClickHouse 数据库连通性与流数据活跃度",
		LatencyMs: chDuration,
	}
	if chErr != nil {
		chItem.Status = "fail"
		chItem.Message = "ClickHouse 数据库连接或查询异常"
		chItem.Details = chErr.Error()
		chItem.Suggestion = "检查 ClickHouse 进程是否存活、端口 9000 是否开放"
		report.Score -= 25
	} else {
		// Calculate time difference between latest flow and now
		timeDiffSec := time.Since(latestTime).Seconds()
		if timeDiffSec < 300 { // within 5 minutes
			chItem.Status = "pass"
			chItem.Message = fmt.Sprintf("数据流链路实时通畅 (累计纳管 %d 条流记录)", totalFlows)
			chItem.Details = fmt.Sprintf("最新数据入库时间: %s (距今 %.1f 秒前) | 查询耗时: %d ms", latestTime.Format("15:04:05"), timeDiffSec, chDuration)
		} else {
			chItem.Status = "warn"
			chItem.Message = fmt.Sprintf("流数据入库存在延迟或断流 (距今 %.1f 分钟无新流)", timeDiffSec/60)
			chItem.Details = fmt.Sprintf("最新记录时间: %s | 累计流记录: %d | 查询耗时: %d ms", latestTime.Format("2006-01-02 15:04:05"), totalFlows, chDuration)
			chItem.Suggestion = "检查网络交换机 NetFlow Exporter 配置与 flow-collector 服务"
			report.Score -= 10
		}
	}
	report.Items = append(report.Items, chItem)

	// [Check 6]: NetFlow UDP 2055 Ingestion Port
	portStart := time.Now()
	portOut, _ := exec.CommandContext(ctx, "ss", "-u", "-a", "-n").CombinedOutput()
	portDuration := time.Since(portStart).Milliseconds()
	portItem := model.InspectionItem{
		ID:        "collector_port_2055",
		Category:  "collector",
		Name:      "NetFlow UDP 2055 采集端口监听状态",
		LatencyMs: portDuration,
	}
	if strings.Contains(string(portOut), ":2055") {
		portItem.Status = "pass"
		portItem.Message = "UDP 2055 端口正常监听就绪"
		portItem.Details = "全网 NetFlow v5/v9/IPFIX 数据包持续接收通道处于 Active 状态"
	} else {
		portItem.Status = "fail"
		portItem.Message = "UDP 2055 端口未在监听，网络流无法接收"
		portItem.Details = "系统未检测到 2055 端口绑定，导致全网交换机流量无法入库"
		portItem.Suggestion = "重启 flow-collector 服务 ('sudo systemctl restart flow-collector')"
		report.Score -= 20
	}
	report.Items = append(report.Items, portItem)

	// [Check 7]: NetBox Third-Party Integration
	if m.netboxClient != nil {
		nbStart := time.Now()
		nbStatus, nbErr := m.netboxClient.TestConnection(ctx)
		nbDuration := time.Since(nbStart).Milliseconds()
		nbItem := model.InspectionItem{
			ID:        "integration_netbox",
			Category:  "integration",
			Name:      "NetBox 资产管理系统 API 连通性",
			LatencyMs: nbDuration,
		}
		nbBaseURL, _ := m.netboxClient.GetConfig()
		if nbErr == nil && nbStatus != nil && nbStatus["status"] == "online" {
			nbItem.Status = "pass"
			nbItem.Message = fmt.Sprintf("API 连接正常 (耗时 %d ms)", nbDuration)
			nbItem.Details = fmt.Sprintf("接口地址: %s | 状态: 在线", nbBaseURL)
		} else {
			nbItem.Status = "warn"
			msg := "NetBox API 连接探测失败"
			if nbErr != nil {
				msg += ": " + nbErr.Error()
			}
			nbItem.Message = msg
			nbItem.Details = fmt.Sprintf("接口地址: %s | 请检查【第三方平台 API 集成】中的 NetBox 配置", nbBaseURL)
			nbItem.Suggestion = "检查 NetBox 服务网络连通性及 Token 权限"
			report.Score -= 5
		}
		report.Items = append(report.Items, nbItem)
	}

	// [Check 8]: LibreNMS Integration
	if m.libreClient != nil {
		lnStart := time.Now()
		lnInfo, lnErr := m.libreClient.GetSystemInfo(ctx)
		lnDuration := time.Since(lnStart).Milliseconds()
		lnBaseURL, _ := m.libreClient.GetConfig()
		lnItem := model.InspectionItem{
			ID:        "integration_librenms",
			Category:  "integration",
			Name:      "LibreNMS 网络监控系统 API 连通性",
			LatencyMs: lnDuration,
		}
		if lnErr == nil && lnInfo != nil {
			lnItem.Status = "pass"
			lnItem.Message = fmt.Sprintf("API 连接正常 (耗时 %d ms)", lnDuration)
			lnItem.Details = fmt.Sprintf("接口地址: %s | 状态: 在线", lnBaseURL)
		} else {
			lnItem.Status = "warn"
			msg := "LibreNMS 连接异常"
			if lnErr != nil {
				msg += ": " + lnErr.Error()
			}
			lnItem.Message = msg
			lnItem.Details = fmt.Sprintf("接口地址: %s | 请检查【第三方平台 API 集成】中的 LibreNMS 配置", lnBaseURL)
			lnItem.Suggestion = "如需设备自动发现与端口同步，请配置合法的 LibreNMS 访问凭证"
			report.Score -= 5
		}
		report.Items = append(report.Items, lnItem)
	}

	// [Check 9]: Host System Resources (Disk, Memory, CPU Load)
	hostStart := time.Now()
	hostItem := model.InspectionItem{
		ID:        "host_resources",
		Category:  "host",
		Name:      "服务器主机硬件资源健康度 (CPU/内存/磁盘)",
		LatencyMs: time.Since(hostStart).Milliseconds(),
	}
	diskOut, _ := exec.CommandContext(ctx, "df", "-h", "/").CombinedOutput()
	memOut, _ := exec.CommandContext(ctx, "free", "-m").CombinedOutput()
	uptimeOut, _ := exec.CommandContext(ctx, "uptime").CombinedOutput()

	diskUsage := parseDiskUsage(string(diskOut))
	memUsage := parseMemoryUsage(string(memOut))
	loadAvg := parseUptimeLoad(string(uptimeOut))

	hostItem.Details = fmt.Sprintf("根分区磁盘: %s | 物理内存: %s | %s", diskUsage, memUsage, loadAvg)
	if strings.Contains(diskUsage, "9") && (strings.Contains(diskUsage, "90%") || strings.Contains(diskUsage, "95%")) {
		hostItem.Status = "fail"
		hostItem.Message = "主机根分区磁盘使用率超过 90%！"
		hostItem.Suggestion = "清理磁盘日志或扩容根目录空间"
		report.Score -= 20
	} else if strings.Contains(diskUsage, "8") && strings.Contains(diskUsage, "85%") {
		hostItem.Status = "warn"
		hostItem.Message = "磁盘使用率较高，建议预警监控"
		report.Score -= 5
	} else {
		hostItem.Status = "pass"
		hostItem.Message = "主机资源充足，运行负载健康稳定"
	}
	report.Items = append(report.Items, hostItem)

	// Summary statistics
	if report.Score < 0 {
		report.Score = 0
	}
	for _, item := range report.Items {
		report.TotalChecks++
		switch item.Status {
		case "pass":
			report.PassedChecks++
		case "warn":
			report.WarningChecks++
		case "fail":
			report.FailedChecks++
		}
	}

	if report.FailedChecks == 0 && report.WarningChecks == 0 {
		report.OverallStatus = "healthy"
	} else if report.FailedChecks == 0 {
		report.OverallStatus = "warning"
	} else {
		report.OverallStatus = "critical"
	}

	report.DurationMs = time.Since(start).Milliseconds()
	return report, nil
}

func parseDiskUsage(out string) string {
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if len(lines) >= 2 {
		fields := strings.Fields(lines[1])
		if len(fields) >= 5 {
			return fmt.Sprintf("已用 %s / 总量 %s (%s)", fields[2], fields[1], fields[4])
		}
	}
	return "正常"
}

func parseMemoryUsage(out string) string {
	lines := strings.Split(strings.TrimSpace(out), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "Mem:") {
			fields := strings.Fields(line)
			if len(fields) >= 7 {
				total, _ := strconv.Atoi(fields[1])
				used, _ := strconv.Atoi(fields[2])
				if total > 0 {
					pct := (used * 100) / total
					return fmt.Sprintf("已用 %d MB / 总计 %d MB (%d%%)", used, total, pct)
				}
			}
		}
	}
	return "正常"
}

func parseUptimeLoad(out string) string {
	idx := strings.Index(out, "load average:")
	if idx != -1 {
		return "系统负载 " + strings.TrimSpace(out[idx:])
	}
	return "运行平稳"
}

func formatBytes(b uint64) string {
	const unit = 1024
	if b < unit {
		return fmt.Sprintf("%d B", b)
	}
	div, exp := uint64(unit), 0
	for n := b / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.2f %cB", float64(b)/float64(div), "KMGTPE"[exp])
}

func formatDockerTimestamp(ts string) string {
	t, err := time.Parse(time.RFC3339Nano, ts)
	if err != nil {
		return ts
	}
	return t.Local().Format("2006-01-02 15:04:05")
}
