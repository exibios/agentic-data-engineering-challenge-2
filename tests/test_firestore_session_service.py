# tests/test_firestore_session_service.py
"""Unit tests for FirestoreSessionService, SessionMemory, and Inter-Agent Memory Sharing."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
  sys.path.insert(0, str(repo_root))

from google.adk.events import Event
from google.adk.sessions import Session
from google.genai import types

from agent.memory import FirestoreSessionService, SessionMemory
from agent.tools import get_governance_verdict


class TestFirestoreSessionService(unittest.IsolatedAsyncioTestCase):

  async def test_in_memory_fallback_lifecycle(self):
    """Verifies that FirestoreSessionService falls back to in-memory store cleanly."""
    service = FirestoreSessionService(collection_name="test_sessions", database="test_db")

    with patch.object(service, "_get_collection", return_value=None):
      session_id = "test-session-fallback-01"
      created = await service.create_session(
          app_name="clinical_trials_app",
          user_id="tester",
          session_id=session_id,
          state={"governance_verdict:NCT01234567": {"verdict": "APPROVED"}},
      )
      self.assertEqual(created.id, session_id)
      self.assertEqual(
          created.state["governance_verdict:NCT01234567"]["verdict"], "APPROVED"
      )

      # Append an event
      event = Event(
          author="model",
          content=types.Content(
              role="model",
              parts=[types.Part.from_text(text="Trial NCT01234567 verified.")],
          ),
          timestamp=1732480000.0,
      )
      appended = await service.append_event(created, event)
      self.assertEqual(len(created.events), 1)

      # Retrieve session
      retrieved = await service.get_session(
          app_name="clinical_trials_app",
          user_id="tester",
          session_id=session_id,
      )
      self.assertIsNotNone(retrieved)
      self.assertEqual(retrieved.id, session_id)
      self.assertEqual(len(retrieved.events), 1)

  async def test_update_session_state_and_tool_retrieval(self):
    """Verifies that governance verdict written to session state is retrieved by get_governance_verdict."""
    service = FirestoreSessionService(collection_name="test_sessions")
    session_id = "session-NCT09999999"

    with patch.object(service, "_get_collection", return_value=None):
      await service.create_session(
          app_name="gov_app",
          user_id="main_data_agent",
          session_id=session_id,
      )

      verdict_record = {
          "nct_id": "NCT09999999",
          "verdict": "APPROVED",
          "reason": "All checks passed cleanly.",
          "timestamp": datetime.now(timezone.utc).isoformat(),
      }
      await service.update_session_state(
          session_id,
          {
              "governance_verdict:NCT09999999": verdict_record,
              "latest_governance_verdict": verdict_record,
          },
      )

      # Test retrieval via ToolContext state
      mock_tool_context = MagicMock()
      mock_tool_context.state = {
          "governance_verdict:NCT09999999": verdict_record,
          "latest_governance_verdict": verdict_record,
      }

      res = get_governance_verdict("NCT09999999", tool_context=mock_tool_context)
      self.assertEqual(res["status"], "found")
      self.assertEqual(res["verdict"]["verdict"], "APPROVED")
      self.assertEqual(res["nct_id"], "NCT09999999")

  def test_get_governance_verdict_not_found(self):
    """Verifies that get_governance_verdict returns not_found when trial is absent."""
    mock_tool_context = MagicMock()
    mock_tool_context.state = {}
    with patch("agent.memory.get_session_service") as mock_svc:
      mock_svc.return_value.get_session_state_sync.return_value = {}
      res = get_governance_verdict("NCT00000000", tool_context=mock_tool_context)
      self.assertEqual(res["status"], "not_found")
      self.assertEqual(res["nct_id"], "NCT00000000")


if __name__ == "__main__":
  unittest.main()
