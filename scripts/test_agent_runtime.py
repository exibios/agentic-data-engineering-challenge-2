#!/usr/bin/env python3
# scripts/test_agent_runtime.py
# export AGENT_ENGINE_RESOURCE_NAME='projects/80080086039/locations/us-central1/reasoningEngines/2889526728277884928'
# export AGENT_ENGINE_RESOURCE_NAME='projects/80080086039/locations/us-central1/reasoningEngines/2162648387248193536'
import os
import vertexai
from vertexai import agent_engines

PROJECT_ID = "data4ai-challenge-03"
REGION = "us-central1"
RESOURCE_NAME = os.environ["AGENT_ENGINE_RESOURCE_NAME"]


def ask_remote_agent(remote_agent, user_id: str, session_id: str, prompt: str):
  print(f"\n🧑 USER: {prompt}")
  for event in remote_agent.stream_query(
      user_id=user_id, session_id=session_id, message=prompt
  ):
    for part in event.get("content", {}).get("parts", []):
      if "function_call" in part:
        print(
            f"🛠️ [REMOTE AGENT TOOL CALL]: {part['function_call']['name']}"
        )
      if "text" in part:
        print(f"🤖 AGENT: {part['text']}")


def main():
  vertexai.init(project=PROJECT_ID, location=REGION)
  remote_agent = agent_engines.get(RESOURCE_NAME)

  # 1. Create a Managed Session on Agent Runtime
  session = remote_agent.create_session(user_id="franco")
  session_id = session["id"]
  print(f"✅ Created Managed Agent Engine Session: {session_id}")

  # 2. Test Analytical SQL Routing (Agent Runtime -> BigQuery)
  ask_remote_agent(
      remote_agent,
      "franco",
      session_id,
      "How many clinical trials are in our studies_metadata table grouped by overall_status?",
  )

  # 3. Test Semantic Vector Search Routing (Agent Runtime -> OIDC Auth -> Cloud Run /search)
  ask_remote_agent(
      remote_agent,
      "franco",
      session_id,
      "What are the inclusion criteria and dosing schedules in the clinical trial protocols?",
  )


if __name__ == "__main__":
  main()
