from collections.abc import Callable
from threading import RLock
from typing import Any

from dungeon_agent.plane_shared.domain.enums import ACTIVE_SESSION_STATUSES
from dungeon_agent.plane_shared.domain.models import (
    CampaignId,
    CampaignRecord,
    SessionRecord,
)
from dungeon_agent.plane_shared.persistence.errors import (
    CampaignAlreadyExistsError,
    CampaignEventSequenceConflictError,
    CampaignRevisionConflictError,
    EventSequenceConflictError,
    PersistenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)


class _InMemoryAggregateRepository:
    def __init__(
        self,
        *,
        aggregate_name: str,
        record_id: Callable[[Any], str],
        event_record_id: Callable[[Any], str],
        already_exists_error: type[PersistenceConflictError],
        revision_conflict_error: type[PersistenceConflictError],
        sequence_conflict_error: type[PersistenceConflictError],
    ) -> None:
        self._aggregate_name = aggregate_name
        self._record_id = record_id
        self._event_record_id = event_record_id
        self._already_exists_error = already_exists_error
        self._revision_conflict_error = revision_conflict_error
        self._sequence_conflict_error = sequence_conflict_error
        self._records: dict[str, Any] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._events: dict[str, dict[int, Any]] = {}
        self._lock = RLock()

    def create(self, record: Any, idempotency_key: str) -> Any:
        lookup_key = (record.owner_id, idempotency_key)
        aggregate_id = self._record_id(record)
        with self._lock:
            existing_id = self._idempotency.get(lookup_key)
            if existing_id is not None:
                return self._records[existing_id]
            if aggregate_id in self._records:
                raise self._already_exists_error(
                    f"{self._aggregate_name} already exists: {aggregate_id}"
                )
            self._records[aggregate_id] = record
            self._idempotency[lookup_key] = aggregate_id
            self._events[aggregate_id] = {}
            return record

    def get(self, aggregate_id: str) -> Any | None:
        with self._lock:
            return self._records.get(aggregate_id)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> Any | None:
        with self._lock:
            aggregate_id = self._idempotency.get((owner_id, idempotency_key))
            return None if aggregate_id is None else self._records.get(aggregate_id)

    def save(self, record: Any, *, expected_revision: int) -> Any:
        if record.revision != expected_revision + 1:
            raise self._revision_conflict_error(
                f"saved {self._aggregate_name} revision must be exactly one greater "
                "than expected revision"
            )
        aggregate_id = self._record_id(record)
        with self._lock:
            current = self._records.get(aggregate_id)
            if current is None or current.revision != expected_revision:
                raise self._revision_conflict_error(
                    f"{self._aggregate_name} revision conflict: {aggregate_id}"
                )
            stored = record.model_copy(update={"last_event_sequence": current.last_event_sequence})
            self._records[aggregate_id] = stored
            return stored

    def append(self, event: Any, *, expected_previous_sequence: int) -> None:
        if event.sequence != expected_previous_sequence + 1:
            raise self._sequence_conflict_error(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        aggregate_id = self._event_record_id(event)
        with self._lock:
            current = self._records.get(aggregate_id)
            if current is None or current.last_event_sequence != expected_previous_sequence:
                raise self._sequence_conflict_error(f"event sequence conflict: {aggregate_id}")
            events = self._events[aggregate_id]
            if event.sequence in events:
                raise self._sequence_conflict_error(
                    f"event sequence already exists: {aggregate_id}/{event.sequence}"
                )
            events[event.sequence] = event
            self._records[aggregate_id] = current.model_copy(
                update={"last_event_sequence": event.sequence}
            )

    def list_after(self, aggregate_id: str, sequence: int) -> tuple[Any, ...]:
        with self._lock:
            events = self._events.get(aggregate_id, {})
            return tuple(events[index] for index in sorted(events) if index > sequence)


class InMemoryControlPlaneRepository(_InMemoryAggregateRepository):
    def __init__(self) -> None:
        super().__init__(
            aggregate_name="session",
            record_id=lambda session: session.session_id,
            event_record_id=lambda event: event.session_id,
            already_exists_error=SessionAlreadyExistsError,
            revision_conflict_error=SessionRevisionConflictError,
            sequence_conflict_error=EventSequenceConflictError,
        )
        self._sessions: dict[str, SessionRecord] = self._records

    def count_active_by_owner(self, owner_id: str) -> int:
        with self._lock:
            return sum(
                1
                for session in self._sessions.values()
                if session.owner_id == owner_id and session.status in ACTIVE_SESSION_STATUSES
            )

    def list_active_by_owner(self, owner_id: str) -> tuple[SessionRecord, ...]:
        with self._lock:
            sessions = [
                session
                for session in self._sessions.values()
                if session.owner_id == owner_id and session.status in ACTIVE_SESSION_STATUSES
            ]
        sessions.sort(key=lambda session: session.created_at, reverse=True)
        return tuple(sessions[:10])

    def count_by_campaign(self, campaign_id: CampaignId) -> int:
        with self._lock:
            return sum(
                1 for session in self._sessions.values() if session.campaign_id == campaign_id
            )


class InMemoryCampaignRepository(_InMemoryAggregateRepository):
    def __init__(self) -> None:
        super().__init__(
            aggregate_name="campaign",
            record_id=lambda campaign: campaign.campaign_id,
            event_record_id=lambda event: event.campaign_id,
            already_exists_error=CampaignAlreadyExistsError,
            revision_conflict_error=CampaignRevisionConflictError,
            sequence_conflict_error=CampaignEventSequenceConflictError,
        )
        self._campaigns: dict[str, CampaignRecord] = self._records

    def count_by_owner(self, owner_id: str) -> int:
        with self._lock:
            return sum(1 for campaign in self._campaigns.values() if campaign.owner_id == owner_id)

    def list_by_owner(
        self, owner_id: str, *, status: str | None = None
    ) -> tuple[CampaignRecord, ...]:
        with self._lock:
            campaigns = [
                campaign
                for campaign in self._campaigns.values()
                if campaign.owner_id == owner_id
                and (status is None or campaign.status.value == status)
            ]
        campaigns.sort(key=lambda campaign: campaign.created_at, reverse=True)
        return tuple(campaigns[:50])
