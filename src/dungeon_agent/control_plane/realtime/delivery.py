"""Best-effort WebSocket delivery after durable event storage."""

from typing import Protocol

from dungeon_agent.control_plane.domain.models import CampaignEvent, SessionEvent
from dungeon_agent.control_plane.domain.ports import EventDeliveryPort, EventRepository
from dungeon_agent.control_plane.realtime.models import ConnectionRecord
from dungeon_agent.control_plane.realtime.ports import ConnectionRepository


class _ApiGatewayExceptions(Protocol):
    GoneException: type[Exception]


class ApiGatewayManagementClient(Protocol):
    @property
    def exceptions(self) -> _ApiGatewayExceptions: ...

    def post_to_connection(self, **kwargs: object) -> object: ...


class BestEffortEventDelivery:
    def __init__(
        self,
        connections: ConnectionRepository,
        client: ApiGatewayManagementClient,
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


class DurableEventPublisher:
    def __init__(self, events: EventRepository, delivery: EventDeliveryPort) -> None:
        self._events = events
        self._delivery = delivery

    def publish(self, owner_id: str, event: SessionEvent) -> None:
        self._events.append(event, expected_previous_sequence=event.sequence - 1)
        self._delivery.deliver(owner_id, event)
