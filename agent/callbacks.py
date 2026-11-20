# agent/callbacks.py
"""ADK Callbacks for PII Guardrails, SQL Safety, and Response Monitoring.

These callbacks are registered on `root_agent` via:
- before_model_callback: pii_guardrail_before_model  — redacts PII from user prompts
- after_model_callback:  safety_response_monitor     — logs safety metadata on responses
- before_tool_callback:  sql_safety_before_tool       — blocks non-SELECT SQL queries

Each callback follows the exact ADK signatures from LlmAgent model_fields:
  before_model_callback(ctx: Context, llm_request: LlmRequest) -> Optional[LlmResponse]
  after_model_callback(ctx: Context, llm_response: LlmResponse) -> Optional[LlmResponse]
  before_tool_callback(tool: BaseTool, args: dict, ctx: Context) -> Optional[dict]
"""

import logging
from typing import Any, Optional

from google.adk.agents.context import Context
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.genai import types
from opentelemetry import trace

logger = logging.getLogger("agent.callbacks")

# ---------------------------------------------------------------------------
# 1. PII Guardrail — before_model_callback
# ---------------------------------------------------------------------------

def pii_guardrail_before_model(
    ctx: Context,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Redacts PII from the latest user message before it reaches Gemini.

    Strategy: redact in-place (mutate llm_request.contents), never block.
    Records telemetry on the ambient ADK span so traces remain correlated.
    Returns None to continue the normal model call.
    """
    # Lazy import to avoid circular dep and GCP network calls at import time
    from agent.guardrails import redact_pii_dlp

    if not llm_request.contents:
        return None

    # Find the last user-role message
    for content in reversed(llm_request.contents):
        if getattr(content, "role", None) == "user":
            new_parts: list[types.Part] = []
            pii_detected_overall = False

            for part in content.parts or []:
                raw_text = getattr(part, "text", None)
                if raw_text:
                    redacted_text, pii_found = redact_pii_dlp(raw_text)
                    new_parts.append(types.Part.from_text(text=redacted_text))
                    if pii_found:
                        pii_detected_overall = True
                        logger.warning(
                            "[PII GUARDRAIL] PII detected and redacted from user prompt "
                            "(session=%s, agent=%s)",
                            getattr(ctx, "session", {}).id if hasattr(ctx, "session") and ctx.session else "unknown",
                            ctx.agent_name,
                        )
                else:
                    new_parts.append(part)

            content.parts = new_parts

            # Attach telemetry attributes to the ambient ADK span
            span = trace.get_current_span()
            span.set_attribute("guardrail.pii.scanned", True)
            span.set_attribute("guardrail.pii.detected", pii_detected_overall)
            break  # Only process the last user message

    return None  # Always continue — we redact, not block


# ---------------------------------------------------------------------------
# 2. Response Safety Monitor — after_model_callback
# ---------------------------------------------------------------------------

def safety_response_monitor(
    ctx: Context,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """Monitors model responses for safety signals and logs telemetry.

    Does NOT modify or block responses. Records finish_reason and any
    safety-related metadata on the ambient ADK span for observability.
    Returns None to keep the original response unchanged.
    """
    span = trace.get_current_span()

    finish_reason = getattr(llm_response, "finish_reason", None)
    if finish_reason:
        span.set_attribute("guardrail.response.finish_reason", str(finish_reason))

    # Log if model response was blocked (SAFETY finish reason)
    finish_reason_str = str(finish_reason) if finish_reason else ""
    if "SAFETY" in finish_reason_str or "BLOCKED" in finish_reason_str:
        logger.warning(
            "[SAFETY MONITOR] Model response flagged (finish_reason=%s, agent=%s, session=%s)",
            finish_reason_str,
            ctx.agent_name,
            getattr(ctx, "session", {}).id if hasattr(ctx, "session") and ctx.session else "unknown",
        )
        span.set_attribute("guardrail.response.safety_blocked", True)
    else:
        span.set_attribute("guardrail.response.safety_blocked", False)

    return None  # Always keep original response — safety settings on Agent handle blocking


# ---------------------------------------------------------------------------
# 3. SQL Injection Guard — before_tool_callback
# ---------------------------------------------------------------------------

_ALLOWED_SQL_PREFIXES = ("SELECT", "WITH")


def sql_safety_before_tool(
    tool: BaseTool,
    args: dict[str, Any],
    ctx: Context,
) -> Optional[dict[str, Any]]:
    """Blocks non-SELECT/WITH SQL queries before execute_clinical_sql runs.

    If the tool is `execute_clinical_sql` and the query does not start with
    SELECT or WITH, returns a structured error dict (short-circuits execution).
    Returns None to allow all other tool calls through unmodified.
    """
    if tool.name != "execute_clinical_sql":
        return None  # Only guard the SQL tool

    sql_query: str = args.get("sql_query", "")
    normalized = sql_query.strip().upper()

    if not normalized.startswith(_ALLOWED_SQL_PREFIXES):
        logger.warning(
            "[SQL GUARD] Blocked disallowed SQL query (tool=%s, agent=%s): %.120s...",
            tool.name,
            ctx.agent_name,
            sql_query,
        )
        span = trace.get_current_span()
        span.set_attribute("guardrail.sql.blocked", True)
        span.set_attribute("guardrail.sql.query_prefix", sql_query[:40] if sql_query else "")

        return {
            "status": "error",
            "error_message": (
                "SQL policy violation: only SELECT and WITH queries are permitted. "
                f"Received: '{sql_query[:60]}...'"
            ),
        }

    span = trace.get_current_span()
    span.set_attribute("guardrail.sql.blocked", False)
    return None  # Allow through

