#!/usr/bin/env bash
# infra/setup_day9_eventarc.sh
set -euo pipefail

# Source .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
elif [ -f ../.env ]; then
  set -a
  source ../.env
  set +a
fi

PROJECT_ID="${PROJECT_ID:-${GCP_PROJECT:-dummy-project-id}}"
REGION="${REGION:-${GCP_LOCATION:-dummy-region}}"
BUCKET_NAME="${BUCKET_NAME:-${GCS_BUCKET:-dummy-bucket-name}}"
SERVICE_NAME="${SERVICE_NAME:-dummy-service-name}"

INGEST_TOPIC="${INGEST_TOPIC_ID:-dummy-ingest-topic}"
DLQ_TOPIC="${DLQ_TOPIC_ID:-${DWL_TOPIC_ID:-dummy-dlq-topic}}"
DLQ_SUB="${DLQ_SUBSCRIPTION_ID:-dummy-dlq-sub}"
INGEST_SUB="${INGEST_SUBSCRIPTION_ID:-dummy-ingest-sub}"


echo "=== 1. Creating Primary Pub/Sub Topic & Dead-Letter Queue (DLQ) Topic ==="
gcloud pubsub topics create "${INGEST_TOPIC}" --project="${PROJECT_ID}" || true
gcloud pubsub topics create "${DLQ_TOPIC}" --project="${PROJECT_ID}" || true

# Create pull subscription on the DLQ so you can inspect intercepted messages
gcloud pubsub subscriptions create "${DLQ_SUB}" \
  --topic="${DLQ_TOPIC}" \
  --project="${PROJECT_ID}" || true

echo "=== 2. Creating Subscription with Retry Policy & Dead-Letter Policy ==="
gcloud pubsub subscriptions create "${INGEST_SUB}" \
  --topic="${INGEST_TOPIC}" \
  --dead-letter-topic="${DLQ_TOPIC}" \
  --max-delivery-attempts=5 \
  --min-retry-delay=10s \
  --max-retry-delay=60s \
  --project="${PROJECT_ID}" || true

echo "=== 3. Creating Cloud Logging Metric for Monitoring DLQ Depth ==="
gcloud logging metrics create governance_dlq_routed_count \
  --description="Counts payloads intercepted by the Governance Agent and routed to DLQ" \
  --log-filter='textPayload:"[GOVERNANCE AGENT INTERCEPTED -> DLQ]"' \
  --project="${PROJECT_ID}" || true

echo "=== 4. Creating Eventarc Trigger on GCS Bucket (Object Finalized) ==="
# Note: Run this after deploying `clinical-trials-rag-api` to Cloud Run
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
GCS_SA=$(gsutil kms serviceaccount -p "${PROJECT_ID}")

# Grant GCS service account permission to publish to Pub/Sub for Eventarc
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${GCS_SA}" \
  --role="roles/pubsub.publisher" >/dev/null

gcloud eventarc triggers create clinical-trials-gcs-trigger \
  --location="us" \
  --destination-run-service="${SERVICE_NAME}" \
  --destination-run-region="${REGION}" \
  --destination-run-path="/v1/events/gcs-ingest" \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=${BUCKET_NAME}" \
  --service-account="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --project="${PROJECT_ID}" || true

echo "✅ Day 9 Eventarc, Pub/Sub DLQ, and Log-Based Metric configured!"
