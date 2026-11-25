# agent/memory.py
"""Manages unified session state and agent memory in Cloud Firestore."""

import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from google.adk.events import Event
from google.adk.sessions import _session_util
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session
from google.cloud import firestore

from agent.clients import get_firestore_client
from agent.config import settings

logger = logging.getLogger("agent.memory")

DEFAULT_FS_TIMEOUT = 5.0


class FirestoreSessionService(BaseSessionService):
  """ADK-native persistent SessionService backed by Google Cloud Firestore."""

  def __init__(
      self,
      collection_name: Optional[str] = None,
      database: Optional[str] = None,
      timeout: float = DEFAULT_FS_TIMEOUT,
  ):
    self.collection_name = collection_name or settings.FIRESTORE_COLLECTION
    self.database = database or settings.FIRESTORE_DATABASE
    self.timeout = timeout
    self._in_memory_fallback: Optional[InMemorySessionService] = None

  def _ensure_in_memory_fallback(self) -> InMemorySessionService:
    if self._in_memory_fallback is None:
      self._in_memory_fallback = InMemorySessionService()
    return self._in_memory_fallback

  def _get_collection(self):
    """Retrieves Firestore collection reference with graceful fallback."""
    if self._in_memory_fallback is not None:
      return None
    try:
      client = get_firestore_client()
      return client.collection(self.collection_name)
    except Exception as e:
      logger.warning(
          f"Firestore client connection failed ({e}). Falling back to InMemorySessionService."
      )
      self._ensure_in_memory_fallback()
      return None

  async def create_session(
      self,
      *,
      app_name: str,
      user_id: str,
      state: Optional[dict[str, Any]] = None,
      session_id: Optional[str] = None,
  ) -> Session:
    col = self._get_collection()
    if col is None:
      return await self._ensure_in_memory_fallback().create_session(
          app_name=app_name, user_id=user_id, state=state, session_id=session_id
      )

    session_id = session_id.strip() if session_id else str(uuid4())
    state_deltas = _session_util.extract_state_delta(state or {})
    session_state = state_deltas.get("session") or {}

    session = Session(
        app_name=app_name,
        user_id=user_id,
        id=session_id,
        state=session_state,
        last_update_time=time.time(),
    )

    doc_ref = col.document(session_id)
    doc_payload = {
        "id": session.id,
        "app_name": session.app_name,
        "user_id": session.user_id,
        "state": session.state,
        "session_json": session.model_dump_json(),
        "last_update_time": session.last_update_time,
        "updated_at": datetime.now(timezone.utc),
    }

    try:
      await asyncio.to_thread(doc_ref.set, doc_payload, merge=True, timeout=self.timeout)
    except Exception as e:
      logger.warning(
          f"Failed writing session {session_id} to Firestore ({e}). Using in-memory fallback."
      )
      return await self._ensure_in_memory_fallback().create_session(
          app_name=app_name, user_id=user_id, state=state, session_id=session_id
      )

    return session

  async def get_session(
      self,
      *,
      app_name: str,
      user_id: str,
      session_id: str,
      config: Optional[GetSessionConfig] = None,
  ) -> Optional[Session]:
    col = self._get_collection()
    if col is None:
      return await self._ensure_in_memory_fallback().get_session(
          app_name=app_name,
          user_id=user_id,
          session_id=session_id,
          config=config,
      )

    session_id = session_id.strip() if session_id else session_id
    doc_ref = col.document(session_id)

    try:
      doc = await asyncio.to_thread(doc_ref.get, timeout=self.timeout)
      if not doc.exists:
        return None
      data = doc.to_dict() or {}
    except Exception as e:
      logger.warning(f"Error fetching session {session_id} from Firestore: {e}")
      return await self._ensure_in_memory_fallback().get_session(
          app_name=app_name,
          user_id=user_id,
          session_id=session_id,
          config=config,
      )

    session: Optional[Session] = None
    if "session_json" in data:
      try:
        session = Session.model_validate_json(data["session_json"])
      except Exception as err:
        logger.warning(
            f"Failed parsing session_json for {session_id} ({err}), falling back to dict"
        )

    if session is None:
      session = Session(
          app_name=data.get("app_name", app_name),
          user_id=data.get("user_id", user_id),
          id=data.get("id", session_id),
          state=data.get("state", {}),
          last_update_time=float(data.get("last_update_time", 0.0)),
      )

    events = session.events
    if config:
      if config.num_recent_events is not None:
        if config.num_recent_events == 0:
          events = []
        else:
          events = events[-config.num_recent_events :]
      if config.after_timestamp is not None:
        i = len(events) - 1
        while i >= 0:
          if events[i].timestamp < config.after_timestamp:
            break
          i -= 1
        if i >= 0:
          events = events[i + 1 :]
    if events is not session.events:
      session = session.model_copy(update={"events": events})

    return session

  async def append_event(self, session: Session, event: Event) -> Event:
    if event.partial:
      return event

    col = self._get_collection()
    if col is None:
      return await self._ensure_in_memory_fallback().append_event(
          session=session, event=event
      )

    # 1. Update in-memory session object and apply state deltas
    await super().append_event(session=session, event=event)
    session.last_update_time = event.timestamp

    # 2. Extract turn message for backward compatibility with SessionMemory
    turn: Optional[Dict[str, Any]] = None
    if event.content and event.content.parts:
      texts = [
          p.text for p in event.content.parts if hasattr(p, "text") and p.text
      ]
      if texts:
        turn = {
            "role": event.content.role or event.author or "assistant",
            "message": " ".join(texts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # 3. Persist updated session to Firestore
    doc_ref = col.document(session.id)
    doc_payload: Dict[str, Any] = {
        "state": session.state,
        "session_json": session.model_dump_json(),
        "last_update_time": session.last_update_time,
        "updated_at": datetime.now(timezone.utc),
    }
    if turn:
      doc_payload["history"] = firestore.ArrayUnion([turn])

    try:
      await asyncio.to_thread(doc_ref.set, doc_payload, merge=True, timeout=self.timeout)
    except Exception as e:
      logger.warning(
          f"Failed appending event to Firestore session {session.id}: {e}"
      )

    return event

  async def list_sessions(
      self, *, app_name: str, user_id: Optional[str] = None
  ) -> ListSessionsResponse:
    col = self._get_collection()
    if col is None:
      return await self._ensure_in_memory_fallback().list_sessions(
          app_name=app_name, user_id=user_id
      )

    try:
      query = col.where("app_name", "==", app_name)
      if user_id:
        query = query.where("user_id", "==", user_id)
      docs = await asyncio.to_thread(query.get, timeout=self.timeout)
      sessions = []
      for d in docs:
        dt = d.to_dict()
        sessions.append(
            Session(
                app_name=dt.get("app_name", app_name),
                user_id=dt.get("user_id", user_id or "unknown"),
                id=dt.get("id", d.id),
                state=dt.get("state", {}),
                last_update_time=float(dt.get("last_update_time", 0.0)),
            )
        )
      return ListSessionsResponse(sessions=sessions)
    except Exception as e:
      logger.warning(f"Error listing sessions: {e}")
      return await self._ensure_in_memory_fallback().list_sessions(
          app_name=app_name, user_id=user_id
      )

  async def delete_session(
      self, *, app_name: str, user_id: str, session_id: str
  ) -> None:
    col = self._get_collection()
    if col is None:
      return await self._ensure_in_memory_fallback().delete_session(
          app_name=app_name, user_id=user_id, session_id=session_id
      )

    doc_ref = col.document(session_id)
    try:
      await asyncio.to_thread(doc_ref.delete, timeout=self.timeout)
    except Exception as e:
      logger.warning(f"Error deleting session {session_id}: {e}")

  async def update_session_state(
      self, session_id: str, state_delta: Dict[str, Any]
  ) -> None:
    """Directly merges a state dictionary into a Firestore session document."""
    col = self._get_collection()
    if col is None:
      fallback = self._ensure_in_memory_fallback()
      for app in fallback.sessions.values():
        for u in app.values():
          if session_id in u:
            u[session_id].state.update(state_delta)
      return

    doc_ref = col.document(session_id)
    try:
      doc = await asyncio.to_thread(doc_ref.get, timeout=self.timeout)
      if doc.exists:
        data = doc.to_dict() or {}
        curr_state = data.get("state", {})
        curr_state.update(state_delta)
        update_data = {
            "state": curr_state,
            "updated_at": datetime.now(timezone.utc),
        }
        if "session_json" in data:
          try:
            sess = Session.model_validate_json(data["session_json"])
            sess.state.update(state_delta)
            sess.last_update_time = time.time()
            update_data["session_json"] = sess.model_dump_json()
            update_data["last_update_time"] = sess.last_update_time
          except Exception:
            pass
        await asyncio.to_thread(doc_ref.set, update_data, merge=True, timeout=self.timeout)
      else:
        await asyncio.to_thread(
            doc_ref.set,
            {
                "id": session_id,
                "state": state_delta,
                "updated_at": datetime.now(timezone.utc),
            },
            merge=True,
            timeout=self.timeout,
        )
    except Exception as e:
      logger.warning(
          f"Failed updating session state for {session_id} in Firestore: {e}"
      )

  def get_session_state_sync(self, session_id: str) -> Dict[str, Any]:
    """Synchronously retrieves the state dictionary for a given session."""
    col = self._get_collection()
    if col is None:
      fallback = self._ensure_in_memory_fallback()
      for app in fallback.sessions.values():
        for u in app.values():
          if session_id in u:
            return u[session_id].state
      return {}

    try:
      doc = col.document(session_id).get(timeout=self.timeout)
      if doc.exists:
        return doc.to_dict().get("state", {})
    except Exception as e:
      logger.warning(f"Error reading session state for {session_id}: {e}")
    return {}


_SESSION_SERVICE_INSTANCE: Optional[FirestoreSessionService] = None


def get_session_service() -> FirestoreSessionService:
  """Returns the singleton instance of FirestoreSessionService."""
  global _SESSION_SERVICE_INSTANCE
  if _SESSION_SERVICE_INSTANCE is None:
    _SESSION_SERVICE_INSTANCE = FirestoreSessionService()
  return _SESSION_SERVICE_INSTANCE


class SessionMemory:
  """Manages short-term conversational state in Firestore.

  Preserves backwards compatibility with legacy tests and endpoints.
  """

  def __init__(self, service: Optional[FirestoreSessionService] = None):
    self.service = service or get_session_service()
    self.collection_name = settings.FIRESTORE_COLLECTION
    self.database = settings.FIRESTORE_DATABASE

  @property
  def collection(self):
    return get_firestore_client().collection(self.collection_name)

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
