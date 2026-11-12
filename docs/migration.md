
---

### Part 2: Investigation — Migrating & Deploying to Gemini Enterprise Agent Platform (Vertex AI Agent Engine)

#### 1. Platform Evolution & Naming Architecture
Google Cloud's agent ecosystem has consolidated under the **Gemini Enterprise** umbrella [Gemini Enterprise Agent Platform Business Pitch [go/agentplatform-biz-pitch]](https://drive.google.com/open?id=1JKMsvaWcs6g5CgMxmaCLUh2jSWGXmYxQajC3DWXJJQ0):
* **Vertex AI Reasoning Engine -> Vertex AI Agent Engine -> Gemini Enterprise Agent Platform (Agent Runtime):** The managed serverless runtime that hosts and scales code-first ADK agents is now referred to as **Agent Engine** (or **Agent Runtime** within the **Gemini Enterprise Agent Platform**) [Gemini Enterprise Agent Platform Business Pitch [go/agentplatform-biz-pitch]](https://drive.google.com/open?id=1JKMsvaWcs6g5CgMxmaCLUh2jSWGXmYxQajC3DWXJJQ0) [Deploying ADK Agents to Agentspace - Agent Engine + Agentspace](https://g3doc.corp.google.com/enterprise/gcbp/genai/golden_gate/g3doc/deploy_adk_agent_to_agentspace.md) [Agent Development Kit (ADK) 2.0 - Agent Development Kit](https://g3doc.corp.google.com/third_party/py/google/adk/open_source_workspace/README.md).
* **Gemini Enterprise App (formerly Agentspace):** The unified enterprise frontend and orchestrator where deployed agents are registered, governed, and discovered by end-users [Gemini Enterprise Agent Platform Business Pitch [go/agentplatform-biz-pitch]](https://drive.google.com/open?id=1JKMsvaWcs6g5CgMxmaCLUh2jSWGXmYxQajC3DWXJJQ0) [Gemini Enterprise agent deployment walkthrough | Google Cloud Documentation](https://docs.cloud.google.com/gemini/enterprise/internal/agent-deployment-walkthrough).

---

#### 2. Architectural Comparison: Current DIY Stack vs. Vertex AI Agent Engine

Right now, your project runs the FastAPI RAG backend on **Cloud Run** and runs the **ADK Agent** via a custom script (`InMemorySessionService` + custom `Firestore` wrapper). Migrating to **Vertex AI Agent Engine** upgrades four core layers [Deploying AI agents with Google ADK and Vertex AI Agent Engine | by Michaël Scherding](https://michael-scherding.medium.com/deploying-ai-agents-with-google-adk-and-vertex-ai-agent-engine-62a5c19396ff):

| Layer | Current DIY Architecture (v1.0) | Managed Agent Platform (Vertex AI Agent Engine) |
| :--- | :--- | :--- |
| **Compute & Packaging** | Manual `Dockerfile` + `gcloud run deploy` | Single-command `adk deploy agent_engine` or Python SDK `AdkApp`; packages Python code, builds the container in GCS, and provisions a `reasoningEngines/{id}` endpoint automatically [Agent Runtime (Agent Engine) Deployment - ADK Dev Teams](https://g3doc.corp.google.com/learning/agents/orcas/adk_dev_teams/g3doc/dev_guide/running_on_agent_engine.md) [From ADK to Gemini Enterprise: Building Production-Grade AI Agents on Google Cloud](https://medium.com/google-cloud/from-adk-to-gemini-enterprise-building-production-grade-ai-agents-on-google-cloud-e32f4977f05a). |
| **Session Management** | Local `InMemorySessionService` + custom `agent/memory.py` Firestore writes | Managed **Agent Engine Sessions** (`create_session`, `get_session`, `list_sessions`, `delete_session`) or native `FirestoreSessionService` in ADK that persists multi-turn state across restarts and horizontal scaling [ADK Developer Guides - Agent Development Kit](https://g3doc.corp.google.com/third_party/py/google/adk/open_source_workspace/docs/guides/README.md) [Deploying AI agents with Google ADK and Vertex AI Agent Engine | by Michaël Scherding](https://michael-scherding.medium.com/deploying-ai-agents-with-google-adk-and-vertex-ai-agent-engine-62a5c19396ff). |
| **Long-Term Memory** | Manual history array slicing (`turns[-10:]`) | Managed **Vertex AI Agent Engine Memory Bank** with token-based truncation and recursive summarization to prevent context rot [Technical Guide: Building Scalable AI Agent PoCs (go/scale-ai-pocs)](https://drive.google.com/open?id=1HuwQ9bXGbILa_d7RRDuAD3xL0WHXfhsScFPVLQA7EAw). |
| **Identity & Security** | Default Compute SA (`80080086039-compute@...`) + manual OIDC Bearer header | **Bring Your Own Service Account (BYOSA)**, VPC Service Controls (VPC-SC), CMEK compliance, and built-in OAuth 2.0 user delegation [Customer Support (Agent Engine) - Vertex AI Agent Engine](https://g3doc.corp.google.com/cloud/ai/optimization/decisionai/g3doc/reasoning_engine/support.md) [Deploying ADK Agents to Agentspace - Agent Engine + Agentspace](https://g3doc.corp.google.com/enterprise/gcbp/genai/golden_gate/g3doc/deploy_adk_agent_to_agentspace.md). |
| **Observability** | Custom `agent/telemetry.py` + YAML log metrics | Native `--otel_to_cloud` flag and built-in **Agent Engine Dashboards** (Overview, Models, Tools, Usage) integrated with Cloud Trace and Cloud Logging [Agent Engine (ADK) agent data availability and reporting specification | Gemini Enterprise | Google Cloud Docu...](https://docs.cloud.google.com/gemini/enterprise/internal/usage-ae-adk-agents) [Agent Runtime (Agent Engine) Deployment - ADK Dev Teams](https://g3doc.corp.google.com/learning/agents/orcas/adk_dev_teams/g3doc/dev_guide/running_on_agent_engine.md). |

---

#### 3. Two Supported Migration Patterns for Your Architecture

##### Pattern A: Full Migration to Vertex AI Agent Engine (Recommended for Production ADK Agents)
Instead of hosting a separate FastAPI `/search` container on Cloud Run and calling it over HTTP from ADK, you deploy `root_agent` (and `governance_agent`) directly to **Vertex AI Agent Engine** [Quickstart: Develop and deploy agents on Vertex AI Agent Engine with Agent Development Kit | Gemini Enterprise...](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/quickstart-adk):
* **Eliminates the Cloud Run HTTP Hop & 403 Error:** Inside `agent/tools.py`, `search_clinical_protocols` queries BigQuery `VECTOR_SEARCH` directly using `get_bq_client()` (just like `execute_clinical_sql` does) or uses ADK's built-in `BigQueryToolset` [ADK Developer Guides - Agent Development Kit](https://g3doc.corp.google.com/third_party/py/google/adk/open_source_workspace/docs/guides/README.md). Because both tools run inside the Agent Engine runtime under your BYOSA service account, no external HTTP call or Bearer token is needed!
* **How to Deploy via ADK CLI (One Command):**
  Install the Agent Engine extras (`pip install "google-cloud-aiplatform[adk,agent_engines]>=1.153.0"`) and run [Vertex AI Agent Engine with ADK Agent Demo](https://g3doc.corp.google.com/ads/ep/agents/cloud/README.md) [Deploying ADK Agents to Agentspace - Agent Engine + Agentspace](https://g3doc.corp.google.com/enterprise/gcbp/genai/golden_gate/g3doc/deploy_adk_agent_to_agentspace.md) [Agent Runtime (Agent Engine) Deployment - ADK Dev Teams](https://g3doc.corp.google.com/learning/agents/orcas/adk_dev_teams/g3doc/dev_guide/running_on_agent_engine.md):
  ```bash
  adk deploy agent_engine \
    --project=data4ai-challenge-03 \
    --region=us-central1 \
    --staging_bucket="gs://data4ai-challenge-03-agentic-data-engineering-raw-docs-2" \
    --display_name="Clinical Trials Data Agent" \
    --otel_to_cloud \
    ./agent
