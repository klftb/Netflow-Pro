package test

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"testing"
	"time"
)

const baseURL = "http://127.0.0.1:8080/api/v1"

func TestHealthCheck(t *testing.T) {
	resp, err := http.Get(baseURL + "/health")
	if err != nil {
		t.Fatalf("Health check request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestTrafficTrend24H_RawRouting(t *testing.T) {
	// Query within 24 hours -> Should route to flows_raw
	now := time.Now()
	payload := map[string]interface{}{
		"start_time": now.Add(-6 * time.Hour).Format("2006-01-02 15:04:05"),
		"end_time":   now.Format("2006-01-02 15:04:05"),
		"direction":  "all",
	}
	body, _ := json.Marshal(payload)

	start := time.Now()
	resp, err := http.Post(baseURL+"/traffic/trend", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("Trend request failed: %v", err)
	}
	defer resp.Body.Close()
	dur := time.Since(start)

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	var res map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&res)
	data, ok := res["data"].(map[string]interface{})
	if !ok {
		t.Fatalf("Invalid response structure: %v", res)
	}

	ds, _ := data["data_source"].(string)
	t.Logf("[24H Query] DataSource: %s, Duration: %v", ds, dur)
}

func TestTrafficTrend90D_AggregatedRouting(t *testing.T) {
	// Query across 90 days -> Should automatically route to flows_5m
	now := time.Now()
	payload := map[string]interface{}{
		"start_time": now.Add(-90 * 24 * time.Hour).Format("2006-01-02 15:04:05"),
		"end_time":   now.Format("2006-01-02 15:04:05"),
		"direction":  "all",
	}
	body, _ := json.Marshal(payload)

	start := time.Now()
	resp, err := http.Post(baseURL+"/traffic/trend", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("90D Trend request failed: %v", err)
	}
	defer resp.Body.Close()
	dur := time.Since(start)

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		t.Fatalf("Expected status 200, got %d: %s", resp.StatusCode, string(b))
	}

	var res map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&res)
	data, ok := res["data"].(map[string]interface{})
	if !ok {
		t.Fatalf("Invalid response structure: %v", res)
	}

	ds, _ := data["data_source"].(string)
	p95, _ := data["p95_bps"].(float64)
	t.Logf("[90D Query] DataSource: %s, P95 Bandwidth: %.2f bps, Duration: %v", ds, p95, dur)

	// Benchmark requirement: Response time MUST be under 1.5 seconds!
	if dur > 1500*time.Millisecond {
		t.Errorf("Benchmark failed: query took %v (limit: 1.5s)", dur)
	} else {
		t.Logf("[PASS] 90D query response time is within SLA: %v <= 1.5s", dur)
	}
}

func TestTopNQuery(t *testing.T) {
	now := time.Now()
	payload := map[string]interface{}{
		"start_time": now.Add(-24 * time.Hour).Format("2006-01-02 15:04:05"),
		"end_time":   now.Format("2006-01-02 15:04:05"),
		"dimension":  "app",
		"limit":      5,
	}
	body, _ := json.Marshal(payload)

	resp, err := http.Post(baseURL+"/traffic/topn", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("TopN request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestSankeyQuery(t *testing.T) {
	now := time.Now()
	payload := map[string]interface{}{
		"start_time": now.Add(-24 * time.Hour).Format("2006-01-02 15:04:05"),
		"end_time":   now.Format("2006-01-02 15:04:05"),
		"limit":      10,
	}
	body, _ := json.Marshal(payload)

	resp, err := http.Post(baseURL+"/traffic/sankey", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("Sankey request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}
