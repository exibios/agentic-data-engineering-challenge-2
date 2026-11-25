# tests/test_firestore_session_service.py
"""Unit and Live Integration Tests for FirestoreSessionService & Inter-Agent Memory."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
  sys.path.insert(0, str(repo_root))

from google.adk.events import Event
from google.genai import types

from agent.clients import get_firestore_client
from agent.config import settings
from agent.memory import FirestoreSessionService, get_session_service
from agent.tools import get_governance_verdict


class TestFirestoreSessionServiceUnit(unittest.IsolatedAsyncioTestCase):

  def test_custom_database_forwarded_to_client(self):
    """Verifies FirestoreSessionService forwards its database parameter to get_firestore_client."""
    service = FirestoreSessionService(
        collection_name="custom_col", database="custom-db-name"
    )
    with patch("agent.memory.get_firestore_client") as mock_get_client:
      service._get_collection()
      mock_get_client.assert_called_once_with(database="custom-db-name")
      mock_get_client.return_value.collection.assert_called_once_with("custom_col")

  def test_no_sticky_fallback_after_transient_error(self):
    """Verifies a transient Firestore failure does NOT permanently lock out Firestore."""
    service = FirestoreSessionService(
        collection_name="test_sessions", database="clinical-trials-agents-sessions-db"
    )
    mock_collection = MagicMock()

    with patch("agent.memory.get_firestore_client") as mock_get_client:
      # First call fails transiently; second call succeeds
      mock_client = MagicMock()
      mock_client.collection.return_value = mock_collection
      mock_get_client.side_effect = [RuntimeError("Transient cold-start error"), mock_client]

      col1 = service._get_collection()
      self.assertIsNone(col1)

      col2 = service._get_collection()
      self.assertIs(col2, mock_collection)

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

      event = Event(
          author="model",
          content=types.Content(
              role="model",
              parts=[types.Part.from_text(text="Trial NCT01234567 verified.")],
          ),
          timestamp=1732480000.0,
      )
      await service.append_event(created, event)
      self.assertEqual(len(created.events), 1)

      retrieved = await service.get_session(
          app_name="clinical_trials_app",
          user_id="tester",
          session_id=session_id,
      )
      self.assertIsNotNone(retrieved)
      self.assertEqual(retrieved.id, session_id)
      self.assertEqual(len(retrieved.events), 1)

  async def test_update_session_state_and_tool_retrieval(self):
    """Verifies governance verdict written to session state is retrieved by get_governance_verdict."""
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


class TestFirestoreSessionServiceLive(unittest.IsolatedAsyncioTestCase):
  """Live integration test against Cloud Firestore (run with RUN_LIVE_FIRESTORE_TESTS=true)."""

  @unittest.skipUnless(
      os.getenv("RUN_LIVE_FIRESTORE_TESTS") == "true",
      "Set RUN_LIVE_FIRESTORE_TESTS=true to run live Cloud Firestore integration tests.",
  )
  async def test_live_firestore_roundtrip(self):
    get_firestore_client.cache_clear()
    service = FirestoreSessionService(
        collection_name=settings.FIRESTORE_COLLECTION,
        database=settings.FIRESTORE_DATABASE,
    )
    session_id = f"live-parity-test-{int(time.time())}"
    nct_id = "NCT99998888"

    try:
      created = await service.create_session(
          app_name="clinical_trials_app",
          user_id="live_tester",
          session_id=session_id,
          state={"init": True},
      )
      self.assertIsNone(service._in_memory_fallback, "Should NOT fall back to in-memory!")
      self.assertEqual(created.id, session_id)

      await service.update_session_state(
          session_id,
          {f"governance_verdict:{nct_id}": {"verdict": "APPROVED", "nct_id": nct_id}},
      )

      retrieved = await service.get_session(
          app_name="clinical_trials_app",
          user_id="live_tester",
          session_id=session_id,
      )
      self.assertIsNotNone(retrieved)
      self.assertEqual(
          retrieved.state[f"governance_verdict:{nct_id}"]["verdict"], "APPROVED"
      )
    finally:
      await service.delete_session(
          app_name="clinical_trials_app",
          user_id="live_tester",
          session_id=session_id,
      )


if __name__ == "__main__":
  unittest.main()
