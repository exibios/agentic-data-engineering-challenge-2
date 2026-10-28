import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pipeline.schemas import (
    IngestRequest,
    IngestResponse,
    DocumentMetadataResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    ChunkResult
)

app = FastAPI(
    title="Autonomous Agentic Data Pipeline API",
    description="Ingestion, Metadata Extraction, and BigQuery Vector RAG API",
    version="1.0.0"
)

BUCKET_NAME = "data4ai-challenge-03-agentic-data-engineering-raw-docs-2"

@app.post("/v1/ingest", response_model=IngestResponse, status_code=202, tags=["Ingestion"])
async def ingest_document(payload: IngestRequest):
    """
    Stages a document in GCS to trigger asynchronous Eventarc/Pub/Sub extraction
    and Governance Agent validation.
    """
    last_two = payload.nct_id[-2:]
    cdn_url = payload.source_url or f"https://cdn.clinicaltrials.gov/large-docs/{last_two}/{payload.nct_id}/{payload.filename}"
    gcs_uri = f"gs://{BUCKET_NAME}/raw/{payload.nct_id}/{payload.filename}"

    # Note: Wire up httpx download + GCS blob upload here
    return IngestResponse(
        ingestion_id=str(uuid.uuid4()),
        nct_id=payload.nct_id,
        gcs_uri=gcs_uri,
        status="QUEUED_ASYNC_EXTRACTION",
        timestamp=datetime.now(timezone.utc)
    )

@app.get("/v1/metadata/{id}", response_model=DocumentMetadataResponse, tags=["Metadata"])
async def get_document_metadata(id: str):
    """
    Fetches structured trial metadata and BigQuery Object Table extraction state by NCTId.
    """
    if not id.startswith("NCT"):
        raise HTTPException(status_code=400, detail="ID must be a valid NCTId (e.g., NCT04001234)")

    # Note: Query BigQuery `studies_metadata` JOIN `extracted_doc_chunks` on nct_id
    return DocumentMetadataResponse(
        nct_id=id,
        brief_title="Sample Clinical Trial Protocol",
        overall_status="RECRUITING",
        gcs_uri=f"gs://{BUCKET_NAME}/raw/{id}/protocol.pdf",
        file_size_bytes=452190,
        extracted_summary={"phase": "Phase 2", "primary_endpoint": "Overall Response Rate"},
        governance_status="VERIFIED",
        updated_at=datetime.now(timezone.utc)
    )

@app.post("/search", response_model=SemanticSearchResponse, tags=["Vector Search"])
async def semantic_search(request: SemanticSearchRequest):
    """
    Executes semantic search over BigQuery Vector Index and returns chunks with cosine similarity.
    """
    # Note: On Day 7, replace stub query with BigQuery VECTOR_SEARCH() SQL call
    return SemanticSearchResponse(
        query=request.query,
        results=[
            ChunkResult(
                nct_id="NCT04001234",
                gcs_uri=f"gs://{BUCKET_NAME}/raw/NCT04001234/protocol.pdf",
                chunk_text="Inclusion Criteria: Patients aged 18-75 with confirmed diagnosis...",
                cosine_similarity=0.892
            )
        ]
    )
