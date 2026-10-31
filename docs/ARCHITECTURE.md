# Autonomous Agentic Data Pipeline Architecture

## 1. End-to-End Architecture Diagram

```mermaid
flowchart LR
    subgraph Sources["1. ClinicalTrials.gov"]
        API["API v2 (/studies)"]
        CDN["CDN (Raw PDFs)"]
    end

    subgraph Ingestion["2. Async Event-Driven Ingestion"]
        GCS[("GCS Bucket\ndata4ai-challenge-03-...-raw-docs-2")]
        EV["Eventarc + Pub/Sub"]
        GOV["Governance Agent (A2A)\nSchema & Cloud DLP Check"]
        DLQ[["Dead-Letter Queue (DLQ)"]]
    end

    subgraph BigQuery["3. BigQuery AI & Vector Layer (clinical_trials_2)"]
        META[("studies_metadata")]
        OBJ[("raw_documents_object_table\n(Conn: us.agentic_conn)")]
        EXT["ML.GENERATE_TEXT\n(gemini-3.8-flash)"]
        CHUNKS[("extracted_doc_chunks\n(section_type, chunk_text)")]
        EMB["ML.GENERATE_EMBEDDING\n(gemini-embedding-001)"]
        VEC[("embedded_doc_chunks\n+ Cosine Vector Index")]
    end

    subgraph Serving["4. RAG & Agent Serving"]
        FASTAPI["FastAPI on Cloud Run\n(/v1/ingest, /v1/metadata, /search)"]
        FS[("Firestore\nSession Memory")]
        ADK["Main Data Agent (ADK)\nSQL Tool + Vector Search Tool"]
    end

    API --> META
    CDN --> GCS
    GCS --> EV --> GOV
    GOV -->|Reject| DLQ
    GOV -->|Approve| OBJ
    GCS -.-> OBJ
    OBJ --> EXT --> CHUNKS --> EMB --> VEC
    VEC <--> FASTAPI
    META <--> FASTAPI
    FASTAPI <--> FS
    ADK <--> FASTAPI
    ADK <--> META
```

2. Unstructured-to-Structured Flow
GCS & Object Table: Raw PDFs land in gs://data4ai-challenge-03-agentic-data-engineering-raw-docs-2/raw/. The BigQuery Object Table (raw_documents_object_table) catalogs these files via the data4ai-challenge-03.us.agentic_conn connection.

Multimodal Section Extraction: ML.GENERATE_TEXT invokes gemini-3.8-flash directly over the Object Table URIs, extracting structured clinical sections (Study Overview, Inclusion Criteria, Exclusion Criteria, Primary Endpoints, Dosing & Intervention) and unnesting them into extracted_doc_chunks.

Vector Indexing: ML.GENERATE_EMBEDDING calls gemini-embedding-001 to embed each section chunk into embedded_doc_chunks, indexed with CREATE VECTOR INDEX (COSINE distance).


3. Why Asynchronous Ingestion (Eventarc + Pub/Sub)?
Non-Blocking Latency: Multimodal PDF extraction and DLP inspection take several seconds per document. Asynchronous ingestion returns HTTP 202 Accepted immediately while processing files in the background.

Rate-Limit Buffering & Backpressure: Pub/Sub absorbs burst uploads and protects Vertex AI quotas (gemini-3.8-flash and gemini-embedding-001), routing corrupted or policy-violating files to a Dead-Letter Queue (DLQ).