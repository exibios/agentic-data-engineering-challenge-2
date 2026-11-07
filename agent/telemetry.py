# agent/telemetry.py
"""OpenTelemetry tracing and zero-latency structured logging for FinOps / Token costs."""

import json
import sys
from typing import Any, Dict
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from agent.config import settings

# 1. Initialize OpenTelemetry Tracer
tracer_provider = TracerProvider()
try:
  cloud_trace_exporter = CloudTraceSpanExporter(project_id=settings.PROJECT_ID)
  tracer_provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
  trace.set_tracer_provider(tracer_provider)
except Exception:
  pass

tracer = trace.get_tracer("clinical_trials_agent")


def log_agent_session_metrics(
    session_id: str,
    user_prompt: str,
    tool_selected: str,
    latency_ms: float,
    prompt_tokens: int,
    response_tokens: int,
    pii_intercepted: bool = False,
) -> None:
  """Writes structured JSON directly to stdout for Cloud Logging (jsonPayload) ingestion.

  Zero-latency stdout logging is automatically ingested into Cloud Logging
  on Cloud Run, matching the log-based metrics for Day 10.
  """
  total_tokens = prompt_tokens + response_tokens

  # FinOps cost estimation for gemini-3.8-flash ($0.075 / 1M in, $0.30 / 1M out)
  estimated_cost_usd = (prompt_tokens * 0.000000075) + (
      response_tokens * 0.00000030
  )

  structured_payload: Dict[str, Any] = {
      "severity": "INFO",
      "message": f"Telemetry emitted for session {session_id}",
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

  # Direct zero-latency structured output to stdout (parsed automatically by GCP Cloud Logging)
  print(json.dumps(structured_payload), file=sys.stdout, flush=True)
