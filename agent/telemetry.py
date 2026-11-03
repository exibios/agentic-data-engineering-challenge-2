# agent/telemetry.py
"""OpenTelemetry tracing and structured Cloud Logging for FinOps / Token costs."""

import json
import logging
import os
import time
from typing import Any, Dict
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

PROJECT_ID = os.getenv("GCP_PROJECT", "data4ai-challenge-03")

# Initialize OpenTelemetry with Google Cloud Trace Exporter
tracer_provider = TracerProvider()
try:
  cloud_trace_exporter = CloudTraceSpanExporter(project_id=PROJECT_ID)
  tracer_provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
  trace.set_tracer_provider(tracer_provider)
except Exception:
  pass  # Fallback to default in-memory tracer if offline

tracer = trace.get_tracer("clinical_trials_agent")
logger = logging.getLogger("agent_telemetry")


def log_agent_session_metrics(
    session_id: str,
    user_prompt: str,
    tool_selected: str,
    latency_ms: float,
    prompt_tokens: int,
    response_tokens: int,
    pii_intercepted: bool = False,
) -> None:
  """Emits a structured JSON log that Cloud Logging metrics parse for dashboard aggregation."""
  total_tokens = prompt_tokens + response_tokens

  # FinOps cost estimation for gemini-3.8-flash ($0.075 / 1M input, $0.30 / 1M output)
  estimated_cost_usd = (prompt_tokens * 0.000000075) + (
      response_tokens * 0.00000030
  )

  structured_payload: Dict[str, Any] = {
      "event_type": "agent_execution_telemetry",
      "session_id": session_id,
      "tool_selected": tool_selected,
      "latency_ms": round(latency_ms, 2),
      "prompt_tokens": prompt_tokens,
      "response_tokens": response_tokens,
      "total_tokens": total_tokens,
      "estimated_cost_usd": round(estimated_cost_usd, 6),
      "pii_intercepted": pii_intercepted,
  }

  # Print structured JSON directly to stdout for Cloud Logging ingestion
  print(json.dumps(structured_payload))
