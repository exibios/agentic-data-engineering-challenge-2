# agent/tools.py
import logging
import subprocess
from typing import Any, Dict, List
from urllib.parse import urlparse

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
import httpx

from agent.clients import get_bq_client
from agent.config import settings
import os

# Configure visible console logging for Day 8 Acceptance Criteria
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("day8_adk_tools")

PROJECT_ID = settings.PROJECT_ID
DATASET_ID = settings.DATASET_ID
TABLE_ID = settings.TABLE_ID
RAG_API_URL = settings.RAG_API_URL

FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"


def _normalize_search_url(raw_url: str) -> str:
  """Ensures the RAG URL always ends with /search even if set to the base Cloud Run URL."""
  cleaned = raw_url.strip().rstrip("/")
  if not cleaned.endswith("/search"):
    return f"{cleaned}/search"
  return cleaned


# In agent/tools.py
def _get_bearer_headers(target_url: str) -> Dict[str, str]:
  """Uses Metadata Server OIDC in Agent Runtime/Cloud Run, and gcloud CLI in Cloud Shell."""
  headers: Dict[str, str] = {
      "accept": "*/*",
      "Content-Type": "application/json",
  }
  if "localhost" in target_url or "127.0.0.1" in target_url:
    return headers

  parsed = urlparse(target_url)
  audience = f"{parsed.scheme}://{parsed.netloc}"

  # When running interactively in Cloud Shell, use the user's gcloud identity token
  if os.getenv("CLOUD_SHELL") == "true":
    try:
      token = subprocess.check_output(
          ["gcloud", "auth", "print-identity-token"],
          text=True,
          stderr=subprocess.DEVNULL,
      ).strip()
      if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers
    except Exception:
      pass

  # In Vertex AI Agent Runtime or Cloud Run, fetch OIDC token from the attached Service Account
  try:
    token = id_token.fetch_id_token(GoogleAuthRequest(), audience)
    if token:
      headers["Authorization"] = f"Bearer {token}"
      return headers
  except Exception as e:
    logger.warning(f"⚠️ Metadata OIDC fetch failed ({e}); trying gcloud fallback...")

  # Final fallback for local laptops
  try:
    token = subprocess.check_output(
        ["gcloud", "auth", "print-identity-token"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if token:
      headers["Authorization"] = f"Bearer {token}"
  except Exception:
    pass

  return headers




def execute_clinical_sql(sql_query: str) -> Dict[str, Any]:
  """Executes a read-only BigQuery SQL query for analytical and structured questions.

  USE THIS TOOL WHEN the user asks analytical questions such as counts,
  aggregations, group-bys, trial statuses, or filtering by NCTId.

  Target Table Schema:
  `studies_metadata` (query
  `data4ai-challenge-03.clinical_trials_2.studies_metadata`):
    - nct_id (STRING): Unique clinical trial ID (e.g., 'NCT04001234')
    - brief_title (STRING): Title of the study
    - overall_status (STRING): Trial status (e.g., 'COMPLETED', 'RECRUITING')
    - doc_filename (STRING): Name of the associated PDF file
    - cdn_url (STRING): Source URL on ClinicalTrials.gov
    - gcs_uri (STRING): Cloud Storage URI of the raw PDF

  Args:
      sql_query: A valid BigQuery Standard SQL SELECT statement querying the
        fully-qualified studies metadata table.

  Returns:
      A dictionary containing the executed SQL and returned rows.
  """
  logger.info(
      "🎯 [ADK ROUTING LOG] -> Selected Tool: SQL Execution Tool"
      " (Analytical Intent)"
  )
  resolved_sql = sql_query.replace(
      "{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}", FULL_TABLE_ID
  )
  logger.info(f"Executing BigQuery SQL: {resolved_sql}")

  # Basic safety guardrail: allow SELECT / WITH statements only
  cleaned_sql = resolved_sql.strip().upper()
  if not (cleaned_sql.startswith("SELECT") or cleaned_sql.startswith("WITH")):
    return {
        "status": "error",
        "error_message": "Only read-only SELECT queries are permitted.",
    }

  try:
    bq_client = get_bq_client()
    query_job = bq_client.query(resolved_sql)
    rows = [dict(row) for row in query_job.result()]
    logger.info(f"✅ SQL Tool returned {len(rows)} rows.")
    return {
        "status": "success",
        "tool_used": "execute_clinical_sql",
        "executed_sql": resolved_sql,
        "row_count": len(rows),
        "rows": rows[:50],  # Cap output to protect prompt context length
    }
  except Exception as e:
    logger.error(f"❌ SQL execution failed: {e}")
    return {"status": "error", "error_message": str(e)}


def search_clinical_protocols(
    search_query: str, top_k: int = 5
) -> Dict[str, Any]:
  """Searches unstructured clinical trial PDFs via the FastAPI Vector Search backend.

  USE THIS TOOL WHEN the user asks conceptual, clinical, or qualitative
  questions about protocol contents, such as inclusion/exclusion criteria,
  dosing regimens, primary endpoints, study objectives, or statistical plans.

  Args:
      search_query: The natural language clinical concept or question to search.
      top_k: Number of most relevant document chunks to retrieve (default 5).

  Returns:
      A dictionary containing the top matching document chunks and cosine
      similarity scores.
  """
  logger.info(
      "🔍 [ADK ROUTING LOG] -> Selected Tool: Vector Search Tool"
      " (Semantic/Conceptual Intent)"
  )
  search_url = _normalize_search_url(RAG_API_URL)
  logger.info(
      f"Querying FastAPI RAG endpoint ({search_url}) for: '{search_query}'"
  )

  headers = _get_bearer_headers(search_url)

  try:
    with httpx.Client(timeout=30.0) as client:
      response = client.post(
          search_url,
          json={
              "query": search_query,
              "top_k": top_k,
              "session_id": "adk-agent-session",
          },
          headers=headers,
      )
      response.raise_for_status()
      data = response.json()

    results: List[Dict[str, Any]] = data.get("results", [])
    logger.info(f"✅ Vector Search Tool retrieved {len(results)} chunks.")
    return {
        "status": "success",
        "tool_used": "search_clinical_protocols",
        "query": search_query,
        "retrieved_chunks": results,
    }
  except Exception as e:
    logger.error(f"❌ Vector Search request failed: {e}")
    return {"status": "error", "error_message": str(e)}
