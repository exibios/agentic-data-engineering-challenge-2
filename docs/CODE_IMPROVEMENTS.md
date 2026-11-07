# Code Improvements & Architectural Evolution

> **Objective:** Practical recommendations to elevate code quality, reliability, and maintainability across `/agent` and `/pipeline` while strictly preserving simplicity, existing functionality, and low cognitive overhead.

---

## Part 1: Simple Best Practice Refactorings (Immediate / Low Effort)

These refactorings eliminate technical debt and subtle bugs without introducing complex design patterns or heavy abstractions.

---

### 1. Centralize Environment Configuration (`agent/config.py`)

#### Problem
Currently, 7+ files (`pipeline/main.py`, `agent/agent.py`, `agent/tools.py`, `agent/governance_agent.py`, `agent/guardrails.py`, `agent/memory.py`, `agent/telemetry.py`) independently duplicate:
- `load_dotenv()` inside `try/except`
- Repeated fallback cascades (`os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT") or "dummy-project-id"`)
- Out-of-sync variable defaults (e.g., `agent/guardrails.py` uses `"data4ai-challenge-03"` directly while others use `"dummy-project-id"`).

#### Solution: Single 30-Line Config Module
Create a lightweight configuration module:

```python
# agent/config.py
import os
from dataclasses import dataclass

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass

@dataclass(frozen=True)
class Settings:
  # GCP & Region
  PROJECT_ID: str = os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT") or "dummy-project-id"
  LOCATION: str = os.getenv("LOCATION") or os.getenv("GCP_LOCATION") or "dummy-location"
  
  # BigQuery & Storage
  DATASET_ID: str = os.getenv("DATASET_ID") or os.getenv("BQ_DATASET") or "dummy_dataset_id"
  TABLE_ID: str = os.getenv("TABLE_ID") or os.getenv("BQ_TABLE") or "dummy_table_id"
  BUCKET_NAME: str = os.getenv("BUCKET_NAME") or os.getenv("GCS_BUCKET") or "dummy-bucket-name"
  
  # Models & Endpoints
  MODEL_NAME: str = os.getenv("MODEL_NAME") or os.getenv("AGENT_MODEL") or "dummy-model-name"
  EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "dummy_embedding_model")
  EXTRACTOR_MODEL: str = os.getenv("EXTRACTOR_MODEL", "dummy_model_extractor")
  RAG_API_URL: str = os.getenv("RAG_API_URL", "http://dummy-rag-api-url/search")
  
  # Pub/Sub & DLQ
  DLQ_TOPIC_ID: str = os.getenv("DLQ_TOPIC_ID") or os.getenv("DWL_TOPIC_ID") or "dummy-dlq-topic-id"
  FIRESTORE_COLLECTION: str = os.getenv("FIRESTORE_COLLECTION", "dummy-agent-sessions")
  GOOGLE_GENAI_USE_VERTEXAI: str = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "dummy-vertexai-flag")

settings = Settings()
```

#### Benefit
- Removes over 60 lines of repeated boilerplate across the repository.
- Single source of truth: updating a variable name or dummy default happens in exactly one place.

---

### 2. Prevent Event Loop Blocking in FastAPI (`asyncio.to_thread`)

#### Problem
In `pipeline/main.py`, both `POST /search` and `POST /v1/events/gcs-ingest` are declared as `async def`, but they call synchronous, blocking BigQuery methods:
```python
rows = list(bq_client.query(sql, job_config=job_config).result())
```
In an async event loop, blocking on `.result()` halts the entire worker thread for 1.5–3.0 seconds, drastically degrading throughput during concurrent load tests.

#### Solution: Run Synchronous Query in a Worker Thread
Use standard Python `asyncio.to_thread`:

```python
# pipeline/main.py
import asyncio

def _run_query(query_sql: str, config: bigquery.QueryJobConfig):
  return list(bq_client.query(query_sql, job_config=config).result())

# Inside async def semantic_search(...):
rows = await asyncio.to_thread(_run_query, sql, job_config)
```

#### Benefit
- Unblocks FastAPI to handle concurrent incoming requests while BigQuery processes the query in GCP.
- Increases `/search` concurrent throughput with zero third-party dependencies.

---

### 3. Extract Multi-Line SQL Queries (`pipeline/queries.py`)

#### Problem
In `pipeline/main.py`, the Eventarc ingestion endpoint contains ~120 lines of SQL embedded directly inside an f-string, requiring awkward escaping:
- `REGEXP_EXTRACT(uri, r'NCT\\d{{8}}')`
- `{{"section_type": "Study Overview"}}`

Any SQL modification risks breaking Python syntax or escaping rules.

#### Solution: Dedicated SQL Template Constants
Move the SQL queries to `pipeline/queries.py`:

```python
# pipeline/queries.py

INCREMENTAL_EXTRACTION_SQL = """
INSERT INTO `{project_id}.{dataset_id}.extracted_doc_chunks`
  (chunk_id, nct_id, gcs_uri, section_type, chunk_text, created_at)
WITH raw_llm_extraction AS (
  SELECT
    uri AS gcs_uri,
    REGEXP_EXTRACT(uri, r'NCT\d{8}') AS nct_id,
    ml_generate_text_llm_result AS raw_response,
    SAFE.PARSE_JSON(
      REGEXP_REPLACE(
        REGEXP_REPLACE(TRIM(ml_generate_text_llm_result), r'^```(?:json)?\s*', ''),
        r'\s*```$', ''
      )
    ) AS parsed_json
  FROM
    ML.GENERATE_TEXT(...)
...
"""
```

In `pipeline/main.py`:
```python
sql = INCREMENTAL_EXTRACTION_SQL.format(
    project_id=settings.PROJECT_ID,
    dataset_id=settings.DATASET_ID,
    extractor_model=settings.EXTRACTOR_MODEL,
)
```

#### Benefit
- Raw regex (`\d{8}`) and JSON syntax (`{"key": "value"}`) remain natural and unescaped.
- Makes `pipeline/main.py` 150+ lines shorter and easier to navigate.

---

### 4. Direct Cloud Logging Optimization (Zero-Latency Standard Output)

#### Problem
In `agent/telemetry.py`:
```python
gcp_logger = logging_client.logger("agent_telemetry_log")
gcp_logger.log_struct(structured_payload, severity="INFO")
```
Every invocation makes an explicit network round-trip HTTP POST to Google Cloud Logging API (`logging.googleapis.com`), adding unnecessary latency (50–150 ms) to `/search`.

#### Solution: Standard Cloud Run JSON Logging
Google Cloud Run and Google Kubernetes Engine natively parse any JSON object written to `sys.stdout` into structured Cloud Logging `jsonPayload` automatically:

```python
# agent/telemetry.py
import json
import sys

def log_agent_session_metrics(...):
  structured_payload = {
      "severity": "INFO",
      "message": f"Telemetry emitted for session {session_id}",
      "event_type": "agent_execution_telemetry",
      "session_id": session_id,
      "latency_ms": round(latency_ms, 2),
      "prompt_tokens": prompt_tokens,
      "response_tokens": response_tokens,
      "total_tokens": prompt_tokens + response_tokens,
      "estimated_cost_usd": round(estimated_cost_usd, 6),
      "pii_intercepted": pii_intercepted,
  }
  print(json.dumps(structured_payload), file=sys.stdout, flush=True)
```

#### Benefit
- Cuts 50–150 ms per request off `/search`.
- Works identically locally and in Cloud Run.
- Cloud Logging Metrics and Dashboards continue to parse `jsonPayload.total_tokens` and `jsonPayload.session_id` without changes.

---

### 5. Lazy GCP Client Instantiation

#### Problem
`bigquery.Client()`, `dlp_v2.DlpServiceClient()`, and `firestore.Client()` are instantiated at the top level of module imports. When running unit tests, linting, or importing schemas, connection attempts to GCP occur immediately, causing crashes or slowdowns when credentials are missing or mocked.

#### Solution: Simple Cached Getters or Properties
```python
# agent/clients.py
from functools import lru_cache
from google.cloud import bigquery, firestore, dlp_v2
from agent.config import settings

@lru_cache(maxsize=1)
def get_bq_client():
  return bigquery.Client(project=settings.PROJECT_ID)

@lru_cache(maxsize=1)
def get_firestore_client():
  return firestore.Client(project=settings.PROJECT_ID)

@lru_cache(maxsize=1)
def get_dlp_client():
  return dlp_v2.DlpServiceClient()
```

#### Benefit
- Clients are created on first use, speeding up imports and making unit tests effortless without mock patching at module load time.

---

## Part 2: Suggestions & Architectural Evolution (Future Milestones)

---

### 1. Automated DLQ Replay & Alerting Worker
- **Current State**: Payloads rejected by the Governance Agent are routed to `clinical-trials-ingest-dlq`. The engineer must run manual `gcloud pubsub subscriptions pull` to inspect rejections.
- **Evolution**:
  - Deploy a Cloud Run Job or Eventarc-triggered Cloud Function listening to `clinical-trials-ingest-dlq-sub`.
  - Push formatted alert cards to Slack / Teams with rejection reasons and NCTId.
  - Provide an endpoint `/v1/dlq/replay` that allows authorized admins to re-queue corrected documents after updating schemas or redacting sensitive records.

### 2. Hybrid Search: Dense Vector + BigQuery Full-Text Search
- **Current State**: `/search` relies strictly on vector cosine similarity via `ML.GENERATE_EMBEDDING`.
- **Limitation**: Pure vector search can struggle on exact pharmaceutical drug codes (e.g., "MK-3475", "NCT04001234", or specific genetic markers like "EGFR T790M").
- **Evolution**:
  - Implement Reciprocal Rank Fusion (RRF) in BigQuery:
    ```sql
    -- Combine VECTOR_SEARCH with BigQuery text search
    WITH vector_hits AS (...),
         keyword_hits AS (
           SELECT chunk_id, SCORE(chunk_text) AS bm25_score
           FROM `clinical_trials_2.extracted_doc_chunks`
           WHERE SEARCH(chunk_text, @query_text)
         )
    -- Reciprocal Rank Fusion score: 1 / (60 + rank_vec) + 1 / (60 + rank_kw)
    ```
  - Yields high semantic comprehension while preserving 100% precision on exact medical terminology.

### 3. Agent Evaluation & Continuous RAG Benchmarking (CI/CD)
- **Current State**: `scripts/final_challenge_test.py` validates technical execution (HTTP status codes, tool selection).
- **Evolution**:
  - Integrate a lightweight automated RAG evaluation framework (e.g., RAGAS or synthetic test generation).
  - Measure 3 core metrics on pull requests:
    1. **Faithfulness**: Is the agent response grounded strictly in retrieved chunks?
    2. **Answer Relevance**: Did the agent directly answer the clinical question?
    3. **Context Recall**: Did vector search find the correct inclusion/exclusion section?
  - Run automatically in GitHub Actions on every pull request.

### 4. Infrastructure as Code (Terraform)
- **Current State**: Infrastructure is created via manual bash scripts (`setup_day9_eventarc.sh`, `logging_metrics.sh`, `deploy_cloud_run.sh`).
- **Evolution**:
  - Consolidate into a single Terraform directory (`infra/terraform/`):
    - `google_bigquery_dataset`, `google_bigquery_table`
    - `google_pubsub_topic` (ingest + DLQ)
    - `google_cloud_run_v2_service`
    - `google_eventarc_trigger`
    - `google_logging_metric`
  - Eliminates drift and enables reproducible multi-environment deployments (`staging` vs. `production`).

---

## Summary Matrix: Prioritization Guide

| Initiative | Effort | Impact | Risk | Recommended Next Step |
| :--- | :---: | :---: | :---: | :--- |
| **1. Centralized Config (`agent/config.py`)** | Low (30 min) | High | Minimal | Immediate implementation |
| **2. Async BigQuery (`asyncio.to_thread`)** | Low (15 min) | High | Minimal | Immediate implementation |
| **3. Extract SQL Queries (`queries.py`)** | Low (30 min) | Medium | Minimal | Immediate implementation |
| **4. Cloud Run Stdout Logging** | Low (20 min) | Medium | Minimal | Immediate implementation |
| **5. Hybrid Search (Vector + BM25)** | Medium (1 day) | High | Low | Next feature sprint |
| **6. Automated DLQ Replay Worker** | Medium (1 day) | Medium | Low | Post-launch operations |
| **7. Terraform IaC Migration** | Medium (1 day) | High | Low | Platform stabilization |
