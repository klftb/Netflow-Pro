package netbox

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

	"flow-analytics-backend/internal/model"
)

type cachedHost struct {
	hostname  string
	expiresAt time.Time
}

// Client interacts with NetBox REST API
type Client struct {
	baseURL    string
	token      string
	mu         sync.RWMutex
	httpClient *http.Client

	cache   map[string]cachedHost
	cacheMu sync.RWMutex
}

// NewClient initializes a NetBox API client
func NewClient(baseURL, token string) *Client {
	baseURL = strings.TrimRight(baseURL, "/")
	return &Client{
		baseURL: baseURL,
		token:   token,
		httpClient: &http.Client{
			Timeout: 6 * time.Second,
		},
		cache: make(map[string]cachedHost),
	}
}

// UpdateConfig updates baseURL and token safely at runtime
func (c *Client) UpdateConfig(baseURL, token string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.baseURL = strings.TrimRight(baseURL, "/")
	c.token = strings.TrimSpace(token)
	log.Printf("[*] NetBox Client configuration updated: %s", c.baseURL)
}

// GetConfig returns current baseURL and token
func (c *Client) GetConfig() (string, string) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.baseURL, c.token
}

// TestConnection checks if NetBox is reachable and returns basic stats
func (c *Client) TestConnection(ctx context.Context) (map[string]interface{}, error) {
	c.mu.RLock()
	currentBase := c.baseURL
	currentToken := c.token
	c.mu.RUnlock()

	if currentBase == "" || currentToken == "" {
		return nil, fmt.Errorf("NetBox API 地址或 Token 未配置")
	}

	testURL := fmt.Sprintf("%s/ipam/ip-addresses/?limit=1", currentBase)
	start := time.Now()

	req, err := http.NewRequestWithContext(ctx, "GET", testURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Token "+currentToken)
	req.Header.Set("Accept", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("请求 NetBox 失败: %w", err)
	}
	defer resp.Body.Close()

	durMs := time.Since(start).Milliseconds()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("NetBox HTTP %d: %s", resp.StatusCode, string(body))
	}

	var data struct {
		Count int `json:"count"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, fmt.Errorf("解析响应失败: %w", err)
	}

	return map[string]interface{}{
		"status":        "online",
		"total_ips":     data.Count,
		"latency_ms":    durMs,
		"endpoint":      testURL,
		"tested_at":     time.Now().Format("2006-01-02 15:04:05"),
	}, nil
}

// NetboxIPRecord models the API response from NetBox
type NetboxIPRecord struct {
	ID             int    `json:"id"`
	Address        string `json:"address"`
	DNSName        string `json:"dns_name"`
	Description    string `json:"description"`
	AssignedObject *struct {
		Device *struct {
			Name    string `json:"name"`
			Display string `json:"display"`
		} `json:"device"`
		VirtualMachine *struct {
			Name    string `json:"name"`
			Display string `json:"display"`
		} `json:"virtual_machine"`
	} `json:"assigned_object"`
}

// ResolveIPs resolves a list of IP addresses into hostnames using in-memory cache and NetBox batch queries
func (c *Client) ResolveIPs(ctx context.Context, ips []string) map[string]string {
	result := make(map[string]string)
	if len(ips) == 0 {
		return result
	}

	c.mu.RLock()
	currentBase := c.baseURL
	currentToken := c.token
	c.mu.RUnlock()

	if currentBase == "" || currentToken == "" {
		return result
	}

	// 1. Check in-memory cache
	var missingIPs []string
	now := time.Now()

	c.cacheMu.RLock()
	for _, ip := range ips {
		ip = strings.TrimSpace(ip)
		if ip == "" {
			continue
		}
		if entry, ok := c.cache[ip]; ok && now.Before(entry.expiresAt) {
			if entry.hostname != "" {
				result[ip] = entry.hostname
			}
		} else {
			missingIPs = append(missingIPs, ip)
		}
	}
	c.cacheMu.RUnlock()

	if len(missingIPs) == 0 {
		return result
	}

	// De-duplicate missing IPs
	uniqueMissing := make(map[string]bool)
	var dedupedMissing []string
	for _, ip := range missingIPs {
		if !uniqueMissing[ip] {
			uniqueMissing[ip] = true
			dedupedMissing = append(dedupedMissing, ip)
		}
	}

	// 2. Query NetBox in batches of 40
	batchSize := 40
	for i := 0; i < len(dedupedMissing); i += batchSize {
		end := i + batchSize
		if end > len(dedupedMissing) {
			end = len(dedupedMissing)
		}
		batch := dedupedMissing[i:end]

		params := url.Values{}
		params.Set("limit", fmt.Sprintf("%d", len(batch)*2))
		for _, ip := range batch {
			params.Add("address", ip)
		}

		queryURL := fmt.Sprintf("%s/ipam/ip-addresses/?%s", currentBase, params.Encode())
		req, err := http.NewRequestWithContext(ctx, "GET", queryURL, nil)
		if err != nil {
			continue
		}
		req.Header.Set("Authorization", "Token "+currentToken)
		req.Header.Set("Accept", "application/json")

		resp, err := c.httpClient.Do(req)
		if err != nil {
			continue
		}

		var apiResp struct {
			Results []NetboxIPRecord `json:"results"`
		}
		_ = json.NewDecoder(resp.Body).Decode(&apiResp)
		resp.Body.Close()

		foundMap := make(map[string]string)
		for _, rec := range apiResp.Results {
			cleanIP := strings.Split(rec.Address, "/")[0]
			hostname := ""

			// Priority 1: dns_name
			if strings.TrimSpace(rec.DNSName) != "" {
				hostname = strings.TrimSpace(rec.DNSName)
			} else if rec.AssignedObject != nil {
				// Priority 2: Device or VirtualMachine name
				if rec.AssignedObject.Device != nil && rec.AssignedObject.Device.Name != "" {
					hostname = rec.AssignedObject.Device.Name
				} else if rec.AssignedObject.VirtualMachine != nil && rec.AssignedObject.VirtualMachine.Name != "" {
					hostname = rec.AssignedObject.VirtualMachine.Name
				}
			}

			// Priority 3: Description if looks like a name
			if hostname == "" && strings.TrimSpace(rec.Description) != "" {
				desc := strings.TrimSpace(rec.Description)
				if !strings.Contains(desc, " ") && len(desc) < 40 {
					hostname = desc
				}
			}

			if hostname != "" {
				foundMap[cleanIP] = hostname
				result[cleanIP] = hostname
			}
		}

		// Update cache
		c.cacheMu.Lock()
		for _, ip := range batch {
			if h, ok := foundMap[ip]; ok {
				c.cache[ip] = cachedHost{hostname: h, expiresAt: now.Add(30 * time.Minute)}
			} else {
				// Negative cache for 5 minutes
				c.cache[ip] = cachedHost{hostname: "", expiresAt: now.Add(5 * time.Minute)}
			}
		}
		c.cacheMu.Unlock()
	}

	return result
}

// FetchAllIPs retrieves all IP addresses and associated hostnames/DNS from NetBox using pagination
func (c *Client) FetchAllIPs(ctx context.Context) ([]model.IPHost, error) {
	c.mu.RLock()
	currentBase := c.baseURL
	currentToken := c.token
	c.mu.RUnlock()

	if currentBase == "" || currentToken == "" {
		return nil, fmt.Errorf("NetBox API 地址或 Token 未配置")
	}

	var allHosts []model.IPHost
	limit := 1000
	offset := 0
	now := time.Now()

	client := &http.Client{
		Timeout: 30 * time.Second,
	}

	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		apiURL := fmt.Sprintf("%s/ipam/ip-addresses/?limit=%d&offset=%d", currentBase, limit, offset)
		req, err := http.NewRequestWithContext(ctx, "GET", apiURL, nil)
		if err != nil {
			return nil, fmt.Errorf("创建请求失败: %w", err)
		}
		req.Header.Set("Authorization", "Token "+currentToken)
		req.Header.Set("Accept", "application/json")

		resp, err := client.Do(req)
		if err != nil {
			return nil, fmt.Errorf("请求 NetBox 失败 (offset=%d): %w", offset, err)
		}

		if resp.StatusCode != http.StatusOK {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			return nil, fmt.Errorf("NetBox HTTP %d: %s", resp.StatusCode, string(body))
		}

		var apiResp struct {
			Count    int              `json:"count"`
			Next     *string          `json:"next"`
			Previous *string          `json:"previous"`
			Results  []NetboxIPRecord `json:"results"`
		}

		if err := json.NewDecoder(resp.Body).Decode(&apiResp); err != nil {
			resp.Body.Close()
			return nil, fmt.Errorf("解析 NetBox 响应失败 (offset=%d): %w", offset, err)
		}
		resp.Body.Close()

		for _, rec := range apiResp.Results {
			cleanIP := strings.Split(rec.Address, "/")[0]
			cleanIP = strings.TrimSpace(cleanIP)
			if cleanIP == "" {
				continue
			}

			dnsName := strings.TrimSpace(rec.DNSName)
			hostname := ""

			// Priority 1: Device / VM Name
			if rec.AssignedObject != nil {
				if rec.AssignedObject.Device != nil && rec.AssignedObject.Device.Name != "" {
					hostname = strings.TrimSpace(rec.AssignedObject.Device.Name)
				} else if rec.AssignedObject.VirtualMachine != nil && rec.AssignedObject.VirtualMachine.Name != "" {
					hostname = strings.TrimSpace(rec.AssignedObject.VirtualMachine.Name)
				}
			}

			// Priority 2: DNS Name
			if hostname == "" && dnsName != "" {
				hostname = dnsName
			}

			// Priority 3: Description if looks like host name
			if hostname == "" && strings.TrimSpace(rec.Description) != "" {
				desc := strings.TrimSpace(rec.Description)
				if !strings.Contains(desc, " ") && len(desc) < 40 {
					hostname = desc
				}
			}

			allHosts = append(allHosts, model.IPHost{
				IP:          cleanIP,
				Hostname:    hostname,
				DNSName:     dnsName,
				Description: strings.TrimSpace(rec.Description),
				Source:      "Netbox",
				UpdatedAt:   now,
			})
		}

		if apiResp.Next == nil || len(apiResp.Results) == 0 {
			break
		}
		offset += limit
	}

	return allHosts, nil
}

