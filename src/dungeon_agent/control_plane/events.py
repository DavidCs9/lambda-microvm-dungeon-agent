"""Durable event append followed by best-effort delivery."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from dungeon_agent.control_plane.domain.enums import EventType
from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignEventPayload,
    CampaignId,
    EventPayload,
    SessionEvent,
    SessionId,
)
from dungeon_agent.control_plane.identifiers import new_event_id
from dungeon_agent.control_plane.persistence.errors import (
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
    """Store one sequenced event, then fan it out without failing the caller."""
    for _ in range(attempts):
        session = store.get(session_id)
        if session is None:
            raise ValueError(f"session does not exist: {session_id}")
        event = SessionEvent(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=session.last_event_sequence + 1,
            type=event_type,
            occurred_at=now,
            correlation_id=correlation_id,
            payload=payload,
        )
        try:
            store.append(event, expected_previous_sequence=session.last_event_sequence)
        except EventSequenceConflictError:
            continue
        if delivery is not None:
            try:
                delivery.deliver(session.owner_id, event)
            except Exception as delivery_error:
                print(f"event delivery failed: {type(delivery_error).__name__}")
        return event
    raise EventSequenceConflictError(f"event sequence conflict: {session_id}")


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
    """Store one sequenced campaign event, then fan it out without failing the caller."""
    for _ in range(attempts):
        campaign = store.get(campaign_id)
        if campaign is None:
            raise ValueError(f"campaign does not exist: {campaign_id}")
        event = CampaignEvent(
            event_id=new_event_id(),
            campaign_id=campaign_id,
            sequence=campaign.last_event_sequence + 1,
            type=event_type,
            occurred_at=now,
            correlation_id=correlation_id,
            payload=payload,
        )
        try:
            store.append(event, expected_previous_sequence=campaign.last_event_sequence)
        except CampaignEventSequenceConflictError:
            continue
        if delivery is not None:
            try:
                delivery.deliver_campaign(campaign.owner_id, event)
            except Exception as delivery_error:
                print(f"event delivery failed: {type(delivery_error).__name__}")
        return event
    raise CampaignEventSequenceConflictError(f"event sequence conflict: {campaign_id}")


def utc_now() -> datetime:
    return datetime.now(UTC)
