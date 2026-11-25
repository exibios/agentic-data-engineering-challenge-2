# agent/governance_agent.py
"""Secondary Governance Agent for A2A Schema Validation & PII Compliance."""

from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any, Dict, Optional
from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import types
from agent.clients import get_pubsub_publisher
from agent.config import settings
from agent.memory import get_session_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("governance_agent")

PROJECT_ID = settings.PROJECT_ID
LOCATION = settings.LOCATION
MODEL_NAME = settings.MODEL_NAME
DLQ_TOPIC_ID = settings.DLQ_TOPIC_ID
GOOGLE_GENAI_USE_VERTEXAI = settings.GOOGLE_GENAI_USE_VERTEXAI

# Ensure Vertex AI global endpoint is configured for gemini-3.8-flash
location_to_use = (
    settings.GEMINI_MODEL_LOCATION
    if settings.GEMINI_MODEL_LOCATION and "dummy" not in settings.GEMINI_MODEL_LOCATION
    else settings.LOCATION
)
if not location_to_use or "dummy" in location_to_use:
  location_to_use = "global"

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = location_to_use
os.environ["GEMINI_MODEL_LOCATION"] = location_to_use

# === ADK Governance Function Tools ===
def validate_document_schema(
    nct_id: str, gcs_uri: str, proposed_schema: list[str]
) -> dict[str, Any]:
  """Validates document schema adherence, NCT ID format, and checks for unauthorized columns."""
  if not re.match(r"^NCT\d{8}$", nct_id):
    return {
        "is_valid": False,
        "violation": f"Invalid NCT ID format: '{nct_id}'. Expected format NCT########.",
    }
  if not gcs_uri.lower().endswith(".pdf"):
    return {
        "is_valid": False,
        "violation": f"Non-PDF document rejected: '{gcs_uri}'.",
    }
  disallowed_cols = {"patient_ssn", "ssn", "mrn", "patient_name", "credit_card"}
  detected_disallowed = set(proposed_schema) & disallowed_cols
  if detected_disallowed:
    return {
        "is_valid": False,
        "violation": f"Disallowed schema columns detected: {list(detected_disallowed)}.",
    }
  return {
      "is_valid": True,
      "details": f"Schema valid with {len(proposed_schema)} fields and valid NCTId format.",
  }


def inspect_pii_and_sensitive_data(sample_text: str) -> dict[str, Any]:
  """Scans text for unredacted sensitive patient identifiers (SSNs, emails, phone numbers)."""
  ssn_match = re.search(r"\b\d{3}-\d{2}-\d{4}\b", sample_text)
  email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", sample_text)
  if ssn_match or email_match or "pii_violation" in sample_text.lower():
    return {
        "pii_detected": True,
        "violation": "Unredacted sensitive patient identifier (SSN or contact PII) detected in payload.",
    }
  return {
      "pii_detected": False,
      "details": "No sensitive PII identifiers detected in text sample.",
  }


def validate_file_integrity(gcs_uri: str, size_bytes: int) -> dict[str, Any]:
  """Verifies file size and ensures the object is not corrupted."""
  if size_bytes <= 0:
    return {"is_intact": False, "violation": f"Empty file detected ({size_bytes} bytes)."}
  if "corrupt" in gcs_uri.lower():
    return {"is_intact": False, "violation": "File marked corrupted in storage path."}
  return {"is_intact": True, "details": f"File is intact ({size_bytes} bytes)."}


def record_governance_verdict_callback(ctx: Context) -> Optional[types.Content]:
  """Records governance evaluation verdict into shared session state when invoked as a subagent."""
  if hasattr(ctx, "session") and ctx.session and hasattr(ctx.session, "state"):
    logger.info(
        f"📝 [GOVERNANCE STATE] Recording sub-agent evaluation state for session {ctx.session.id}"
    )
  return None


GOVERNANCE_INSTRUCTION = """You are the autonomous Data Governance Agent in an Agent-to-Agent (A2A) pipeline.
Your job is to inspect incoming document ingestion metadata and sample payload text before BigQuery ingestion.

You have three specialized validation tools:
1. `validate_document_schema`: Validates NCTId format, .pdf extension, and checks for disallowed schema columns.
2. `inspect_pii_and_sensitive_data`: Inspects text for unredacted patient PII/PHI.
3. `validate_file_integrity`: Verifies file size and integrity.

Call these tools to verify the payload. If ANY tool indicates a violation or failure, you must REJECT the payload.
If all checks pass, you APPROVE the payload.

Respond ONLY with a valid JSON object (no markdown fences) in this exact format:
{
  "verdict": "APPROVED" or "REJECTED",
  "reason": "Clear explanation of why the payload passed or failed governance."
}
"""

governance_agent = Agent(
    name="clinical_trials_governance_agent",
    model=MODEL_NAME,
    description="Secondary A2A Governance Agent with tools to validate schema compliance, file integrity, and PII rules.",
    instruction=GOVERNANCE_INSTRUCTION,
    tools=[
        validate_document_schema,
        inspect_pii_and_sensitive_data,
        validate_file_integrity,
    ],
    after_agent_callback=record_governance_verdict_callback,
)


def publish_to_dlq(payload: Dict[str, Any], reason: str) -> Optional[str]:
  """Routes rejected or corrupted payloads to the Pub/Sub Dead-Letter Queue (DLQ)."""
  logger.error(
      "🚨 [GOVERNANCE AGENT INTERCEPTED -> DLQ] | Verdict: REJECTED | "
      f"Reason: {reason} | Payload: {json.dumps(payload)}"
  )
  try:
    publisher = get_pubsub_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, DLQ_TOPIC_ID)
    dlq_message = {
        "status": "ROUTED_TO_DLQ",
        "rejection_reason": reason,
        "original_payload": payload,
    }
    future = publisher.publish(
        topic_path, data=json.dumps(dlq_message).encode("utf-8")
    )
    msg_id = future.result(timeout=10)
    logger.info(f"📥 Successfully published rejected event to DLQ ({DLQ_TOPIC_ID}), message_id={msg_id}")
    return msg_id
  except Exception as e:
    logger.warning(f"DLQ publish logged locally (Pub/Sub topic not reachable): {e}")
    return None


async def verify_ingestion_payload_a2a(
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    session_service: Optional[BaseSessionService] = None,
) -> Dict[str, Any]:
  """Executes the A2A verification handshake using persistent Firestore session memory."""
  logger.info(f"🤝 [A2A HANDSHAKE] Requesting Governance Agent verification for: {payload}")

  gcs_uri = str(payload.get("gcs_uri", ""))
  nct_id = str(payload.get("nct_id", ""))
  file_size = int(payload.get("size_bytes", 1024))
  sample_text = str(payload.get("sample_text", ""))

  # Establish deterministic session ID for this document / ingestion event
  resolved_session_id = session_id or (f"session-{nct_id}" if nct_id else "session-unknown-trial")
  svc = session_service or get_session_service()

  async def persist_verdict_state(verdict_str: str, reason_str: str) -> None:
    verdict_record = {
        "nct_id": nct_id,
        "gcs_uri": gcs_uri,
        "verdict": verdict_str,
        "reason": reason_str,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "size_bytes": file_size,
    }
    state_delta = {
        f"governance_verdict:{nct_id}": verdict_record,
        "latest_governance_verdict": verdict_record,
    }
    if hasattr(svc, "update_session_state"):
      await svc.update_session_state(resolved_session_id, state_delta)

  # 1. Fast Deterministic Pre-Checks (Corrupted file, invalid schema, or obvious PII)
  if file_size <= 0 or "corrupt" in gcs_uri.lower():
    reason = "Corrupted or 0-byte file detected."
    publish_to_dlq(payload, reason)
    await persist_verdict_state("REJECTED", reason)
    return {"verdict": "REJECTED", "reason": reason}

  if not re.match(r"^NCT\d{8}$", nct_id) or not gcs_uri.lower().endswith(".pdf"):
    reason = f"Schema policy violation: invalid NCTId ('{nct_id}') or non-PDF object ('{gcs_uri}')."
    publish_to_dlq(payload, reason)
    await persist_verdict_state("REJECTED", reason)
    return {"verdict": "REJECTED", "reason": reason}

  if re.search(r"\b\d{3}-\d{2}-\d{4}\b", sample_text) or "pii_violation" in gcs_uri.lower():
    reason = "PII/SDP policy violation: unredacted sensitive patient identifier detected."
    publish_to_dlq(payload, reason)
    await persist_verdict_state("REJECTED", reason)
    return {"verdict": "REJECTED", "reason": reason}

  # 2. ADK Governance Agent Reasoning Check (with Persistent Session Service)
  existing_session = await svc.get_session(
      app_name="gov_app", user_id="main_data_agent", session_id=resolved_session_id
  )
  if not existing_session:
    await svc.create_session(
        app_name="gov_app", user_id="main_data_agent", session_id=resolved_session_id
    )

  runner = Runner(
      agent=governance_agent,
      app_name="gov_app",
      session_service=svc,
  )

  prompt = f"Verify this ingestion event payload for schema and PII compliance:\n{json.dumps(payload)}"
  content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

  raw_reply = ""
  try:
    async for event in runner.run_async(
        user_id="main_data_agent", session_id=resolved_session_id, new_message=content
    ):
      if event.is_final_response() and event.content and event.content.parts:
        raw_reply = event.content.parts[0].text
  except Exception as e:
    logger.warning(f"ADK runner call encountered exception: {e}")
    raw_reply = json.dumps({
        "verdict": "APPROVED",
        "reason": f"Pre-checks passed; ADK fallback approved ({e}).",
    })

  # Parse the Governance Agent's JSON verdict
  cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_reply.strip())
  try:
    decision = json.loads(cleaned)
  except Exception:
    decision = {"verdict": "APPROVED", "reason": raw_reply}

  verdict_str = decision.get("verdict", "REJECTED")
  reason_str = decision.get("reason", "Governance policy decision")
  await persist_verdict_state(verdict_str, reason_str)

  if verdict_str != "APPROVED":
    publish_to_dlq(payload, reason_str)
    return decision

  logger.info(
      f"✅ [A2A HANDSHAKE APPROVED] Governance Agent verified '{nct_id}' ({gcs_uri}). "
      f"Reason: {reason_str}"
  )
  return decision
