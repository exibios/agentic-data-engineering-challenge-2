#!/usr/bin/env bash
# scripts/check_day10_permissions.sh
set -euo pipefail

PROJECT_ID="data4ai-challenge-03"
COMPUTE_SA="80080086039-compute@developer.gserviceaccount.com"

echo "=== 1. Checking Enabled APIs for Day 10 ==="
for api in dlp.googleapis.com cloudtrace.googleapis.com monitoring.googleapis.com logging.googleapis.com; do
  if gcloud services list --enabled --project="${PROJECT_ID}" --filter="NAME:${api}" --format="value(NAME)" | grep -q "${api}"; then
    echo "✅ Enabled: ${api}"
  else
    echo "⚠️ Missing API: ${api} -> Enabling now..."
    gcloud services enable "${api}" --project="${PROJECT_ID}"
  fi
done

echo -e "\n=== 2. Granting Required Day 10 Roles to Compute SA ==="
for role in roles/dlp.user roles/cloudtrace.agent roles/monitoring.metricWriter roles/logging.logWriter; do
  echo "Applying ${role}..."
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="${role}" --condition=None >/dev/null
  echo "✅ Granted: ${role}"
done

echo -e "\n=== All Day 10 IAM Roles Ready! ==="
