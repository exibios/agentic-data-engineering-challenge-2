# agent/memory.py
"""Manages short-term conversational state in Firestore."""

from datetime import datetime, timezone
from typing import Any, Dict, List
from google.cloud import firestore
from agent.clients import get_firestore_client
from agent.config import settings


class SessionMemory:
  """Manages short-term conversational state in Firestore."""

  def __init__(self):
    self.collection_name = settings.FIRESTORE_COLLECTION

  @property
  def collection(self):
    return get_firestore_client().collection(self.collection_name)

  def add_turn(self, session_id: str, role: str, message: str) -> None:
    doc_ref = self.collection.document(session_id)
    doc_ref.set(
        {
            "updated_at": datetime.now(timezone.utc),
            "history": firestore.ArrayUnion([{
                "role": role,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]),
        },
        merge=True,
    )

  def get_turns(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    doc = self.collection.document(session_id).get()
    if not doc.exists:
      return []
    history = doc.to_dict().get("history", [])
    return history[-limit:]
