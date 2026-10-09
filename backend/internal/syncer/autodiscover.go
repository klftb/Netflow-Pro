package syncer

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"flow-analytics-backend/internal/librenms"
	"flow-analytics-backend/internal/model"
	"flow-analytics-backend/internal/repository"
)

type AutoDiscoverSyncer struct {
	repo        *repository.ClickHouseRepo
	libreClient *librenms.Client
	interval    time.Duration
	stopCh      chan struct{}
	syncMu      sync.Mutex
}

func NewAutoDiscoverSyncer(repo *repository.ClickHouseRepo, libreClient *librenms.Client, interval time.Duration) *AutoDiscoverSyncer {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	return &AutoDiscoverSyncer{
		repo:        repo,
		libreClient: libreClient,
		interval:    interval,
		stopCh:      make(chan struct{}),
	}
}

func (s *AutoDiscoverSyncer) Start() {
	go func() {
		log.Printf("[*] NetFlow Auto-Discovery & LibreNMS Syncer started (Interval: %v)", s.interval)

		// Immediate check on startup
		initCtx, initCancel := context.WithTimeout(context.Background(), 20*time.Second)
		_, _ = s.CheckAndSyncNewExporters(initCtx)
		initCancel()

		ticker := time.NewTicker(s.interval)
		defer ticker.Stop()

		for {
			select {
			case <-s.stopCh:
				log.Println("[*] NetFlow Auto-Discovery Syncer stopped")
				return
			case <-ticker.C:
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				_, _ = s.CheckAndSyncNewExporters(ctx)
				cancel()
			}
		}
	}()
}

func (s *AutoDiscoverSyncer) Stop() {
	close(s.stopCh)
}

func (s *AutoDiscoverSyncer) CheckAndSyncNewExporters(ctx context.Context) ([]string, error) {
	s.syncMu.Lock()
	defer s.syncMu.Unlock()

	unregistered, err := s.repo.FindUnregisteredExporters(ctx, 10)
	if err != nil {
		log.Printf("[WARN] [AutoDiscover] Failed to query unregistered exporters: %v", err)
		return nil, err
	}

	if len(unregistered) == 0 {
		return nil, nil
	}

	log.Printf("[+] [AutoDiscover] Detected %d new NetFlow exporter(s) needing registration: %v", len(unregistered), unregistered)
	var synced []string
	for _, ip := range unregistered {
		if err := s.syncSingleDevice(ctx, ip); err == nil {
			synced = append(synced, ip)
		} else {
			log.Printf("[WARN] [AutoDiscover] Failed to auto-register exporter %s: %v", ip, err)
		}
	}
	return synced, nil
}

func (s *AutoDiscoverSyncer) SyncDevice(ctx context.Context, ip string) error {
	s.syncMu.Lock()
	defer s.syncMu.Unlock()
	return s.syncSingleDevice(ctx, ip)
}

func (s *AutoDiscoverSyncer) syncSingleDevice(ctx context.Context, ip string) error {
	ip = strings.TrimSpace(ip)
	if ip == "" || ip == "0.0.0.0" {
		return nil
	}

	// 1. Try LibreNMS API first
	if s.libreClient != nil {
		ld, err := s.libreClient.GetDeviceByIP(ctx, ip)
		if err == nil && ld != nil {
			sysName := ld.SysName
			if sysName == "" {
				sysName = ld.Hostname
			}
			sysDescr := ld.SysDescr
			if sysDescr == "" {
				sysDescr = ld.Hardware
			}
			devType := InferDeviceType(ld.OS + " " + ld.Hardware + " " + sysDescr + " " + ld.Type)
			displayName := fmt.Sprintf("%s (%s)", sysName, ip)

			dev := model.ExporterDevice{
				ExporterIP:    ip,
				DeviceName:    displayName,
				DeviceType:    devType,
				Location:      ld.Location,
				Admin:         ld.SysContact,
				SNMPCommunity: ld.Community,
				SNMPVersion:   ld.SNMPVer,
				Description:   fmt.Sprintf("由 NetFlow 流量自动发现，并从 LibreNMS 同步: %s (硬件: %s, 系统: %s)", sysName, ld.Hardware, ld.OS),
			}
			if err := s.repo.SaveExporterDevice(ctx, dev); err != nil {
				return fmt.Errorf("failed to save exporter device: %w", err)
			}

			// Automatically sync interfaces from LibreNMS as well
			portCount := 0
			ports, pErr := s.libreClient.GetDevicePorts(ctx, ip)
			if pErr == nil && len(ports) > 0 {
				for _, p := range ports {
					if p.IfIndex == 0 {
						continue
					}
					speed := uint32(p.IfSpeed / 1000000)
					if speed == 0 {
						speed = 1000
					}
					dispName := p.IfName
					if p.IfAlias != "" && p.IfAlias != p.IfName {
						dispName = fmt.Sprintf("%s (%s)", p.IfName, p.IfAlias)
					}
					ifc := model.DeviceInterface{
						ExporterIP:  ip,
						IfIndex:     p.IfIndex,
						IfName:      p.IfName,
						IfDescr:     p.IfDescr,
						IfAlias:     p.IfAlias,
						DisplayName: dispName,
						SpeedMbps:   speed,
					}
					if err := s.repo.SaveDeviceInterface(ctx, ifc); err == nil {
						portCount++
					}
				}
			}
			log.Printf("[+] [AutoDiscover] Successfully registered %s as %s (%s) with %d ports from LibreNMS", ip, sysName, devType, portCount)
			return nil
		}
	}

	// 2. Fallback: Not found in LibreNMS, create basic record with active flow ports
	dev := model.ExporterDevice{
		ExporterIP:  ip,
		DeviceName:  fmt.Sprintf("网络设备 (%s)", ip),
		DeviceType:  "Switch",
		Description: "由 NetFlow 流量自动发现入库 (LibreNMS 暂无对应资产记录)",
	}
	if err := s.repo.SaveExporterDevice(ctx, dev); err != nil {
		return fmt.Errorf("failed to save fallback exporter device: %w", err)
	}

	ifIndices, _ := s.repo.GetActiveInterfacesForExporter(ctx, ip)
	for _, idx := range ifIndices {
		ifc := model.DeviceInterface{
			ExporterIP:  ip,
			IfIndex:     idx,
			IfName:      fmt.Sprintf("Port #%d", idx),
			DisplayName: fmt.Sprintf("接口 #%d (自动流采样口)", idx),
			SpeedMbps:   1000,
		}
		_ = s.repo.SaveDeviceInterface(ctx, ifc)
	}
	log.Printf("[+] [AutoDiscover] Registered fallback exporter %s with %d active flow ports", ip, len(ifIndices))
	return nil
}

func (s *AutoDiscoverSyncer) SyncAllRegisteredDevices(ctx context.Context) (int, error) {
	s.syncMu.Lock()
	defer s.syncMu.Unlock()

	devs, err := s.repo.GetExporterDevices(ctx)
	if err != nil {
		return 0, err
	}

	syncedCount := 0
	for _, dev := range devs {
		if err := s.syncSingleDevice(ctx, dev.ExporterIP); err == nil {
			syncedCount++
		}
	}

	// Also catch any newly arrived unregistered exporters
	unregistered, _ := s.repo.FindUnregisteredExporters(ctx, 60)
	for _, ip := range unregistered {
		if err := s.syncSingleDevice(ctx, ip); err == nil {
			syncedCount++
		}
	}

	return syncedCount, nil
}

func InferDeviceType(raw string) string {
	rawLower := strings.ToLower(raw)
	if strings.Contains(rawLower, "forti") || strings.Contains(rawLower, "firewall") {
		return "Firewall"
	}
	if strings.Contains(rawLower, "router") {
		return "Router"
	}
	if strings.Contains(rawLower, "switch") || strings.Contains(rawLower, "catalyst") ||
		strings.Contains(rawLower, "c29") || strings.Contains(rawLower, "c9") ||
		strings.Contains(rawLower, "ios") || strings.Contains(rawLower, "h3c") {
		return "Switch"
	}
	return "Switch"
}
