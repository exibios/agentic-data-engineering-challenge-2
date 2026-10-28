-- infra/bq_setup.sql

-- 1. Create Dataset
CREATE SCHEMA IF NOT EXISTS `data4ai-challenge-03-agentic-data-engineering-raw-docs-2`
OPTIONS(location="us");

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
OPTIONS (endpoint = 'gemini-1.5-flash');

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
