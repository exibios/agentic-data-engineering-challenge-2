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
from agent.telemetry import get_active_conversation_id, log_agent_session_metrics
from opentelemetry import trace
import os
import time

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
  start_time = time.time()
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

    latency_ms = (time.time() - start_time) * 1000.0
    approx_prompt_tokens = len(resolved_sql.split()) * 2
    capped_rows = rows[:50]
    approx_response_tokens = len(str(capped_rows).split())

    # Attach metrics to ambient ADK execute_tool span to preserve gen_ai.conversation.id
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
      current_span.set_attribute("clinical.row_count", len(rows))
      current_span.set_attribute("clinical.latency_ms", latency_ms)

    session_id = get_active_conversation_id()
    log_agent_session_metrics(
        session_id=session_id,
        user_prompt=resolved_sql,
        tool_selected="execute_clinical_sql",
        latency_ms=latency_ms,
        prompt_tokens=approx_prompt_tokens,
        response_tokens=approx_response_tokens,
        pii_intercepted=False,
    )

    return {
        "status": "success",
        "tool_used": "execute_clinical_sql",
        "executed_sql": resolved_sql,
        "row_count": len(rows),
        "rows": capped_rows,  # Cap output to protect prompt context length
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
  start_time = time.time()
  logger.info(
      "🔍 [ADK ROUTING LOG] -> Selected Tool: Vector Search Tool"
      " (Semantic/Conceptual Intent)"
  )
  search_url = _normalize_search_url(RAG_API_URL)
  logger.info(
      f"Querying FastAPI RAG endpoint ({search_url}) for: '{search_query}'"
  )

  headers = _get_bearer_headers(search_url)
  session_id = get_active_conversation_id()

  try:
    with httpx.Client(timeout=30.0) as client:
      response = client.post(
          search_url,
          json={
              "query": search_query,
              "top_k": top_k,
              "session_id": session_id,
          },
          headers=headers,
      )
      response.raise_for_status()
      data = response.json()

    results: List[Dict[str, Any]] = data.get("results", [])
    logger.info(f"✅ Vector Search Tool retrieved {len(results)} chunks.")

    latency_ms = (time.time() - start_time) * 1000.0
    approx_prompt_tokens = len(search_query.split()) * 2
    approx_response_tokens = sum(
        len(str(r.get("chunk_text", "")).split()) for r in results
    )

    # Attach metrics to ambient ADK execute_tool span to preserve gen_ai.conversation.id
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
      current_span.set_attribute("clinical.chunks_retrieved", len(results))
      current_span.set_attribute("clinical.latency_ms", latency_ms)

    log_agent_session_metrics(
        session_id=session_id,
        user_prompt=search_query,
        tool_selected="search_clinical_protocols",
        latency_ms=latency_ms,
        prompt_tokens=approx_prompt_tokens,
        response_tokens=approx_response_tokens,
        pii_intercepted=False,
    )

    return {
        "status": "success",
        "tool_used": "search_clinical_protocols",
        "query": search_query,
        "retrieved_chunks": results,
    }
  except Exception as e:
    logger.error(f"❌ Vector Search request failed: {e}")
    return {"status": "error", "error_message": str(e)}


def get_governance_verdict(
    nct_id: str,
    tool_context: Any = None,
) -> dict[str, Any]:
  """Retrieves the governance, schema, and PII verification verdict for a specific clinical trial (NCT ID).

  Checks active session state and persistent Firestore session memory for prior evaluation records.
  """
  state_key = f"governance_verdict:{nct_id}"

  # 1. Check local session state via injected ToolContext
  if tool_context and hasattr(tool_context, "state") and tool_context.state:
    if state_key in tool_context.state:
      return {
          "status": "found",
          "source": "session_state",
          "nct_id": nct_id,
          "verdict": tool_context.state[state_key],
      }
    if "latest_governance_verdict" in tool_context.state:
      latest = tool_context.state["latest_governance_verdict"]
      if isinstance(latest, dict) and latest.get("nct_id") == nct_id:
        return {
            "status": "found",
            "source": "session_state_latest",
            "nct_id": nct_id,
            "verdict": latest,
        }

  # 2. Check persistent Firestore session memory
  try:
    from agent.memory import get_session_service

    svc = get_session_service()
    if hasattr(svc, "get_session_state_sync"):
      state = svc.get_session_state_sync(f"session-{nct_id}")
      if state and state_key in state:
        return {
            "status": "found",
            "source": "firestore_session",
            "nct_id": nct_id,
            "verdict": state[state_key],
        }
      if state and "latest_governance_verdict" in state:
        return {
            "status": "found",
            "source": "firestore_session_latest",
            "nct_id": nct_id,
            "verdict": state["latest_governance_verdict"],
        }
  except Exception as e:
    logger.warning(f"Error checking Firestore session state for {nct_id}: {e}")

  return {
      "status": "not_found",
      "nct_id": nct_id,
      "message": (
          f"No governance verification record found for {nct_id}. "
          "The document may not have been ingested yet or was processed in an unlinked session."
      ),
  }

