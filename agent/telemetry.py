# agent/telemetry.py
"""OpenTelemetry tracing and direct Cloud Logging for FinOps / Token costs."""

import os
from typing import Any, Dict
from google.cloud import logging as gcp_logging
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

PROJECT_ID = os.getenv("GCP_PROJECT", "data4ai-challenge-03")

# 1. Initialize OpenTelemetry Tracer
tracer_provider = TracerProvider()
try:
  cloud_trace_exporter = CloudTraceSpanExporter(project_id=PROJECT_ID)
  tracer_provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
  trace.set_tracer_provider(tracer_provider)
except Exception:
  pass

tracer = trace.get_tracer("clinical_trials_agent")

# 2. Initialize Direct Cloud Logging Client
# This writes directly to GCP Cloud Logging via the API (works from localhost and Cloud Run)
try:
  logging_client = gcp_logging.Client(project=PROJECT_ID)
  gcp_logger = logging_client.logger("agent_telemetry_log")
except Exception as e:
  gcp_logger = None
  print(f"⚠️ Cloud Logging client initialization warning: {e}")


def log_agent_session_metrics(
    session_id: str,
    user_prompt: str,
    tool_selected: str,
    latency_ms: float,
    prompt_tokens: int,
    response_tokens: int,
    pii_intercepted: bool = False,
) -> None:
  """Writes structured JSON directly to Cloud Logging (jsonPayload)

  for the Day 10 token and latency metrics.
  """
  total_tokens = prompt_tokens + response_tokens

  # FinOps cost estimation for gemini-3.8-flash ($0.075 / 1M in, $0.30 / 1M out)
  estimated_cost_usd = (prompt_tokens * 0.000000075) + (
      response_tokens * 0.00000030
  )

  structured_payload: Dict[str, Any] = {
      "event_type": "agent_execution_telemetry",
      "session_id": session_id,
      "user_prompt": user_prompt,
      "tool_selected": tool_selected,
      "latency_ms": round(latency_ms, 2),
      "prompt_tokens": prompt_tokens,
      "response_tokens": response_tokens,
      "total_tokens": total_tokens,
      "estimated_cost_usd": round(estimated_cost_usd, 6),
      "pii_intercepted": pii_intercepted,
  }

  # Direct write to GCP Cloud Logging as a structured JSON payload
  if gcp_logger:
    try:
      gcp_logger.log_struct(structured_payload, severity="INFO")
    except Exception as e:
      print(f"Failed to send log to GCP Cloud Logging: {e}")

  # Also flush to stdout for local terminal visibility
  print(f"📡 [TELEMETRY EMITTED]: {structured_payload}", flush=True)
