from typing import Any

from dungeon_agent.plane_shared.domain.models import CampaignEvent, SessionEvent
from dungeon_agent.plane_shared.realtime.models import ConnectionRecord


class BestEffortEventDelivery:
    def __init__(
        self,
        connections: Any,
        client: Any,
    ) -> None:
        self._connections = connections
        self._client = client

    def deliver(self, owner_id: str, event: SessionEvent) -> None:
        payload = event.model_dump_json(by_alias=True).encode()
        for connection in self._connections.list_subscribers(event.session_id):
            if connection.owner_id != owner_id:
                continue
            self._post(connection, payload)

    def deliver_campaign(self, owner_id: str, event: CampaignEvent) -> None:
        payload = event.model_dump_json(by_alias=True).encode()
        for connection in self._connections.list_campaign_subscribers(event.campaign_id):
            if connection.owner_id != owner_id:
                continue
            self._post(connection, payload)

    def _post(self, connection: ConnectionRecord, payload: bytes) -> None:
        try:
            self._client.post_to_connection(
                ConnectionId=connection.connection_id,
                Data=payload,
            )
        except self._client.exceptions.GoneException:
            self._connections.delete(connection.connection_id)
