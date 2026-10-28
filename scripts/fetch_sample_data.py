# scripts/fetch_sample_data.py
import httpx
from google.cloud import storage, bigquery
import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

PROJECT_ID = "data4ai-challenge-03"
BUCKET_NAME = "data4ai-challenge-03-agentic-data-engineering-raw-docs-2"
BQ_DATASET = "clinical_trials_2"
BQ_TABLE = "studies_metadata"

API_URL = "https://clinicaltrials.gov/api/v2/studies"
QUERY_PARAMS = {
    "filter.advanced": "AREA[LargeDocHasProtocol]true OR AREA[LargeDocHasSAP]true OR AREA[LargeDocHasICF]true",
    "fields": "NCTId,BriefTitle,OverallStatus,Phase,LargeDocumentModule",
    "pageSize": 60  # Respects 50-100 document budget
}

def build_cdn_url(nct_id: str, filename: str) -> str:
    last_two = nct_id[-2:]
    return f"https://cdn.clinicaltrials.gov/large-docs/{last_two}/{nct_id}/{filename}"

def fetch_and_stage_trials():
    logging.info("fetch_and_stage_trials")

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    bq_client = bigquery.Client(project=PROJECT_ID)

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(API_URL, params=QUERY_PARAMS)
        resp.raise_for_status()
        studies = resp.json().get("studies", [])

        structured_rows = []
        pdf_count = 0

        for study in studies:
            print("study: ", study.get("protocolSection", {}).get("identificationModule", {}).get("nctId"))
            protocol = study.get("protocolSection", {})
            nct_id = protocol.get("identificationModule", {}).get("nctId")
            title = protocol.get("identificationModule", {}).get("briefTitle", "")
            status = protocol.get("statusModule", {}).get("overallStatus", "")
            
            large_docs = study.get("documentSection", {}).get("largeDocumentModule", {}).get("largeDocs", [])
            for doc in large_docs:
                filename = doc.get("filename")
                if not filename or pdf_count >= 75:
                    continue
                
                cdn_url = build_cdn_url(nct_id, filename)
                gcs_uri = f"gs://{BUCKET_NAME}/raw/{nct_id}/{filename}"
                
                # Download PDF and upload to GCS
                pdf_resp = client.get(cdn_url)
                if pdf_resp.status_code == 200:
                    blob = bucket.blob(f"raw/{nct_id}/{filename}")
                    blob.upload_from_string(pdf_resp.content, content_type="application/pdf")
                    pdf_count += 1

                    structured_rows.append({
                        "nct_id": nct_id,
                        "brief_title": title,
                        "overall_status": status,
                        "doc_filename": filename,
                        "cdn_url": cdn_url,
                        "gcs_uri": gcs_uri
                    })

        # Insert structured metadata into BigQuery
        if structured_rows:
            table_id = f"{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"
            errors = bq_client.insert_rows_json(table_id, structured_rows)
            print(f"Uploaded {pdf_count} PDFs to GCS. BigQuery insert errors: {errors}")

if __name__ == "__main__":
    logging.info("MAIN")
    fetch_and_stage_trials()
