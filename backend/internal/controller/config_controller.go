package controller

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"flow-analytics-backend/internal/alert"
	"flow-analytics-backend/internal/auth"
	"flow-analytics-backend/internal/librenms"
	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/netbox"
	"flow-analytics-backend/internal/repository"
	"flow-analytics-backend/internal/syncer"
	"flow-analytics-backend/internal/system"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
)

type ConfigController struct {
	repo         *repository.ClickHouseRepo
	alertEngine  *alert.Engine
	libreClient  *librenms.Client
	netboxClient *netbox.Client
	ldapClient   *auth.LDAPClient
	syncer       *syncer.AutoDiscoverSyncer
	netboxSyncer *syncer.NetboxSyncer
	resolver     *repository.IPResolver
	sysMgr       *system.Manager
}

func NewConfigController(
	repo *repository.ClickHouseRepo,
	alertEngine *alert.Engine,
	libreClient *librenms.Client,
	syncer *syncer.AutoDiscoverSyncer,
	netboxClient *netbox.Client,
	ldapClient *auth.LDAPClient,
	netboxSyncer *syncer.NetboxSyncer,
	resolver *repository.IPResolver,
	sysMgr *system.Manager,
) *ConfigController {
	return &ConfigController{
		repo:         repo,
		alertEngine:  alertEngine,
		libreClient:  libreClient,
		syncer:       syncer,
		netboxClient: netboxClient,
		ldapClient:   ldapClient,
		netboxSyncer: netboxSyncer,
		resolver:     resolver,
		sysMgr:       sysMgr,
	}
}

func (c *ConfigController) RegisterRoutes(r *gin.Engine) {
	cfg := r.Group("/api/v1/config")
	{
		// 1. Business Groups & Subnets
		cfg.GET("/business-groups", c.GetBusinessGroups)
		cfg.GET("/subnets-summary", c.GetSubnetsSummary)
		cfg.POST("/business-groups", c.SaveBusinessGroup)
		cfg.DELETE("/business-groups/:id", c.DeleteBusinessGroup)

		// 1b. 32-bit IP Hosts Maintenance (Netbox / Local)
		cfg.GET("/ip-hosts", c.GetIPHosts)
		cfg.POST("/ip-hosts", c.SaveIPHost)
		cfg.DELETE("/ip-hosts/:ip", c.DeleteIPHost)

		// 1c. NetBox Sync
		cfg.GET("/netbox/sync/status", c.GetNetboxSyncStatus)
		cfg.POST("/netbox/sync/now", c.TriggerNetboxSync)

		// 2. App & Port Mappings
		cfg.GET("/app-mappings", c.GetAppMappings)
		cfg.POST("/app-mappings", c.SaveAppMapping)
		cfg.DELETE("/app-mappings/:proto/:port", c.DeleteAppMapping)

		// 3. Exporter Devices
		cfg.GET("/exporters", c.GetExporters)
		cfg.POST("/exporters", c.SaveExporter)
		cfg.DELETE("/exporters/:ip", c.DeleteExporter)
		cfg.POST("/exporters/snmp-probe", c.ProbeSNMPDeviceName)
		cfg.GET("/exporters/:ip/interfaces", c.GetDeviceInterfaces)
		cfg.POST("/exporters/interfaces", c.SaveDeviceInterface)
		cfg.POST("/exporters/snmp-interfaces", c.SnmpWalkInterfaces)
		cfg.POST("/exporters/snmp-sync-all", c.SnmpSyncAllExporters)

		// 4. Alert Thresholds & System Info
		cfg.GET("/system-info", c.GetSystemInfo)
		cfg.POST("/alert-thresholds", c.SaveAlertThresholds)

		// 5. LibreNMS Integration & Auto-Discovery
		cfg.GET("/librenms/status", c.GetLibreNMSStatus)
		cfg.POST("/librenms/sync-all", c.SyncAllFromLibreNMS)
		cfg.POST("/librenms/sync-device/:ip", c.SyncDeviceFromLibreNMS)

		// 6. Third-party API Integrations (LibreNMS, NetBox & LDAP)
		cfg.GET("/api-settings", c.GetApiSettings)
		cfg.POST("/api-settings", c.SaveApiSettings)
		cfg.POST("/librenms/test", c.TestLibreNMS)
		cfg.POST("/netbox/test", c.TestNetBox)
		cfg.POST("/ldap/test", c.TestLDAP)

		// 7. Core Services & System Health Inspection
		cfg.GET("/system/services", c.GetServicesStatus)
		cfg.POST("/system/services/restart", c.RestartService)
		cfg.POST("/system/inspect", c.RunSystemInspection)

		// 8. Account Management & Unified Config Export/Import
		cfg.GET("/users", c.GetUsers)
		cfg.POST("/users", c.SaveUserAccount)
		cfg.DELETE("/users/:username", c.DeleteUserAccount)
		cfg.GET("/export", c.ExportConfigBundle)
		cfg.POST("/import", c.ImportConfigBundle)
	}

	sys := r.Group("/api/v1/system")
	{
		sys.GET("/services", c.GetServicesStatus)
		sys.POST("/services/restart", c.RestartService)
		sys.POST("/inspect", c.RunSystemInspection)
	}
}

// 1. Business Groups Handlers
func (c *ConfigController) GetBusinessGroups(ctx *gin.Context) {
	groups, err := c.repo.GetBusinessGroups(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: groups})
}

func (c *ConfigController) SaveBusinessGroup(ctx *gin.Context) {
	var item model.BusinessGroup
	if err := ctx.ShouldBindJSON(&item); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Invalid payload: " + err.Error()})
		return
	}
	item.GroupName = strings.TrimSpace(item.GroupName)
	item.CIDR = strings.TrimSpace(item.CIDR)
	item.Department = strings.TrimSpace(item.Department)
	if item.GroupName == "" || item.CIDR == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "GroupName and CIDR are required"})
		return
	}
	if !strings.Contains(item.CIDR, "/") {
		item.CIDR = item.CIDR + "/32"
	}
	if err := c.repo.SaveBusinessGroup(ctx.Request.Context(), item); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}
	if c.resolver != nil {
		_ = c.resolver.Reload(ctx.Request.Context(), c.repo)
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "Business group saved successfully"})
}

func (c *ConfigController) DeleteBusinessGroup(ctx *gin.Context) {
	idStr := ctx.Param("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4003, Message: "Invalid group id"})
		return
	}
	if err := c.repo.DeleteBusinessGroup(ctx.Request.Context(), uint32(id)); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5003, Message: err.Error()})
		return
	}
	if c.resolver != nil {
		_ = c.resolver.Reload(ctx.Request.Context(), c.repo)
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "Business group deleted successfully"})
}

func (c *ConfigController) GetSubnetsSummary(ctx *gin.Context) {
	summary, err := c.repo.GetSubnetsSummary(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: summary})
}

// 2. App & Port Mappings Handlers
func (c *ConfigController) GetAppMappings(ctx *gin.Context) {
	apps, err := c.repo.GetAppMappings(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: apps})
}

func (c *ConfigController) SaveAppMapping(ctx *gin.Context) {
	var item model.AppMappingItem
	if err := ctx.ShouldBindJSON(&item); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Invalid payload: " + err.Error()})
		return
	}
	if item.Port == 0 || item.AppName == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "Port and AppName are required"})
		return
	}
	if item.Proto == 0 {
		item.Proto = 6 // Default TCP
	}
	if item.Category == "" {
		item.Category = "Custom Service"
	}
	if err := c.repo.SaveAppMapping(ctx.Request.Context(), item); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "App mapping saved successfully"})
}

func (c *ConfigController) DeleteAppMapping(ctx *gin.Context) {
	protoStr := ctx.Param("proto")
	portStr := ctx.Param("port")

	protoVal, err := strconv.ParseUint(protoStr, 10, 8)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Invalid proto parameter"})
		return
	}
	portVal, err := strconv.ParseUint(portStr, 10, 16)
	if err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "Invalid port parameter"})
		return
	}

	if err := c.repo.DeleteAppMapping(ctx.Request.Context(), uint8(protoVal), uint16(portVal)); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5003, Message: "Failed to delete app mapping: " + err.Error()})
		return
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "App mapping deleted successfully"})
}

// 3. Exporter Devices Handlers
func (c *ConfigController) GetExporters(ctx *gin.Context) {
	exporters, err := c.repo.GetExporterDevices(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: exporters})
}

func (c *ConfigController) SaveExporter(ctx *gin.Context) {
	var item model.ExporterDevice
	if err := ctx.ShouldBindJSON(&item); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Invalid payload: " + err.Error()})
		return
	}
	if item.ExporterIP == "" || item.DeviceName == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "ExporterIP and DeviceName are required"})
		return
	}
	if item.DeviceType == "" {
		item.DeviceType = "Switch"
	}
	if err := c.repo.SaveExporterDevice(ctx.Request.Context(), item); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "Exporter device saved successfully"})
}

func (c *ConfigController) DeleteExporter(ctx *gin.Context) {
	ip := ctx.Param("ip")
	if ip == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Device IP is required"})
		return
	}
	if err := c.repo.DeleteExporterDevice(ctx.Request.Context(), ip); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "Exporter device deleted successfully"})
}

// 4. Alert Thresholds & System Info
func (c *ConfigController) GetSystemInfo(ctx *gin.Context) {
	var portScan uint64 = 100
	var silenceMin int = 5
	if c.alertEngine != nil {
		portScan, silenceMin = c.alertEngine.GetConfig()
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data: gin.H{
			"port_scan_threshold": portScan,
			"silence_minutes":    silenceMin,
			"retention_raw":      "7 Days (High Precision Detail Flows)",
			"retention_5m":       "90 Days (Pre-aggregated Rollup MV)",
			"clickhouse_version": "26.x (Akvorado Compatible)",
			"kafka_mode":         "KRaft 9092 (Buffering & Decoupling)",
		},
	})
}

func (c *ConfigController) SaveAlertThresholds(ctx *gin.Context) {
	var payload struct {
		PortScanThreshold uint64 `json:"port_scan_threshold"`
		SilenceMinutes    int    `json:"silence_minutes"`
	}
	if err := ctx.ShouldBindJSON(&payload); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Invalid payload: " + err.Error()})
		return
	}
	if c.alertEngine != nil {
		c.alertEngine.SetConfig(payload.PortScanThreshold, payload.SilenceMinutes)
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "Alert thresholds updated successfully"})
}

// 5. SNMP Device Details & Interface Management Handlers

func (c *ConfigController) ProbeSNMPDeviceName(ctx *gin.Context) {
	var req struct {
		ExporterIP string `json:"exporter_ip"`
	}
	if err := ctx.ShouldBindJSON(&req); err != nil || strings.TrimSpace(req.ExporterIP) == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "exporter_ip is required"})
		return
	}
	ip := strings.TrimSpace(req.ExporterIP)
	if c.syncer != nil {
		if err := c.syncer.SyncDevice(ctx.Request.Context(), ip); err != nil {
			ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "从 LibreNMS 同步设备失败: " + err.Error()})
			return
		}
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: fmt.Sprintf("设备 %s 已成功通过 LibreNMS 同步入库", ip),
	})
}

func (c *ConfigController) GetDeviceInterfaces(ctx *gin.Context) {
	ip := ctx.Param("ip")
	if ip == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "ip parameter is required"})
		return
	}
	interfaces, err := c.repo.GetDeviceInterfaces(ctx.Request.Context(), ip)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: interfaces})
}

func (c *ConfigController) SaveDeviceInterface(ctx *gin.Context) {
	var item model.DeviceInterface
	if err := ctx.ShouldBindJSON(&item); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "Invalid payload: " + err.Error()})
		return
	}
	if item.ExporterIP == "" || item.IfIndex == 0 {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "exporter_ip and if_index are required"})
		return
	}
	if err := c.repo.SaveDeviceInterface(ctx.Request.Context(), item); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "接口定义已保存生效"})
}

func (c *ConfigController) SnmpWalkInterfaces(ctx *gin.Context) {
	var req struct {
		ExporterIP string `json:"exporter_ip"`
	}
	if err := ctx.ShouldBindJSON(&req); err != nil || strings.TrimSpace(req.ExporterIP) == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "exporter_ip is required"})
		return
	}
	ip := strings.TrimSpace(req.ExporterIP)
	if c.syncer != nil {
		if err := c.syncer.SyncDevice(ctx.Request.Context(), ip); err != nil {
			ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "从 LibreNMS 同步设备失败: " + err.Error()})
			return
		}
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: fmt.Sprintf("设备 %s 端口与描述已成功通过 LibreNMS 同步", ip),
	})
}

func (c *ConfigController) SnmpSyncAllExporters(ctx *gin.Context) {
	c.SyncAllFromLibreNMS(ctx)
}

// 6. Dedicated LibreNMS Handlers

func (c *ConfigController) GetLibreNMSStatus(ctx *gin.Context) {
	if c.libreClient == nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 5001, Message: "LibreNMS 客户端未初始化"})
		return
	}
	info, err := c.libreClient.GetSystemInfo(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{
			Code:    5002,
			Message: "LibreNMS 连接探测失败: " + err.Error(),
			Data:    gin.H{"connected": false, "error": err.Error()},
		})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "LibreNMS 连接正常",
		Data: gin.H{
			"connected": true,
			"info":      info,
		},
	})
}

func (c *ConfigController) SyncAllFromLibreNMS(ctx *gin.Context) {
	if c.syncer == nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 5001, Message: "Syncer 未初始化"})
		return
	}

	count, err := c.syncer.SyncAllRegisteredDevices(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "从 LibreNMS 同步失败: " + err.Error()})
		return
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: fmt.Sprintf("已成功从 LibreNMS 批量同步了 %d 台网络资产设备与全部端口信息", count),
		Data: gin.H{
			"total_synced": count,
		},
	})
}

func (c *ConfigController) SyncDeviceFromLibreNMS(ctx *gin.Context) {
	ip := ctx.Param("ip")
	if ip == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "ip is required"})
		return
	}
	if c.syncer == nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: "Syncer 未初始化"})
		return
	}
	if err := c.syncer.SyncDevice(ctx.Request.Context(), ip); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "从 LibreNMS 同步失败: " + err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: fmt.Sprintf("已成功从 LibreNMS 同步设备 %s 及其端口信息", ip)})
}

// 7. Third-Party API Settings Handlers
func (c *ConfigController) GetApiSettings(ctx *gin.Context) {
	configs, err := c.repo.GetSystemConfigs(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "success",
		Data: model.ApiSettings{
			LibreNMSURL:      configs["librenms_url"],
			LibreNMSToken:    configs["librenms_token"],
			NetBoxURL:        configs["netbox_url"],
			NetBoxToken:      configs["netbox_token"],
			LdapEnabled:      configs["ldap_enabled"] == "true",
			LdapURL:          configs["ldap_url"],
			LdapBaseDN:       configs["ldap_base_dn"],
			LdapBindDN:       configs["ldap_bind_dn"],
			LdapBindPassword: configs["ldap_bind_password"],
			LdapUserFilter:   configs["ldap_user_filter"],
			LdapDefaultRole:  configs["ldap_default_role"],
		},
	})
}

func (c *ConfigController) SaveApiSettings(ctx *gin.Context) {
	var req model.ApiSettings
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: err.Error()})
		return
	}

	configs := map[string]string{
		"librenms_url":       strings.TrimSpace(req.LibreNMSURL),
		"librenms_token":     strings.TrimSpace(req.LibreNMSToken),
		"netbox_url":         strings.TrimSpace(req.NetBoxURL),
		"netbox_token":       strings.TrimSpace(req.NetBoxToken),
		"ldap_enabled":       strconv.FormatBool(req.LdapEnabled),
		"ldap_url":           strings.TrimSpace(req.LdapURL),
		"ldap_base_dn":       strings.TrimSpace(req.LdapBaseDN),
		"ldap_bind_dn":       strings.TrimSpace(req.LdapBindDN),
		"ldap_bind_password": req.LdapBindPassword,
		"ldap_user_filter":   strings.TrimSpace(req.LdapUserFilter),
		"ldap_default_role":  strings.TrimSpace(req.LdapDefaultRole),
	}

	if err := c.repo.SaveSystemConfigs(ctx.Request.Context(), configs); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "保存配置失败: " + err.Error()})
		return
	}

	// Hot reload in-memory clients immediately
	if c.libreClient != nil && req.LibreNMSURL != "" {
		c.libreClient.UpdateConfig(req.LibreNMSURL, req.LibreNMSToken)
	}
	if c.netboxClient != nil && req.NetBoxURL != "" {
		c.netboxClient.UpdateConfig(req.NetBoxURL, req.NetBoxToken)
	}
	if c.ldapClient != nil {
		c.ldapClient.UpdateConfig(&model.LdapSettings{
			Enabled:      req.LdapEnabled,
			URL:          req.LdapURL,
			BaseDN:       req.LdapBaseDN,
			BindDN:       req.LdapBindDN,
			BindPassword: req.LdapBindPassword,
			UserFilter:   req.LdapUserFilter,
			DefaultRole:  req.LdapDefaultRole,
		})
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "第三方 API 与域认证配置已成功保存并即时生效",
		Data:    req,
	})
}

func (c *ConfigController) TestLibreNMS(ctx *gin.Context) {
	var req struct {
		URL   string `json:"url"`
		Token string `json:"token"`
	}
	_ = ctx.ShouldBindJSON(&req)

	client := c.libreClient
	if req.URL != "" && req.Token != "" {
		client = librenms.NewClient(req.URL, req.Token)
	}
	if client == nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "LibreNMS 未配置"})
		return
	}

	info, err := client.GetSystemInfo(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{
			Code:    5002,
			Message: "LibreNMS 连接探测失败: " + err.Error(),
			Data:    gin.H{"connected": false, "error": err.Error()},
		})
		return
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "LibreNMS API 连接探测成功",
		Data: gin.H{
			"connected": true,
			"info":      info,
		},
	})
}

func (c *ConfigController) TestNetBox(ctx *gin.Context) {
	var req struct {
		URL   string `json:"url"`
		Token string `json:"token"`
	}
	_ = ctx.ShouldBindJSON(&req)

	client := c.netboxClient
	if req.URL != "" && req.Token != "" {
		client = netbox.NewClient(req.URL, req.Token)
	}
	if client == nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "NetBox 未配置"})
		return
	}

	res, err := client.TestConnection(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{
			Code:    5002,
			Message: "NetBox 连接探测失败: " + err.Error(),
			Data:    gin.H{"connected": false, "error": err.Error()},
		})
		return
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: fmt.Sprintf("NetBox API 连接正常 (纳管 IP 资产数: %v)", res["total_ips"]),
		Data: gin.H{
			"connected": true,
			"details":   res,
		},
	})
}

func (c *ConfigController) TestLDAP(ctx *gin.Context) {
	var req model.LdapTestReq
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "参数错误: " + err.Error()})
		return
	}
	if req.URL == "" && c.ldapClient != nil {
		cur := c.ldapClient.GetConfig()
		req.URL = cur.URL
		req.BaseDN = cur.BaseDN
		req.BindDN = cur.BindDN
		req.BindPassword = cur.BindPassword
		req.UserFilter = cur.UserFilter
	}
	if req.URL == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "LDAP 服务器 URL 不能为空"})
		return
	}

	client := c.ldapClient
	if client == nil {
		client = auth.NewLDAPClient(nil)
	}

	latency, msg, err := client.TestConnection(&req)
	if err != nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{
			Code:    5002,
			Message: "LDAP 连接探测失败: " + err.Error(),
			Data:    gin.H{"connected": false, "error": err.Error()},
		})
		return
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: fmt.Sprintf("%s (耗时: %dms)", msg, latency),
		Data: gin.H{
			"connected":  true,
			"latency_ms": latency,
		},
	})
}

// 1b. 32-bit Host Handlers & NetBox Sync
func (c *ConfigController) GetIPHosts(ctx *gin.Context) {
	page, _ := strconv.Atoi(ctx.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(ctx.DefaultQuery("page_size", "50"))
	req := model.IPHostQueryRequest{
		Keyword:  ctx.Query("keyword"),
		Source:   ctx.Query("source"),
		Page:     page,
		PageSize: pageSize,
	}

	res, err := c.repo.GetIPHosts(ctx.Request.Context(), req)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}

	if c.netboxSyncer != nil {
		status := c.netboxSyncer.GetStatus()
		res.SyncStatus = &status
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: res})
}

func (c *ConfigController) SaveIPHost(ctx *gin.Context) {
	var host model.IPHost
	if err := ctx.ShouldBindJSON(&host); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "参数错误: " + err.Error()})
		return
	}

	host.IP = strings.TrimSpace(host.IP)
	host.Hostname = strings.TrimSpace(host.Hostname)
	host.DNSName = strings.TrimSpace(host.DNSName)
	host.Description = strings.TrimSpace(host.Description)

	if host.IP == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "IP 地址不能为空"})
		return
	}

	if host.Source == "" {
		host.Source = "Local"
	}

	if err := c.repo.SaveIPHost(ctx.Request.Context(), host); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}

	if c.resolver != nil {
		_ = c.resolver.Reload(ctx.Request.Context(), c.repo)
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "主机记录已成功保存", Data: host})
}

func (c *ConfigController) DeleteIPHost(ctx *gin.Context) {
	ip := strings.TrimSpace(ctx.Param("ip"))
	if ip == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "IP 参数不能为空"})
		return
	}

	if err := c.repo.DeleteIPHost(ctx.Request.Context(), ip); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5003, Message: err.Error()})
		return
	}

	if c.resolver != nil {
		_ = c.resolver.Reload(ctx.Request.Context(), c.repo)
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "主机记录已成功删除"})
}

func (c *ConfigController) GetNetboxSyncStatus(ctx *gin.Context) {
	if c.netboxSyncer == nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "未启用 NetBox 同步器", Data: model.NetboxSyncStatus{}})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: c.netboxSyncer.GetStatus()})
}

func (c *ConfigController) TriggerNetboxSync(ctx *gin.Context) {
	if c.netboxSyncer == nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4004, Message: "NetBox 同步器未初始化"})
		return
	}

	go func() {
		_ = c.netboxSyncer.SyncNow(context.Background())
	}()

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "已触发 NetBox 全量同步任务，正在后台高速拉取并写入本地数据库...",
		Data:    c.netboxSyncer.GetStatus(),
	})
}

// 7. System Services & Health Inspection Handlers
func (c *ConfigController) GetServicesStatus(ctx *gin.Context) {
	if c.sysMgr == nil {
		ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "系统服务管理器未启用", Data: []model.ManagedService{}})
		return
	}
	services, err := c.sysMgr.GetServicesStatus(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: services})
}

func (c *ConfigController) RestartService(ctx *gin.Context) {
	if c.sysMgr == nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4004, Message: "系统服务管理器未启用"})
		return
	}
	var req model.RestartServiceRequest
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "无效的请求格式: " + err.Error()})
		return
	}
	msg, err := c.sysMgr.RestartService(ctx.Request.Context(), req.ServiceID)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: msg})
}

func (c *ConfigController) RunSystemInspection(ctx *gin.Context) {
	if c.sysMgr == nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4004, Message: "系统服务管理器未启用"})
		return
	}
	report, err := c.sysMgr.RunInspection(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5003, Message: err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: report})
}

// 8. Account Management & Unified Configuration Export/Import Handlers

func (c *ConfigController) GetUsers(ctx *gin.Context) {
	users, err := c.repo.GetAllUsers(ctx.Request.Context())
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: err.Error()})
		return
	}
	// Strip password_hash for normal UI display
	safeUsers := make([]model.UserConfigItem, len(users))
	for i, u := range users {
		safeUsers[i] = model.UserConfigItem{
			Username:    u.Username,
			DisplayName: u.DisplayName,
			Role:        u.Role,
			AuthType:    u.AuthType,
		}
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "success", Data: safeUsers})
}

func (c *ConfigController) SaveUserAccount(ctx *gin.Context) {
	var req model.UserConfigItem
	if err := ctx.ShouldBindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "请求格式错误: " + err.Error()})
		return
	}
	req.Username = strings.TrimSpace(req.Username)
	req.DisplayName = strings.TrimSpace(req.DisplayName)
	if req.Username == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4002, Message: "用户名不能为空"})
		return
	}
	if req.DisplayName == "" {
		req.DisplayName = req.Username
	}
	if req.Role == "" {
		req.Role = "admin"
	}
	if req.AuthType == "" {
		req.AuthType = "local"
	}

	pwdHash := req.PasswordHash
	if req.Password != "" {
		hashed, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
		if err != nil {
			ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5001, Message: "密码加密失败: " + err.Error()})
			return
		}
		pwdHash = string(hashed)
	} else if pwdHash == "" {
		if existing, err := c.repo.GetUser(ctx.Request.Context(), req.Username); err == nil && existing != nil && existing.PasswordHash != "" {
			pwdHash = existing.PasswordHash
		} else {
			hashed, _ := bcrypt.GenerateFromPassword([]byte("admin"), bcrypt.DefaultCost)
			pwdHash = string(hashed)
		}
	}

	u := &model.SystemUser{
		Username:     req.Username,
		PasswordHash: pwdHash,
		DisplayName:  req.DisplayName,
		Role:         req.Role,
		AuthType:     req.AuthType,
	}
	if err := c.repo.SaveUser(ctx.Request.Context(), u); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "保存账号失败: " + err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "账号配置已保存生效"})
}

func (c *ConfigController) DeleteUserAccount(ctx *gin.Context) {
	username := strings.TrimSpace(ctx.Param("username"))
	if username == "" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4001, Message: "用户名不能为空"})
		return
	}
	if username == "admin" {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{Code: 4003, Message: "系统内置超级管理员账号 admin 不可删除"})
		return
	}
	if err := c.repo.DeleteUser(ctx.Request.Context(), username); err != nil {
		ctx.JSON(http.StatusInternalServerError, model.ResponseEnvelope{Code: 5002, Message: "删除账号失败: " + err.Error()})
		return
	}
	ctx.JSON(http.StatusOK, model.ResponseEnvelope{Code: 0, Message: "账号已成功删除"})
}

// ExportConfigBundle handles GET /api/v1/config/export?sections=accounts,snmp_api,ipam
func (c *ConfigController) ExportConfigBundle(ctx *gin.Context) {
	rCtx := ctx.Request.Context()
	sectionsParam := strings.ToLower(strings.TrimSpace(ctx.DefaultQuery("sections", "accounts,snmp_api,ipam")))
	includeAll := sectionsParam == "" || sectionsParam == "all"
	hasSection := func(sec string) bool {
		if includeAll {
			return true
		}
		for _, part := range strings.Split(sectionsParam, ",") {
			if strings.TrimSpace(part) == sec {
				return true
			}
		}
		return false
	}

	sysConfigs, _ := c.repo.GetSystemConfigs(rCtx)
	if sysConfigs == nil {
		sysConfigs = map[string]string{}
	}

	bundle := model.ConfigBundle{
		Version:    "1.3",
		ExportedAt: time.Now().Format("2006-01-02 15:04:05"),
	}

	if hasSection("accounts") {
		users, _ := c.repo.GetAllUsers(rCtx)
		if users == nil {
			users = []model.UserConfigItem{}
		}
		defaultRole := sysConfigs["ldap_default_role"]
		if defaultRole == "" {
			defaultRole = "admin"
		}
		userFilter := sysConfigs["ldap_user_filter"]
		if userFilter == "" {
			userFilter = "(&(objectClass=user)(sAMAccountName=%s))"
		}
		bundle.Accounts = &model.AccountsConfigSection{
			Users:            users,
			LdapEnabled:      sysConfigs["ldap_enabled"] == "true",
			LdapURL:          sysConfigs["ldap_url"],
			LdapBaseDN:       sysConfigs["ldap_base_dn"],
			LdapBindDN:       sysConfigs["ldap_bind_dn"],
			LdapBindPassword: sysConfigs["ldap_bind_password"],
			LdapUserFilter:   userFilter,
			LdapDefaultRole:  defaultRole,
		}
	}

	if hasSection("snmp_api") {
		exporters, _ := c.repo.GetExporterDevices(rCtx)
		if exporters == nil {
			exporters = []model.ExporterDevice{}
		}
		interfaces, _ := c.repo.GetAllDeviceInterfaces(rCtx)
		if interfaces == nil {
			interfaces = []model.DeviceInterface{}
		}
		apps, _ := c.repo.GetAppMappings(rCtx)
		if apps == nil {
			apps = []model.AppMappingItem{}
		}
		var portScan uint64 = 100
		var silenceMin int = 5
		if c.alertEngine != nil {
			portScan, silenceMin = c.alertEngine.GetConfig()
		}
		bundle.SnmpApi = &model.SnmpApiConfigSection{
			LibreNMSURL:       sysConfigs["librenms_url"],
			LibreNMSToken:     sysConfigs["librenms_token"],
			NetBoxURL:         sysConfigs["netbox_url"],
			NetBoxToken:       sysConfigs["netbox_token"],
			PortScanThreshold: portScan,
			SilenceMinutes:    silenceMin,
			Exporters:         exporters,
			Interfaces:        interfaces,
			AppMappings:       apps,
		}
	}

	if hasSection("ipam") {
		subnets, _ := c.repo.GetBusinessGroups(rCtx)
		if subnets == nil {
			subnets = []model.BusinessGroup{}
		}
		hosts, _ := c.repo.GetAllIPHostsForExport(rCtx)
		if hosts == nil {
			hosts = []model.IPHost{}
		}
		bundle.Ipam = &model.IpamConfigSection{
			Subnets: subnets,
			Hosts:   hosts,
		}
	}

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: "配置文件导出成功",
		Data:    bundle,
	})
}

// ImportConfigBundle handles POST /api/v1/config/import
func (c *ConfigController) ImportConfigBundle(ctx *gin.Context) {
	rCtx := ctx.Request.Context()
	var bundle model.ConfigBundle
	if err := ctx.ShouldBindJSON(&bundle); err != nil {
		ctx.JSON(http.StatusBadRequest, model.ResponseEnvelope{
			Code:    4001,
			Message: "配置文件 JSON 格式解析失败: " + err.Error(),
		})
		return
	}

	sectionsParam := strings.ToLower(strings.TrimSpace(ctx.DefaultQuery("sections", "accounts,snmp_api,ipam")))
	includeAll := sectionsParam == "" || sectionsParam == "all"
	hasSection := func(sec string) bool {
		if includeAll {
			return true
		}
		for _, part := range strings.Split(sectionsParam, ",") {
			if strings.TrimSpace(part) == sec {
				return true
			}
		}
		return false
	}

	importedUsers := 0
	importedExporters := 0
	importedInterfaces := 0
	importedApps := 0
	importedSubnets := 0
	importedHosts := 0

	sysConfigsToSave := map[string]string{}

	// 1. Import Accounts & LDAP settings
	if bundle.Accounts != nil && hasSection("accounts") {
		acc := bundle.Accounts
		sysConfigsToSave["ldap_enabled"] = strconv.FormatBool(acc.LdapEnabled)
		sysConfigsToSave["ldap_url"] = strings.TrimSpace(acc.LdapURL)
		sysConfigsToSave["ldap_base_dn"] = strings.TrimSpace(acc.LdapBaseDN)
		sysConfigsToSave["ldap_bind_dn"] = strings.TrimSpace(acc.LdapBindDN)
		sysConfigsToSave["ldap_bind_password"] = acc.LdapBindPassword
		if strings.TrimSpace(acc.LdapUserFilter) != "" {
			sysConfigsToSave["ldap_user_filter"] = strings.TrimSpace(acc.LdapUserFilter)
		}
		if strings.TrimSpace(acc.LdapDefaultRole) != "" {
			sysConfigsToSave["ldap_default_role"] = strings.TrimSpace(acc.LdapDefaultRole)
		}

		if c.ldapClient != nil {
			c.ldapClient.UpdateConfig(&model.LdapSettings{
				Enabled:      acc.LdapEnabled,
				URL:          acc.LdapURL,
				BaseDN:       acc.LdapBaseDN,
				BindDN:       acc.LdapBindDN,
				BindPassword: acc.LdapBindPassword,
				UserFilter:   acc.LdapUserFilter,
				DefaultRole:  acc.LdapDefaultRole,
			})
		}

		for _, u := range acc.Users {
			uname := strings.TrimSpace(u.Username)
			if uname == "" {
				continue
			}
			pwdHash := strings.TrimSpace(u.PasswordHash)
			if u.Password != "" {
				if hashed, err := bcrypt.GenerateFromPassword([]byte(u.Password), bcrypt.DefaultCost); err == nil {
					pwdHash = string(hashed)
				}
			}
			if pwdHash == "" {
				if existing, err := c.repo.GetUser(rCtx, uname); err == nil && existing != nil && existing.PasswordHash != "" {
					pwdHash = existing.PasswordHash
				} else {
					hashed, _ := bcrypt.GenerateFromPassword([]byte("admin"), bcrypt.DefaultCost)
					pwdHash = string(hashed)
				}
			}
			dname := strings.TrimSpace(u.DisplayName)
			if dname == "" {
				dname = uname
			}
			role := strings.TrimSpace(u.Role)
			if role == "" {
				role = "admin"
			}
			authType := strings.TrimSpace(u.AuthType)
			if authType == "" {
				authType = "local"
			}
			if err := c.repo.SaveUser(rCtx, &model.SystemUser{
				Username:     uname,
				PasswordHash: pwdHash,
				DisplayName:  dname,
				Role:         role,
				AuthType:     authType,
			}); err == nil {
				importedUsers++
			}
		}
	}

	// 2. Import SNMP / API / Exporters / Interfaces / App Mappings
	if bundle.SnmpApi != nil && hasSection("snmp_api") {
		sa := bundle.SnmpApi
		if sa.LibreNMSURL != "" || sa.LibreNMSToken != "" {
			sysConfigsToSave["librenms_url"] = strings.TrimSpace(sa.LibreNMSURL)
			sysConfigsToSave["librenms_token"] = strings.TrimSpace(sa.LibreNMSToken)
			if c.libreClient != nil && sa.LibreNMSURL != "" {
				c.libreClient.UpdateConfig(sa.LibreNMSURL, sa.LibreNMSToken)
			}
		}
		if sa.NetBoxURL != "" || sa.NetBoxToken != "" {
			sysConfigsToSave["netbox_url"] = strings.TrimSpace(sa.NetBoxURL)
			sysConfigsToSave["netbox_token"] = strings.TrimSpace(sa.NetBoxToken)
			if c.netboxClient != nil && sa.NetBoxURL != "" {
				c.netboxClient.UpdateConfig(sa.NetBoxURL, sa.NetBoxToken)
			}
		}
		if sa.PortScanThreshold > 0 && sa.SilenceMinutes > 0 && c.alertEngine != nil {
			c.alertEngine.SetConfig(sa.PortScanThreshold, sa.SilenceMinutes)
		}

		for _, dev := range sa.Exporters {
			dev.ExporterIP = strings.TrimSpace(dev.ExporterIP)
			if dev.ExporterIP == "" {
				continue
			}
			if dev.DeviceName == "" {
				dev.DeviceName = dev.ExporterIP
			}
			if dev.DeviceType == "" {
				dev.DeviceType = "Switch"
			}
			if err := c.repo.SaveExporterDevice(rCtx, dev); err == nil {
				importedExporters++
			}
		}

		for _, iface := range sa.Interfaces {
			iface.ExporterIP = strings.TrimSpace(iface.ExporterIP)
			if iface.ExporterIP == "" || iface.IfIndex == 0 {
				continue
			}
			if err := c.repo.SaveDeviceInterface(rCtx, iface); err == nil {
				importedInterfaces++
			}
		}

		for _, app := range sa.AppMappings {
			if app.Port == 0 || strings.TrimSpace(app.AppName) == "" {
				continue
			}
			if app.Proto == 0 {
				app.Proto = 6
			}
			if err := c.repo.SaveAppMapping(rCtx, app); err == nil {
				importedApps++
			}
		}
	}

	if len(sysConfigsToSave) > 0 {
		_ = c.repo.SaveSystemConfigs(rCtx, sysConfigsToSave)
	}

	// 3. Import IPAM (Business Subnets & 32-bit IP Hosts)
	if bundle.Ipam != nil && hasSection("ipam") {
		ipam := bundle.Ipam
		for _, bg := range ipam.Subnets {
			bg.GroupName = strings.TrimSpace(bg.GroupName)
			bg.CIDR = strings.TrimSpace(bg.CIDR)
			if bg.GroupName == "" || bg.CIDR == "" {
				continue
			}
			if err := c.repo.SaveBusinessGroup(rCtx, bg); err == nil {
				importedSubnets++
			}
		}

		var validHosts []model.IPHost
		now := time.Now()
		for _, h := range ipam.Hosts {
			h.IP = strings.TrimSpace(h.IP)
			if h.IP == "" {
				continue
			}
			if h.Source == "" {
				h.Source = "Local"
			}
			if h.UpdatedAt.IsZero() {
				h.UpdatedAt = now
			}
			validHosts = append(validHosts, h)
		}
		if len(validHosts) > 0 {
			if err := c.repo.BatchSaveIPHosts(rCtx, validHosts); err == nil {
				importedHosts = len(validHosts)
			}
		}

		if c.resolver != nil {
			_ = c.resolver.Reload(rCtx, c.repo)
		}
	}

	summaryMsg := fmt.Sprintf(
		"配置导入成功并已热生效！账号: %d 个, 导出器设备: %d 台, 端口映射: %d 个, 应用协议: %d 条, 业务网段: %d 个, 主机IP: %d 条",
		importedUsers, importedExporters, importedInterfaces, importedApps, importedSubnets, importedHosts,
	)

	ctx.JSON(http.StatusOK, model.ResponseEnvelope{
		Code:    0,
		Message: summaryMsg,
		Data: gin.H{
			"imported_users":      importedUsers,
			"imported_exporters":  importedExporters,
			"imported_interfaces": importedInterfaces,
			"imported_apps":       importedApps,
			"imported_subnets":    importedSubnets,
			"imported_hosts":      importedHosts,
		},
	})
}


