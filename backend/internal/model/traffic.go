package model

import "time"

// TrendRequest represents the query parameters for traffic bandwidth trends
type TrendRequest struct {
	StartTime   string `json:"start_time"`   // YYYY-MM-DD HH:MM:SS or RFC3339
	EndTime     string `json:"end_time"`     // YYYY-MM-DD HH:MM:SS or RFC3339
	SrcIP       string `json:"src_ip"`       // IP or CIDR (e.g. 192.168.0.0/16)
	DstIP       string `json:"dst_ip"`       // IP or CIDR
	Port        int    `json:"port"`         // Port filter
	Proto       string `json:"proto"`        // tcp, udp, icmp or number
	ExporterIP  string `json:"exporter_ip"`  // Switch or firewall IP
	IfIndex     uint32 `json:"if_index"`     // Specific interface filter
	Direction   string `json:"direction"`    // "inbound", "outbound", "all"
	StepSeconds int    `json:"step_seconds"` // Aggregation step in seconds
}

// TrendPoint represents a single data point in bandwidth time series
type TrendPoint struct {
	Timestamp string  `json:"timestamp"`
	TxBps     float64 `json:"tx_bps"`    // Outbound Bandwidth bits per sec
	RxBps     float64 `json:"rx_bps"`    // Inbound Bandwidth bits per sec
	TotalBps  float64 `json:"total_bps"` // Combined Bandwidth bits per sec
	Pps       float64 `json:"pps"`       // Packets per sec
	Flows     uint64  `json:"flows"`     // Flow count in this bucket
}

// TrendResponse returns trend time series along with summary stats & P95
type TrendResponse struct {
	DataSource  string       `json:"data_source"` // "flows_raw" or "flows_5m"
	Points      []TrendPoint `json:"points"`
	TotalBytes  uint64       `json:"total_bytes"`
	TotalFlows  uint64       `json:"total_flows"`
	P95Bps      float64      `json:"p95_bps"`      // 95th Percentile Bandwidth
	MaxBps      float64      `json:"max_bps"`      // Peak Bandwidth
	AvgBps      float64      `json:"avg_bps"`      // Average Bandwidth
	QueryTimeMs float64      `json:"query_time_ms"`
}

// TopNRequest queries top talkers by various dimensions
type TopNRequest struct {
	StartTime  string `json:"start_time"`
	EndTime    string `json:"end_time"`
	Dimension  string `json:"dimension"` // "ip", "port", "app", "business_group"
	Direction  string `json:"direction"` // "inbound", "outbound", "all"
	SrcIP      string `json:"src_ip"`
	DstIP      string `json:"dst_ip"`
	ExporterIP string `json:"exporter_ip"`
	Limit      int    `json:"limit"` // Top N (default 10)
}

// TopNItem represents one row of aggregated top statistics
type TopNItem struct {
	Key        string  `json:"key"`        // IP / Port / App Name / Group Name
	Label      string  `json:"label"`      // Friendly display label
	Hostname   string  `json:"hostname,omitempty"` // NetBox resolved hostname
	Bytes      uint64  `json:"bytes"`      // Volume in bytes
	Formatted  string  `json:"formatted"`  // e.g. "1.25 GB"
	Flows      uint64  `json:"flows"`
	Percentage float64 `json:"percentage"` // % of total queried traffic
}

// TopNResponse returns top N aggregated items
type TopNResponse struct {
	DataSource  string     `json:"data_source"`
	Items       []TopNItem `json:"items"`
	TotalBytes  uint64     `json:"total_bytes"`
	QueryTimeMs float64    `json:"query_time_ms"`
}

// SankeyRequest queries end-to-end flow paths
type SankeyRequest struct {
	StartTime  string `json:"start_time"`
	EndTime    string `json:"end_time"`
	SrcIP      string `json:"src_ip"`
	DstIP      string `json:"dst_ip"`
	Port       int    `json:"port"`
	Direction  string `json:"direction"`
	ExporterIP string `json:"exporter_ip"`
	Limit      int    `json:"limit"`
}

// SankeyNode represents a node in Sankey graph
type SankeyNode struct {
	Name string `json:"name"`
}

// SankeyLink represents a directed edge with traffic weight
type SankeyLink struct {
	Source string `json:"source"`
	Target string `json:"target"`
	Value  uint64 `json:"value"` // Bytes transferred
}

// SankeyResponse returns nodes and links for ECharts Sankey series
type SankeyResponse struct {
	Nodes       []SankeyNode `json:"nodes"`
	Links       []SankeyLink `json:"links"`
	QueryTimeMs float64      `json:"query_time_ms"`
}

// Common JSON API envelope
type ResponseEnvelope struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data"`
}

// TimeRangeHelper calculates duration
func ParseTimeSpan(startStr, endStr string) (time.Time, time.Time, time.Duration) {
	now := time.Now()
	startTime := now.Add(-1 * time.Hour)
	endTime := now

	if startStr != "" {
		if t, err := time.Parse("2006-01-02 15:04:05", startStr); err == nil {
			startTime = t
		} else if t, err := time.Parse(time.RFC3339, startStr); err == nil {
			startTime = t
		}
	}
	if endStr != "" {
		if t, err := time.Parse("2006-01-02 15:04:05", endStr); err == nil {
			endTime = t
		} else if t, err := time.Parse(time.RFC3339, endStr); err == nil {
			endTime = t
		}
	}
	return startTime, endTime, endTime.Sub(startTime)
}

// Configuration Models

type BusinessGroup struct {
	GroupID    uint32 `json:"group_id"`
	GroupName  string `json:"group_name"`
	CIDR       string `json:"cidr"`
	Department string `json:"department"`
	Source     string `json:"source"` // 'Netbox' or 'Local'
}

type AppMappingItem struct {
	Proto    uint8  `json:"proto"`
	Port     uint16 `json:"port"`
	AppName  string `json:"app_name"`
	Category string `json:"category"`
}

type ExporterDevice struct {
	ExporterIP    string `json:"exporter_ip"`
	DeviceName    string `json:"device_name"`
	DeviceType    string `json:"device_type"`
	Description   string `json:"description"`
	Location      string `json:"location"`
	Admin         string `json:"admin"`
	SNMPCommunity string `json:"snmp_community"`
	SNMPVersion   string `json:"snmp_version"`
}

type SubnetSummaryItem struct {
	GroupID        uint32  `json:"group_id"`
	GroupName      string  `json:"group_name"`
	CIDR           string  `json:"cidr"`
	Department     string  `json:"department"`
	Source         string  `json:"source"` // 'Netbox' or 'Local'
	Bytes          uint64  `json:"bytes"`
	FormattedBytes string  `json:"formatted_bytes"`
	Flows          uint64  `json:"flows"`
	ActiveIPCount  uint32  `json:"active_ip_count"`
	Percentage     float64 `json:"percentage"`
}

// IPHost models a 32-bit Host IP entry (from NetBox or Local)
type IPHost struct {
	IP          string    `json:"ip"`
	Hostname    string    `json:"hostname"`
	DNSName     string    `json:"dns_name"`
	Description string    `json:"description"`
	Source      string    `json:"source"` // 'Netbox' or 'Local'
	UpdatedAt   time.Time `json:"updated_at"`
}

// IPHostQueryRequest models query parameters for IP hosts
type IPHostQueryRequest struct {
	Keyword  string `json:"keyword"`
	Source   string `json:"source"` // 'all', 'Netbox', 'Local'
	Page     int    `json:"page"`
	PageSize int    `json:"page_size"`
}

// IPHostQueryResponse models paginated response for IP hosts
type IPHostQueryResponse struct {
	Total          int64             `json:"total"`
	Items          []IPHost          `json:"items"`
	TotalNetboxIPs int64             `json:"total_netbox_ips"`
	TotalLocalIPs  int64             `json:"total_local_ips"`
	SyncStatus     *NetboxSyncStatus `json:"sync_status,omitempty"`
}

// NetboxSyncStatus models the status and metrics of Netbox synchronization
type NetboxSyncStatus struct {
	LastSyncTime   string `json:"last_sync_time"`
	LastSyncStatus string `json:"last_sync_status"`
	TotalNetboxIPs int    `json:"total_netbox_ips"`
	TotalLocalIPs  int    `json:"total_local_ips"`
	IsSyncing      bool   `json:"is_syncing"`
}

type AlertConfig struct {
	PortScanThreshold uint64 `json:"port_scan_threshold"`
	SilenceMinutes    int    `json:"silence_minutes"`
}

type DeviceInterface struct {
	ExporterIP  string `json:"exporter_ip"`
	IfIndex     uint32 `json:"if_index"`
	IfName      string `json:"if_name"`
	IfDescr     string `json:"if_descr"`
	IfAlias     string `json:"if_alias"`
	DisplayName string `json:"display_name"`
	SpeedMbps   uint32 `json:"speed_mbps"`
	UpdatedAt   string `json:"updated_at,omitempty"`
}

type DeviceSNMPDetails struct {
	ExporterIP  string `json:"exporter_ip"`
	SysName     string `json:"sys_name"`
	SysDescr    string `json:"sys_descr"`
	SysUpTime   string `json:"sys_uptime"`
	SysContact  string `json:"sys_contact"`
	SysLocation string `json:"sys_location"`
	DeviceType  string `json:"device_type"`
}

// SessionRequest queries individual flow sessions for a specific device/interface
type SessionRequest struct {
	StartTime  string `json:"start_time"`
	EndTime    string `json:"end_time"`
	ExporterIP string `json:"exporter_ip"`
	IfIndex    uint32 `json:"if_index"`
	Direction  string `json:"direction"` // "all", "inbound", "outbound"
	SrcIP      string `json:"src_ip"`     // Host A
	DstIP      string `json:"dst_ip"`     // Host B
	App        string `json:"app"`        // App name filter
	Port       int    `json:"port"`
	Proto      string `json:"proto"`
	Limit      int    `json:"limit"`
	Offset     int    `json:"offset"`
}

// SessionItem represents a detailed communication flow session
type SessionItem struct {
	FirstSwitched  string  `json:"first_switched"`
	LastSwitched   string  `json:"last_switched"`
	DurationSec    uint32  `json:"duration_sec"`
	Bps            float64 `json:"bps"`
	FormattedRate  string  `json:"formatted_rate"`
	SrcIP          string  `json:"src_ip"`
	DstIP          string  `json:"dst_ip"`
	SrcHostname    string  `json:"src_hostname,omitempty"`
	DstHostname    string  `json:"dst_hostname,omitempty"`
	SrcPort        uint16  `json:"src_port"`
	DstPort        uint16  `json:"dst_port"`
	Proto          string  `json:"proto"` // "TCP", "UDP", "ICMP", etc.
	AppName        string  `json:"app_name"`
	Direction      string  `json:"direction"` // "inbound" or "outbound" relative to interface
	InIf           uint32  `json:"in_if"`
	OutIf          uint32  `json:"out_if"`
	InIfName       string  `json:"in_if_name"`
	OutIfName      string  `json:"out_if_name"`
	Bytes          uint64  `json:"bytes"`
	FormattedBytes string  `json:"formatted_bytes"`
	Packets        uint64  `json:"packets"`
	ExporterIP     string  `json:"exporter_ip"`
}

// ApiSettings represents third-party platform API configurations
type ApiSettings struct {
	LibreNMSURL      string `json:"librenms_url"`
	LibreNMSToken    string `json:"librenms_token"`
	NetBoxURL        string `json:"netbox_url"`
	NetBoxToken      string `json:"netbox_token"`
	LdapEnabled      bool   `json:"ldap_enabled"`
	LdapURL          string `json:"ldap_url"`
	LdapBaseDN       string `json:"ldap_base_dn"`
	LdapBindDN       string `json:"ldap_bind_dn"`
	LdapBindPassword string `json:"ldap_bind_password"`
	LdapUserFilter   string `json:"ldap_user_filter"`
	LdapDefaultRole  string `json:"ldap_default_role"`
}

// SessionResponse returns paginated session items
type SessionResponse struct {
	TotalCount  uint64        `json:"total_count"`
	Items       []SessionItem `json:"items"`
	QueryTimeMs float64       `json:"query_time_ms"`
	TimeClipped bool          `json:"time_clipped,omitempty"`
	Notice      string        `json:"notice,omitempty"`
}

// DeviceInterfaceStat represents interface sampling status & bandwidth
type DeviceInterfaceStat struct {
	IfIndex        uint32  `json:"if_index"`
	IfName         string  `json:"if_name"`
	DisplayName    string  `json:"display_name"`
	SpeedMbps      uint32  `json:"speed_mbps"`
	HasFlow        bool    `json:"has_flow"`
	RxBps          float64 `json:"rx_bps"`
	TxBps          float64 `json:"tx_bps"`
	TotalBytes     uint64  `json:"total_bytes"`
	FormattedBytes string  `json:"formatted_bytes"`
	FlowCount      uint64  `json:"flow_count"`
	LastSeen       string  `json:"last_seen"`
	LibreInBps     float64 `json:"libre_in_bps,omitempty"`
	LibreOutBps    float64 `json:"libre_out_bps,omitempty"`
}

// DeviceOverviewItem represents a network device with its sampling interfaces
type DeviceOverviewItem struct {
	ExporterIP      string                `json:"exporter_ip"`
	DeviceName      string                `json:"device_name"`
	DeviceType      string                `json:"device_type"`
	Location        string                `json:"location"`
	Admin           string                `json:"admin"`
	Description     string                `json:"description"`
	Status          string                `json:"status"` // "online", "sampling"
	TotalRxBps      float64               `json:"total_rx_bps"`
	TotalTxBps      float64               `json:"total_tx_bps"`
	TotalBytes      uint64                `json:"total_bytes"`
	TotalFlows      uint64                `json:"total_flows"`
	SamplingIfCount int                   `json:"sampling_if_count"`
	TotalIfCount    int                   `json:"total_if_count"`
	Interfaces      []DeviceInterfaceStat `json:"interfaces"`
}

// UserConfigItem represents an exported/imported user account record
type UserConfigItem struct {
	Username     string `json:"username"`
	DisplayName  string `json:"display_name"`
	Role         string `json:"role"`
	AuthType     string `json:"auth_type"`
	PasswordHash string `json:"password_hash,omitempty"`
	Password     string `json:"password,omitempty"` // Optional plaintext password on import
}

// AccountsConfigSection holds local user accounts and LDAP/AD settings
type AccountsConfigSection struct {
	Users            []UserConfigItem `json:"users"`
	LdapEnabled      bool             `json:"ldap_enabled"`
	LdapURL          string           `json:"ldap_url"`
	LdapBaseDN       string           `json:"ldap_base_dn"`
	LdapBindDN       string           `json:"ldap_bind_dn"`
	LdapBindPassword string           `json:"ldap_bind_password"`
	LdapUserFilter   string           `json:"ldap_user_filter"`
	LdapDefaultRole  string           `json:"ldap_default_role"`
}

// SnmpApiConfigSection holds SNMP exporter devices, interfaces, third-party APIs, app mappings, and alert thresholds
type SnmpApiConfigSection struct {
	LibreNMSURL       string            `json:"librenms_url"`
	LibreNMSToken     string            `json:"librenms_token"`
	NetBoxURL         string            `json:"netbox_url"`
	NetBoxToken       string            `json:"netbox_token"`
	PortScanThreshold uint64            `json:"port_scan_threshold"`
	SilenceMinutes    int               `json:"silence_minutes"`
	Exporters         []ExporterDevice  `json:"exporters"`
	Interfaces        []DeviceInterface `json:"interfaces"`
	AppMappings       []AppMappingItem  `json:"app_mappings"`
}

// IpamConfigSection holds subnet business groups and 32-bit IP host definitions
type IpamConfigSection struct {
	Subnets []BusinessGroup `json:"subnets"`
	Hosts   []IPHost        `json:"hosts"`
}

// ConfigBundle represents the unified export/import configuration file format
type ConfigBundle struct {
	Version    string                 `json:"version"`
	ExportedAt string                 `json:"exported_at"`
	Accounts   *AccountsConfigSection `json:"accounts,omitempty"`
	SnmpApi    *SnmpApiConfigSection  `json:"snmp_api,omitempty"`
	Ipam       *IpamConfigSection     `json:"ipam,omitempty"`
}


