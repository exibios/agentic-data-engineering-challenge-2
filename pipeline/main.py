# pipeline/main.py
import asyncio
import base64
from datetime import datetime, timezone
import json
import re
import os
import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from google.cloud import bigquery
from agent.clients import get_bq_client
from agent.config import settings
from agent.governance_agent import verify_ingestion_payload_a2a
from agent.guardrails import redact_pii_dlp
from agent.memory import SessionMemory
from agent.telemetry import log_agent_session_metrics, tracer
from pipeline.metadata_service import fetch_study_metadata_or_fallback
from pipeline.queries import (
    build_incremental_embedding_query,
    build_incremental_extraction_query,
    build_metadata_query,
    build_semantic_search_query,
    build_upsert_metadata_query,
)
from pipeline.schemas import (
    ChunkHit,
    IngestRequest,
    IngestResponse,
    MetadataResponse,
    SearchRequest,
    SearchResponse,
    ChatRequest,
)
import vertexai
from vertexai import agent_engines

app = FastAPI(
    title="Clinical Trials Agentic Data Pipeline API",
    description="Day 6 & Day 7: Ingestion, Metadata, and BigQuery Vector Search RAG API",
    version="1.0.0",
)

memory = SessionMemory()


# === Helper Functions for Non-Blocking Database Execution ===
def _run_query(sql_str: str, config: bigquery.QueryJobConfig) -> list:
  """Executes a synchronous BigQuery query in a worker thread."""
  return list(get_bq_client().query(sql_str, job_config=config).result())


def _execute_incremental_ingest(
    extract_sql: str, embed_sql: str, config: bigquery.QueryJobConfig
) -> int:
  """Executes incremental extraction and embedding queries in a worker thread."""
  bq = get_bq_client()
  extract_job = bq.query(extract_sql, job_config=config)
  extract_job.result()
  rows_extracted = extract_job.num_dml_affected_rows or 0

  if rows_extracted > 0:
    embed_job = bq.query(embed_sql, job_config=config)
    embed_job.result()

  return rows_extracted


# === API Endpoints ===
@app.post("/v1/ingest", response_model=IngestResponse, status_code=202)
async def ingest_document(req: IngestRequest):
  """Registers a document upload target in GCS for async Eventarc/PubSub ingestion."""
  gcs_uri = f"gs://{settings.BUCKET_NAME}/raw/{req.nct_id}/{req.filename}"
  return IngestResponse(
      ingestion_id=str(uuid.uuid4()),
      nct_id=req.nct_id,
      gcs_uri=gcs_uri,
      status="QUEUED_ASYNC_EXTRACTION",
      timestamp=datetime.now(timezone.utc),
  )


@app.get("/v1/metadata/{id}", response_model=MetadataResponse)
async def get_metadata(id: str):
  """Retrieves trial metadata and count of extracted chunks from BigQuery (non-blocking)."""
  sql = build_metadata_query(
      project_id=settings.PROJECT_ID,
      dataset_id=settings.DATASET_ID,
      table_id=settings.TABLE_ID,
  )
  job_config = bigquery.QueryJobConfig(
      query_parameters=[bigquery.ScalarQueryParameter("nct_id", "STRING", id)]
  )

  try:
    rows = await asyncio.to_thread(_run_query, sql, job_config)
  except Exception as e:
    raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")

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
  """Embeds query and executes BigQuery VECTOR_SEARCH with DLP and Telemetry (non-blocking)."""
  start_time = time.time()
  session_id = req.session_id or "default-session"

  with tracer.start_as_current_span("semantic_vector_search") as span:
    # 1. Cloud DLP Guardrail Check
    sanitized_query, pii_detected = redact_pii_dlp(req.query)
    span.set_attribute("pii_detected", pii_detected)

    # 2. BigQuery Vector Search (Offloaded to worker thread)
    sql = build_semantic_search_query(
        project_id=settings.PROJECT_ID,
        dataset_id=settings.DATASET_ID,
        embedding_model=settings.EMBEDDING_MODEL,
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "query_text", "STRING", sanitized_query
            ),
            bigquery.ScalarQueryParameter("top_k", "INT64", req.top_k),
        ]
    )

    try:
      rows = await asyncio.to_thread(_run_query, sql, job_config)
    except Exception as e:
      raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")

    hits = [
        ChunkHit(
            nct_id=r["nct_id"],
            section_type=r["section_type"],
            gcs_uri=r["gcs_uri"],
            chunk_text=r["chunk_text"],
            cosine_similarity=float(r["cosine_similarity"]),
        )
        for r in rows
    ]

    # 3. Calculate latency and tokens for FinOps tracking
    latency_ms = (time.time() - start_time) * 1000.0
    approx_prompt_tokens = len(sanitized_query.split()) * 2
    approx_response_tokens = sum(len(h.chunk_text.split()) for h in hits)

    span.set_attribute("latency_ms", latency_ms)
    span.set_attribute("total_hits", len(hits))

    # Structured Cloud Logging for Dashboard
    log_agent_session_metrics(
        session_id=session_id,
        user_prompt=sanitized_query,
        tool_selected="search_clinical_protocols",
        latency_ms=latency_ms,
        prompt_tokens=approx_prompt_tokens,
        response_tokens=approx_response_tokens,
        pii_intercepted=pii_detected,
    )

    return SearchResponse(query=sanitized_query, results=hits)


@app.post("/v1/events/gcs-ingest", tags=["Eventarc A2A Ingestion"])
async def handle_eventarc_gcs_upload(request: Request):
  """Receives GCS Object Finalize events, runs A2A Governance, and triggers incremental BQ extraction."""
  raw_body = await request.json()

  # 1. Unpack Pub/Sub Push base64 envelope or Eventarc 'data' envelope if present
  if "message" in raw_body and "data" in raw_body["message"]:
    decoded = base64.b64decode(raw_body["message"]["data"]).decode("utf-8")
    body = json.loads(decoded)
  elif "data" in raw_body and isinstance(raw_body["data"], dict):
    body = raw_body["data"]
  else:
    body = raw_body

  bucket = body.get("bucket", settings.BUCKET_NAME)
  object_name = body.get("name", "")

  # GUARD CLAUSE: Only process files inside the raw/ folder. Ignore everything else.
  if not object_name.startswith("raw/"):
    print(f"🛡️ Ignoring object outside ingestion scope: {object_name}", flush=True)
    return {"status": "ignored", "reason": "outside raw prefix"}

  size_bytes = int(body.get("size", 1024))
  sample_text = body.get("sample_text", "")

  # Extract NCTId from path `raw/NCT12345678/filename.pdf`
  nct_match = re.search(r"(NCT\d{8})", object_name)
  nct_id = nct_match.group(1) if nct_match else "UNKNOWN_NCT"
  gcs_uri = f"gs://{bucket}/{object_name}"

  event_payload = {
      "nct_id": nct_id,
      "gcs_uri": gcs_uri,
      "size_bytes": size_bytes,
      "sample_text": sample_text,
      "proposed_schema": ["nct_id", "gcs_uri", "section_type", "chunk_text"],
  }

  # 2. Step 1: A2A Governance Agent Verification
  decision = await verify_ingestion_payload_a2a(event_payload)
  if decision.get("verdict") != "APPROVED":
    return {
        "status": "INTERCEPTED_ROUTED_TO_DLQ",
        "nct_id": nct_id,
        "gcs_uri": gcs_uri,
        "governance_decision": decision,
    }

  # 3. Step 1: Idempotent Metadata Ingestion
  ingest_timestamp = datetime.now(timezone.utc)
  filename = object_name.split("/")[-1] if "/" in object_name else object_name
  meta_record = fetch_study_metadata_or_fallback(nct_id, filename, gcs_uri)

  upsert_meta_sql = build_upsert_metadata_query(
      project_id=settings.PROJECT_ID,
      dataset_id=settings.DATASET_ID,
      table_id=settings.TABLE_ID,
  )
  meta_job_config = bigquery.QueryJobConfig(
      query_parameters=[
          bigquery.ScalarQueryParameter("nct_id", "STRING", meta_record["nct_id"]),
          bigquery.ScalarQueryParameter(
              "brief_title", "STRING", meta_record["brief_title"]
          ),
          bigquery.ScalarQueryParameter(
              "overall_status", "STRING", meta_record["overall_status"]
          ),
          bigquery.ScalarQueryParameter(
              "doc_filename", "STRING", meta_record["doc_filename"]
          ),
          bigquery.ScalarQueryParameter("cdn_url", "STRING", meta_record["cdn_url"]),
          bigquery.ScalarQueryParameter("gcs_uri", "STRING", meta_record["gcs_uri"]),
          bigquery.ScalarQueryParameter("ingest_ts", "TIMESTAMP", ingest_timestamp),
      ]
  )

  meta_status = "SUCCESS"
  try:
    await asyncio.to_thread(_run_query, upsert_meta_sql, meta_job_config)
    print(
        f"✅ [BIGQUERY METADATA UPSERT] Ingested study metadata for {nct_id} ({gcs_uri})",
        flush=True,
    )
  except Exception as e:
    meta_status = f"META_ERROR: {str(e)}"
    print(f"❌ [BIGQUERY METADATA ERROR]: {e}", flush=True)

  # 4. Step 2 & 3: Incremental Extraction and Embedding (non-blocking)
  incremental_extract_sql = build_incremental_extraction_query(
      project_id=settings.PROJECT_ID,
      dataset_id=settings.DATASET_ID,
      extractor_model=settings.EXTRACTOR_MODEL,
  )
  incremental_embed_sql = build_incremental_embedding_query(
      project_id=settings.PROJECT_ID,
      dataset_id=settings.DATASET_ID,
      embedding_model=settings.EMBEDDING_MODEL,
  )

  job_config = bigquery.QueryJobConfig(
      query_parameters=[
          bigquery.ScalarQueryParameter("gcs_uri", "STRING", gcs_uri),
          bigquery.ScalarQueryParameter(
              "ingest_ts", "TIMESTAMP", ingest_timestamp
          ),
      ]
  )

  bq_status = "SUCCESS"
  rows_extracted = 0
  try:
    rows_extracted = await asyncio.to_thread(
        _execute_incremental_ingest,
        incremental_extract_sql,
        incremental_embed_sql,
        job_config,
    )
    print(
        f"✅ [BIGQUERY INCREMENTAL INGEST] Extracted & embedded {rows_extracted} section chunks for {gcs_uri}",
        flush=True,
    )
  except Exception as e:
    bq_status = f"BQ_ERROR: {str(e)}"
    print(f"❌ [BIGQUERY INGEST ERROR]: {e}", flush=True)

  return {
      "status": "INGESTED_AND_VERIFIED",
      "nct_id": nct_id,
      "gcs_uri": gcs_uri,
      "metadata_status": meta_status,
      "sections_extracted": rows_extracted,
      "bigquery_status": bq_status,
      "governance_decision": decision,
  }

@app.post("/v1/chat", tags=["Agent Runtime Proxy"])
def chat_with_agent_runtime(req: ChatRequest):
  """Forwards natural-language queries from FastAPI to the deployed Vertex AI Agent Engine."""
  if not settings.AGENT_ENGINE_ID:
    raise HTTPException(
        status_code=500, detail="AGENT_ENGINE_RESOURCE_NAME env var not set."
    )

  vertexai.init(project=settings.PROJECT_ID, location=settings.REGION)
  remote_agent = agent_engines.get(settings.AGENT_ENGINE_ID)

  # Create or resume a managed Agent Engine Session
  session_id = req.session_id
  if not session_id:
    session = remote_agent.create_session(user_id=req.user_id)
    session_id = session["id"]

  final_answer = []
  for event in remote_agent.stream_query(
      user_id=req.user_id,
      session_id=session_id,
      message=req.prompt,
  ):
    parts = event.get("content", {}).get("parts", [])
    for part in parts:
      if "text" in part:
        final_answer.append(part["text"])

  return {
      "session_id": session_id,
      "prompt": req.prompt,
      "response": "".join(final_answer),
  }