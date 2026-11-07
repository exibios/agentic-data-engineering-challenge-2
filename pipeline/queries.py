# pipeline/queries.py
"""Dedicated BigQuery SQL query templates."""

METADATA_QUERY_TEMPLATE = """
SELECT
  m.nct_id,
  ANY_VALUE(m.brief_title) AS brief_title,
  ANY_VALUE(m.overall_status) AS overall_status,
  ANY_VALUE(m.gcs_uri) AS gcs_uri,
  COUNT(c.chunk_id) AS chunks_count
FROM `{project_id}.{dataset_id}.{table_id}` m
LEFT JOIN `{project_id}.{dataset_id}.extracted_doc_chunks` c
  ON m.nct_id = c.nct_id AND m.gcs_uri = c.gcs_uri
WHERE m.nct_id = @nct_id
GROUP BY m.nct_id
"""

SEMANTIC_SEARCH_QUERY_TEMPLATE = """
WITH query_vec AS (
    SELECT ml_generate_embedding_result AS q_embedding
    FROM ML.GENERATE_EMBEDDING(
        MODEL `{project_id}.{dataset_id}.{embedding_model}`,
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
        TABLE `{project_id}.{dataset_id}.embedded_doc_chunks`,
        'text_embedding',
        TABLE query_vec,
        top_k => @top_k,
        distance_type => 'COSINE'
    )
ORDER BY cosine_similarity DESC
"""

INCREMENTAL_EXTRACTION_SQL_TEMPLATE = r"""
INSERT INTO `{project_id}.{dataset_id}.extracted_doc_chunks`
  (chunk_id, nct_id, gcs_uri, section_type, chunk_text, created_at)
WITH raw_llm_extraction AS (
  SELECT
    uri AS gcs_uri,
    REGEXP_EXTRACT(uri, r'NCT\d{8}') AS nct_id,
    ml_generate_text_llm_result AS raw_response,
    -- Strip markdown ```json fences if the LLM includes them, then parse safely
    SAFE.PARSE_JSON(
      REGEXP_REPLACE(
        REGEXP_REPLACE(TRIM(ml_generate_text_llm_result), r'^```(?:json)?\s*', ''),
        r'\s*```$', ''
      )
    ) AS parsed_json
  FROM
    ML.GENERATE_TEXT(
      MODEL `{project_id}.{dataset_id}.{extractor_model}`,
      (
        SELECT *
        FROM `{project_id}.{dataset_id}.documents_table`
        WHERE uri = @gcs_uri AND content_type = 'application/pdf'
      ),
      STRUCT(
        '''You are a clinical trial data extractor. Read this PDF and extract its key sections.
Return ONLY a valid JSON array of objects (no markdown fences, no extra commentary) using this exact structure:
[
  {"section_type": "Study Overview", "chunk_text": "Detailed summary of study title, phase, and objectives..."},
  {"section_type": "Inclusion Criteria", "chunk_text": "Detailed inclusion criteria..."},
  {"section_type": "Exclusion Criteria", "chunk_text": "Detailed exclusion criteria..."},
  {"section_type": "Primary Endpoints", "chunk_text": "Primary and secondary outcome measures..."},
  {"section_type": "Dosing & Intervention", "chunk_text": "Treatment arms, dosing schedule, and safety protocol..."}
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

INCREMENTAL_EMBEDDING_SQL_TEMPLATE = """
INSERT INTO `{project_id}.{dataset_id}.embedded_doc_chunks`
  (chunk_id, nct_id, gcs_uri, section_type, chunk_text, text_embedding)
SELECT
  chunk_id,
  nct_id,
  gcs_uri,
  section_type,
  chunk_text,
  ml_generate_embedding_result AS text_embedding
FROM ML.GENERATE_EMBEDDING(
  MODEL `{project_id}.{dataset_id}.{embedding_model}`,
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
    FROM `{project_id}.{dataset_id}.extracted_doc_chunks`
    WHERE gcs_uri = @gcs_uri AND created_at = @ingest_ts
  ),
  STRUCT(TRUE AS flatten_json_output)
)
WHERE ARRAY_LENGTH(ml_generate_embedding_result) > 0;
"""


def build_metadata_query(project_id: str, dataset_id: str, table_id: str) -> str:
  return METADATA_QUERY_TEMPLATE.format(
      project_id=project_id, dataset_id=dataset_id, table_id=table_id
  )


def build_semantic_search_query(
    project_id: str, dataset_id: str, embedding_model: str
) -> str:
  return SEMANTIC_SEARCH_QUERY_TEMPLATE.format(
      project_id=project_id,
      dataset_id=dataset_id,
      embedding_model=embedding_model,
  )


def build_incremental_extraction_query(
    project_id: str, dataset_id: str, extractor_model: str
) -> str:
  return INCREMENTAL_EXTRACTION_SQL_TEMPLATE.format(
      project_id=project_id,
      dataset_id=dataset_id,
      extractor_model=extractor_model,
  )


def build_incremental_embedding_query(
    project_id: str, dataset_id: str, embedding_model: str
) -> str:
  return INCREMENTAL_EMBEDDING_SQL_TEMPLATE.format(
      project_id=project_id,
      dataset_id=dataset_id,
      embedding_model=embedding_model,
  )
