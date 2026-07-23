from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from dungeon_agent.plane_shared.domain.enums import EventType
from dungeon_agent.plane_shared.domain.models import (
    CampaignEvent,
    CampaignEventPayload,
    CampaignId,
    EventPayload,
    SessionEvent,
    SessionId,
)
from dungeon_agent.plane_shared.identifiers import new_event_id
from dungeon_agent.plane_shared.persistence.errors import (
    CampaignEventSequenceConflictError,
    EventSequenceConflictError,
)

Clock = Callable[[], datetime]


def append_session_event(
    store: Any,
    delivery: Any | None,
    session_id: SessionId,
    event_type: EventType,
    payload: EventPayload,
    correlation_id: str,
    now: datetime,
    *,
    attempts: int = 3,
) -> SessionEvent:
    return _append_event(
        store,
        delivery,
        session_id,
        attempts=attempts,
        missing_message=f"session does not exist: {session_id}",
        conflict_error=EventSequenceConflictError,
        build_event=lambda session: SessionEvent(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=session.last_event_sequence + 1,
            type=event_type,
            occurred_at=now,
            correlation_id=correlation_id,
            payload=payload,
        ),
        deliver=lambda target, owner_id, event: target.deliver(owner_id, event),
    )


def append_campaign_event(
    store: Any,
    delivery: Any | None,
    campaign_id: CampaignId,
    event_type: EventType,
    payload: CampaignEventPayload,
    correlation_id: str,
    now: datetime,
    *,
    attempts: int = 3,
) -> CampaignEvent:
    return _append_event(
        store,
        delivery,
        campaign_id,
        attempts=attempts,
        missing_message=f"campaign does not exist: {campaign_id}",
        conflict_error=CampaignEventSequenceConflictError,
        build_event=lambda campaign: CampaignEvent(
            event_id=new_event_id(),
            campaign_id=campaign_id,
            sequence=campaign.last_event_sequence + 1,
            type=event_type,
            occurred_at=now,
            correlation_id=correlation_id,
            payload=payload,
        ),
        deliver=lambda target, owner_id, event: target.deliver_campaign(owner_id, event),
    )


def _append_event[EventT: (SessionEvent, CampaignEvent)](
    store: Any,
    delivery: Any | None,
    aggregate_id: str,
    *,
    attempts: int,
    missing_message: str,
    conflict_error: type[Exception],
    build_event: Callable[[Any], EventT],
    deliver: Callable[[Any, str, EventT], None],
) -> EventT:
    for _ in range(attempts):
        aggregate = store.get(aggregate_id)
        if aggregate is None:
            raise ValueError(missing_message)
        event = build_event(aggregate)
        try:
            store.append(event, expected_previous_sequence=aggregate.last_event_sequence)
        except conflict_error:
            continue
        if delivery is not None:
            try:
                deliver(delivery, aggregate.owner_id, event)
            except Exception as delivery_error:
                print(f"event delivery failed: {type(delivery_error).__name__}")
        return event
    raise conflict_error(f"event sequence conflict: {aggregate_id}")


def utc_now() -> datetime:
    return datetime.now(UTC)
