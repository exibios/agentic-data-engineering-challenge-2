# pipeline/schemas.py
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
  nct_id: str = Field(..., examples=["NCT04001234"])
  filename: str = Field(..., examples=["Prot_000.pdf"])
  doc_type: str = Field(default="Protocol", examples=["Protocol"])


class IngestResponse(BaseModel):
  ingestion_id: str
  nct_id: str
  gcs_uri: str
  status: str
  timestamp: datetime


class MetadataResponse(BaseModel):
  nct_id: str
  brief_title: Optional[str] = None
  overall_status: Optional[str] = None
  gcs_uri: Optional[str] = None
  extracted_sections_count: int = 0


class SearchRequest(BaseModel):
  query: str = Field(
      ..., examples=["What are the inclusion criteria and dosing schedule?"]
  )
  top_k: int = Field(default=5, ge=1, le=20)
  session_id: Optional[str] = Field(default="demo-session-01")


class ChunkHit(BaseModel):
  nct_id: str
  section_type: str
  gcs_uri: str
  chunk_text: str
  cosine_similarity: float


class SearchResponse(BaseModel):
  query: str
  results: List[ChunkHit]
