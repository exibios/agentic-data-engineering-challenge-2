# pipeline/main.py
from datetime import datetime, timezone
import os
import uuid
from fastapi import FastAPI, HTTPException
from google.cloud import bigquery
from agent.memory import SessionMemory
from pipeline.schemas import (
    ChunkHit,
    IngestRequest,
    IngestResponse,
    MetadataResponse,
    SearchRequest,
    SearchResponse,
)

# === Environment Configuration ===
PROJECT_ID = os.getenv("GCP_PROJECT", "data4ai-challenge-03")
DATASET_ID = os.getenv("BQ_DATASET", "clinical_trials_2")
BUCKET_NAME = os.getenv(
    "GCS_BUCKET", "data4ai-challenge-03-agentic-data-engineering-raw-docs-2"
)

app = FastAPI(
    title="Clinical Trials Agentic Data Pipeline API",
    description="Day 6 & Day 7: Ingestion, Metadata, and BigQuery Vector Search RAG API",
    version="1.0.0",
)

bq_client = bigquery.Client(project=PROJECT_ID)
memory = SessionMemory()


@app.post("/v1/ingest", response_model=IngestResponse, status_code=202)
async def ingest_document(req: IngestRequest):
  """Registers a document upload target in GCS for async Eventarc/PubSub ingestion."""
  gcs_uri = f"gs://{BUCKET_NAME}/raw/{req.nct_id}/{req.filename}"
  return IngestResponse(
      ingestion_id=str(uuid.uuid4()),
      nct_id=req.nct_id,
      gcs_uri=gcs_uri,
      status="QUEUED_ASYNC_EXTRACTION",
      timestamp=datetime.now(timezone.utc),
  )


@app.get("/v1/metadata/{id}", response_model=MetadataResponse)
async def get_metadata(id: str):
  """Retrieves trial metadata and count of extracted chunks from BigQuery."""
  sql = f"""
      SELECT
        m.nct_id,
        ANY_VALUE(m.brief_title) AS brief_title,
        ANY_VALUE(m.overall_status) AS overall_status,
        ANY_VALUE(m.gcs_uri) AS gcs_uri,
        COUNT(c.chunk_id) AS chunks_count
      FROM `{PROJECT_ID}.{DATASET_ID}.studies_metadata` m
      LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.extracted_doc_chunks` c
        ON m.nct_id = c.nct_id AND m.gcs_uri = c.gcs_uri
      WHERE m.nct_id = @nct_id
      GROUP BY m.nct_id
  """
  job_config = bigquery.QueryJobConfig(
      query_parameters=[bigquery.ScalarQueryParameter("nct_id", "STRING", id)]
  )
  rows = list(bq_client.query(sql, job_config=job_config).result())
  if not rows:
    raise HTTPException(status_code=404, detail=f"NCTId {id} not found")

  r = rows[0]
  return MetadataResponse(
      nct_id=r["nct_id"],
      brief_title=r["brief_title"],
      overall_status=r["overall_status"],
      gcs_uri=r["gcs_uri"],
      extracted_sections_count=r["chunks_count"],
  )


@app.post("/search", response_model=SearchResponse)
async def semantic_search(req: SearchRequest):
  """Embeds the query with gemini-embedding-001 and runs VECTOR_SEARCH in BigQuery."""
  sql = f"""
      WITH query_vec AS (
        SELECT ml_generate_embedding_result AS q_embedding
        FROM ML.GENERATE_EMBEDDING(
          MODEL `{PROJECT_ID}.{DATASET_ID}.embedding_model`,
          (SELECT @query_text AS content),
          STRUCT(TRUE AS flatten_json_output)
        )
      )
      SELECT
        base.nct_id,
        base.section_type,
        base.gcs_uri,
        base.chunk_text,
        ROUND(1.0 - distance, 4) AS cosine_similarity
      FROM
        VECTOR_SEARCH(
          TABLE `{PROJECT_ID}.{DATASET_ID}.embedded_doc_chunks`,
          'text_embedding',
          TABLE query_vec,
          top_k => @top_k,
          distance_type => 'COSINE'
        )
      ORDER BY cosine_similarity DESC
  """
  job_config = bigquery.QueryJobConfig(
      query_parameters=[
          bigquery.ScalarQueryParameter("query_text", "STRING", req.query),
          bigquery.ScalarQueryParameter("top_k", "INT64", req.top_k),
      ]
  )

  try:
    rows = list(bq_client.query(sql, job_config=job_config).result())
  except Exception as e:
    raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")

  hits = [
      ChunkHit(
          nct_id=row["nct_id"],
          section_type=row["section_type"],
          gcs_uri=row["gcs_uri"],
          chunk_text=row["chunk_text"],
          cosine_similarity=float(row["cosine_similarity"]),
      )
      for row in rows
  ]

  # Persist conversational context in Firestore if session_id is provided
  if req.session_id:
    try:
      memory.add_turn(req.session_id, "user", req.query)
    except Exception:
      pass  # Non-blocking if Firestore is not yet enabled locally

  return SearchResponse(query=req.query, results=hits)
