# agent/clients.py
"""Lazy singleton instantiation of Google Cloud SDK clients."""

from functools import lru_cache
from google.cloud import bigquery, dlp_v2, firestore, pubsub_v1, storage
from agent.config import settings


@lru_cache(maxsize=1)
def get_bq_client() -> bigquery.Client:
  """Returns a cached BigQuery client instance."""
  return bigquery.Client(project=settings.PROJECT_ID)


@lru_cache(maxsize=1)
def get_firestore_client() -> firestore.Client:
  """Returns a cached Firestore client instance."""
  return firestore.Client(project=settings.PROJECT_ID)


@lru_cache(maxsize=1)
def get_dlp_client() -> dlp_v2.DlpServiceClient:
  """Returns a cached Cloud DLP service client instance."""
  return dlp_v2.DlpServiceClient()


@lru_cache(maxsize=1)
def get_storage_client() -> storage.Client:
  """Returns a cached Cloud Storage client instance."""
  return storage.Client(project=settings.PROJECT_ID)


@lru_cache(maxsize=1)
def get_pubsub_publisher() -> pubsub_v1.PublisherClient:
  """Returns a cached Pub/Sub publisher client instance."""
  return pubsub_v1.PublisherClient()
