# Clinical Trials Agentic Data Pipeline - Coding Agent Guide

> **Target Audience:** Coding agents (LLMs / pair programmers) needing high-signal, comprehensive context to modify, debug, or extend this repository without exploratory file reading.

---

## 1. Project Purpose & Architecture Overview

An autonomous, event-driven data engineering and agentic RAG pipeline built on Google Cloud Platform (GCP) for clinical trials documents (Protocols, SAPs, ICFs from ClinicalTrials.gov).

```
                      [ClinicalTrials.gov / User]
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │                 FastAPI on Cloud Run                 │
        │               (pipeline/main.py: 8080)               │
        ├──────────────────────────┬───────────────────────────┤
        │  POST /v1/ingest         │  POST /search             │
        │  POST /v1/events/gcs-    │  GET /v1/metadata/{id}    │
        │       ingest (Eventarc)  │                           │
        └────────────┬─────────────┴─────────────▲─────────────┘
                     │                           │
        (Async File Stage)               (Semantic RAG Tool)
                     ▼                           │
        ┌────────────────────────┐  ┌────────────┴─────────────┐
        │  Cloud Storage (GCS)   │  │   ADK Conversational     │
        │  gs://.../raw/{nct_id} │  │       Data Agent         │
        └────────────┬───────────┘  │    (agent/agent.py)      │
                     │              └────────────┬─────────────┘
          (Eventarc / PubSub)                    │
                     ▼                 (SQL Tool / Vector Tool)
        ┌────────────────────────┐               │
        │ A2A Governance Agent   │               ▼
        │ (governance_agent.py)  │  ┌──────────────────────────┐
        │  - Valid Schema        │  │   BigQuery AI Layer      │
        │  - DLP / PII Sanitized │  │  (clinical_trials_2)     │
        │  - Rejections -> DLQ   │  │  - studies_metadata      │
        └────────────┬───────────┘  │  - extracted_doc_chunks  │
                     │ (Approved)   │  - embedded_doc_chunks   │
                     ▼              │  - VECTOR_SEARCH (Cosine)│
        ┌────────────────────────┐  └──────────────────────────┘
        │ BigQuery Object Table  │
        │ + ML.GENERATE_TEXT     │
        │ + ML.GENERATE_EMBEDDING│
        └────────────────────────┘
```

---

## 2. Core Modules: `/agent` (Agent Development Kit & LLM Ops)

All agent code lives in `/agent`. Built with `google-adk` (`google.adk`), `google-genai`, Vertex AI, and Cloud SDKs.

### 2.1 `agent/agent.py` - Primary Conversational Data Agent
- **Agent Name**: `clinical_trials_data_agent`
- **Model**: `gemini-3.8-flash` (via Vertex AI endpoint, configured via `GOOGLE_GENAI_USE_VERTEXAI=True`)
- **Role**: Conversational router handling natural language queries through two registered tools:
  - `execute_clinical_sql`: Analytical queries (counts, trial statuses, grouping by status, filtering by `nct_id`).
  - `search_clinical_protocols`: Semantic / conceptual queries (inclusion/exclusion criteria, endpoints, dosing, adverse events).
  - *Hybrid*: Executes SQL first to retrieve/filter `nct_id`s, then vector search to query protocol contents.

### 2.2 `agent/tools.py` - ADK Function Tools
- `execute_clinical_sql(sql_query: str) -> Dict[str, Any]`
  - Queries: Fully qualified BigQuery table `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` (`studies_metadata`).
  - Columns: `nct_id`, `brief_title`, `overall_status`, `doc_filename`, `cdn_url`, `gcs_uri`.
  - Guardrail: Rejects queries not starting with `SELECT` or `WITH`. Caps results to 50 rows.
- `search_clinical_protocols(search_query: str, top_k: int = 5) -> Dict[str, Any]`
  - Queries: FastAPI RAG endpoint `POST {RAG_API_URL}` (`http://localhost:8080/search` or Cloud Run URL).
  - Returns: Retrieved chunks with `nct_id`, `section_type`, `gcs_uri`, `chunk_text`, `cosine_similarity`.

### 2.3 `agent/governance_agent.py` - Agent-to-Agent (A2A) Governance & DLQ
- **Agent Name**: `clinical_trials_governance_agent` (Model: `gemini-3.8-flash`)
- **Key Functions**:
  - `verify_ingestion_payload_a2a(payload: Dict[str, Any]) -> Dict[str, Any]`:
    1. Fast deterministic pre-checks: validates `nct_id` regex (`^NCT\d{8}$`), `.pdf` extension, non-zero file size, and raw regex for SSN/PII.
    2. LLM validation: Launches ADK runner to evaluate payload against Schema, File Integrity, and PII policies.
    3. Output: JSON verdict `{"verdict": "APPROVED" | "REJECTED", "reason": "..."}`.
  - `publish_to_dlq(payload: Dict[str, Any], reason: str) -> Optional[str]`:
    - Publishes rejected events to Cloud Pub/Sub DLQ topic (`DLQ_TOPIC_ID`, default: `clinical-trials-ingest-dlq`).
    - Emits structured error log: `🚨 [GOVERNANCE AGENT INTERCEPTED -> DLQ]`.

### 2.4 `agent/guardrails.py` - Cloud DLP & Vertex Safety
- `redact_pii_dlp(text: str) -> Tuple[str, bool]`:
  - Uses Google Cloud DLP (`google.cloud.dlp_v2.DlpServiceClient`).
  - Target InfoTypes: `PERSON_NAME`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_SOCIAL_SECURITY_NUMBER`, `US_HEALTHCARE_NPI`.
  - De-identifies text replacing matches with `[INFO_TYPE]`. Returns `(sanitized_text, pii_detected_bool)`.
- `VERTEX_SAFETY_SETTINGS`: Configures `types.SafetySetting` for `HATE_SPEECH`, `DANGEROUS_CONTENT`, `SEXUALLY_EXPLICIT`, `HARASSMENT` at `BLOCK_MEDIUM_AND_ABOVE`.

### 2.5 `agent/memory.py` - Firestore Session Memory
- `SessionMemory` class:
  - Short-term conversational state backed by Cloud Firestore (`FIRESTORE_COLLECTION`, default: `agent_sessions`).
  - Methods:
    - `add_turn(session_id, role, message)`: Appends turn to `history` array via `firestore.ArrayUnion`.
    - `get_turns(session_id, limit=10) -> List[Dict]`: Retrieves last `N` turns.

### 2.6 `agent/telemetry.py` - FinOps & OpenTelemetry
- Tracer: OpenTelemetry `TracerProvider` with `CloudTraceSpanExporter` (`BatchSpanProcessor`).
- Cloud Logging: Direct write to Cloud Logging via `gcp_logging.Client` -> `agent_telemetry_log`.
- `log_agent_session_metrics(...)`:
  - Emits JSON payload: `event_type="agent_execution_telemetry"`, `session_id`, `latency_ms`, `prompt_tokens`, `response_tokens`, `total_tokens`, `estimated_cost_usd` (Gemini Flash: $0.075/1M prompt, $0.30/1M response), `pii_intercepted`.

---

## 3. Core Modules: `/pipeline` (FastAPI Serving & Ingestion)

All API and serving logic lives in `/pipeline`.

### 3.1 `pipeline/schemas.py` - Pydantic Contracts
- `IngestRequest`: `nct_id` (str), `filename` (str), `doc_type` (str, default "Protocol").
- `IngestResponse`: `ingestion_id` (UUID str), `nct_id`, `gcs_uri`, `status` ("QUEUED_ASYNC_EXTRACTION"), `timestamp` (datetime).
- `MetadataResponse`: `nct_id`, `brief_title`, `overall_status`, `gcs_uri`, `extracted_sections_count` (int).
- `SearchRequest`: `query` (str), `top_k` (int, 1-20, default 5), `session_id` (optional str).
- `ChunkHit`: `nct_id`, `section_type`, `gcs_uri`, `chunk_text`, `cosine_similarity` (float).
- `SearchResponse`: `query` (str), `results` (List[ChunkHit]).

### 3.2 `pipeline/main.py` - Application Endpoints
- Port: `8080`.
- **`POST /v1/ingest`** (Status 202 Accepted):
  - Stages document URI `gs://{BUCKET_NAME}/raw/{nct_id}/{filename}`. Non-blocking acknowledgment for async upload.
- **`GET /v1/metadata/{id}`**:
  - Joins `{PROJECT_ID}.{DATASET_ID}.studies_metadata` with `{PROJECT_ID}.{DATASET_ID}.extracted_doc_chunks` on `nct_id`.
  - Returns metadata + total count of extracted sections.
- **`POST /search`**:
  1. Checks prompt with `redact_pii_dlp(req.query)`.
  2. Embeds sanitized query in BigQuery using `ML.GENERATE_EMBEDDING` with `embedding_model` (`gemini-embedding-001`).
  3. Executes BigQuery `VECTOR_SEARCH` over `embedded_doc_chunks` using `COSINE` distance. Calculates `cosine_similarity = ROUND(1.0 - distance, 4)`.
  4. Wraps execution in OpenTelemetry span `semantic_vector_search`.
  5. Emits FinOps telemetry via `log_agent_session_metrics`.
- **`POST /v1/events/gcs-ingest`** (Eventarc / Pub/Sub Push Webhook):
  1. Decodes incoming Pub/Sub push envelope or direct Eventarc CloudEvent.
  2. Runs A2A verification via `verify_ingestion_payload_a2a()`.
  3. If rejected: Returns 200/202 with `INTERCEPTED_ROUTED_TO_DLQ`.
  4. If approved:
     - Executes BigQuery `ML.GENERATE_TEXT` with `model_extractor` (`gemini-3.8-flash`) against `documents_table` for `@gcs_uri`.
     - Extracts 5 structured sections: `Study Overview`, `Inclusion Criteria`, `Exclusion Criteria`, `Primary Endpoints`, `Dosing & Intervention`.
     - Unnests JSON into `extracted_doc_chunks`.
     - Executes BigQuery `ML.GENERATE_EMBEDDING` with `embedding_model` (`gemini-embedding-001`) into `embedded_doc_chunks`.

---

## 4. Reference Components

### 4.1 `/infra` - Infrastructure as Code & Scripts
- `infra/bq_setup.sql`:
  - Dataset `clinical_trials_2`.
  - Tables: `studies_metadata`, external object table `documents_table` over `gs://.../raw/*` using connection `us.agentic_conn`.
  - Remote models: `model_extractor` (`gemini-3.8-flash`), `embedding_model` (`gemini-embedding-001`).
  - Target tables: `extracted_doc_chunks`, `embedded_doc_chunks` + IVF `COSINE` Vector Index `doc_chunks_cosine_idx`.
- `infra/setup_day9_eventarc.sh`: Creates Pub/Sub topic `clinical-trials-ingest-topic`, DLQ `clinical-trials-ingest-dlq`, pull subscription, log metric `governance_dlq_routed_count`, and Eventarc GCS object finalized trigger routing to `/v1/events/gcs-ingest`.
- `infra/logging_metrics.sh`: Configures Cloud Monitoring distribution metrics for `agent_session_total_tokens` (grouped by `session_id`) and `agent_execution_latency_ms`.
- `infra/load_test_native.py` & `load_test_native.sh`: Zero-dependency multi-threaded load test for `/search` (p50, p90, p95, throughput). Supports Cloud Run IAM tokens.
- `infra/deploy_cloud_run.sh`: Command to deploy `clinical-trials-rag-api` from source to Cloud Run in `us-central1`.

### 4.2 `/scripts` - Utilities & Verification
- `scripts/fetch_sample_data.py`: Fetches studies from ClinicalTrials.gov API v2, downloads up to 20 protocol PDFs, stages in GCS (`raw/{nct_id}/{filename}`), and inserts rows into BigQuery `studies_metadata`.
- `scripts/test_day8_agent.py`: ADK runner script testing intent routing (Analytical SQL vs. Semantic Search).
- `scripts/test_day9_governance.py`: Tests 3 scenarios for A2A Governance (Valid PDF -> Approved, PII -> Rejected/DLQ, Corrupt -> Rejected/DLQ).
- `scripts/final_challenge_test.py`: Comprehensive test runner covering all Days 6-10 acceptance criteria (local or against Cloud Run).

### 4.3 `/docs` - Architecture & Decision Records
- `docs/ARCHITECTURE.md`: High-level flowchart and unstructured-to-structured explanation.
- `docs/ADR-001-agentic-ingestion.md`: Decisions on chunking strategy (semantic sectioning via LLM vs. naive character split), model choice (`gemini-3.8-flash`), schema evolution policy, and DLP.

---

## 5. Configuration & Environment Variables Contract

All variables are loaded via `.env` with fallback dummy values when unset:

| Variable | Default Fallback | Purpose / Production Example |
| :--- | :--- | :--- |
| `PROJECT_ID` / `GCP_PROJECT` | `"dummy-project-id"` | GCP Project ID (`data4ai-challenge-03`) |
| `LOCATION` / `GCP_LOCATION` | `"dummy-location"` | Vertex AI / Cloud Region (`global` or `us-central1`) |
| `DATASET_ID` / `BQ_DATASET` | `"dummy_dataset_id"` | BigQuery dataset (`clinical_trials_2`) |
| `TABLE_ID` / `BQ_TABLE` | `"dummy_table_id"` | Metadata table (`studies_metadata`) |
| `BUCKET_NAME` / `GCS_BUCKET` | `"dummy-bucket-name"` | GCS raw bucket name |
| `MODEL_NAME` / `AGENT_MODEL` | `"dummy-model-name"` | Gemini model (`gemini-3.8-flash`) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `"dummy-vertexai-flag"` | Enable Vertex backend in ADK (`True`) |
| `DLQ_TOPIC_ID` / `DWL_TOPIC_ID`| `"dummy-dlq-topic-id"` | Pub/Sub Dead-Letter Queue topic |
| `RAG_API_URL` | `"http://dummy-rag-api-url/search"` | Vector search endpoint URL |
| `FIRESTORE_COLLECTION` | `"dummy-agent-sessions"`| Firestore collection name (`agent_sessions`) |
| `EMBEDDING_MODEL` | `"dummy_embedding_model"`| BigQuery model (`embedding_model`) |
| `EXTRACTOR_MODEL` | `"dummy_model_extractor"`| BigQuery model (`model_extractor`) |

---

## 6. Key Invariants & Rules for Coding Agents

1. **Always Preserve Read-Only Safety**: `execute_clinical_sql` must remain restricted to `SELECT` and `WITH` statements.
2. **Deterministic Pre-Checks Before LLM**: In `agent/governance_agent.py`, regex checks (`NCT\d{8}`, file size, obvious SSN patterns) must run before calling ADK runner to conserve tokens and minimize latency.
3. **Escaping Inside BigQuery F-strings**: In `pipeline/main.py`, SQL blocks inside Python f-strings must escape JSON braces as `{{` and `}}` and regex slashes as `\\d{{8}}`.
4. **Cloud Run Concurrency**: The `/search` endpoint is stateless; state is maintained in Firestore (`agent_sessions`) and BigQuery. Do not store in-memory session dictionaries.
5. **FinOps & Telemetry**: When adding or modifying endpoints, maintain the `log_agent_session_metrics` call to ensure Cloud Logging metrics and dashboard charts stay synchronized.
