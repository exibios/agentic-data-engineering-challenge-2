# tests/test_firestore_session_service.py
"""Unit and Live Integration Tests for the Hybrid Blackboard Pattern (Firestore)."""

import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
  sys.path.insert(0, str(repo_root))

from agent.clients import get_firestore_client
from agent.tools import (
    BLACKBOARD_INGEST_COLLECTION,
    BLACKBOARD_VERDICTS_COLLECTION,
    get_governance_verdict,
    record_governance_verdict,
    record_ingest_event,
)


class TestFirestoreBlackboardUnit(unittest.TestCase):

  def test_record_ingest_event_writes_to_blackboard(self):
    """Verifies record_ingest_event writes to ingest_records/{nct_id}."""
    mock_db = MagicMock()
    with patch("agent.tools.get_firestore_client", return_value=mock_db):
      res = record_ingest_event(
          nct_id="NCT01234567",
          gcs_uri="gs://bucket/raw/NCT01234567/Prot_000.pdf",
          size_bytes=1024,
          status="PENDING_GOVERNANCE",
      )
      self.assertEqual(res["status"], "recorded")
      mock_db.collection.assert_called_with(BLACKBOARD_INGEST_COLLECTION)
      mock_db.collection.return_value.document.assert_called_with("NCT01234567")
      mock_db.collection.return_value.document.return_value.set.assert_called_once()

  def test_record_and_get_governance_verdict(self):
    """Verifies record_governance_verdict writes and get_governance_verdict reads from Firestore Blackboard."""
    store = {}

    def make_doc(col_name, doc_id):
      doc_mock = MagicMock()

      def _set(data, merge=True, timeout=None):
        existing = store.setdefault((col_name, doc_id), {})
        if merge:
          existing.update(data)
        else:
          store[(col_name, doc_id)] = dict(data)

      def _get(timeout=None):
        snap = MagicMock()
        key = (col_name, doc_id)
        snap.exists = key in store
        snap.to_dict.return_value = store.get(key, {})
        return snap

      doc_mock.set.side_effect = _set
      doc_mock.get.side_effect = _get
      return doc_mock

    mock_db = MagicMock()
    mock_db.collection.side_effect = lambda col_name: MagicMock(
        document=lambda doc_id: make_doc(col_name, doc_id)
    )

    with patch("agent.tools.get_firestore_client", return_value=mock_db):
      write_res = record_governance_verdict(
          nct_id="NCT09999999",
          verdict="APPROVED",
          reason="Schema and PII checks passed.",
          gcs_uri="gs://bucket/raw/NCT09999999/Prot_000.pdf",
          size_bytes=2048,
      )
      self.assertEqual(write_res["status"], "recorded")

      read_res = get_governance_verdict("NCT09999999")
      self.assertEqual(read_res["status"], "found")
      self.assertEqual(read_res["verdict"]["verdict"], "APPROVED")
      self.assertEqual(read_res["ingest_record"]["status"], "APPROVED")

  def test_get_governance_verdict_not_found(self):
    """Verifies get_governance_verdict returns not_found when trial is absent."""
    mock_db = MagicMock()
    mock_snap = MagicMock()
    mock_snap.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_snap

    with patch("agent.tools.get_firestore_client", return_value=mock_db):
      res = get_governance_verdict("NCT00000000")
      self.assertEqual(res["status"], "not_found")
      self.assertEqual(res["nct_id"], "NCT00000000")


class TestFirestoreBlackboardLive(unittest.TestCase):
  """Live integration test against Cloud Firestore (run with RUN_LIVE_FIRESTORE_TESTS=true)."""

  @unittest.skipUnless(
      os.getenv("RUN_LIVE_FIRESTORE_TESTS") == "true",
      "Set RUN_LIVE_FIRESTORE_TESTS=true to run live Cloud Firestore integration tests.",
  )
  def test_live_blackboard_roundtrip(self):
    get_firestore_client.cache_clear()
    nct_id = f"NCT{int(time.time()) % 100000000:08d}"
    db = get_firestore_client()

    try:
      ingest_res = record_ingest_event(
          nct_id=nct_id,
          gcs_uri=f"gs://test-bucket/raw/{nct_id}/Prot_000.pdf",
          size_bytes=4096,
          status="PENDING_GOVERNANCE",
      )
      self.assertEqual(ingest_res["status"], "recorded")

      verdict_res = record_governance_verdict(
          nct_id=nct_id,
          verdict="APPROVED",
          reason="Live Blackboard integration check passed.",
          gcs_uri=f"gs://test-bucket/raw/{nct_id}/Prot_000.pdf",
          size_bytes=4096,
      )
      self.assertEqual(verdict_res["status"], "recorded")

      fetched = get_governance_verdict(nct_id)
      self.assertEqual(fetched["status"], "found")
      self.assertEqual(fetched["verdict"]["verdict"], "APPROVED")
      self.assertEqual(fetched["ingest_record"]["status"], "APPROVED")
    finally:
      db.collection(BLACKBOARD_VERDICTS_COLLECTION).document(nct_id).delete()
      db.collection(BLACKBOARD_INGEST_COLLECTION).document(nct_id).delete()


if __name__ == "__main__":
  unittest.main()
