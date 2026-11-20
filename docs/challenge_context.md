GSD LatAm - Data vPractice

Partner - Data Agent Challenge

Last updated: Oct 5, 2026

Authors:

Cristian Devrient Gomez, Clara Rodriguez, Leonardo Almiron, Matias Ferraro,

Azul Zaietz, Sam Sobrino, Georgina De Bellis



Attendees who wish to monitor their advancement or record specific

observations are encouraged to create a personal copy of this resource.



Context

Modern data engineering pipelines are evolving rapidly to leverage agentic workflows,

LLM-powered orchestrations, and real-time integration across complex, multi-modal data

ecosystems. As a result, data engineers and architects often face challenges in designing

scalable, autonomous data platforms that go beyond traditional ETL/ELT.

We have designed this hands-on practice to cover foundational knowledge required to

architect intelligent data agents, build resilient event-driven data pipelines, and orchestrate

automated data governance solutions using modern agentic frameworks.



Objective

Reach working proficiency in Agentic Data Engineering enough to design, architect, deploy,

and govern intelligent data agents on Google Cloud without supervision and prove it with a

shipped, autonomous data project.



Concretely, by day 10 you can:

1. Understand foundational Gen AI and leverage Gemini Enterprise for data orchestration.

2. Utilize Vertex AI Studio for multimodal prompt engineering and implement BigQuery

Vector Search.

3. Understand conversational agents and initialize the Agent Development Kit (ADK)

framework.

4. Optimize agent instructions, manage persistent memory states, and configure custom

tool schemas.

5. Operationalize AI agents with AgentOps, including CI/CD deployment, basic monitoring,

and safety compliance.

6. Design and architect structured ingestion pipelines using GCS Object Tables and

BigQuery metadata extraction.

7. Generate embeddings via BigQuery ML and deploy a FastAPI Retrieval-Augmented

Generation (RAG) backend.

8. Initialize the ADK framework to build a custom Data Agent equipped with SQL and

semantic search tools.

9. Orchestrate event-driven pipelines with Eventarc and deploy an automated

agent-to-agent (A2A) governance loop.

10. Implement advanced telemetry (OpenTelemetry, Cloud Logging), integrate DLP safety

settings, and perform load testing.



Goal for the program: It is NOT passing a certification exam. This is a build-competence

sprint, not an exam cram.



Requirements

The ideal candidate for the program should have:

- GCP fundamentals - learning path

- Data Engineering practice experience in some service stack (GCP preferable)

- Programming skills

- Active GCP Project with Billing enabled (for project work)



Prerequisite knowledge (self-check on Day 0)

You should already be comfortable with:

- Intermediate Python skills, including experience with FastAPI and asynchronous REST

API development.

- Familiarity with containerization (Docker/Cloud Run basics) for the Day 7 FastAPI

deployment.

- Core Data Engineering concepts, such as ETL/ELT pipeline design, data modeling,

schema evolution, and automated data governance.

- Familiarity with cloud-native Event-Driven architectures and messaging patterns (e.g.,

Pub/Sub, Eventarc, or webhooks).



Out of Scope

Explicitly excluded so the two weeks stay achievable:

- Machine Learning.

- Google Cloud Certification Exams.



Curriculum - Key Focus Topics

- Generative AI & LLM Foundations: D1 (Gen AI Intro, Gemini Enterprise), D2 (Vertex AI Studio, Multimodal)

- Vector Search & RAG Architectures: D2 (Embeddings, BQ Vector search), D7 (BQ ML, BQ Vector Index, FastAPI RAG)

- Agent Framework & ADK: D3 (Cloud Agents intro), D4 (ADK optimization), D8 (ADK python initialization)

- Custom Tool Development: D4 (Agent capabilities, schema definition), D8 (SQL Execution & Vector Search tools)

- Event-Driven Data Pipelines: D6 (Ingestion design), D9 (Eventarc, GCS to Pub/Sub async pipeline)

- A2A Multi-Agent Systems & Collaboration: D9 (Main Agent & Governance Agent schema/PII verification loop)

- AgentOps & Telemetry: D5 (Monitoring, operationalization), D10 (OpenTelemetry, Cloud Logging metrics)

- Safety, Guardrails & Governance: D5 (Compliance, guardrails), D10 (Cloud DLP PII redaction, Vertex AI Safety)

- Modern Language Proficiency: Python, FastAPI, and OpenTelemetry throughout (Week 2: D6-D10)



Content

Week 1 - Courses (Google Skills)



Day 1 - Foundational

- Course: Introduction to Generative AI (45 mins)

- Course: Introduction to Gemini Enterprise (2:15 hrs)

- Course: Create Generative AI Apps on Google Cloud (4 hours)



Day 2 - Vertex AI Introduction

- Course: Introduction to Vertex AI Studio (2 hrs)

  - Prompt to product lifecycle.

  - Multimodal applications.

  - Prompt design.

  - Prompt engineering.

  - Model tuning.

- Course: Vector Search and Embeddings - skill badge, Introductory (4 hrs)

  - Vector search basics.

  - Encode with embeddings.

  - Index and search.

  - Vertex AI Vector search.

  - RAG and grounded agent.

  - Hybrid search.

- Course: Implement Multimodal Vector Search with BigQuery (30 mins)

  - Developing code with Gemini in BigQuery.

  - Creating RAG Applications with BigQuery.

  - Challenge Lab.



Day 3 - Agents Introduction

- Course: Understand Google Cloud Agents (8 hrs)

  - Gemini Enterprise app.

  - Conversational Agents.

  - Customer Experience Studio.

  - Gemini Enterprise Agent Platform.

  - ADK (intro).



Day 4 - Agent Engineering & Operations

- Course: Optimize Agent Behavior (1 hr)

  - Prompt engineering and fine-tuning agent instructions.

  - Optimizing system prompts and context length.

  - Evaluating and benchmarking response quality.

- Course: Add Agent Capabilities With Tools (1 hr)

  - Connecting agents to external APIs and services.

  - Function calling and schema definition.

  - Tool authorization and execution error handling.

- Course: Manage Agent Memory and State (1 hr)

  - Short-term conversational context vs. long-term memory.

  - Session management and persistent state storage.

  - Summarization and memory retrieval strategies.

- Course: Engineer AI Agents with Agent Development Kit (ADK) (1:45 hrs)

  - ADK framework architecture and component initialization.

  - Custom tool development and integration using ADK.

  - Local testing, debugging, and deployment workflows.



Day 5 - AgentOps

- Course: Operationalize AI Agents on Google Cloud (5 hrs)

  - CI/CD pipelines for agent deployment and versioning.

  - Monitoring, logging, and performance telemetry for AI agents.

  - Governance, safety guardrails, and compliance in production.



Week 2 - Personal Project: Autonomous Agentic Data Pipeline

Public Datasets program (such as the GitHub Archive or US Census Data) to ingest, analyze,

and build agentic workflows over large-scale real-world data without needing to upload local

datasets.



Data Budget & Volume Restrictions:

To prevent runaway billing in GCP resources, participants won't deploy large-scale production

datasets. The practical pipeline must be built using a controlled mix of structured metadata and

unstructured documents:

- Unstructured Volume Limit: A maximum of 50 to 100 individual documents (e.g., text,

  PDF, or JSON format), with an average size of less than 5-10 pages per document.

- Structured Volume Limit: Structured database tables and object table records should

  scale proportionally, maintaining a footprint of around 500 rows and under 1 GB of total

  storage.



Structured dataset proposed: Clinical Trials.gov link

Unstructured data proposed: link



1. For Structured Data:

Use the Clinical Trials.gov API v2 /studies endpoint to query trial metadata:

a. Base URL: https://clinicaltrials.gov/api/v2/studies

b. API Parameters: Query using fields like NCTId and DocumentSection. You can

   filter for trials containing large documents with:

   filter.advanced=AREA[LargeDocHasProtocol]=true OR

   AREA[LargeDocHasSAP]=true OR AREA[LargeDocHasCF]=true



2. For Unstructured Documents (PDFs):

PDFs (Protocols, SAPs, ICFs) are hosted on the Clinical Trials.gov CDN (not retrieved

directly from the API). Programmatically construct the download URL for each

document using the metadata obtained from the API:

a. CDN URL Format:

   https://cdn.clinicaltrials.gov/large-docs/{last_two_digits_of_NCTId}/{NCTId}/{filename}

b. Example: For study NCT04001234 and file protocol.pdf, the URL is:

   https://cdn.clinicaltrials.gov/large-docs/34/NCT04001234/protocol.pdf



Day 6 - Design & Ingestion Pipeline (~2.5 h)

Goal: Design the end-to-end agentic data pipeline architecture and set up

unstructured-to-structured ingestion.

Activities:

- Create a schema for document ingestion and metadata extraction: POST /v1/ingest, GET /v1/metadata/{id}.

- Set up a BigQuery Object Table over Google Cloud Storage (GCS) to catalog raw unstructured documents.

- Write docs/ARCHITECTURE.md explaining the flow: GCS -> Object Table -> BigQuery ML (Gemini) metadata extraction -> BigQuery Vector Search. Highlight the asynchronous Eventarc/Pub/Sub flow and why we use async ingestion.

- Write docs/ADR-001-agentic-ingestion.md describing the chunking strategies, model selection (Gemini 1.5 Flash vs. Pro), and schema evolution policies.

- Scaffold the project repository structure: /pipeline, /agent, /infra, /docs, /scripts.

- Data Governance, SDP.



Day 7 - Embeddings & Vector Search (~6 h)

Goal: Generate vector embeddings on ingestion and set up semantic indexing.

Activities:

- Use BigQuery ML to generate text embeddings (ML.GENERATE_EMBEDDING) from the extracted metadata and document chunks.

- Create a Vector Index in BigQuery (CREATE VECTOR INDEX) to enable high-performance semantic search over the corpus.

- Implement a Python FastAPI backend deployed on Cloud Run that exposes semantic search capabilities over BigQuery.

- Configure Firestore to persist short-term conversational context and agent session states.



Day 8 - Data Agent & Custom Tools (~3.5 h)

Goal: Build a conversational Data Agent using the Agent Development Kit (ADK) with

custom data tools.

Activities:

- Initialize the ADK framework for Python to develop your intelligent agent.

- Create two custom tools for the agent:

  - SQL Execution Tool: Dynamically translates natural language analytical queries into structured BigQuery SQL and executes them.

  - Vector Search Tool: Interacts with the FastAPI semantic search endpoint to fetch unstructured context.

- Optimize and fine-tune the agent's system instructions and prompt context length in Vertex AI Studio.



Day 9 - Event-Driven Automation & Inter-Agent Collaboration (~2.5 h)

Goal: Automate pipeline ingestion and implement agent-to-agent verification.

Activities:

- Set up an Eventarc trigger that detects new files in GCS and publishes a Pub/Sub event to automatically run the metadata extraction and vector index update.

- Agent-to-Agent (A2A) Communication Scenario: Implement inter-agent collaboration where the main Data Agent triggers a secondary Governance Agent via Pub/Sub or direct gRPC calls to validate schema changes and PII compliance, proceeding with the data ingestion pipeline only upon receiving explicit agreement and verification from the Governance Agent.

- Configure retry policies and a Dead-Letter Queue (DLQ) for failed ingestion events, including a log-based metric for monitoring DLQ depth.



Day 10 - AgentOps, Guardrails, and Demo (~2.5 h)

Goal: Harden security, instrument telemetry, and demonstrate the operational pipeline.

Activities:

- Integrate Cloud DLP or Vertex AI Safety Settings as a security guardrail to redact PII and filter out unsafe inputs/outputs.

- Set up monitoring and logging using Cloud Logging and OpenTelemetry to trace tool calls, model latency, and token execution costs per session.

- Run a local load test (e.g., using k6 or hey) to verify concurrency behavior on the agent endpoints.

- Prepare and record a 15-minute demo showcasing the end-to-end flow: raw document upload -> event-driven extraction & Governance Agent check -> querying the Data Agent in natural language.



Acceptance Criteria

- Day 6: The project Git repository must contain the /docs directory including the /v1/ingest API schema successfully verified in the FastAPI Swagger UI (/docs), with the basic folder structure scaffolded. You can perform a semantic query against the FastAPI endpoint and retrieve the most relevant document chunks from BigQuery.

- Day 7: A test curl request executed against the FastAPI /search endpoint must return a structured JSON response containing the most relevant retrieved document chunks alongside their matching cosine similarity scores.

- Day 8: The agent can dynamically decide whether to query structured data using SQL or perform a semantic vector search based on the user's natural language question. Consoles or application logs must visibly demonstrate that the ADK routing layer dynamically selects the SQL Execution Tool for analytical query intents (e.g., aggregations) and the Vector Search Tool for semantic/conceptual query intents.

- Day 9: A document upload to GCS triggers automatic ingestion, schema validation via the Governance Agent, and vector updating, with failures routing to the DLQ. An ingestion test using a corrupted or policy-violating file in GCS must trigger a failure, with execution logs in Cloud Logging confirming that the Governance Agent successfully intercepted the payload and routed it to the Dead-Letter Queue (DLQ).

- Day 10: The pipeline is fully secured, monitored, load-tested, and demonstrated. A Cloud Logging monitoring dashboard output must display active performance metrics, capturing total token consumption per session and average latency under a simulated API concurrent request load test.



Self-Assessment

Soft criteria (self-assessed on Day 10, 1-5):

- I can articulate the architectural differences between traditional automated pipelines and autonomous agentic workflows, focusing on non-deterministic planning and agent reasoning capabilities.

- I can design and implement ADK-based agentic workflows, creating custom tools that bridge structured SQL queries with unstructured semantic vector retrieval.

- I can explain the architecture of multi-agent systems, specifically regarding A2A (Agent-to-Agent) collaboration for governance, schema verification, and compliance validation.

- I can implement and defend robust AgentOps patterns, including telemetry, cost-per-token tracking, and safety guardrails in event-driven production pipelines.

- I could build a secure, event-driven agentic pipeline with automated metadata extraction, RAG indexing, and governance checks from scratch in under 90 minutes.



Anti-criteria - signs the sprint went wrong:

- More time spent watching theory videos than actively writing ADK code or debugging agent-to-agent interactions.

- Solving semantic search inaccuracies solely through prompt engineering instead of tuning Vector Index parameters or chunking strategies.

- Bypassing the Governance Agent's validation logic just to 'make the demo pass'.

- Ignoring tool execution latency, token costs, or Cloud Logging telemetry during development.

- A project that functions during the demo but uses hardcoded logic rather than dynamic agent reasoning.

- Zero commits during the build week.