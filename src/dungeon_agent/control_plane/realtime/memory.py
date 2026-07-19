"""In-memory connection repository for tests and local clients."""

from threading import RLock

from dungeon_agent.control_plane.domain.models import CampaignId, SessionId
from dungeon_agent.control_plane.realtime.models import ConnectionRecord


class InMemoryConnectionRepository:
    def __init__(self) -> None:
        self._connections: dict[str, ConnectionRecord] = {}
        self._lock = RLock()

    def put(self, connection: ConnectionRecord) -> None:
        with self._lock:
            self._connections[connection.connection_id] = connection

    def get(self, connection_id: str) -> ConnectionRecord | None:
        with self._lock:
            return self._connections.get(connection_id)

    def subscribe(self, connection: ConnectionRecord) -> None:
        self.put(connection)

    def delete(self, connection_id: str) -> None:
        with self._lock:
            self._connections.pop(connection_id, None)

    def list_subscribers(self, session_id: SessionId) -> tuple[ConnectionRecord, ...]:
        with self._lock:
            return tuple(
                connection
                for connection in self._connections.values()
                if connection.session_id == session_id
            )

    def list_campaign_subscribers(self, campaign_id: CampaignId) -> tuple[ConnectionRecord, ...]:
        with self._lock:
            return tuple(
                connection
                for connection in self._connections.values()
                if connection.campaign_id == campaign_id
            )
