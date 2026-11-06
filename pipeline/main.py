# pipeline/main.py
from datetime import datetime, timezone
import os
import base64
import json
import uuid
from fastapi import FastAPI, HTTPException, Request
from google.cloud import bigquery
from agent.memory import SessionMemory
from agent.governance_agent import verify_ingestion_payload_a2a
from pipeline.schemas import (
    ChunkHit,
    IngestRequest,
    IngestResponse,
    MetadataResponse,
    SearchRequest,
    SearchResponse,
)

import re
import time
from agent.guardrails import redact_pii_dlp
from agent.telemetry import log_agent_session_metrics, tracer

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass

# === Environment Configuration ===
PROJECT_ID = os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT") or "dummy-project-id"
DATASET_ID = os.getenv("DATASET_ID") or os.getenv("BQ_DATASET") or "dummy_dataset_id"
BUCKET_NAME = (
    os.getenv("BUCKET_NAME")
    or os.getenv("GCS_BUCKET")
    or "dummy-bucket-name"
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "dummy_embedding_model")
EXTRACTOR_MODEL = os.getenv("EXTRACTOR_MODEL", "dummy_model_extractor")


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
  start_time = time.time()
  session_id = req.session_id or "default-session"

  with tracer.start_as_current_span("semantic_vector_search") as span:
    # 1. Cloud DLP Guardrail Check
    sanitized_query, pii_detected = redact_pii_dlp(req.query)
    span.set_attribute("pii_detected", pii_detected)

    # 2. BigQuery Vector Search
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
            bigquery.ScalarQueryParameter(
                "query_text", "STRING", sanitized_query
            ),
            bigquery.ScalarQueryParameter("top_k", "INT64", req.top_k),
        ]
    )

    rows = list(bq_client.query(sql, job_config=job_config).result())
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
  """Receives GCS Object Finalize events from Eventarc/PubSub, runs A2A Governance verification,

  and executes the exact 5-section JSON extraction + UNNEST query using
  `model_extractor` and `documents_table` for the newly uploaded `@gcs_uri`.
  """
  raw_body = await request.json()

  # 1. Unpack Pub/Sub Push base64 envelope or Eventarc 'data' envelope if present
  if "message" in raw_body and "data" in raw_body["message"]:
    decoded = base64.b64decode(raw_body["message"]["data"]).decode("utf-8")
    body = json.loads(decoded)
  elif "data" in raw_body and isinstance(raw_body["data"], dict):
    body = raw_body["data"]
  else:
    body = raw_body

  bucket = body.get("bucket", BUCKET_NAME)
  object_name = body.get("name", "")
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

  # 3. Step 2: Incremental Extraction into `extracted_doc_chunks`
  # Matches your batch query 1-for-1 (using `model_extractor` and `documents_table` filtered by `uri = @gcs_uri`)
  # Note: Double curly braces {{ }} escape Python f-string formatting inside the SQL string.
  ingest_timestamp = datetime.now(timezone.utc)
  incremental_extract_sql = f"""
      INSERT INTO `{PROJECT_ID}.{DATASET_ID}.extracted_doc_chunks`
        (chunk_id, nct_id, gcs_uri, section_type, chunk_text, created_at)
      WITH raw_llm_extraction AS (
        SELECT
          uri AS gcs_uri,
          REGEXP_EXTRACT(uri, r'NCT\\d{{8}}') AS nct_id,
          ml_generate_text_llm_result AS raw_response,
          -- Strip markdown ```json fences if the LLM includes them, then parse safely
          SAFE.PARSE_JSON(
            REGEXP_REPLACE(
              REGEXP_REPLACE(TRIM(ml_generate_text_llm_result), r'^```(?:json)?\\s*', ''),
              r'\\s*```$', ''
            )
          ) AS parsed_json
        FROM
          ML.GENERATE_TEXT(
            MODEL `{PROJECT_ID}.{DATASET_ID}.model_extractor`,
            (
              SELECT *
              FROM `{PROJECT_ID}.{DATASET_ID}.documents_table`
              WHERE uri = @gcs_uri AND content_type = 'application/pdf'
            ),
            STRUCT(
              '''You are a clinical trial data extractor. Read this PDF and extract its key sections.
Return ONLY a valid JSON array of objects (no markdown fences, no extra commentary) using this exact structure:
[
  {{"section_type": "Study Overview", "chunk_text": "Detailed summary of study title, phase, and objectives..."}},
  {{"section_type": "Inclusion Criteria", "chunk_text": "Detailed inclusion criteria..."}},
  {{"section_type": "Exclusion Criteria", "chunk_text": "Detailed exclusion criteria..."}},
  {{"section_type": "Primary Endpoints", "chunk_text": "Primary and secondary outcome measures..."}},
  {{"section_type": "Dosing & Intervention", "chunk_text": "Treatment arms, dosing schedule, and safety protocol..."}}
]''' AS prompt,
              0.0 AS temperature,
              2048 AS max_output_tokens,
              TRUE AS flatten_json_output
            )
          )
      ),
      unnested_chunks AS (
        -- Path A: When Gemini returns the valid JSON array of sections
        SELECT
          nct_id,
          gcs_uri,
          STRING(section_obj.section_type) AS section_type,
          STRING(section_obj.chunk_text) AS chunk_text
        FROM
          raw_llm_extraction,
          UNNEST(JSON_QUERY_ARRAY(parsed_json)) AS section_obj
        WHERE parsed_json IS NOT NULL

        UNION ALL

        -- Path B (Safety Fallback): If a PDF caused non-JSON plain text output, preserve it as a single chunk
        SELECT
          nct_id,
          gcs_uri,
          'General Summary' AS section_type,
          raw_response AS chunk_text
        FROM
          raw_llm_extraction
        WHERE parsed_json IS NULL AND raw_response IS NOT NULL
      )
      SELECT
        GENERATE_UUID() AS chunk_id,
        IFNULL(nct_id, 'UNKNOWN_NCT') AS nct_id,
        gcs_uri,
        IFNULL(section_type, 'General') AS section_type,
        chunk_text,
        @ingest_ts AS created_at
      FROM
        unnested_chunks
      WHERE
        chunk_text IS NOT NULL
        AND LENGTH(TRIM(chunk_text)) > 15;
  """

  # 4. Step 3: Generate Embeddings for the newly extracted sections of `@gcs_uri`
  incremental_embed_sql = f"""
      INSERT INTO `{PROJECT_ID}.{DATASET_ID}.embedded_doc_chunks`
        (chunk_id, nct_id, gcs_uri, section_type, chunk_text, text_embedding)
      SELECT
        chunk_id,
        nct_id,
        gcs_uri,
        section_type,
        chunk_text,
        ml_generate_embedding_result AS text_embedding
      FROM ML.GENERATE_EMBEDDING(
        MODEL `{PROJECT_ID}.{DATASET_ID}.embedding_model`,
        (
          SELECT
            chunk_id,
            nct_id,
            gcs_uri,
            section_type,
            chunk_text,
            CONCAT(
              'Clinical Trial NCTId: ', nct_id,
              ' | Document Section: ', section_type,
              ' | Text: ', chunk_text
            ) AS content
          FROM `{PROJECT_ID}.{DATASET_ID}.extracted_doc_chunks`
          WHERE gcs_uri = @gcs_uri AND created_at = @ingest_ts
        ),
        STRUCT(TRUE AS flatten_json_output)
      )
      WHERE ARRAY_LENGTH(ml_generate_embedding_result) > 0;
  """

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
    extract_job = bq_client.query(
        incremental_extract_sql, job_config=job_config
    )
    extract_job.result()
    rows_extracted = extract_job.num_dml_affected_rows or 0

    if rows_extracted > 0:
      embed_job = bq_client.query(incremental_embed_sql, job_config=job_config)
      embed_job.result()

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
      "sections_extracted": rows_extracted,
      "bigquery_status": bq_status,
      "governance_decision": decision,
  }