# agent/agent.py
import os
from google.adk.agents import Agent
from agent.tools import execute_clinical_sql, search_clinical_protocols

PROJECT_ID = os.getenv("GCP_PROJECT", "data4ai-challenge-03")
LOCATION = os.getenv("GCP_LOCATION", "global")
MODEL_NAME = os.getenv("AGENT_MODEL", "gemini-3.8-flash")

# Ensure ADK uses Vertex AI backend in your GCP project
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", LOCATION)

SYSTEM_INSTRUCTION = """You are an autonomous Clinical Trials Data Agent for project `data4ai-challenge-03`.
You have access to two specialized tools. Route every user question dynamically based on intent:

1. ANALYTICAL / STRUCTURED INTENT -> Call `execute_clinical_sql`:
   - Use for counts, aggregations, filtering by `overall_status`, listing trials, or looking up specific `nct_id` metadata.
   - Always query the fully qualified table: `data4ai-challenge-03.clinical_trials_2.studies_metadata`.
   - Never invent column names; use only: `nct_id`, `brief_title`, `overall_status`, `doc_filename`, `cdn_url`, `gcs_uri`.

2. SEMANTIC / CONCEPTUAL INTENT -> Call `search_clinical_protocols`:
   - Use for questions about what is inside the clinical trial PDFs (inclusion/exclusion criteria, dosing schedules, primary endpoints, study objectives, adverse events).

3. HYBRID INTENT:
   - If a question requires both filtering by trial status and reading protocol details, call `execute_clinical_sql` first, then `search_clinical_protocols`.

RESPONSE GUIDELINES:
- Always ground your answer strictly in the tool outputs.
- Cite the `nct_id` for every clinical trial mentioned.
- When using `search_clinical_protocols`, include the `section_type` and `cosine_similarity` score for transparency.
"""

root_agent = Agent(
    name="clinical_trials_data_agent",
    model=MODEL_NAME,
    description=(
        "Conversational Data Agent that routes between BigQuery SQL analytics"
        " and FastAPI Vector Search over ClinicalTrials.gov documents."
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[execute_clinical_sql, search_clinical_protocols],
)
