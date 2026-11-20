# ADR-001: Agentic Ingestion, Semantic Chunking, Model Selection, Schema Evolution, and Governance Architecture

- **Status:** Approved / Accepted
- **Date:** October 2026 (Updated November 2026 for Agent Runtime v2)
- **Context:** Google Cloud Partner Data Agent Challenge (Days 6–10)
- **Scope:** Document ingestion, chunking strategy, remote model selection, schema evolution, A2A data governance, and Agent Runtime hosting.

---

## 1. Context & Problem Statement

Clinical trial documents (Protocols, Statistical Analysis Plans [SAPs], Informed Consent Forms [ICFs]) from ClinicalTrials.gov are dense, multi-page PDFs (typically 10–50+ pages) containing complex medical terminology, tabular inclusion/exclusion criteria, primary endpoints, and strict dosing schedules.

Traditional ETL pipelines face three core failure modes when processing these documents for Retrieval-Augmented Generation (RAG):
1. **Naive Chunking Loss**: Fixed-character or recursive token chunking cuts clinical tables and exclusion criteria lists in half, creating out-of-context chunks that confuse semantic retrieval and generate hallucinated agent answers.
2. **Synchronous Ingestion Bottlenecks**: Extracting multimodal content and generating vector embeddings takes several seconds per PDF. Synchronous ingestion causes HTTP timeouts and degrades client-facing throughput.
3. **Data Quality & Privacy Risks**: Uploaded documents may contain corrupted bytes, unexpected schema alterations, or sensitive patient Protected Health Information (PHI) / Personally Identifiable Information (PII) that violates HIPAA and GDPR.

---

## 2. Decision Summary

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Core Architectural Decisions                      │
├────────────────────────────────┬───────────────────────────────────────┤
│ 1. Chunking Strategy           │ Prompt-Driven Semantic Sectioning     │
│ 2. Model Selection             │ gemini-3.8-flash (Extraction/Agent)   │
│                                │ gemini-embedding-001 (Vector Store)   │
│ 3. Ingestion Architecture      │ Asynchronous Eventarc + Pub/Sub       │
│ 4. Governance & Compliance     │ Inter-Agent (A2A) Governance Loop+DLP │
│ 5. Schema Evolution            │ Additive Nullable + Idempotent MERGE  │
│ 6. Agent Hosting               │ Vertex AI Agent Engine (Agent Runtime)│
└────────────────────────────────┴───────────────────────────────────────┘
```

---

## 3. Detailed Architectural Decisions

### 3.1 Decision 1: Prompt-Driven Semantic Section Chunking
- **Decision:** Segment PDFs into 5 clinically meaningful sections using BigQuery `ML.GENERATE_TEXT` with `gemini-3.8-flash` directly over the BigQuery Object Table:
  1. `Study Overview` (Objectives, phase, study design)
  2. `Inclusion Criteria` (Full patient eligibility list)
  3. `Exclusion Criteria` (Full contraindication list)
  4. `Primary Endpoints` (Efficacy and safety measurement criteria)
  5. `Dosing & Intervention` (Drug dosages, delivery schedules)
  Each section is stored as an individual row in `extracted_doc_chunks` prefixed with `NCTId` and `section_type`.
- **Alternatives Considered:**
  - *Fixed-Character Chunking (e.g. 1000 chars with 200 overlap)*: Rejected. Arbitrary cutoffs severed inclusion criteria halfway through numbered lists, causing the Data Agent to retrieve incomplete patient safety criteria.
  - *Client-Side PDF Parsing (PyPDF / pdfminer)*: Rejected. Complex multi-column layouts, tables, and headers in clinical protocols frequently degrade into unparseable text streams. Gemini's native multimodal vision parses tables accurately.
- **Consequences:** Maximizes cosine similarity retrieval quality; each chunk represents a complete, self-contained clinical decision domain.

### 3.2 Decision 2: Model Selection Strategy
- **Decision:** Use `gemini-3.8-flash` for extraction, governance validation, and conversational reasoning; use `gemini-embedding-001` for vector representations.
- **Rationale:**
  - **Latency**: `gemini-3.8-flash` delivers sub-second multimodal document extraction, whereas Pro models incur 3–4x higher latency.
  - **FinOps & Cost Efficiency**: At $0.075 / 1M input tokens and $0.30 / 1M output tokens, Flash models reduce operational costs by over 75% compared to Gemini Pro, satisfying the Day 10 FinOps cost criteria.
  - **Accuracy**: Gemini Flash provides more than sufficient clinical comprehension to identify eligibility criteria and structure JSON outputs with `SAFE.PARSE_JSON`.

### 3.3 Decision 3: Asynchronous Ingestion & Event-Driven Decoupling
- **Decision:** Decouple document ingestion using Google Cloud Storage (GCS) $\rightarrow$ Eventarc $\rightarrow$ Cloud Pub/Sub $\rightarrow$ Cloud Run webhook (`/v1/events/gcs-ingest`).
- **Rationale:**
  - Client uploads receive an immediate `202 Accepted` response.
  - Pub/Sub provides native message buffering, automatic retries with exponential backoff, and dead-letter queueing, insulating downstream BigQuery quotas from traffic bursts.

### 3.4 Decision 4: Agent-to-Agent (A2A) Governance & Dead-Letter Queue (DLQ)
- **Decision:** Establish an automated Agent-to-Agent (A2A) validation checkpoint before BigQuery ingestion. The pipeline invokes `clinical_trials_governance_agent` to review the incoming document payload against three policies:
  1. **Schema Policy**: Strict NCT ID format (`^NCT\d{8}$`), `.pdf` filename extension, and valid metadata fields.
  2. **File Integrity Policy**: Object size $> 0$ bytes, non-corrupted header.
  3. **PII/PHI Compliance Policy**: Zero unredacted patient identifiers (SSNs, medical record numbers, patient names). Cloud DLP inspects sample text.
  - Violations are immediately intercepted, published to `clinical-trials-ingest-dlq`, and logged with `🚨 [GOVERNANCE AGENT INTERCEPTED -> DLQ]`.
- **Rationale:** Guarantees that untrusted external inputs cannot corrupt the enterprise clinical lakehouse.

### 3.5 Decision 5: Idempotency & Schema Evolution Policy
- **Decision:**
  - Enforce backward-compatible schema evolution: additive nullable columns are permitted; dropping required fields (`nct_id`) or type mutations are rejected.
  - Implement idempotent BigQuery upserts using `MERGE INTO studies_metadata` keyed on `nct_id`.
  - Filter incremental extraction queries with `WHERE gcs_uri NOT IN (SELECT gcs_uri FROM extracted_doc_chunks)` and incremental embedding with `WHERE chunk_id NOT IN (SELECT chunk_id FROM embedded_doc_chunks)`.
- **Rationale:** Enables safe replay of events and prevents duplicate rows or runaway embedding API costs when re-processing files.

### 3.6 Decision 6: Hosting the Conversational Agent on Vertex AI Agent Engine
- **Decision:** Package and deploy the conversational ADK agent (`root_agent`) onto **Vertex AI Agent Engine** (`vertexai.agent_engines.AdkApp`) using Bring Your Own Service Account (BYOSA).
- **Rationale:**
  - Managed serverless lifecycle with automatic scaling.
  - Out-of-the-box managed session memory and conversational history tracking.
  - Native integration with Google Cloud Trace via OpenTelemetry (`enable_tracing=True`).
  - Strict compliance and IAM boundary via `80080086039-compute@developer.gserviceaccount.com`.

---

## 4. Consequences & Verification

### Positive Consequences
- **High Retrieval Precision**: Clinical researchers can search for specific inclusion/exclusion criteria and receive grounded, cited answers with similarity scores.
- **Enterprise Safety**: Corrupted or PII-violating files are blocked before touching BigQuery.
- **Complete Observability**: OpenTelemetry spans and structured Cloud Logging metrics monitor token costs and latency in real time.

### Negative / Trade-Offs
- **Packaging & Cloudpickle Dependency Alignment**: Serializing `AdkApp` via `cloudpickle` packages object models from the local environment (`.venv`); package versions and definitions must match the remote container's dependencies to prevent descriptor deserialization errors.
- **Eventual Consistency**: Asynchronous extraction introduces a small processing delay (typically 5–15 seconds) between file upload to GCS and chunk availability in BigQuery vector search.
