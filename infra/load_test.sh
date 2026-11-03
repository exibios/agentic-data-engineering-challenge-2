# Linux
curl -sf https://gobinaries.com/rakyll/hey | sh
# Or macOS: brew install hey
#!/usr/bin/env bash
# infra/load_test.sh
set -euo pipefail

# Point to your local service or deployed Cloud Run URL
TARGET_URL="${1:-http://localhost:8080/search}"

echo "🚀 Running 50 requests with 5 concurrent workers against ${TARGET_URL} ..."

hey -n 10 -c 5 -m POST \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the common exclusion criteria and dosing limits?", "top_k": 3, "session_id": "load-test-session"}' \
  "${TARGET_URL}"
