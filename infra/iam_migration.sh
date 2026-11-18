#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="data4ai-challenge-03"
PROJECT_NUMBER="80080086039"
REGION="us-central1"
CLOUD_RUN_SERVICE="clinical-trials-rag-api"

SA_NAME="clinical-agent-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RE_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

echo "=== 1. Creating Dedicated Service Account for Agent Runtime ==="
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Clinical Trials Agent Runtime SA" \
  --project="${PROJECT_ID}" || true

echo "=== 2. Granting Project Roles (Vertex AI, BigQuery, Storage, Logging, Trace) ==="
for role in \
  roles/aiplatform.user \
  roles/bigquery.jobUser \
  roles/bigquery.dataViewer \
  roles/storage.objectViewer \
  roles/logging.logWriter \
  roles/monitoring.metricWriter \
  roles/cloudtrace.agent; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" --condition=None >/dev/null
done

echo "=== 3. Granting Cloud Run Invoker on FastAPI Service to Agent SA ==="
gcloud run services add-iam-policy-binding "${CLOUD_RUN_SERVICE}" \
  --region="${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

echo "=== 4. Provisioning Reasoning Engine Service Agent & Granting Token/User Permissions ==="
gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}" || true

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member="serviceAccount:${RE_SERVICE_AGENT}" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member="serviceAccount:${RE_SERVICE_AGENT}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${PROJECT_ID}"