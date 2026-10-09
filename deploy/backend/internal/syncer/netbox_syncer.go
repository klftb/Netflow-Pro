package syncer

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/netbox"
	"flow-analytics-backend/internal/repository"
)

// NetboxSyncer orchestrates scheduled and on-demand synchronization of NetBox IP addresses
type NetboxSyncer struct {
	repo         *repository.ClickHouseRepo
	netboxClient *netbox.Client
	resolver     *repository.IPResolver

	mu     sync.RWMutex
	status model.NetboxSyncStatus
}

// NewNetboxSyncer initializes a new NetboxSyncer instance
func NewNetboxSyncer(repo *repository.ClickHouseRepo, nbClient *netbox.Client, resolver *repository.IPResolver) *NetboxSyncer {
	return &NetboxSyncer{
		repo:         repo,
		netboxClient: nbClient,
		resolver:     resolver,
		status: model.NetboxSyncStatus{
			LastSyncTime:   "从未同步",
			LastSyncStatus: "idle",
		},
	}
}

// Start begins the daily background sync routine and initializes the IPResolver
func (s *NetboxSyncer) Start(ctx context.Context) {
	// First: Initial reload of resolver from existing DB data
	if err := s.resolver.Reload(ctx, s.repo); err != nil {
		log.Printf("[!] Failed to initial load IPResolver: %v", err)
	} else {
		nbC, locC := s.resolver.GetHostCounts()
		log.Printf("[*] IPResolver initialized: %d NetBox hosts, %d Local hosts", nbC, locC)
		s.mu.Lock()
		s.status.TotalNetboxIPs = nbC
		s.status.TotalLocalIPs = locC
		s.mu.Unlock()
	}

	// Trigger async background sync on startup if NetBox configured
	go func() {
		time.Sleep(3 * time.Second)
		baseURL, token := s.netboxClient.GetConfig()
		if baseURL != "" && token != "" {
			log.Println("[*] Starting initial NetBox IP synchronization...")
			if err := s.SyncNow(context.Background()); err != nil {
				log.Printf("[!] Initial NetBox sync completed with error: %v", err)
			}
		}
	}()

	// Daily schedule: 24h ticker
	ticker := time.NewTicker(24 * time.Hour)
	go func() {
		for {
			select {
			case <-ctx.Done():
				ticker.Stop()
				return
			case <-ticker.C:
				baseURL, token := s.netboxClient.GetConfig()
				if baseURL != "" && token != "" {
					log.Println("[*] Scheduled daily NetBox IP synchronization triggered")
					_ = s.SyncNow(context.Background())
				}
			}
		}
	}()
}

// SyncNow executes full NetBox IP synchronization immediately
func (s *NetboxSyncer) SyncNow(ctx context.Context) error {
	s.mu.Lock()
	if s.status.IsSyncing {
		s.mu.Unlock()
		return fmt.Errorf("同步正在进行中，请稍候")
	}
	s.status.IsSyncing = true
	s.mu.Unlock()

	defer func() {
		s.mu.Lock()
		s.status.IsSyncing = false
		s.mu.Unlock()
	}()

	startTime := time.Now()
	log.Println("[NetboxSyncer] Starting full IP fetch from NetBox...")

	// 1. Fetch all IPs from NetBox
	hosts, err := s.netboxClient.FetchAllIPs(ctx)
	if err != nil {
		s.mu.Lock()
		s.status.LastSyncTime = startTime.Format("2006-01-02 15:04:05")
		s.status.LastSyncStatus = fmt.Sprintf("拉取失败: %v", err)
		s.mu.Unlock()
		return err
	}

	log.Printf("[NetboxSyncer] Fetched %d IP records from NetBox. Fetching local protected hosts...", len(hosts))

	// 2. Fetch local protected hosts to prevent overriding
	localSet, err := s.repo.GetLocalIPHostSet(ctx)
	if err != nil {
		log.Printf("[NetboxSyncer] Warning: failed to query local IP set: %v", err)
		localSet = make(map[string]bool)
	}

	// Filter out Local hosts
	var validHosts []model.IPHost
	for _, h := range hosts {
		if localSet[h.IP] {
			continue // Preserve Local configuration
		}
		validHosts = append(validHosts, h)
	}

	log.Printf("[NetboxSyncer] Saving %d NetBox hosts into ClickHouse...", len(validHosts))

	// 3. Batch insert into ClickHouse
	batchSize := 2000
	for i := 0; i < len(validHosts); i += batchSize {
		end := i + batchSize
		if end > len(validHosts) {
			end = len(validHosts)
		}
		if err := s.repo.BatchSaveIPHosts(ctx, validHosts[i:end]); err != nil {
			log.Printf("[NetboxSyncer] Batch save error [%d:%d]: %v", i, end, err)
			s.mu.Lock()
			s.status.LastSyncTime = time.Now().Format("2006-01-02 15:04:05")
			s.status.LastSyncStatus = fmt.Sprintf("入库失败: %v", err)
			s.mu.Unlock()
			return err
		}
	}

	// 4. Reload in-memory IPResolver
	if err := s.resolver.Reload(ctx, s.repo); err != nil {
		log.Printf("[NetboxSyncer] Failed to reload resolver after sync: %v", err)
	}

	nbCount, locCount := s.resolver.GetHostCounts()
	elapsed := time.Since(startTime).Round(time.Millisecond)

	s.mu.Lock()
	s.status.LastSyncTime = time.Now().Format("2006-01-02 15:04:05")
	s.status.LastSyncStatus = fmt.Sprintf("成功同步 %d 条 Netbox 记录 (耗时 %s)", len(validHosts), elapsed)
	s.status.TotalNetboxIPs = nbCount
	s.status.TotalLocalIPs = locCount
	s.mu.Unlock()

	log.Printf("[NetboxSyncer] Synchronization finished successfully in %s. Netbox: %d, Local: %d", elapsed, nbCount, locCount)
	return nil
}

// GetStatus returns the current sync status
func (s *NetboxSyncer) GetStatus() model.NetboxSyncStatus {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.status
}
