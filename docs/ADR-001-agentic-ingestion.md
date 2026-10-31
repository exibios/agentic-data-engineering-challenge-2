# ADR-001: Chunking Strategy, Model Selection, Schema Evolution, and SDP Governance

## 1. Chunking Strategy: Prompt-Driven Semantic Section Chunking
- **Decision:** Use `gemini-3.8-flash` via BigQuery `ML.GENERATE_TEXT` to segment each PDF into logical clinical sections (`Study Overview`, `Inclusion Criteria`, `Exclusion Criteria`, `Primary Endpoints`, `Dosing & Intervention`) and unnest them into individual rows with `section_type` and `chunk_text`. Prepend `NCTId` and `section_type` to `chunk_text` prior to embedding with `gemini-embedding-001`.
- **Rationale:** Naive character splitting breaks clinical tables and eligibility bullet lists across chunks. Section-aligned chunks preserve clinical semantics and maximize cosine similarity accuracy during `VECTOR_SEARCH`.

## 2. Model Selection: `gemini-3.8-flash` vs. Pro Models
- **Decision:** Use `gemini-3.8-flash` for bulk PDF metadata/section extraction and Governance Agent validation; reserve Pro models for complex multi-step reasoning in the conversational Data Agent.
- **Rationale:** `gemini-3.8-flash` provides native multimodal PDF comprehension at significantly lower latency and token cost per document, aligning with Day 10 FinOps telemetry requirements.

## 3. Schema Evolution Policy
- **Decision:** Enforce backward-compatible schema evolution verified via the Agent-to-Agent (A2A) Governance loop. Additive nullable fields are permitted; missing required keys (`nct_id`), type mutations, or unparseable documents are rejected to the Dead-Letter Queue (DLQ).

## 4. Sensitive Data Protection (Cloud DLP / SDP)
- **Decision:** Inspect ingested chunks and user prompts for PII/PHI (`PERSON_NAME`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `MEDICAL_RECORD_NUMBER`) via Cloud DLP prior to indexing or LLM generation.
