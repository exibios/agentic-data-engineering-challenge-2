# scripts/test_day9_governance.py
#  python -m scripts.test_day9_governance

'''
gcloud pubsub subscriptions pull clinical-trials-ingest-dlq-sub \
  --project=data4ai-challenge-03 \
  --auto-ack \
  --limit=5
'''

import asyncio
from agent.governance_agent import verify_ingestion_payload_a2a

BUCKET = "data4ai-challenge-03-agentic-data-engineering-raw-docs-2"


async def main():
  print("\n" + "=" * 80)
  print("🧪 TEST 1: Valid Clinical Trial PDF Upload (Should be APPROVED)")
  print("=" * 80)
  valid_payload = {
      "nct_id": "NCT04001234",
      "gcs_uri": f"gs://{BUCKET}/raw/NCT04001234/Prot_000.pdf",
      "size_bytes": 412800,
      "sample_text": "Phase 2 Study Objectives and Inclusion Criteria for adult oncology.",
      "proposed_schema": ["nct_id", "gcs_uri", "section_type", "chunk_text"],
  }
  res1 = await verify_ingestion_payload_a2a(valid_payload)
  print(f"Result 1: {res1}\n")

  print("=" * 80)
  print("🧪 TEST 2: Policy-Violating PII File Upload (Should be REJECTED -> DLQ)")
  print("=" * 80)
  pii_payload = {
      "nct_id": "NCT04001234",
      "gcs_uri": f"gs://{BUCKET}/raw/NCT04001234/patient_records_pii_violation.pdf",
      "size_bytes": 15200,
      "sample_text": "Patient John Doe, SSN: 123-45-6789, phone 555-0199.",
      "proposed_schema": ["nct_id", "gcs_uri", "patient_ssn"],
  }
  res2 = await verify_ingestion_payload_a2a(pii_payload)
  print(f"Result 2: {res2}\n")

  print("=" * 80)
  print("🧪 TEST 3: Corrupted / Breaking Schema Upload (Should be REJECTED -> DLQ)")
  print("=" * 80)
  corrupt_payload = {
      "nct_id": "BAD_ID_999",
      "gcs_uri": f"gs://{BUCKET}/raw/corrupt_upload.txt",
      "size_bytes": 0,
      "sample_text": "",
  }
  res3 = await verify_ingestion_payload_a2a(corrupt_payload)
  print(f"Result 3: {res3}\n")


if __name__ == "__main__":
  asyncio.run(main())
