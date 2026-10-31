# agent/tools.py
import logging
import os
from typing import Any, Dict, List
from google.cloud import bigquery
import httpx

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass

# Configure visible console logging for Day 8 Acceptance Criteria
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("day8_adk_tools")

PROJECT_ID = os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT") or "dummy-project-id"
DATASET_ID = os.getenv("DATASET_ID") or os.getenv("BQ_DATASET") or "dummy_dataset_id"
TABLE_ID = os.getenv("TABLE_ID") or os.getenv("BQ_TABLE") or "dummy_table_id"
RAG_API_URL = os.getenv("RAG_API_URL", "http://dummy-rag-api-url/search")
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

bq_client = bigquery.Client(project=PROJECT_ID)


def execute_clinical_sql(sql_query: str) -> Dict[str, Any]:
  """Executes a read-only BigQuery SQL query for analytical and structured questions.

  USE THIS TOOL WHEN the user asks analytical questions such as counts,
  aggregations, group-bys, trial statuses, or filtering by NCTId.

  Target Table Schema:
  `studies_metadata` (query `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`):
    - nct_id (STRING): Unique clinical trial ID (e.g., 'NCT04001234')
    - brief_title (STRING): Title of the study
    - overall_status (STRING): Trial status (e.g., 'COMPLETED', 'RECRUITING')
    - doc_filename (STRING): Name of the associated PDF file
    - cdn_url (STRING): Source URL on ClinicalTrials.gov
    - gcs_uri (STRING): Cloud Storage URI of the raw PDF

  Args:
      sql_query: A valid BigQuery Standard SQL SELECT statement querying
        the fully-qualified studies metadata table.

  Returns:
      A dictionary containing the executed SQL and returned rows.
  """
  logger.info(
      "🎯 [ADK ROUTING LOG] -> Selected Tool: SQL Execution Tool"
      " (Analytical Intent)"
  )
  logger.info(f"Executing BigQuery SQL: {sql_query}")

  # Basic safety guardrail: allow SELECT / WITH statements only
  cleaned_sql = sql_query.strip().upper()
  if not (cleaned_sql.startswith("SELECT") or cleaned_sql.startswith("WITH")):
    return {
        "status": "error",
        "error_message": "Only read-only SELECT queries are permitted.",
    }

  try:
    query_job = bq_client.query(sql_query)
    rows = [dict(row) for row in query_job.result()]
    logger.info(f"✅ SQL Tool returned {len(rows)} rows.")
    return {
        "status": "success",
        "tool_used": "execute_clinical_sql",
        "executed_sql": sql_query,
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
  logger.info(
      f"Querying FastAPI RAG endpoint ({RAG_API_URL}) for: '{search_query}'"
  )

  try:
    with httpx.Client(timeout=30.0) as client:
      response = client.post(
          RAG_API_URL,
          json={"query": search_query, "top_k": top_k},
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
