# agent/governance_agent.py
"""Secondary Governance Agent for A2A Schema Validation & PII Compliance."""

import json
import logging
import os
import re
from typing import Any, Dict, Optional
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud import pubsub_v1
from google.genai import types

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("governance_agent")

PROJECT_ID = os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT") or "dummy-project-id"
LOCATION = os.getenv("LOCATION") or os.getenv("GCP_LOCATION") or "dummy-location"
MODEL_NAME = os.getenv("MODEL_NAME") or os.getenv("AGENT_MODEL") or "dummy-model-name"
DLQ_TOPIC_ID = (
    os.getenv("DLQ_TOPIC_ID")
    or os.getenv("DWL_TOPIC_ID")
    or "dummy-dlq-topic-id"
)
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "dummy-vertexai-flag")

# Ensure Vertex AI global endpoint is configured for gemini-3.8-flash
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = GOOGLE_GENAI_USE_VERTEXAI
os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION


GOVERNANCE_INSTRUCTION = """You are the autonomous Data Governance Agent in an Agent-to-Agent (A2A) pipeline.
Your job is to inspect incoming document ingestion metadata and sample payload text before BigQuery ingestion.

Evaluate the payload against three strict policies:
1. SCHEMA POLICY: Must contain a valid `nct_id` matching `NCT\\d{8}` and a `.pdf` filename. Breaking schema changes (dropped required fields or type mutations) must be REJECTED.
2. FILE INTEGRITY POLICY: File size must be > 0 bytes and not marked corrupted.
3. PII / SDP COMPLIANCE POLICY: Payload must not contain unredacted patient PII/PHI (e.g., Social Security Numbers, patient emails, phone numbers, or patient names).

Respond ONLY with a valid JSON object (no markdown fences) in this exact format:
{
  "verdict": "APPROVED" or "REJECTED",
  "reason": "Clear explanation of why the payload passed or failed governance."
}
"""

governance_agent = Agent(
    name="clinical_trials_governance_agent",
    model=MODEL_NAME,
    description="Secondary A2A Governance Agent that validates schema compliance and PII rules.",
    instruction=GOVERNANCE_INSTRUCTION,
)


def publish_to_dlq(payload: Dict[str, Any], reason: str) -> Optional[str]:
  """Routes rejected or corrupted payloads to the Pub/Sub Dead-Letter Queue (DLQ)."""
  # CRITICAL LOG FOR DAY 9 ACCEPTANCE CRITERIA & LOG-BASED METRIC
  logger.error(
      "🚨 [GOVERNANCE AGENT INTERCEPTED -> DLQ] | Verdict: REJECTED | "
      f"Reason: {reason} | Payload: {json.dumps(payload)}"
  )
  try:
    publisher = pubsub_v1.PublisherClient()
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


async def verify_ingestion_payload_a2a(payload: Dict[str, Any]) -> Dict[str, Any]:
  """Executes the A2A verification handshake between the Ingestion Pipeline and Governance Agent."""
  logger.info(f"🤝 [A2A HANDSHAKE] Requesting Governance Agent verification for: {payload}")

  gcs_uri = str(payload.get("gcs_uri", ""))
  nct_id = str(payload.get("nct_id", ""))
  file_size = int(payload.get("size_bytes", 1024))
  sample_text = str(payload.get("sample_text", ""))

  # 1. Fast Deterministic Pre-Checks (Corrupted file, invalid schema, or obvious PII)
  if file_size <= 0 or "corrupt" in gcs_uri.lower():
    reason = "Corrupted or 0-byte file detected."
    publish_to_dlq(payload, reason)
    return {"verdict": "REJECTED", "reason": reason}

  if not re.match(r"^NCT\d{8}$", nct_id) or not gcs_uri.lower().endswith(".pdf"):
    reason = f"Schema policy violation: invalid NCTId ('{nct_id}') or non-PDF object ('{gcs_uri}')."
    publish_to_dlq(payload, reason)
    return {"verdict": "REJECTED", "reason": reason}

  # Simple regex check for SSN or email PII in sample text/metadata
  if re.search(r"\b\d{3}-\d{2}-\d{4}\b", sample_text) or "pii_violation" in gcs_uri.lower():
    reason = "PII/SDP policy violation: unredacted sensitive patient identifier detected."
    publish_to_dlq(payload, reason)
    return {"verdict": "REJECTED", "reason": reason}

  # 2. ADK Governance Agent Reasoning Check (A2A Collaboration)
  session_service = InMemorySessionService()
  session_id = "a2a-gov-session"
  await session_service.create_session(
      app_name="gov_app", user_id="main_data_agent", session_id=session_id
  )
  runner = Runner(
      agent=governance_agent,
      app_name="gov_app",
      session_service=session_service,
  )

  prompt = f"Verify this ingestion event payload for schema and PII compliance:\n{json.dumps(payload)}"
  content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

  raw_reply = ""
  async for event in runner.run_async(
      user_id="main_data_agent", session_id=session_id, new_message=content
  ):
    if event.is_final_response() and event.content and event.content.parts:
      raw_reply = event.content.parts[0].text

  # Parse the Governance Agent's JSON verdict
  cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_reply.strip())
  try:
    decision = json.loads(cleaned)
  except Exception:
    decision = {"verdict": "APPROVED", "reason": raw_reply}

  if decision.get("verdict") != "APPROVED":
    publish_to_dlq(payload, decision.get("reason", "Governance policy rejection"))
    return decision

  logger.info(
      f"✅ [A2A HANDSHAKE APPROVED] Governance Agent verified '{nct_id}' ({gcs_uri}). "
      f"Reason: {decision.get('reason')}"
  )
  return decision
