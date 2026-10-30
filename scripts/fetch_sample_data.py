# scripts/fetch_sample_data.py
import httpx
from google.cloud import bigquery, storage

# === Project Constants ===
PROJECT_ID = "data4ai-challenge-03"
DATASET_ID = "clinical_trials_2"
TABLE_ID = "studies_metadata"
BUCKET_NAME = "data4ai-challenge-03-agentic-data-engineering-raw-docs-2"
MAX_PDFS = 20  # Respects the 50-100 document budget

API_URL = "https://clinicaltrials.gov/api/v2/studies"
QUERY_PARAMS = {
    "filter.advanced": (
        "AREA[LargeDocHasProtocol]true OR AREA[LargeDocHasSAP]true OR"
        " AREA[LargeDocHasICF]true"
    ),
    "fields": "NCTId,BriefTitle,OverallStatus,LargeDocumentModule",
    "pageSize": 30,
}


def build_cdn_url(nct_id: str, filename: str) -> str:
  """Constructs the ClinicalTrials.gov CDN URL using the last 2 digits of NCTId."""
  last_two = nct_id[-2:]
  return f"https://cdn.clinicaltrials.gov/large-docs/{last_two}/{nct_id}/{filename}"


def main():
  storage_client = storage.Client(project=PROJECT_ID)
  bucket = storage_client.bucket(BUCKET_NAME)
  bq_client = bigquery.Client(project=PROJECT_ID)

  # Ensure structured table exists before inserting
  full_table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
  schema = [
      bigquery.SchemaField("nct_id", "STRING", mode="REQUIRED"),
      bigquery.SchemaField("brief_title", "STRING"),
      bigquery.SchemaField("overall_status", "STRING"),
      bigquery.SchemaField("doc_filename", "STRING"),
      bigquery.SchemaField("cdn_url", "STRING"),
      bigquery.SchemaField("gcs_uri", "STRING"),
  ]
  table_ref = bigquery.Table(full_table_id, schema=schema)
  bq_client.create_table(table_ref, exists_ok=True)

  structured_rows = []
  pdf_count = 0

  with httpx.Client(timeout=30.0, follow_redirects=True) as client:
    resp = client.get(API_URL, params=QUERY_PARAMS)
    resp.raise_for_status()
    studies = resp.json().get("studies", [])

    for study in studies:
      if pdf_count >= MAX_PDFS:
        break

      protocol = study.get("protocolSection", {})
      nct_id = protocol.get("identificationModule", {}).get("nctId")
      title = protocol.get("identificationModule", {}).get("briefTitle", "")
      status = protocol.get("statusModule", {}).get("overallStatus", "")

      large_docs = (
          study.get("documentSection", {})
          .get("largeDocumentModule", {})
          .get("largeDocs", [])
      )

      for doc in large_docs:
        if pdf_count >= MAX_PDFS:
          break
        filename = doc.get("filename")
        if not filename:
          continue

        cdn_url = build_cdn_url(nct_id, filename)
        blob_path = f"raw/{nct_id}/{filename}"
        gcs_uri = f"gs://{BUCKET_NAME}/{blob_path}"

        print(f"[{pdf_count+1}/{MAX_PDFS}] Downloading {cdn_url} ...")
        pdf_resp = client.get(cdn_url)
        if pdf_resp.status_code == 200:
          blob = bucket.blob(blob_path)
          blob.upload_from_string(
              pdf_resp.content, content_type="application/pdf"
          )
          pdf_count += 1

          structured_rows.append({
              "nct_id": nct_id,
              "brief_title": title,
              "overall_status": status,
              "doc_filename": filename,
              "cdn_url": cdn_url,
              "gcs_uri": gcs_uri,
          })

  if structured_rows:
    errors = bq_client.insert_rows_json(full_table_id, structured_rows)
    print(f"Done! Uploaded {pdf_count} PDFs. BQ Insert Errors: {errors}")


if __name__ == "__main__":
  main()
