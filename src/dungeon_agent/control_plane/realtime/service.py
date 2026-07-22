"""Connect, subscribe, disconnect, and replay use cases."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignId,
    OwnerId,
    SessionEvent,
    SessionId,
)
from dungeon_agent.control_plane.realtime.models import ConnectionRecord

Clock = Callable[[], datetime]


class RealtimeSessionService:
    def __init__(
        self,
        connections: Any,
        store: Any,
        *,
        campaign_store: Any | None = None,
        clock: Clock | None = None,
        connection_ttl: timedelta = timedelta(hours=2),
    ) -> None:
        self._connections = connections
        self._store = store
        self._campaign_store = campaign_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._connection_ttl = connection_ttl

    def connect(self, connection_id: str, owner_id: OwnerId) -> ConnectionRecord:
        now = self._clock()
        connection = ConnectionRecord(
            connection_id=connection_id,
            owner_id=owner_id,
            connected_at=now,
            expires_at=int((now + self._connection_ttl).timestamp()),
        )
        self._connections.put(connection)
        return connection

    def subscribe(
        self,
        connection_id: str,
        owner_id: OwnerId,
        session_id: SessionId,
        *,
        after_sequence: int,
    ) -> tuple[SessionEvent, ...]:
        connection = self._connections.get(connection_id)
        if connection is None or connection.owner_id != owner_id:
            raise PermissionError("connection does not belong to this player")
        session = self._store.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise PermissionError("session does not belong to this player")
        subscribed = connection.model_copy(
            update={"session_id": session_id, "campaign_id": None, "after_sequence": after_sequence}
        )
        self._connections.subscribe(ConnectionRecord.model_validate(subscribed))
        return cast(tuple[SessionEvent, ...], self._store.list_after(session_id, after_sequence))

    def subscribe_campaign(
        self,
        connection_id: str,
        owner_id: OwnerId,
        campaign_id: CampaignId,
        *,
        after_sequence: int,
    ) -> tuple[CampaignEvent, ...]:
        if self._campaign_store is None:
            raise RuntimeError("campaign subscriptions are not configured")
        connection = self._connections.get(connection_id)
        if connection is None or connection.owner_id != owner_id:
            raise PermissionError("connection does not belong to this player")
        campaign = self._campaign_store.get(campaign_id)
        if campaign is None or campaign.owner_id != owner_id:
            raise PermissionError("campaign does not belong to this player")
        subscribed = connection.model_copy(
            update={
                "session_id": None,
                "campaign_id": campaign_id,
                "after_sequence": after_sequence,
            }
        )
        self._connections.subscribe(ConnectionRecord.model_validate(subscribed))
        return cast(
            tuple[CampaignEvent, ...],
            self._campaign_store.list_after(campaign_id, after_sequence),
        )

    def disconnect(self, connection_id: str) -> None:
        self._connections.delete(connection_id)
