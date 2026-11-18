#!/usr/bin/env python3
# scripts/deploy_agent_runtime.py
"""Deploys root_agent to Vertex AI Agent Engine (Agent Runtime) with BYOSA."""

import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
  sys.path.insert(0, str(repo_root))

import vertexai
from vertexai import agent_engines
from vertexai.agent_engines import AdkApp
from agent.agent import root_agent

PROJECT_ID = "data4ai-challenge-03"
DEPLOY_REGION = "us-central1"  # Agent Engine hosting region
STAGING_BUCKET = "gs://data4ai-challenge-03-agentic-data-engineering-raw-docs-2-stg"
SERVICE_ACCOUNT = "80080086039-compute@developer.gserviceaccount.com"

CLOUD_RUN_RAG_URL = "https://clinical-trials-rag-api-xqvchgmmha-uc.a.run.app/search"


def main():
  print(f"🚀 Initializing Vertex AI Agent Engine in {PROJECT_ID} ({DEPLOY_REGION})...")
  vertexai.init(
      project=PROJECT_ID,
      location=DEPLOY_REGION,
      staging_bucket=STAGING_BUCKET,
  )

  # Wrap the ADK Agent in AdkApp with Cloud Trace / OpenTelemetry enabled
  adk_app = AdkApp(
      agent=root_agent,
      enable_tracing=True,
  )

  print("📦 Packaging ./agent and deploying to Agent Runtime (takes ~3-5 mins)...")
  remote_agent = agent_engines.create(
      adk_app,
      display_name="clinical-trials-data-agent",
      description="Autonomous Clinical Trials Data Agent with BigQuery SQL and Cloud Run Vector Search tools.",
      service_account=SERVICE_ACCOUNT,
      requirements=[
          "google-auth>=2.29.0",
          "fastapi>=0.110.0",
          "uvicorn[standard]>=0.28.0",
          "pydantic>=2.6.0",
          "httpx>=0.27.0",
          "google-cloud-storage>=2.16.0",
          "google-cloud-bigquery>=3.19.0",
          "google-cloud-firestore>=2.16.0",
          "google-adk==2.12.0",
          "google-cloud-pubsub>=2.21.0",
          "python-dotenv>=1.0.0",
          "opentelemetry-api>=1.24.0",
          "opentelemetry-sdk>=1.24.0",
          "opentelemetry-exporter-gcp-trace>=1.7.0",
          "google-cloud-logging>=3.10.0",
          "google-cloud-dlp>=3.40.0",
          "google-cloud-aiplatform[agent_engines,adk]>=2.9.0",
        ],
      extra_packages=["./agent"],
      env_vars={
          "GCP_PROJECT": PROJECT_ID,
          "BQ_DATASET": "clinical_trials_2",
          "RAG_API_URL": CLOUD_RUN_RAG_URL,
          # Keep Gemini 3.8 Flash model inference routed through the 'global' endpoint
          "GEMINI_MODEL_LOCATION": "global",
          "AGENT_MODEL": "gemini-3.8-flash",
          "LOCATION": "global"
      },
  )

  print("\n" + "=" * 75)
  print("✅ SUCCESS! Agent Deployed to Vertex AI Agent Runtime")
  print(f"   Resource Name: {remote_agent.resource_name}")
  print("=" * 75)
  print(f"Export this variable for your FastAPI endpoint and test scripts:")
  print(f"export AGENT_ENGINE_RESOURCE_NAME='{remote_agent.resource_name}'")


if __name__ == "__main__":
  main()
