from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

import pytest

from dungeon_agent.plane_shared.domain.enums import EventType, SessionPhase, SessionStatus
from dungeon_agent.plane_shared.domain.models import (
    CreationStartedPayload,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.plane_shared.persistence.memory import InMemoryControlPlaneRepository
from dungeon_agent.plane_shared.realtime.delivery import BestEffortEventDelivery
from dungeon_agent.plane_shared.realtime.dynamodb import DynamoDbConnectionRepository
from dungeon_agent.plane_shared.realtime.memory import InMemoryConnectionRepository
from dungeon_agent.plane_shared.realtime.service import RealtimeSessionService

NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)
SESSION_ID: SessionId = "ses_01J00000000000000000000000"


def make_session(owner_id: str = "user_demo") -> SessionRecord:
    return SessionRecord(
        session_id=SESSION_ID,
        owner_id=owner_id,
        language="es",
        status=SessionStatus.REQUESTED,
        phase=SessionPhase.REQUESTED,
        revision=0,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
    )


def make_event() -> SessionEvent:
    return SessionEvent(
        event_id="evt_01J00000000000000000000001",
        session_id=SESSION_ID,
        sequence=1,
        type=EventType.SESSION_CREATION_STARTED,
        occurred_at=NOW,
        correlation_id="corr-realtime-test",
        payload=CreationStartedPayload(language="es"),
    )


def test_connect_subscribe_and_replay_durable_events() -> None:
    store = InMemoryControlPlaneRepository()
    store.create(make_session(), "create-request-001")
    event = make_event()
    store.append(event, expected_previous_sequence=0)
    connections = InMemoryConnectionRepository()
    realtime = RealtimeSessionService(connections, store, clock=lambda: NOW)

    connection = realtime.connect("connection-1", "user_demo")
    replay = realtime.subscribe("connection-1", "user_demo", SESSION_ID, after_sequence=0)

    assert connection.expires_at == int(NOW.timestamp()) + 2 * 60 * 60
    assert replay == (event,)
    assert connections.list_subscribers(SESSION_ID)[0].after_sequence == 0


def test_subscribe_rejects_a_different_owner() -> None:
    store = InMemoryControlPlaneRepository()
    store.create(make_session(), "create-request-001")
    realtime = RealtimeSessionService(InMemoryConnectionRepository(), store, clock=lambda: NOW)
    realtime.connect("connection-1", "user_demo")

    with pytest.raises(PermissionError):
        realtime.subscribe("connection-1", "other_user", SESSION_ID, after_sequence=0)


class Gone(Exception):
    pass


class ApiExceptions:
    GoneException: type[Exception] = Gone


class FakeManagementClient:
    exceptions = ApiExceptions()

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.gone: set[str] = set()

    def post_to_connection(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if kwargs["ConnectionId"] in self.gone:
            raise Gone
        return {}


def test_delivery_removes_stale_connections() -> None:
    store = InMemoryControlPlaneRepository()
    store.create(make_session(), "create-request-001")
    connections = InMemoryConnectionRepository()
    realtime = RealtimeSessionService(connections, store, clock=lambda: NOW)
    realtime.connect("connection-1", "user_demo")
    realtime.subscribe("connection-1", "user_demo", SESSION_ID, after_sequence=0)
    client = FakeManagementClient()
    client.gone.add("connection-1")

    BestEffortEventDelivery(connections, client).deliver("user_demo", make_event())

    assert connections.get("connection-1") is None


class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, object]] = {}

    def put_item(self, **kwargs: object) -> Mapping[str, object]:
        item = dict(cast(Mapping[str, object], kwargs["Item"]))
        self.items[(str(item["PK"]), str(item["SK"]))] = item
        return {}

    def get_item(self, **kwargs: object) -> Mapping[str, object]:
        key = cast(Mapping[str, object], kwargs["Key"])
        item = self.items.get((str(key["PK"]), str(key["SK"])))
        return {} if item is None else {"Item": item}

    def update_item(self, **kwargs: object) -> Mapping[str, object]:
        key = kwargs["Key"]
        values = kwargs["ExpressionAttributeValues"]
        assert isinstance(key, dict) and isinstance(values, dict)
        item = self.items[(str(key["PK"]), str(key["SK"]))]
        item["document"] = values[":document"]
        item["expiresAt"] = values[":expiresAt"]
        return {}

    def delete_item(self, **kwargs: object) -> Mapping[str, object]:
        key = kwargs["Key"]
        assert isinstance(key, dict)
        self.items.pop((str(key["PK"]), str(key["SK"])), None)
        return {}

    def query(self, **kwargs: object) -> Mapping[str, object]:
        return {
            "Items": [
                item
                for (pk, sk), item in self.items.items()
                if pk == f"SESSION#{SESSION_ID}" and sk.startswith("CONNECTION#")
            ]
        }


def test_dynamodb_adapter_writes_ttl_to_connection_and_subscription() -> None:
    table = FakeTable()
    repository = DynamoDbConnectionRepository(table)
    store = InMemoryControlPlaneRepository()
    store.create(make_session(), "create-request-001")
    realtime = RealtimeSessionService(repository, store, clock=lambda: NOW)

    connection = realtime.connect("connection-1", "user_demo")
    realtime.subscribe("connection-1", "user_demo", SESSION_ID, after_sequence=0)

    assert table.items[("CONNECTION#connection-1", "METADATA")]["expiresAt"] == (
        connection.expires_at
    )
    assert (
        table.items[(f"SESSION#{SESSION_ID}", "CONNECTION#connection-1")]["expiresAt"]
        == connection.expires_at
    )
