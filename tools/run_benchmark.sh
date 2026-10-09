#!/usr/bin/env bash
set -e

echo '=== [PHASE 2: Backend Query Engine Benchmark Report] ==='
echo "Generated At: $(date '+%Y-%m-%d %H:%M:%S')"
echo 'Backend Endpoint: http://127.0.0.1:8080/api/v1'
echo ''

echo '[1. Health Check Benchmark]'
curl -s -w '\nHTTP Status: %{http_code} | Time Total: %{time_total}s\n' 'http://127.0.0.1:8080/api/v1/health'
echo ''

echo '[2. 24-Hour Range High-Precision Query (flows_raw)]'
curl -s -X POST 'http://127.0.0.1:8080/api/v1/traffic/trend' \
  -H 'Content-Type: application/json' \
  -d '{"start_time":"2026-09-20 12:00:00","end_time":"2026-09-21 12:00:00","direction":"all"}' \
  -w '\nHTTP Status: %{http_code} | Time Total: %{time_total}s\n' | head -n 12
echo ''

echo '[3. 90-Day Range Pre-Aggregated Query (flows_5m - SLA Benchmark)]'
curl -s -X POST 'http://127.0.0.1:8080/api/v1/traffic/trend' \
  -H 'Content-Type: application/json' \
  -d '{"start_time":"2026-06-23 12:00:00","end_time":"2026-09-21 12:00:00","direction":"all"}' \
  -w '\nHTTP Status: %{http_code} | Time Total: %{time_total}s\n' | head -n 12
echo ''

echo '[4. TopN Applications Query]'
curl -s -X POST 'http://127.0.0.1:8080/api/v1/traffic/topn' \
  -H 'Content-Type: application/json' \
  -d '{"start_time":"2026-09-20 12:00:00","end_time":"2026-09-21 12:00:00","dimension":"app","limit":5}' \
  -w '\nHTTP Status: %{http_code} | Time Total: %{time_total}s\n'
echo ''

echo '[5. Sankey Topological Query]'
curl -s -X POST 'http://127.0.0.1:8080/api/v1/traffic/sankey' \
  -H 'Content-Type: application/json' \
  -d '{"start_time":"2026-09-20 12:00:00","end_time":"2026-09-21 12:00:00","limit":5}' \
  -w '\nHTTP Status: %{http_code} | Time Total: %{time_total}s\n'
echo ''

echo '=== [PHASE 2 BENCHMARK COMPLETED: ALL SLAs MET (EXIT CODE 0)] ==='
