# Clinical Trials Agentic Data Pipeline - Coding Agent Guide

> **Target Audience:** Coding agents (LLMs / pair programmers) needing high-signal, comprehensive context to modify, debug, or extend this repository without exploratory file reading.
> **Aligned Curriculum:** Google Cloud Partner Data Agent Challenge (Days 1–10) detailed in [`docs/challenge_context.md`](file:///usr/local/google/home/cfrancoisrael/repos/agentic-data-engineering-challenge-2/docs/challenge_context.md).

---

## 1. Project Purpose & Architecture Overview

An autonomous, event-driven data engineering and agentic RAG pipeline built on Google Cloud Platform (GCP) for clinical trials documents (Protocols, SAPs, ICFs from ClinicalTrials.gov).

```
                      [ClinicalTrials.gov / User]
                                   │
                                   ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                     FastAPI on Cloud Run                      │
        │                   (pipeline/main.py: 8080)                    │
        ├──────────────────────────┬────────────────────────────────────┤
        │  POST /v1/ingest         │  POST /search                      │
        │  POST /v1/events/gcs-    │  GET /v1/metadata/{id}             │
        │       ingest (Eventarc)  │  POST /v1/chat (Agent Runtime)     │
        └────────────┬─────────────┴─────────────────▲──────────────────┘
                     │                               │
        (Async File Stage)                   (Semantic RAG Tool)
                     ▼                               │
        ┌────────────────────────┐      ┌────────────┴──────────────────┐
        │  Cloud Storage (GCS)   │      │ Vertex AI Agent Engine Runtime│
        │  gs://.../raw/{nct_id} │      │      (ADK root_agent)         │
        └────────────┬───────────┘      │     - Python 3.11 BYOSA       │
                     │                  │     - Managed Session Memory  │
          (Eventarc / PubSub)           └────────────┬──────────────────┘
                     ▼                               │
        ┌────────────────────────┐                   │ (SQL Tool / Vector Tool)
        │ A2A Governance Agent   │                   │
        │ (governance_agent.py)  │                   ▼
        │  - Valid Schema        │      ┌───────────────────────────────┐
        │  - DLP / PII Sanitized │      │      BigQuery AI Layer        │
        │  - Rejections -> DLQ   │      │     (clinical_trials_2)       │
        └────────────┬───────────┘      │  - studies_metadata (Upsert)  │
                     │ (Approved)       │  - extracted_doc_chunks       │
                     ▼                  │  - embedded_doc_chunks        │
        ┌────────────────────────┐      │  - doc_chunks_cosine_idx      │
        │ BigQuery Object Table  │      │  - VECTOR_SEARCH (Cosine)     │
        │ + ML.GENERATE_TEXT     │      └───────────────────────────────┘
        │ + ML.GENERATE_EMBEDDING│
        └────────────────────────┘
```

---

## 2. Curriculum Mapping: 10-Day Challenge Context

This codebase fulfills the complete requirements of the 10-Day Agentic Data Engineering Challenge ([`docs/challenge_context.md`](file:///usr/local/google/home/cfrancoisrael/repos/agentic-data-engineering-challenge-2/docs/challenge_context.md)):

| Day | Focus Topic | Core Implementation in this Repository | Key Deliverable / Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **Day 1** | Gen AI & Gemini Enterprise | `gemini-3.8-flash` configured via Vertex AI endpoint (`settings.LOCATION="global"`). | Baseline LLM orchestration setup. |
| **Day 2** | Vertex AI Studio & Multimodal | Multimodal PDF prompt extraction in BigQuery Object Tables (`model_extractor`). | Direct multimodal PDF comprehension. |
| **Day 3** | Google Cloud Agents & ADK | Initialized `google.adk` foundation (`Agent`, `Runner`, `AdkApp`). | Agent Development Kit architecture initialized. |
| **Day 4** | Prompt Engineering & Memory | System instructions with dynamic intent routing; Firestore session state (`agent/memory.py`). | Structured tool calling schemas and persistent turns. |
| **Day 5** | AgentOps & Governance | Cloud DLP guardrails (`agent/guardrails.py`), safety filters, and structured logging. | Guardrail and compliance foundation. |
| **Day 6** | Ingestion & Object Tables | `POST /v1/ingest`, BigQuery Object Table `documents_table`, `docs/ARCHITECTURE.md`, `docs/ADR-001-agentic-ingestion.md`. | Swagger UI (`/docs`) operational; non-blocking 202 async ingestion. |
| **Day 7** | Embeddings & Vector Search | `ML.GENERATE_EMBEDDING` (`embedding_model`), `CREATE VECTOR INDEX` (IVF COSINE), FastAPI `/search`. | `POST /search` returns top chunks with cosine similarity. |
| **Day 8** | ADK Conversational Agent | `clinical_trials_data_agent` with `execute_clinical_sql` & `search_clinical_protocols`. | Dynamic intent routing (SQL vs. Vector vs. Hybrid). |
| **Day 9** | Eventarc & A2A Governance | GCS Eventarc trigger, Pub/Sub DLQ, `verify_ingestion_payload_a2a()` with ADK runner. | Corrupted/PII files intercepted and routed to DLQ topic. |
| **Day 10**| AgentOps, Telemetry & Runtime | Cloud Trace (`OpenTelemetry`), Cloud Logging metrics (`agent_session_total_tokens`), Vertex AI Agent Engine deployment. | Token consumption & latency dashboards; concurrent load test. |

---

## 3. Core Modules: `/agent` (Agent Development Kit & LLM Ops)

All agent code lives in `/agent`. Built with `google-adk` (`google.adk`), `google-genai`, Vertex AI, and Cloud SDKs.

### 3.1 `agent/agent.py` - Primary Conversational Data Agent
- **Agent Name**: `clinical_trials_data_agent`
- **Model**: `gemini-3.8-flash` (Vertex AI endpoint with `GOOGLE_GENAI_USE_VERTEXAI=True`, `GOOGLE_CLOUD_LOCATION="global"`).
- **Sub-Agents**: `sub_agents=[governance_agent]` for live A2A delegation.
- **Safety & Callbacks**:
  - `generate_content_config=types.GenerateContentConfig(safety_settings=VERTEX_SAFETY_SETTINGS)`
  - `before_model_callback=pii_guardrail_before_model`
  - `after_model_callback=safety_response_monitor`
  - `before_tool_callback=sql_safety_before_tool`
- **Role**: Conversational router handling natural language queries through three registered tools:
  - `execute_clinical_sql`: Analytical queries (counts, trial statuses, grouping by status, filtering by `nct_id`).
  - `search_clinical_protocols`: Semantic / conceptual queries (inclusion/exclusion criteria, endpoints, dosing, adverse events).
  - `get_governance_verdict`: Retrieves persisted governance/compliance verdicts for a given `nct_id` from session state or Firestore.
  - *Hybrid*: Executes SQL first to retrieve/filter `nct_id`s, then vector search to query protocol contents.

### 3.2 `agent/tools.py` - ADK Function Tools
- `execute_clinical_sql(sql_query: str) -> Dict[str, Any]`
  - Queries: Fully qualified BigQuery table `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` (`studies_metadata`).
  - Columns: `nct_id`, `brief_title`, `overall_status`, `doc_filename`, `cdn_url`, `gcs_uri`.
  - Guardrail: Rejects queries not starting with `SELECT` or `WITH` (also enforced upfront by `sql_safety_before_tool`). Caps results to 50 rows.
  - Telemetry: Attaches `clinical.row_count` and `clinical.latency_ms` to the ambient ADK `execute_tool` span and resolves session ID via `get_active_conversation_id()`.
- `search_clinical_protocols(search_query: str, top_k: int = 5) -> Dict[str, Any]`
  - Queries: FastAPI RAG endpoint `POST {RAG_API_URL}` (`http://localhost:8080/search` or Cloud Run URL).
  - Auth: Automatically attaches OIDC identity tokens using GCP Metadata Server (in Cloud Run / Agent Engine) or `gcloud auth print-identity-token` (in Cloud Shell).
  - Returns: Retrieved chunks with `nct_id`, `section_type`, `gcs_uri`, `chunk_text`, `cosine_similarity`.
  - Telemetry: Attaches `clinical.chunks_retrieved` and `clinical.latency_ms` to the ambient ADK span and emits structured Cloud Logging metrics.
- `get_governance_verdict(nct_id: str, tool_context: Any = None) -> Dict[str, Any]`
  - Checks `tool_context.state` first (`governance_verdict:{nct_id}` / `latest_governance_verdict`), then queries `FirestoreSessionService.get_session_state_sync(f"session-{nct_id}")`.

### 3.3 `agent/governance_agent.py` - Agent-to-Agent (A2A) Governance & DLQ
- **Agent Name**: `clinical_trials_governance_agent` (Model: `gemini-3.8-flash`)
- **Tools**: `validate_document_schema`, `inspect_pii_and_sensitive_data`, `validate_file_integrity`.
- **Callback**: `after_agent_callback=record_governance_verdict_callback`.
- **Key Functions**:
  - `verify_ingestion_payload_a2a(payload: Dict[str, Any], session_id: Optional[str] = None, session_service: Optional[BaseSessionService] = None) -> Dict[str, Any]`:
    1. *Deterministic Session*: Resolves `session_id = session_id or f"session-{nct_id}"` using `get_session_service()` (`FirestoreSessionService`).
    2. *Fast deterministic pre-checks*: validates `nct_id` regex (`^NCT\d{8}$`), `.pdf` extension, non-zero file size, and raw regex for SSN/PII.
    3. *LLM validation*: Launches an ADK `Runner` with `FirestoreSessionService` to evaluate payload against Schema, File Integrity, and PII policies.
    4. *Persistence & Output*: Persists structured verdict (`governance_verdict:{nct_id}`, `latest_governance_verdict`) into Firestore session state and returns `{"verdict": "APPROVED" | "REJECTED", "reason": "..."}`.
  - `publish_to_dlq(payload: Dict[str, Any], reason: str) -> Optional[str]`:
    - Publishes rejected events to Cloud Pub/Sub DLQ topic (`DLQ_TOPIC_ID`, default: `clinical-trials-ingest-dlq`).
    - Emits structured error log: `🚨 [GOVERNANCE AGENT INTERCEPTED -> DLQ]`.

### 3.4 `agent/config.py` - Centralized Configuration
- Immutable dataclass `Settings` providing single source of truth for all GCP project names, dataset IDs, model names, and endpoints.
- Robust production defaults prevent accidental `"dummy-location"` or `"dummy-table"` failures during containerized or remote runtime execution.

### 3.5 `agent/guardrails.py` - Cloud DLP & Vertex Safety
- `redact_pii_dlp(text: str) -> Tuple[str, bool]`:
  - Uses Google Cloud DLP (`google.cloud.dlp_v2.DlpServiceClient`).
  - Target InfoTypes: `PERSON_NAME`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_SOCIAL_SECURITY_NUMBER`, `US_HEALTHCARE_NPI`.
  - De-identifies text replacing matches with `[INFO_TYPE]`. Returns `(sanitized_text, pii_detected_bool)`.
- `VERTEX_SAFETY_SETTINGS`: Configures `types.SafetySetting` for `HATE_SPEECH`, `DANGEROUS_CONTENT`, `SEXUALLY_EXPLICIT`, `HARASSMENT` at `BLOCK_MEDIUM_AND_ABOVE`.

### 3.6 `agent/memory.py` - Unified Firestore Session Service
- `FirestoreSessionService(BaseSessionService)`:
  - ADK-native persistent session provider backed by Cloud Firestore (`FIRESTORE_DATABASE`, `FIRESTORE_COLLECTION`), with automatic `InMemorySessionService` fallback for offline tests.
  - Implements `create_session`, `get_session`, `append_event`, `list_sessions`, `delete_session`, `update_session_state`, and `get_session_state_sync`.
- `get_session_service() -> FirestoreSessionService`: Singleton factory shared across ADK runners and tools.
- `SessionMemory` class: Backwards-compatible facade over the same Firestore collection (`add_turn`, `get_turns`).

### 3.7 `agent/telemetry.py` - FinOps & OpenTelemetry
- Tracer: `_init_cloud_trace_provider_if_needed()` checks `GOOGLE_CLOUD_AGENT_ENGINE_ID` / `GOOGLE_CLOUD_AGENT_ENGINE_LOCATION` so Agent Engine's native OTLP exporter (`telemetry.googleapis.com`) is never clobbered.
- `get_active_conversation_id()`: Extracts `gen_ai.conversation.id` from the active OpenTelemetry span attributes.
- Structured Cloud Logging: Emits zero-latency JSON payloads directly to `sys.stdout` for Cloud Run and Cloud Logging log-based metrics:
  - Metric 1: `agent_session_total_tokens` (distribution metric grouped by `session_id`).
  - Metric 2: `agent_execution_latency_ms` (distribution metric capturing execution latency).
  - FinOps Cost Formula: `(prompt_tokens * $0.000000075) + (response_tokens * $0.00000030)`.

### 3.8 `agent/callbacks.py` - ADK Guardrail Callbacks
- `pii_guardrail_before_model(ctx, llm_request)`: Intercepts user prompts before Gemini calls, redacts PII in-place via `redact_pii_dlp()`, and stamps `guardrail.pii.*` attributes on the ambient span.
- `safety_response_monitor(ctx, llm_response)`: Records `guardrail.response.finish_reason` and `guardrail.response.safety_blocked` on the ambient span.
- `sql_safety_before_tool(tool, args, ctx)`: Intercepts `execute_clinical_sql` calls and blocks any query not starting with `SELECT` or `WITH`.

---

## 4. Core Modules: `/pipeline` (FastAPI Serving & Ingestion)

All API and serving logic lives in `/pipeline`.

### 4.1 `pipeline/main.py` - Application Endpoints
- Port: `8080`.
- **`POST /v1/ingest`** (Status 202 Accepted):
  - Stages document URI `gs://{BUCKET_NAME}/raw/{nct_id}/{filename}`. Non-blocking acknowledgment for async upload.
- **`GET /v1/metadata/{id}`**:
  - Joins `studies_metadata` with `extracted_doc_chunks` on `nct_id`.
  - Returns metadata + total count of extracted sections.
- **`POST /search`**:
  - Checks prompt with `redact_pii_dlp(req.query)`.
  - Generates query embedding via BigQuery `ML.GENERATE_EMBEDDING` and runs `VECTOR_SEARCH` against `embedded_doc_chunks` with `COSINE` distance.
  - Returns matching chunks with `cosine_similarity = ROUND(1.0 - distance, 4)`.
  - Emits telemetry and OpenTelemetry spans.
- **`POST /v1/events/gcs-ingest`** (Eventarc Webhook):
  - Decodes incoming Pub/Sub push envelope or direct Eventarc CloudEvent.
  - Derives deterministic `session_id = f"session-{nct_id}"` and executes A2A verification via `verify_ingestion_payload_a2a(event_payload, session_id=session_id)`. If rejected, routes to DLQ and returns 200/202.
  - Fetches study metadata from ClinicalTrials.gov API v2 and performs an idempotent BigQuery `MERGE` into `studies_metadata`.
  - Executes incremental extraction and embedding queries via `pipeline/queries.py`.
- **`POST /v1/chat`** (Agent Runtime Proxy):
  - Connects to the deployed Vertex AI Agent Engine (`AGENT_ENGINE_RESOURCE_NAME`).
  - Creates or resumes a managed session and streams tokens back to client.

### 4.2 `pipeline/queries.py` - Modular BigQuery SQL Templates
Contains dedicated, parameterized SQL builder functions with built-in idempotency:
- `build_upsert_metadata_query()`: Uses `MERGE INTO studies_metadata` to insert or update trial records idempotently.
- `build_incremental_extraction_query()`: Runs `ML.GENERATE_TEXT` with `SAFE.PARSE_JSON` and filters `WHERE gcs_uri NOT IN (SELECT gcs_uri FROM extracted_doc_chunks)`.
- `build_incremental_embedding_query()`: Runs `ML.GENERATE_EMBEDDING` on un-embedded chunks into `embedded_doc_chunks`.
- `build_semantic_search_query()`: Generates query embedding on-the-fly and executes `VECTOR_SEARCH`.
- `build_metadata_query()`: Reads study metadata joined with chunk counts.

### 4.3 `pipeline/metadata_service.py` - ClinicalTrials.gov API Integration
- `fetch_study_metadata_or_fallback(nct_id, filename, gcs_uri)`:
  - Queries `https://clinicaltrials.gov/api/v2/studies/{nct_id}`.
  - Extracts official `briefTitle` and `overallStatus`.
  - Generates deterministic fallback values if the external API is unreachable or rate-limited.

---

## 5. Deployment Architecture: Vertex AI Agent Engine (Agent Runtime)

The conversational ADK agent is deployed to **Vertex AI Agent Engine** (managed Reasoning Engine runtime):

### 5.1 Deployment Script (`scripts/deploy_agent_runtime.py`)
- Uses modern template: `from vertexai.agent_engines import AdkApp`.
- Wraps `root_agent` with OpenTelemetry tracing: `adk_app = AdkApp(agent=root_agent, enable_tracing=True)`.
- Deploys via `agent_engines.create()` with:
  - `service_account="80080086039-compute@developer.gserviceaccount.com"` (BYOSA).
  - Explicit production `env_vars`: `LOCATION="global"`, `GOOGLE_CLOUD_LOCATION="global"`, `BQ_DATASET="clinical_trials_2"`, `BQ_TABLE="studies_metadata"`, `RAG_API_URL="..."`.
  - Pinned requirements: `google-adk==2.12.0`, `google-cloud-aiplatform[agent_engines,adk]>=2.9.0`.

### 5.2 Virtual Environment & Deployment Contract
- Vertex AI Agent Engine remote containers execute on managed Google Cloud infrastructure.
- Deployment and testing scripts must be executed inside the project's primary virtual environment (`.venv`):
- Deployment invocation:
  ```bash
  source .venv/bin/activate
  python scripts/deploy_agent_runtime.py
  # or directly:
  ./.venv/bin/python scripts/deploy_agent_runtime.py
  ```

### 5.3 Testing Agent Engine & Unified Verification
```bash
export AGENT_ENGINE_RESOURCE_NAME="projects/80080086039/locations/us-central1/reasoningEngines/5928414139729838080"
./.venv/bin/python scripts/test_agent_runtime.py

# Unit tests for FirestoreSessionService & inter-agent verdict lookup
./.venv/bin/python tests/test_firestore_session_service.py

# Full end-to-end verification (Days 6-10 + Agent Runtime)
./.venv/bin/python scripts/final_challenge_test.py --url "<CLOUD_RUN_URL>" --auth --verify-runtime
```

---

## 6. Key Invariants & Rules for Coding Agents

1. **Always Preserve Read-Only Safety**: `execute_clinical_sql` must remain restricted to `SELECT` and `WITH` statements.
2. **Deterministic Pre-Checks Before LLM**: In `agent/governance_agent.py`, regex checks (`NCT\d{8}`, file size, obvious SSN patterns) must run before calling ADK runner to conserve tokens and minimize latency.
3. **Escaping Inside BigQuery F-strings**: In `pipeline/queries.py`, SQL blocks inside Python strings must format unescaped regex (`\d{8}`) cleanly without breaking string interpolation.
4. **Cloud Run Concurrency**: The `/search` endpoint is stateless; state is maintained in Firestore (`agent_sessions`) and BigQuery. Do not store in-memory session dictionaries.
5. **FinOps & Telemetry Invariant**: Every tool execution and user chat request must emit structured Cloud Logging JSON metrics with `session_id`, `latency_ms`, `total_tokens`, and `estimated_cost_usd` to ensure Cloud Monitoring dashboards stay populated.
6. **Virtual Environment Standard**: Execute all local verification, pipeline runs, and deployment tasks within the project's active `.venv` environment.
