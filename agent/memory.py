# agent/memory.py
import os
from datetime import datetime, timezone
from typing import Any, Dict, List
from google.cloud import firestore

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass

PROJECT_ID = os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT") or "dummy-project-id"
COLLECTION_NAME = os.getenv("FIRESTORE_COLLECTION", "dummy-agent-sessions")


class SessionMemory:
  """Manages short-term conversational state in Firestore."""

  def __init__(self):
    self.db = firestore.Client(project=PROJECT_ID)
    self.collection = self.db.collection(COLLECTION_NAME)

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
