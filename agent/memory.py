# agent/memory.py
"""Manages lightweight business metrics and legacy turn logging in Cloud Firestore.

Under Pattern A (Hybrid Blackboard), conversational chat history is managed
natively by Vertex AI Agent Engine (`AdkApp` defaults), while inter-agent
governance and ingestion state lives in the Firestore Blackboard (`agent/tools.py`).
"""

from datetime import datetime, timezone
import os
from typing import Any, Dict, List

from google.cloud import firestore

from agent.clients import get_firestore_client
from agent.config import settings

DEFAULT_FS_TIMEOUT = 5.0


class SessionMemory:
  """Lightweight Firestore register for business metrics and legacy turn tracking."""

  def __init__(self):
    self.collection_name = (
        os.getenv("FIRESTORE_COLLECTION") or settings.FIRESTORE_COLLECTION
    )
    self.database = (
        os.getenv("FIRESTORE_DATABASE") or settings.FIRESTORE_DATABASE
    )

  @property
  def collection(self):
    return get_firestore_client(database=self.database).collection(
        self.collection_name
    )

  def add_turn(self, session_id: str, role: str, message: str) -> None:
    doc_ref = self.collection.document(session_id)
    doc_ref.set(
        {
            "id": session_id,
            "updated_at": datetime.now(timezone.utc),
            "history": firestore.ArrayUnion([{
                "role": role,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]),
        },
        merge=True,
        timeout=DEFAULT_FS_TIMEOUT,
    )

  def get_turns(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    doc = self.collection.document(session_id).get(timeout=DEFAULT_FS_TIMEOUT)
    if not doc.exists:
      return []
    history = doc.to_dict().get("history", [])
    return history[-limit:]
