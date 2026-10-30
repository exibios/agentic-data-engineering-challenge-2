-- infra/bq_setup.sql

-- Create the bucket

-- create dataset

-- 2. Create Structured Metadata Table (~500 rows limit)
CREATE TABLE IF NOT EXISTS `data4ai-challenge-03.clinical_trials_2.studies_metadata` (
  nct_id STRING NOT NULL,
  brief_title STRING,
  overall_status STRING,
  doc_filename STRING,
  cdn_url STRING,
  gcs_uri STRING,
  ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- 3. Create BigQuery Object Table over GCS to catalog raw PDFs

Create or replace external table `data4ai-challenge-03.clinical_trials_2.documents_table`
with connection `data4ai-challenge-03.us.agentic_conn`
options
(
object_metadata='SIMPLE',
uris=['gs://data4ai-challenge-03-agentic-data-engineering-raw-docs-2/raw/*']
  -- max_staleness = INTERVAL 30 MINUTE,
  -- metadata_cache_mode = 'AUTOMATIC'
)

-- 4. Register Remote Gemini 1.5 Flash Model for Metadata Extraction
CREATE OR REPLACE MODEL `data4ai-challenge-03.clinical_trials_2.model_extractor`
REMOTE WITH CONNECTION `data4ai-challenge-03.us.agentic_conn`
OPTIONS (endpoint = 'gemini-3.8-flash')
;


'''
V1
-- 5. Extract Structured Metadata & Document Chunks from Object Table
CREATE TABLE IF NOT EXISTS `data4ai-challenge-03.clinical_trials_2.extracted_doc_chunks` AS
SELECT
  uri AS gcs_uri,
  REGEXP_EXTRACT(uri, r'NCT\d{8}') AS nct_id,
  content_type,
  size AS file_size_bytes,
  ml_generate_text_llm_result AS extracted_summary_json
FROM ML.GENERATE_TEXT(
  MODEL `data4ai-challenge-03.clinical_trials_2.model_extractor`,
  TABLE `data4ai-challenge-03.clinical_trials_2.documents_table`,
  STRUCT(
    'Extract study phase, primary endpoints, inclusion criteria summary, and key protocol sections as JSON.' AS prompt,
    0.1 AS temperature,
    1024 AS max_output_tokens,
    TRUE AS flatten_json_output
  )
);
'''
'''
V2
CREATE OR REPLACE TABLE `clinical_trials_2.extracted_doc_chunks` AS
WITH raw_extractions AS (
  SELECT
    uri AS gcs_uri,
    REGEXP_EXTRACT(uri, r'NCT\d{8}') AS nct_id,
    PARSE_JSON(
      REGEXP_REPLACE(
        REGEXP_REPLACE(ml_generate_text_llm_result, r'^```json\s*', ''),
        r'\s*```$', ''
      )
    ) AS json_content
  FROM ML.GENERATE_TEXT(
    MODEL `clinical_trials_2.model_extractor`,
    TABLE `clinical_trials_2.documents_table`,
    STRUCT(
      '''Analyze this clinical trial document. Return ONLY a valid JSON object with the following schema:
      {
        "sections": [
          {"section_type": "Study Objectives", "chunk_text": "<summary of objectives>"},
          {"section_type": "Inclusion Criteria", "chunk_text": "<detailed list of inclusion criteria>"},
          {"section_type": "Exclusion Criteria", "chunk_text": "<detailed list of exclusion criteria>"},
          {"section_type": "Primary Endpoints", "chunk_text": "<summary of primary and secondary endpoints>"},
          {"section_type": "Dosing & Intervention", "chunk_text": "<dosing schedule and regimen>"}
        ]
      }''' AS prompt,
      0.1 AS temperature,
      2048 AS max_output_tokens,
      TRUE AS flatten_json_output
    )
  )
)
SELECT
  GENERATE_UUID() AS chunk_id,
  nct_id,
  gcs_uri,
  STRING(item.section_type) AS section_type,
  STRING(item.chunk_text) AS chunk_text,
  CURRENT_TIMESTAMP() AS created_at
FROM
  raw_extractions,
  UNNEST(JSON_EXTRACT_ARRAY(json_content, '$.sections')) AS item
WHERE item.chunk_text IS NOT NULL;

'''
-- ============================================================================
-- STEP 3.4: Extract & Chunk PDFs into `extracted_doc_chunks`
-- Guaranteeing `section_type` and `chunk_text` columns are created!
-- ============================================================================
CREATE OR REPLACE TABLE `data4ai-challenge-03.clinical_trials_2.extracted_doc_chunks` AS
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
      MODEL `data4ai-challenge-03.clinical_trials_2.model_extractor`,
      TABLE `data4ai-challenge-03.clinical_trials_2.documents_table`,
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
  WHERE content_type = 'application/pdf'
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

  -- Path B (Safety Fallback): If a PDF caused non-JSON plain text output, preserve it as a single chunk so zero documents are lost
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
  CURRENT_TIMESTAMP() AS created_at
FROM
  unnested_chunks
WHERE
  chunk_text IS NOT NULL
  AND LENGTH(TRIM(chunk_text)) > 15;


  -- Quick Sanity Check: Verify `section_type` and `chunk_text` exist and have rows!
SELECT chunk_id, nct_id, section_type, SUBSTR(chunk_text, 1, 100) AS preview
FROM `data4ai-challenge-03.clinical_trials_2.extracted_doc_chunks`
LIMIT 10;




-- ============================================================================
-- STEP 3.5: Generate Vector Embeddings using `gemini-embedding-001`
-- ============================================================================
CREATE OR REPLACE TABLE `data4ai-challenge-03.clinical_trials_2.embedded_doc_chunks` AS
SELECT
  chunk_id,
  nct_id,
  gcs_uri,
  section_type,
  chunk_text,
  ml_generate_embedding_result AS text_embedding
FROM
  ML.GENERATE_EMBEDDING(
    MODEL `data4ai-challenge-03.clinical_trials_2.embedding_model`,
    (
      SELECT
        chunk_id,
        nct_id,
        gcs_uri,
        section_type,
        chunk_text,
        -- `content` is the required input column name for ML.GENERATE_EMBEDDING
        CONCAT(
          'Clinical Trial NCTId: ', nct_id,
          ' | Document Section: ', section_type,
          ' | Text: ', chunk_text
        ) AS content
      FROM
        `data4ai-challenge-03.clinical_trials_2.extracted_doc_chunks`
    ),
    STRUCT(TRUE AS flatten_json_output)
  )
WHERE ARRAY_LENGTH(ml_generate_embedding_result) > 0;





-- ============================================================================
-- STEP 3.6: Create Vector Index & Test Vector Search
-- ============================================================================
-- Note: BigQuery requires at least 5,000 rows to build an IVF index.
-- If your sample table has <5,000 rows (per the 50-100 PDF budget), BigQuery may return
-- a warning/error on CREATE VECTOR INDEX. That is completely normal: `VECTOR_SEARCH()`
-- still works out-of-the-box using exact brute-force cosine calculation!
CREATE OR REPLACE VECTOR INDEX `doc_chunks_cosine_idx`
ON `data4ai-challenge-03.clinical_trials_2.embedded_doc_chunks`(text_embedding)
OPTIONS(
  index_type = 'IVF',
  distance_type = 'COSINE'
);

-- Test Semantic Search directly in BigQuery:
WITH query_vec AS (
  SELECT ml_generate_embedding_result AS q_embedding
  FROM ML.GENERATE_EMBEDDING(
    MODEL `data4ai-challenge-03.clinical_trials_2.embedding_model`,
    (SELECT 'What are the inclusion criteria for adult patients?' AS content),
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
    TABLE `data4ai-challenge-03.clinical_trials_2.embedded_doc_chunks`,
    'text_embedding',
    TABLE query_vec,
    top_k => 5,
    distance_type => 'COSINE'
  )
ORDER BY cosine_similarity DESC;