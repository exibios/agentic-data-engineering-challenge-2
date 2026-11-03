#!/usr/bin/env bash
# infra/load_test_native.sh
# Runs concurrent load test without external dependencies.
set -euo pipefail

TARGET_URL="${1:-${TARGET_URL:-http://localhost:8080/search}}"
NUM_REQUESTS="${2:-50}"
CONCURRENCY="${3:-5}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/load_test_native.py" "${TARGET_URL}" -n "${NUM_REQUESTS}" -c "${CONCURRENCY}"
