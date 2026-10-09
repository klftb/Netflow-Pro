package repository

import (
	"context"
	"fmt"
	"net"
	"strings"
	"sync"
)

type SubnetRule struct {
	Name  string
	IPNet *net.IPNet
}

// IPResolver manages high-speed, thread-safe in-memory IP to Hostname/DNS resolution
// Priority 1: NetBox DNS / Hostname ('Netbox')
// Priority 2: Local 32-bit Host / Local Subnet Name ('Local')
// Fallback: Original IP
type IPResolver struct {
	mu           sync.RWMutex
	netboxMap    map[string]string // IP -> Hostname (Source: Netbox)
	localHostMap map[string]string // IP -> Hostname (Source: Local)
	subnets      []SubnetRule      // CIDR rules for local network names
}

// NewIPResolver creates an empty IPResolver instance
func NewIPResolver() *IPResolver {
	return &IPResolver{
		netboxMap:    make(map[string]string),
		localHostMap: make(map[string]string),
	}
}

// Reload reloads NetBox and Local hosts and subnets from repository into memory
func (r *IPResolver) Reload(ctx context.Context, repo *ClickHouseRepo) error {
	// 1. Load IP Hosts
	nbMap, locMap, err := repo.GetAllIPHostsMap(ctx)
	if err != nil {
		return err
	}

	// 2. Load Subnets
	groups, err := repo.GetBusinessGroups(ctx)
	if err != nil {
		return err
	}

	var subnetRules []SubnetRule
	for _, g := range groups {
		cidr := strings.TrimSpace(g.CIDR)
		if !strings.Contains(cidr, "/") {
			cidr += "/32"
		}
		_, ipNet, err := net.ParseCIDR(cidr)
		if err == nil && ipNet != nil {
			subnetRules = append(subnetRules, SubnetRule{
				Name:  g.GroupName,
				IPNet: ipNet,
			})
		}
	}

	r.mu.Lock()
	r.netboxMap = nbMap
	r.localHostMap = locMap
	r.subnets = subnetRules
	r.mu.Unlock()

	return nil
}

// Resolve applies the 2-tier matching rule:
// 1. Priority 1: NetBox DNS/Hostname -> returns "hostname (ip)"
// 2. Priority 2: Local Hostname or Subnet Name -> returns "localName (ip)"
// 3. Fallback: original ip
func (r *IPResolver) Resolve(ip string) (displayName string, matchedName string, source string) {
	ip = strings.TrimSpace(ip)
	if ip == "" {
		return "", "", ""
	}

	r.mu.RLock()
	defer r.mu.RUnlock()

	// Tier 1: NetBox DNS / Hostname
	if h, ok := r.netboxMap[ip]; ok && h != "" {
		return fmt.Sprintf("%s (%s)", h, ip), h, "Netbox"
	}

	// Tier 2a: Local 32-bit Host
	if h, ok := r.localHostMap[ip]; ok && h != "" {
		return fmt.Sprintf("%s (%s)", h, ip), h, "Local"
	}

	// Tier 2b: Local Subnet Rule
	parsedIP := net.ParseIP(ip)
	if parsedIP != nil {
		for _, s := range r.subnets {
			if s.IPNet.Contains(parsedIP) {
				return fmt.Sprintf("%s (%s)", s.Name, ip), s.Name, "Local"
			}
		}
	}

	// Fallback
	return ip, "", ""
}

// GetHostCounts returns total active count of Netbox and Local hosts cached
func (r *IPResolver) GetHostCounts() (netboxCount int, localCount int) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return len(r.netboxMap), len(r.localHostMap)
}
