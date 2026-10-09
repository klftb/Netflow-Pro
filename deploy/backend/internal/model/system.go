package model

import "time"

// ManagedService represents a managed background service in the platform
type ManagedService struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Type        string    `json:"type"` // "systemd" or "docker"
	ServiceName string    `json:"service_name"`
	Port        string    `json:"port"`
	Status      string    `json:"status"`   // "active", "inactive", "failed"
	SubState    string    `json:"sub_state"` // "running", "dead", etc.
	PID         int       `json:"pid"`
	Uptime      string    `json:"uptime"`
	Memory      string    `json:"memory"`
	Description string    `json:"description"`
	UpdatedAt   time.Time `json:"updated_at"`
}

// RestartServiceRequest specifies which service to restart
type RestartServiceRequest struct {
	ServiceID string `json:"service_id" binding:"required"`
}

// InspectionItem represents a single health check check item
type InspectionItem struct {
	ID          string `json:"id"`
	Category    string `json:"category"` // "service", "database", "collector", "integration", "host"
	Name        string `json:"name"`
	Status      string `json:"status"` // "pass", "warn", "fail"
	LatencyMs   int64  `json:"latency_ms"`
	Message     string `json:"message"`
	Details     string `json:"details"`
	Suggestion  string `json:"suggestion,omitempty"`
}

// InspectionReport represents the full system health check report
type InspectionReport struct {
	Score         int              `json:"score"`          // 0 - 100
	OverallStatus string           `json:"overall_status"` // "healthy", "warning", "critical"
	InspectedAt   string           `json:"inspected_at"`
	DurationMs    int64            `json:"duration_ms"`
	TotalChecks   int              `json:"total_checks"`
	PassedChecks  int              `json:"passed_checks"`
	WarningChecks int              `json:"warning_checks"`
	FailedChecks  int              `json:"failed_checks"`
	Items         []InspectionItem `json:"items"`
}
