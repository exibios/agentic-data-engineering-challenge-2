# agent/config.py
"""Centralized environment configuration with dummy defaults."""

import os
from dataclasses import dataclass

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass


@dataclass(frozen=True) # immutable
class Settings:
  # GCP & Region
  PROJECT_ID: str = (
      os.getenv("PROJECT_ID")
      or os.getenv("GCP_PROJECT")
      or "dummy-project-id"
  )
  LOCATION: str = (
      os.getenv("LOCATION")
      or os.getenv("GCP_LOCATION")
      or "dummy-location"
  )
  REGION: str = (os.getenv("REGION") or "dummy-region")

  # BigQuery & Storage
  DATASET_ID: str = (
      os.getenv("DATASET_ID")
      or os.getenv("BQ_DATASET")
      or "dummy_dataset_id"
  )
  TABLE_ID: str = (
      os.getenv("TABLE_ID")
      or os.getenv("BQ_TABLE")
      or "dummy_table_id"
  )
  BUCKET_NAME: str = (
      os.getenv("BUCKET_NAME")
      or os.getenv("GCS_BUCKET")
      or "dummy-bucket-name"
  )

  # Models & Endpoints
  MODEL_NAME: str = (
      os.getenv("MODEL_NAME")
      or os.getenv("AGENT_MODEL")
      or "dummy-model-name"
  )
  EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "dummy_embedding_model")
  EXTRACTOR_MODEL: str = os.getenv("EXTRACTOR_MODEL", "dummy_model_extractor")
  RAG_API_URL: str = os.getenv("RAG_API_URL", "http://dummy-rag-api-url/search")

  # Pub/Sub, DLQ & Memory
  DLQ_TOPIC_ID: str = (
      os.getenv("DLQ_TOPIC_ID")
      or os.getenv("DWL_TOPIC_ID")
      or "dummy-dlq-topic-id"
  )
  FIRESTORE_COLLECTION: str = os.getenv(
      "FIRESTORE_COLLECTION", "dummy-firestore-collection"
  )
  FIRESTORE_DATABASE: str = os.getenv(
      "FIRESTORE_DATABASE", "dummy-firestore-database"
  )

  GOOGLE_GENAI_USE_VERTEXAI: str = os.getenv(
      "GOOGLE_GENAI_USE_VERTEXAI", "dummy-vertexai-flag"
  )

  AGENT_ENGINE_ID: str = os.getenv("AGENT_ENGINE_RESOURCE_NAME", "")
  GEMINI_MODEL_LOCATION: str = os.getenv("GEMINI_MODEL_LOCATION","dummy-gemini-model-location")

settings = Settings()

# Direct convenience exports for backward compatibility
PROJECT_ID = settings.PROJECT_ID
LOCATION = settings.LOCATION
DATASET_ID = settings.DATASET_ID
TABLE_ID = settings.TABLE_ID
BUCKET_NAME = settings.BUCKET_NAME
MODEL_NAME = settings.MODEL_NAME
EMBEDDING_MODEL = settings.EMBEDDING_MODEL
EXTRACTOR_MODEL = settings.EXTRACTOR_MODEL
RAG_API_URL = settings.RAG_API_URL
DLQ_TOPIC_ID = settings.DLQ_TOPIC_ID
FIRESTORE_COLLECTION = settings.FIRESTORE_COLLECTION
FIRESTORE_DATABASE = settings.FIRESTORE_DATABASE
GOOGLE_GENAI_USE_VERTEXAI = settings.GOOGLE_GENAI_USE_VERTEXAI
AGENT_ENGINE_ID = settings.AGENT_ENGINE_ID
GEMINI_MODEL_LOCATION = settings.GEMINI_MODEL_LOCATION