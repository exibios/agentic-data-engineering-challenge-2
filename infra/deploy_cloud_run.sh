gcloud run deploy clinical-trials-rag-api \
  --source . \
  --project data4ai-challenge-03 \
  --region us-central1 \
  --set-env-vars "GCP_PROJECT=data4ai-challenge-03,BQ_DATASET=clinical_trials_2,GCS_BUCKET=data4ai-challenge-03-agentic-data-engineering-raw-docs-2" \
  --allow-unauthenticated
