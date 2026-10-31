# scripts/test_day8_agent.py
import asyncio
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass

from agent.agent import root_agent
from agent.memory import SessionMemory

APP_NAME = os.getenv("APP_NAME", "clinical_trials_app")
USER_ID = os.getenv("USER_ID", "challenge_engineer")
SESSION_ID = os.getenv("SESSION_ID", "day8-verification-session")



async def ask_agent(runner: Runner, memory: SessionMemory, prompt: str) -> None:
  print("\n" + "=" * 80)
  print(f"🧑 USER PROMPT: {prompt}")
  print("=" * 80)

  # Persist user turn in Firestore (from Day 7 SessionMemory)
  try:
    memory.add_turn(SESSION_ID, "user", prompt)
  except Exception:
    pass

  content = types.Content(
      role="user", parts=[types.Part.from_text(text=prompt)]
  )
  final_text = ""

  async for event in runner.run_async(
      user_id=USER_ID, session_id=SESSION_ID, new_message=content
  ):
    if event.is_final_response() and event.content and event.content.parts:
      final_text = event.content.parts[0].text

  print(f"\n🤖 AGENT RESPONSE:\n{final_text}\n")

  # Persist assistant response in Firestore
  try:
    memory.add_turn(SESSION_ID, "assistant", final_text)
  except Exception:
    pass


async def main():
  session_service = InMemorySessionService()
  await session_service.create_session(
      app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
  )

  runner = Runner(
      agent=root_agent,
      app_name=APP_NAME,
      session_service=session_service,
  )
  firestore_memory = SessionMemory()

  # Test 1: Analytical Intent -> Must dynamically trigger `execute_clinical_sql`
  await ask_agent(
      runner,
      firestore_memory,
      "How many clinical trials do we have per overall_status in our metadata"
      " table?",
  )

  # Test 2: Semantic Intent -> Must dynamically trigger `search_clinical_protocols`
  await ask_agent(
      runner,
      firestore_memory,
      "What are the common inclusion and exclusion criteria for patients across"
      " our protocols?",
  )


if __name__ == "__main__":
  asyncio.run(main())
