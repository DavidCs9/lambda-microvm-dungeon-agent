"""Thread-safe in-memory persistence for local use and unit tests."""

from threading import RLock

from dungeon_agent.control_plane.domain.models import SessionEvent, SessionId, SessionRecord
from dungeon_agent.control_plane.persistence.errors import (
    EventSequenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)


class InMemoryControlPlaneRepository:
    """Implement session and event ports without external services."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._events: dict[str, dict[int, SessionEvent]] = {}
        self._lock = RLock()

    def create(self, session: SessionRecord, idempotency_key: str) -> SessionRecord:
        """Create a session once, returning the first result for a duplicate request."""
        lookup_key = (session.owner_id, idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(lookup_key)
            if existing_id is not None:
                return self._sessions[existing_id]
            if session.session_id in self._sessions:
                raise SessionAlreadyExistsError(f"session already exists: {session.session_id}")
            self._sessions[session.session_id] = session
            self._idempotency[lookup_key] = session.session_id
            self._events[session.session_id] = {}
            return session

    def get(self, session_id: SessionId) -> SessionRecord | None:
        """Return a session by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> SessionRecord | None:
        """Find the session produced by one owner's creation request."""
        with self._lock:
            session_id = self._idempotency.get((owner_id, idempotency_key))
            return None if session_id is None else self._sessions.get(session_id)

    def save(self, session: SessionRecord, *, expected_revision: int) -> SessionRecord:
        """Replace a session only when its stored revision matches the caller's revision."""
        if session.revision != expected_revision + 1:
            raise SessionRevisionConflictError(
                "saved session revision must be exactly one greater than expected revision"
            )
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is None or current.revision != expected_revision:
                raise SessionRevisionConflictError(
                    f"session revision conflict: {session.session_id}"
                )
            # Event sequencing is independent of state revision. Preserve event progress
            # if an append raced with the caller while it prepared this state change.
            stored = session.model_copy(update={"last_event_sequence": current.last_event_sequence})
            self._sessions[session.session_id] = stored
            return stored

    def append(self, event: SessionEvent, *, expected_previous_sequence: int) -> None:
        """Atomically reserve and store the next sequence for a session."""
        if event.sequence != expected_previous_sequence + 1:
            raise EventSequenceConflictError(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        with self._lock:
            current = self._sessions.get(event.session_id)
            if current is None or current.last_event_sequence != expected_previous_sequence:
                raise EventSequenceConflictError(f"event sequence conflict: {event.session_id}")
            events = self._events[event.session_id]
            if event.sequence in events:
                raise EventSequenceConflictError(
                    f"event sequence already exists: {event.session_id}/{event.sequence}"
                )
            events[event.sequence] = event
            self._sessions[event.session_id] = current.model_copy(
                update={"last_event_sequence": event.sequence}
            )

    def list_after(self, session_id: SessionId, sequence: int) -> tuple[SessionEvent, ...]:
        """Replay events strictly after a known session-local sequence."""
        with self._lock:
            events = self._events.get(session_id, {})
            return tuple(events[index] for index in sorted(events) if index > sequence)
