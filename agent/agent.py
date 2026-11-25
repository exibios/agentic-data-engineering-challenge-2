# agent/agent.py
import os
from google.adk.agents import Agent
from google.genai import types
from agent.config import settings
from agent.tools import (
    execute_clinical_sql,
    search_clinical_protocols,
    get_governance_verdict,
)
from agent.governance_agent import governance_agent
from agent.callbacks import (
    pii_guardrail_before_model,
    safety_response_monitor,
    sql_safety_before_tool,
)
from agent.guardrails import VERTEX_SAFETY_SETTINGS

# Sanitise GOOGLE_CLOUD_LOCATION — never forward dummy-* values to Vertex AI
location_to_use = settings.GEMINI_MODEL_LOCATION or settings.LOCATION
if not location_to_use or "dummy" in location_to_use:
    location_to_use = "global"

# Ensure ADK uses Vertex AI backend in your GCP project
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = settings.GOOGLE_GENAI_USE_VERTEXAI
os.environ["GOOGLE_CLOUD_PROJECT"] = settings.PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = location_to_use
os.environ["GEMINI_MODEL_LOCATION"] = location_to_use

PROJECT_ID = settings.PROJECT_ID
LOCATION = location_to_use
MODEL_NAME = settings.MODEL_NAME
DATASET_ID = settings.DATASET_ID
TABLE_ID = settings.TABLE_ID

SYSTEM_INSTRUCTION = f"""You are an autonomous Clinical Trials Data Agent for project `{PROJECT_ID}`.
You have access to two specialized tools AND a Governance sub-agent. Route every user question dynamically based on intent:

1. ANALYTICAL / STRUCTURED INTENT -> Call `execute_clinical_sql`:
   - Use for counts, aggregations, filtering by `overall_status`, listing trials, or looking up specific `nct_id` metadata.
   - Always query the fully qualified table: `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`.
   - Never invent column names; use only: `nct_id`, `brief_title`, `overall_status`, `doc_filename`, `cdn_url`, `gcs_uri`.

2. SEMANTIC / CONCEPTUAL INTENT -> Call `search_clinical_protocols`:
   - Use for questions about what is inside the clinical trial PDFs (inclusion/exclusion criteria, dosing schedules, primary endpoints, study objectives, adverse events).

3. HYBRID INTENT:
   - If a question requires both filtering by trial status and reading protocol details, call `execute_clinical_sql` first, then `search_clinical_protocols`.

4. GOVERNANCE / COMPLIANCE INTENT:
   - Call `get_governance_verdict` to check if a specific clinical trial (NCT ID) was evaluated, approved, or rejected by governance.
   - Delegate to `clinical_trials_governance_agent` when asked to perform real-time verification of a document schema, inspect PII/PHI policies, or audit an ingestion payload.
   - The Governance Agent has specialized tools for schema validation, PII inspection, and file integrity checks.

RESPONSE GUIDELINES:
- Always ground your answer strictly in the tool outputs.
- Cite the `nct_id` for every clinical trial mentioned.
- When using `search_clinical_protocols`, include the `section_type` and `cosine_similarity` score for transparency.
- All user prompts are automatically scanned for PII before reaching you. Treat all data as de-identified.
"""

root_agent = Agent(
    name="clinical_trials_data_agent",
    model=MODEL_NAME,
    description=(
        "Conversational Data Agent that routes between BigQuery SQL analytics,"
        " FastAPI Vector Search over ClinicalTrials.gov documents, and a"
        " Governance sub-agent for schema/PII/compliance validation."
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[execute_clinical_sql, search_clinical_protocols, get_governance_verdict],
    # --- Governance sub-agent (ADK-native A2A delegation) ---
    sub_agents=[governance_agent],
    # --- Safety settings applied at model generation time ---
    generate_content_config=types.GenerateContentConfig(
        safety_settings=VERTEX_SAFETY_SETTINGS,
    ),
    # --- ADK Callbacks for Guardrails ---
    before_model_callback=pii_guardrail_before_model,
    after_model_callback=safety_response_monitor,
    before_tool_callback=sql_safety_before_tool,
)
