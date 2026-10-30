-- infra/bq_embeddings.sql

-- 1. Register the Remote Embedding Model
-- Uses the Cloud Resource Connection established on Day 6 (e.g. `us.agentic_conn`)
CREATE OR REPLACE MODEL `clinical_trials_2.embedding_model`
REMOTE WITH CONNECTION `us.agentic_conn`
OPTIONS (
  endpoint = 'gemini-embedding-001'
);

'''
V1
-- 2. Generate Embeddings for Chunked Documents & Metadata
-- Reads extracted text chunks and generates dense vectors
CREATE OR REPLACE TABLE `clinical_trials_2.embedded_doc_chunks` AS
SELECT
  chunk_id,
  nct_id,
  gcs_uri,
  chunk_text,
  section_type, -- Protocol, Inclusion Criteria, SAP, Endpoints
  ml_generate_embedding_result AS text_embedding
FROM
  ML.GENERATE_EMBEDDING(
    MODEL `clinical_trials_2.embedding_model`,
    (
      SELECT
        -- Unique deterministic identifier per chunk
        GENERATE_UUID() AS chunk_id,
        nct_id,
        gcs_uri,
        -- Combined chunk text and structural context
        CONCAT('NCTId: ', nct_id, ' | Section: ', IFNULL(section_type, 'General'), ' | Content: ', chunk_text) AS content,
        chunk_text,
        section_type
      FROM
        `clinical_trials_2.extracted_doc_chunks`
      WHERE
        chunk_text IS NOT NULL AND LENGTH(TRIM(chunk_text)) > 20
    ),
    STRUCT(TRUE AS flatten_json_output)
  );

-- Verify table creation and embedding dimensions (768 for text-embedding-004)
SELECT
  chunk_id,
  nct_id,
  ARRAY_LENGTH(text_embedding) AS vector_dimensions,
  SUBSTR(chunk_text, 1, 80) AS sample_text
FROM
  `clinical_trials_2.embedded_doc_chunks`
LIMIT 5;
'''

'''
V1
CREATE OR REPLACE TABLE `clinical_trials_2.embedded_doc_chunks` AS
SELECT
  chunk_id,
  nct_id,
  gcs_uri,
  chunk_text,
  section_type, -- Protocol, Inclusion Criteria, SAP, Endpoints
  ml_generate_embedding_result AS text_embedding
FROM
  ML.GENERATE_EMBEDDING(
    MODEL `clinical_trials_2.embedding_model`,
    (
      SELECT
        -- Unique deterministic identifier per chunk
        GENERATE_UUID() AS chunk_id,
        nct_id,
        gcs_uri,
        -- Combined chunk text and structural context
        CONCAT('NCTId: ', nct_id, ' | Section: ', IFNULL(section_type, 'General'), ' | Content: ', chunk_text) AS content,
        chunk_text,
        section_type
      FROM
        `clinical_trials_2.extracted_doc_chunks`
      WHERE
        chunk_text IS NOT NULL AND LENGTH(TRIM(chunk_text)) > 20
    ),
    STRUCT(TRUE AS flatten_json_output)
  );
  '''

  CREATE OR REPLACE TABLE `clinical_trials_agent.embedded_doc_chunks` AS
SELECT
  chunk_id,
  nct_id,
  gcs_uri,
  section_type,
  chunk_text,
  ml_generate_embedding_result AS text_embedding
FROM
  ML.GENERATE_EMBEDDING(
    MODEL `clinical_trials_agent.embedding_model`,
    (
      SELECT
        chunk_id,
        nct_id,
        gcs_uri,
        section_type,
        chunk_text,
        -- Embed rich contextual string
        CONCAT('NCTId: ', nct_id, ' | Section: ', section_type, ' | Content: ', chunk_text) AS content
      FROM
        `clinical_trials_agent.extracted_doc_chunks`
      WHERE
        chunk_text IS NOT NULL AND LENGTH(TRIM(chunk_text)) > 20
    ),
    STRUCT(TRUE AS flatten_json_output)
  );

SELECT
  chunk_id,
  nct_id,
  section_type,
  ARRAY_LENGTH(text_embedding) AS embedding_dim,
  SUBSTR(chunk_text, 1, 80) AS sample_chunk
FROM
  `clinical_trials_agent.embedded_doc_chunks`
LIMIT 5;
