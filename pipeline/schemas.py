from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime

class IngestRequest(BaseModel):
    nct_id: str = Field(..., pattern=r"^NCT\d{8}$", examples=["NCT04001234"])
    doc_type: str = Field(..., description="Protocol, SAP, or ICF", examples=["Protocol"])
    filename: str = Field(..., examples=["protocol.pdf"])
    source_url: Optional[HttpUrl] = Field(
        None, examples=["https://cdn.clinicaltrials.gov/large-docs/34/NCT04001234/protocol.pdf"]
    )
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class IngestResponse(BaseModel):
    ingestion_id: str
    nct_id: str
    gcs_uri: str
    status: str = Field(..., examples=["QUEUED_ASYNC_EXTRACTION"])
    timestamp: datetime

class DocumentMetadataResponse(BaseModel):
    nct_id: str
    brief_title: Optional[str] = None
    overall_status: Optional[str] = None
    gcs_uri: str
    content_type: str = "application/pdf"
    file_size_bytes: Optional[int] = None
    extracted_summary: Optional[Dict[str, Any]] = None
    governance_status: str = "VERIFIED"
    updated_at: datetime

class SemanticSearchRequest(BaseModel):
    query: str = Field(..., examples=["What are the inclusion criteria for phase 2 trials?"])
    top_k: int = Field(default=5, ge=1, le=20)

class ChunkResult(BaseModel):
    nct_id: str
    gcs_uri: str
    chunk_text: str
    cosine_similarity: float

class SemanticSearchResponse(BaseModel):
    query: str
    results: List[ChunkResult]
