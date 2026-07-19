"""Thread-safe in-memory persistence for local use and unit tests."""

from threading import RLock

from dungeon_agent.control_plane.domain.enums import SessionStatus
from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignId,
    CampaignRecord,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.persistence.errors import (
    CampaignAlreadyExistsError,
    CampaignEventSequenceConflictError,
    CampaignRevisionConflictError,
    EventSequenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)

_ACTIVE_STATUSES = frozenset(
    {
        SessionStatus.REQUESTED,
        SessionStatus.CREATING,
        SessionStatus.READY,
        SessionStatus.ACTIVE,
    }
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

    def count_active_by_owner(self, owner_id: str) -> int:
        """Count one owner's sessions that still hold or can still take a turn."""
        with self._lock:
            return sum(
                1
                for session in self._sessions.values()
                if session.owner_id == owner_id and session.status in _ACTIVE_STATUSES
            )

    def count_by_campaign(self, campaign_id: CampaignId) -> int:
        """Count every session forked from one campaign, including finished ones."""
        with self._lock:
            return sum(
                1 for session in self._sessions.values() if session.campaign_id == campaign_id
            )


class InMemoryCampaignRepository:
    """Implement campaign and campaign-event ports without external services."""

    def __init__(self) -> None:
        self._campaigns: dict[str, CampaignRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._events: dict[str, dict[int, CampaignEvent]] = {}
        self._lock = RLock()

    def create(self, campaign: CampaignRecord, idempotency_key: str) -> CampaignRecord:
        """Create a campaign once, returning the first result for a duplicate request."""
        lookup_key = (campaign.owner_id, idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(lookup_key)
            if existing_id is not None:
                return self._campaigns[existing_id]
            if campaign.campaign_id in self._campaigns:
                raise CampaignAlreadyExistsError(f"campaign already exists: {campaign.campaign_id}")
            self._campaigns[campaign.campaign_id] = campaign
            self._idempotency[lookup_key] = campaign.campaign_id
            self._events[campaign.campaign_id] = {}
            return campaign

    def get(self, campaign_id: CampaignId) -> CampaignRecord | None:
        """Return a campaign by ID."""
        with self._lock:
            return self._campaigns.get(campaign_id)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> CampaignRecord | None:
        """Find the campaign produced by one owner's creation request."""
        with self._lock:
            campaign_id = self._idempotency.get((owner_id, idempotency_key))
            return None if campaign_id is None else self._campaigns.get(campaign_id)

    def save(self, campaign: CampaignRecord, *, expected_revision: int) -> CampaignRecord:
        """Replace a campaign only when its stored revision matches the caller's revision."""
        if campaign.revision != expected_revision + 1:
            raise CampaignRevisionConflictError(
                "saved campaign revision must be exactly one greater than expected revision"
            )
        with self._lock:
            current = self._campaigns.get(campaign.campaign_id)
            if current is None or current.revision != expected_revision:
                raise CampaignRevisionConflictError(
                    f"campaign revision conflict: {campaign.campaign_id}"
                )
            stored = campaign.model_copy(
                update={"last_event_sequence": current.last_event_sequence}
            )
            self._campaigns[campaign.campaign_id] = stored
            return stored

    def append(self, event: CampaignEvent, *, expected_previous_sequence: int) -> None:
        """Atomically reserve and store the next sequence for a campaign."""
        if event.sequence != expected_previous_sequence + 1:
            raise CampaignEventSequenceConflictError(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        with self._lock:
            current = self._campaigns.get(event.campaign_id)
            if current is None or current.last_event_sequence != expected_previous_sequence:
                raise CampaignEventSequenceConflictError(
                    f"event sequence conflict: {event.campaign_id}"
                )
            events = self._events[event.campaign_id]
            if event.sequence in events:
                raise CampaignEventSequenceConflictError(
                    f"event sequence already exists: {event.campaign_id}/{event.sequence}"
                )
            events[event.sequence] = event
            self._campaigns[event.campaign_id] = current.model_copy(
                update={"last_event_sequence": event.sequence}
            )

    def list_after(self, campaign_id: CampaignId, sequence: int) -> tuple[CampaignEvent, ...]:
        """Replay events strictly after a known campaign-local sequence."""
        with self._lock:
            events = self._events.get(campaign_id, {})
            return tuple(events[index] for index in sorted(events) if index > sequence)

    def count_by_owner(self, owner_id: str) -> int:
        """Count every campaign one owner has created."""
        with self._lock:
            return sum(1 for campaign in self._campaigns.values() if campaign.owner_id == owner_id)
