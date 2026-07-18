"""Ports local to realtime delivery."""

from typing import Protocol

from dungeon_agent.control_plane.domain.models import SessionId
from dungeon_agent.control_plane.realtime.models import ConnectionRecord


class ConnectionRepository(Protocol):
    def put(self, connection: ConnectionRecord) -> None: ...

    def get(self, connection_id: str) -> ConnectionRecord | None: ...

    def subscribe(self, connection: ConnectionRecord) -> None: ...

    def delete(self, connection_id: str) -> None: ...

    def list_subscribers(self, session_id: SessionId) -> tuple[ConnectionRecord, ...]: ...
