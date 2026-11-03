#!/usr/bin/env bash
# infra/run_k6_test.sh
# Runs k6 load testing inside an isolated Docker container (grafana/k6)
# Supports:
#   1. Local services (localhost / 127.0.0.1) across Linux, macOS, and Windows Docker Desktop
#   2. Remote deployments (e.g., Cloud Run https://...)
#   3. Flexible parameter input: positional argument ($1) or TARGET_URL environment variable

set -euo pipefail

# 1. Resolve Target URL: CLI argument ($1) takes priority, falls back to $TARGET_URL, defaults to localhost:8080
RAW_TARGET_URL="${1:-${TARGET_URL:-http://localhost:8080}}"

# Detect Operating System for Docker networking resolution
OS_TYPE="$(uname -s)"
DOCKER_NET_ARGS=""

# 2. Handle Docker networking when targeting localhost from within a container
if [[ "${RAW_TARGET_URL}" =~ localhost|127\.0\.0\.1 ]]; then
  if [[ "${OS_TYPE}" == "Linux" ]]; then
    # On Linux, --network=host allows the container to share the host's network stack directly
    DOCKER_NET_ARGS="--network=host"
    RESOLVED_TARGET_URL="${RAW_TARGET_URL}"
  else
    # On macOS / Windows (Docker Desktop), 'localhost' inside the container points to itself.
    # Map localhost to 'host.docker.internal' so the container can reach host services.
    DOCKER_NET_ARGS="--add-host=host.docker.internal:host-gateway"
    RESOLVED_TARGET_URL="$(echo "${RAW_TARGET_URL}" | sed -E 's/(localhost|127\.0\.0\.1)/host.docker.internal/g')"
  fi
else
  # Remote destination (e.g., Cloud Run HTTPS URL)
  DOCKER_NET_ARGS=""
  RESOLVED_TARGET_URL="${RAW_TARGET_URL}"
fi

# Locate repository root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "============================================================"
echo "🚀 Running k6 Load Test in Docker (grafana/k6)"
echo "   Host Target URL:     ${RAW_TARGET_URL}"
echo "   Container Endpoint:  ${RESOLVED_TARGET_URL}"
echo "   Docker Networking:   ${DOCKER_NET_ARGS:-default bridge}"
echo "============================================================"

# 3. Execute k6 container mounting the test script into /scripts
docker run --rm -i \
  ${DOCKER_NET_ARGS} \
  -v "${REPO_ROOT}/infra/load_test_k6.js:/scripts/load_test_k6.js:ro" \
  -e TARGET_URL="${RESOLVED_TARGET_URL}" \
  grafana/k6:latest run \
  --summary-trend-stats="avg,min,med,max,p(90),p(95),p(99)" \
  /scripts/load_test_k6.js

echo "============================================================"
echo "✅ Docker k6 load test execution complete."
echo "============================================================"
