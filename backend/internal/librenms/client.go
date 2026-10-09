package librenms

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// LibreDevice represents a device returned by LibreNMS API
type LibreDevice struct {
	DeviceID   int    `json:"device_id"`
	Hostname   string `json:"hostname"`
	IP         string `json:"ip"`
	SysName    string `json:"sysName"`
	SysDescr   string `json:"sysDescr"`
	SysContact string `json:"sysContact"`
	Location   string `json:"location"` // Normalized string location
	Hardware   string `json:"hardware"`
	OS         string `json:"os"`
	Type       string `json:"type"`
	Status     int    `json:"status"`
	Uptime     uint64 `json:"uptime"`
	Community  string `json:"community"`
	SNMPVer    string `json:"snmpver"`
}

// LibrePort represents an interface/port returned by LibreNMS API
type LibrePort struct {
	PortID          int     `json:"port_id"`
	IfIndex         uint32  `json:"ifIndex"`
	IfName          string  `json:"ifName"`
	IfDescr         string  `json:"ifDescr"`
	IfAlias         string  `json:"ifAlias"`
	IfSpeed         uint64  `json:"ifSpeed"` // bps
	IfType          string  `json:"ifType"`
	IfInOctetsRate  float64 `json:"ifInOctets_rate"`  // Bytes/sec
	IfOutOctetsRate float64 `json:"ifOutOctets_rate"` // Bytes/sec
}

type Client struct {
	baseURL    string
	token      string
	httpClient *http.Client
	mu         sync.RWMutex
}

func NewClient(rawURL, token string) *Client {
	// Normalize URL
	trimmed := strings.TrimRight(rawURL, "/")
	return &Client{
		baseURL: trimmed,
		token:   token,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// UpdateConfig updates baseURL and token safely at runtime
func (c *Client) UpdateConfig(rawURL, token string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.baseURL = strings.TrimRight(rawURL, "/")
	c.token = strings.TrimSpace(token)
	log.Printf("[*] LibreNMS Client configuration updated: %s", c.baseURL)
}

// GetConfig returns current baseURL and token
func (c *Client) GetConfig() (string, string) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.baseURL, c.token
}

// doRequest performs HTTP request with auth header and automatic HTTPS -> HTTP fallback
func (c *Client) doRequest(ctx context.Context, endpoint string) ([]byte, error) {
	c.mu.RLock()
	currentBase := c.baseURL
	currentToken := c.token
	c.mu.RUnlock()

	makeReq := func(base string) ([]byte, int, error) {
		reqURL := base + endpoint
		req, err := http.NewRequestWithContext(ctx, "GET", reqURL, nil)
		if err != nil {
			return nil, 0, err
		}
		req.Header.Set("X-Auth-Token", currentToken)
		req.Header.Set("Accept", "application/json")

		resp, err := c.httpClient.Do(req)
		if err != nil {
			return nil, 0, err
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		return body, resp.StatusCode, err
	}

	body, statusCode, err := makeReq(currentBase)
	if err != nil {
		// If currentBase is https, try falling back to http
		if strings.HasPrefix(currentBase, "https://") {
			fallbackBase := strings.Replace(currentBase, "https://", "http://", 1)
			bodyFallback, codeFallback, errFallback := makeReq(fallbackBase)
			if errFallback == nil && codeFallback == http.StatusOK {
				// Update base URL to the working one
				c.mu.Lock()
				c.baseURL = fallbackBase
				c.mu.Unlock()
				return bodyFallback, nil
			}
		}
		return nil, fmt.Errorf("LibreNMS request error to %s: %w", currentBase+endpoint, err)
	}

	if statusCode != http.StatusOK {
		return nil, fmt.Errorf("LibreNMS HTTP error %d: %s", statusCode, string(body))
	}

	return body, nil
}

// GetSystemInfo checks connectivity to LibreNMS
func (c *Client) GetSystemInfo(ctx context.Context) (map[string]interface{}, error) {
	body, err := c.doRequest(ctx, "/system")
	if err != nil {
		return nil, err
	}

	var res struct {
		Status string                   `json:"status"`
		System []map[string]interface{} `json:"system"`
		Count  int                      `json:"count"`
	}
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, err
	}

	info := map[string]interface{}{
		"status":   res.Status,
		"base_url": c.baseURL,
		"count":    res.Count,
	}
	if len(res.System) > 0 {
		info["details"] = res.System[0]
	}
	return info, nil
}

// GetAllDevices retrieves all devices from LibreNMS
func (c *Client) GetAllDevices(ctx context.Context) ([]LibreDevice, error) {
	body, err := c.doRequest(ctx, "/devices")
	if err != nil {
		return nil, err
	}

	var res struct {
		Status  string            `json:"status"`
		Devices []json.RawMessage `json:"devices"`
	}
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, err
	}

	devices := make([]LibreDevice, 0, len(res.Devices))
	for _, raw := range res.Devices {
		dev, err := parseLibreDevice(raw)
		if err == nil {
			devices = append(devices, *dev)
		}
	}
	return devices, nil
}

// GetDeviceByIP finds a device by IP or hostname
func (c *Client) GetDeviceByIP(ctx context.Context, ip string) (*LibreDevice, error) {
	// First try direct device query: /devices/{ip}
	endpoint := fmt.Sprintf("/devices/%s", url.PathEscape(ip))
	body, err := c.doRequest(ctx, endpoint)
	if err == nil {
		var res struct {
			Status  string            `json:"status"`
			Devices []json.RawMessage `json:"devices"`
		}
		if err := json.Unmarshal(body, &res); err == nil && len(res.Devices) > 0 {
			return parseLibreDevice(res.Devices[0])
		}
	}

	// Fallback: search in all devices
	all, err := c.GetAllDevices(ctx)
	if err != nil {
		return nil, err
	}

	for _, d := range all {
		if d.IP == ip || d.Hostname == ip {
			return &d, nil
		}
	}

	// Check if IP is contained in hostname or vice versa
	for _, d := range all {
		if strings.Contains(d.Hostname, ip) || strings.Contains(d.IP, ip) {
			return &d, nil
		}
	}

	return nil, fmt.Errorf("device %s not found in LibreNMS", ip)
}

// GetDevicePorts queries ports for a device (by device_id or IP)
func (c *Client) GetDevicePorts(ctx context.Context, deviceIdOrIP string) ([]LibrePort, error) {
	endpoint := fmt.Sprintf("/devices/%s/ports?columns=port_id,ifIndex,ifName,ifDescr,ifAlias,ifSpeed,ifType,ifInOctets_rate,ifOutOctets_rate", url.PathEscape(deviceIdOrIP))
	body, err := c.doRequest(ctx, endpoint)
	if err != nil {
		return nil, err
	}

	var res struct {
		Status string      `json:"status"`
		Ports  []LibrePort `json:"ports"`
	}
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, err
	}

	return res.Ports, nil
}

// parseLibreDevice handles polymorphic location (string or object)
func parseLibreDevice(raw []byte) (*LibreDevice, error) {
	// Temporary map to extract raw fields
	var m map[string]interface{}
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, err
	}

	dev := &LibreDevice{}
	if id, ok := m["device_id"].(float64); ok {
		dev.DeviceID = int(id)
	}
	if v, ok := m["hostname"].(string); ok {
		dev.Hostname = v
	}
	if v, ok := m["ip"].(string); ok {
		dev.IP = v
	}
	if dev.IP == "" {
		dev.IP = dev.Hostname
	}
	if v, ok := m["sysName"].(string); ok {
		dev.SysName = v
	}
	if v, ok := m["sysDescr"].(string); ok {
		dev.SysDescr = v
	}
	if v, ok := m["sysContact"].(string); ok {
		dev.SysContact = v
	}
	if v, ok := m["hardware"].(string); ok {
		dev.Hardware = v
	}
	if v, ok := m["os"].(string); ok {
		dev.OS = v
	}
	if v, ok := m["type"].(string); ok {
		dev.Type = v
	}
	if v, ok := m["community"].(string); ok {
		dev.Community = v
	}
	if v, ok := m["snmpver"].(string); ok {
		dev.SNMPVer = v
	}
	if st, ok := m["status"].(float64); ok {
		dev.Status = int(st)
	}
	if ut, ok := m["uptime"].(float64); ok {
		dev.Uptime = uint64(ut)
	}

	// Handle location (can be string or {"id": 44, "location": "SHOffice"})
	if locVal, ok := m["location"]; ok && locVal != nil {
		switch l := locVal.(type) {
		case string:
			dev.Location = l
		case map[string]interface{}:
			if strLoc, ok := l["location"].(string); ok {
				dev.Location = strLoc
			}
		}
	}

	return dev, nil
}
