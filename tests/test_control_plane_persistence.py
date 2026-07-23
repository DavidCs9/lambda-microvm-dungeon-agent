from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from dungeon_agent.control_plane.domain.enums import EventType, SessionPhase, SessionStatus
from dungeon_agent.control_plane.domain.models import (
    CreationStartedPayload,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.persistence.dynamodb import DynamoDbControlPlaneRepository
from dungeon_agent.control_plane.persistence.errors import (
    EventSequenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)
from dungeon_agent.control_plane.persistence.memory import InMemoryControlPlaneRepository

SESSION_ID: SessionId = "ses_01J00000000000000000000000"
NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)


def make_session(*, session_id: SessionId = SESSION_ID) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        owner_id="user_demo",
        language="es",
        status=SessionStatus.REQUESTED,
        phase=SessionPhase.REQUESTED,
        revision=0,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
    )


def make_event(sequence: int, *, suffix: str = "1") -> SessionEvent:
    return SessionEvent(
        event_id=f"evt_01J0000000000000000000000{suffix}",
        session_id=SESSION_ID,
        sequence=sequence,
        type=EventType.SESSION_CREATION_STARTED,
        occurred_at=NOW + timedelta(seconds=sequence),
        correlation_id="corr-persistence-test",
        payload=CreationStartedPayload(language="es"),
    )


def test_in_memory_create_is_owner_scoped_and_idempotent() -> None:
    repository = InMemoryControlPlaneRepository()
    first = make_session()
    duplicate = make_session(session_id="ses_01J00000000000000000000009")

    assert repository.create(first, "create-request-001") == first
    assert repository.create(duplicate, "create-request-001") == first
    assert repository.find_by_idempotency_key("user_demo", "create-request-001") == first
    assert repository.find_by_idempotency_key("other_user", "create-request-001") is None


def test_in_memory_rejects_same_session_id_for_a_different_request() -> None:
    repository = InMemoryControlPlaneRepository()
    session = make_session()
    repository.create(session, "create-request-001")

    with pytest.raises(SessionAlreadyExistsError):
        repository.create(session, "create-request-002")


def test_in_memory_save_requires_and_advances_exact_revision() -> None:
    repository = InMemoryControlPlaneRepository()
    original = repository.create(make_session(), "create-request-001")
    updated = original.model_copy(update={"revision": 1, "updated_at": NOW + timedelta(seconds=1)})

    assert repository.save(updated, expected_revision=0).revision == 1
    with pytest.raises(SessionRevisionConflictError):
        repository.save(updated, expected_revision=0)
    with pytest.raises(SessionRevisionConflictError):
        repository.save(updated.model_copy(update={"revision": 3}), expected_revision=1)


def test_in_memory_event_append_is_monotonic_and_replayable() -> None:
    repository = InMemoryControlPlaneRepository()
    repository.create(make_session(), "create-request-001")
    first = make_event(1, suffix="1")
    second = make_event(2, suffix="2")

    repository.append(first, expected_previous_sequence=0)
    repository.append(second, expected_previous_sequence=1)

    stored = repository.get(SESSION_ID)
    assert stored is not None
    assert stored.last_event_sequence == 2
    assert repository.list_after(SESSION_ID, 0) == (first, second)
    assert repository.list_after(SESSION_ID, 1) == (second,)
    assert repository.list_after(SESSION_ID, 2) == ()


def test_session_save_does_not_roll_back_an_independent_event_append() -> None:
    repository = InMemoryControlPlaneRepository()
    stale = repository.create(make_session(), "create-request-001")
    repository.append(make_event(1), expected_previous_sequence=0)
    updated = stale.model_copy(update={"revision": 1, "updated_at": NOW + timedelta(seconds=2)})

    saved = repository.save(updated, expected_revision=0)

    assert saved.revision == 1
    assert saved.last_event_sequence == 1


def _ready_session(
    session_id: SessionId, owner_id: str, *, created_at: datetime, microvm_id: str
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        owner_id=owner_id,
        language="es",
        status=SessionStatus.READY,
        phase=SessionPhase.READY,
        revision=0,
        last_event_sequence=0,
        created_at=created_at,
        updated_at=created_at,
        active_microvm_id=microvm_id,
    )


def test_in_memory_list_active_by_owner_filters_orders_and_caps() -> None:
    repository = InMemoryControlPlaneRepository()
    owner = "user_demo"
    finished = make_session(session_id="ses_01J00000000000000000000F01").model_copy(
        update={"status": SessionStatus.COMPLETED, "phase": SessionPhase.COMPLETED}
    )
    repository.create(finished, "create-request-finished")
    other_owner_active = _ready_session(
        "ses_01J00000000000000000000F02",
        "user_other",
        created_at=NOW,
        microvm_id="mvm-other",
    )
    repository.create(other_owner_active, "create-request-other")

    active_ids = [f"ses_01J0000000000000000000{index:04d}" for index in range(1, 13)]
    for offset, session_id in enumerate(active_ids):
        session = _ready_session(
            session_id,
            owner,
            created_at=NOW - timedelta(minutes=offset),
            microvm_id=f"mvm-{offset}",
        )
        repository.create(session, f"create-request-{offset}")

    listed = repository.list_active_by_owner(owner)

    assert [session.session_id for session in listed] == active_ids[:10]
    assert all(session.owner_id == owner for session in listed)


def test_concurrent_event_appends_cannot_claim_the_same_sequence() -> None:
    repository = InMemoryControlPlaneRepository()
    repository.create(make_session(), "create-request-001")
    candidates = [make_event(1, suffix=str(index)) for index in range(1, 9)]

    def append(event: SessionEvent) -> bool:
        try:
            repository.append(event, expected_previous_sequence=0)
        except EventSequenceConflictError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(append, candidates))

    assert sum(results) == 1
    assert len(repository.list_after(SESSION_ID, 0)) == 1


class FakeConditionalCheckFailed(Exception):
    pass


class FakeTransactionCanceled(Exception):
    pass


class FakeExceptions:
    ConditionalCheckFailedException: type[Exception] = FakeConditionalCheckFailed
    TransactionCanceledException: type[Exception] = FakeTransactionCanceled


class FakeDynamoDbClient:
    exceptions = FakeExceptions()

    def __init__(self) -> None:
        self.get_responses: list[Mapping[str, object]] = []
        self.update_response: Mapping[str, object] = {}
        self.query_responses: list[Mapping[str, object]] = [{"Items": []}]
        self.raise_transaction = False
        self.raise_update = False
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_item(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(("get_item", kwargs))
        return self.get_responses.pop(0) if self.get_responses else {}

    def put_item(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(("put_item", kwargs))
        return {}

    def update_item(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(("update_item", kwargs))
        if self.raise_update:
            raise FakeConditionalCheckFailed
        return self.update_response

    def transact_write_items(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(("transact_write_items", kwargs))
        if self.raise_transaction:
            raise FakeTransactionCanceled
        return {}

    def get_paginator(self, operation_name: str) -> FakeQueryPaginator:
        self.calls.append(("get_paginator", {"operation_name": operation_name}))
        return FakeQueryPaginator(self)


class FakeQueryPaginator:
    def __init__(self, client: FakeDynamoDbClient) -> None:
        self._client = client

    def paginate(self, **kwargs: object) -> list[Mapping[str, object]]:
        self._client.calls.append(("paginate", kwargs))
        return self._client.query_responses


def session_item(session: SessionRecord) -> dict[str, object]:
    return {
        "PK": {"S": f"SESSION#{session.session_id}"},
        "SK": {"S": "METADATA"},
        "revision": {"N": str(session.revision)},
        "lastEventSequence": {"N": str(session.last_event_sequence)},
        "document": {"S": session.model_dump_json(by_alias=True)},
    }


def event_item(event: SessionEvent) -> dict[str, object]:
    return {
        "PK": {"S": f"SESSION#{event.session_id}"},
        "SK": {"S": f"EVENT#{event.sequence:020d}"},
        "document": {"S": event.model_dump_json(by_alias=True)},
    }


def test_dynamodb_create_uses_one_conditional_transaction_and_ttl() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbControlPlaneRepository(client, "control-plane", idempotency_ttl_seconds=60)
    session = make_session()

    assert repository.create(session, "create-request-001") == session

    operation, arguments = client.calls[-1]
    assert operation == "transact_write_items"
    writes = cast(list[dict[str, object]], arguments["TransactItems"])
    session_put = cast(dict[str, object], writes[0]["Put"])
    idempotency_put = cast(dict[str, object], writes[1]["Put"])
    assert session_put["ConditionExpression"] == "attribute_not_exists(PK)"
    assert idempotency_put["ConditionExpression"] == "attribute_not_exists(PK)"
    item = cast(dict[str, dict[str, str]], idempotency_put["Item"])
    assert item["expiresAt"]["N"] == str(int((NOW + timedelta(seconds=60)).timestamp()))


def test_dynamodb_duplicate_create_returns_original_session() -> None:
    client = FakeDynamoDbClient()
    original = make_session()
    client.get_responses = [
        {"Item": {"sessionId": {"S": original.session_id}}},
        {"Item": session_item(original)},
    ]
    repository = DynamoDbControlPlaneRepository(client, "control-plane")

    assert repository.create(make_session(), "create-request-001") == original
    assert all(operation != "transact_write_items" for operation, _ in client.calls)


def test_dynamodb_save_uses_revision_condition_and_preserves_event_counter() -> None:
    client = FakeDynamoDbClient()
    current = make_session().model_copy(update={"last_event_sequence": 4})
    updated = current.model_copy(update={"revision": 1, "updated_at": NOW + timedelta(seconds=1)})
    client.update_response = {"Attributes": session_item(updated)}
    repository = DynamoDbControlPlaneRepository(client, "control-plane")

    assert repository.save(updated, expected_revision=0) == updated
    _, arguments = client.calls[-1]
    assert arguments["ConditionExpression"] == "#revision = :expectedRevision"
    assert "lastEventSequence" not in cast(str, arguments["UpdateExpression"])

    client.raise_update = True
    with pytest.raises(SessionRevisionConflictError):
        repository.save(updated.model_copy(update={"revision": 2}), expected_revision=1)


def test_dynamodb_append_and_replay_use_ordered_conditional_operations() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbControlPlaneRepository(client, "control-plane")
    event = make_event(1)

    repository.append(event, expected_previous_sequence=0)
    _, arguments = client.calls[-1]
    writes = cast(list[dict[str, object]], arguments["TransactItems"])
    update = cast(dict[str, object], writes[0]["Update"])
    put = cast(dict[str, object], writes[1]["Put"])
    assert update["ConditionExpression"] == "#lastSequence = :expectedSequence"
    assert put["ConditionExpression"] == "attribute_not_exists(PK)"

    client.query_responses = [{"Items": []}, {"Items": [event_item(event)]}]
    assert repository.list_after(SESSION_ID, 0) == (event,)
    operation, query = client.calls[-1]
    assert operation == "paginate"
    assert query["ConsistentRead"] is True
    assert query["ScanIndexForward"] is True
    assert query["KeyConditionExpression"] == "PK = :pk AND SK BETWEEN :after AND :eventEnd"


def test_dynamodb_replay_key_range_excludes_session_metadata() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbControlPlaneRepository(client, "control-plane")

    assert repository.list_after(SESSION_ID, 0) == ()

    _, query = client.calls[-1]
    values = cast(dict[str, dict[str, str]], query["ExpressionAttributeValues"])
    lower = values[":after"]["S"]
    upper = values[":eventEnd"]["S"]
    first_event_key = "EVENT#00000000000000000001"
    assert lower < first_event_key <= upper
    assert upper < "METADATA"


def test_dynamodb_conditional_event_conflict_is_domain_specific() -> None:
    client = FakeDynamoDbClient()
    client.raise_transaction = True
    repository = DynamoDbControlPlaneRepository(client, "control-plane")

    with pytest.raises(EventSequenceConflictError):
        repository.append(make_event(1), expected_previous_sequence=0)


def test_dynamodb_list_active_by_owner_queries_the_by_owner_index() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbControlPlaneRepository(client, "control-plane")
    older = make_session(session_id="ses_01J00000000000000000000001")
    newer = make_session(session_id="ses_01J00000000000000000000002").model_copy(
        update={"created_at": NOW + timedelta(minutes=5), "updated_at": NOW + timedelta(minutes=5)}
    )
    client.query_responses = [{"Items": [session_item(older), session_item(newer)]}]

    listed = repository.list_active_by_owner("user_demo")

    assert [session.session_id for session in listed] == [newer.session_id, older.session_id]
    _, query = client.calls[-1]
    assert query["IndexName"] == "ByOwner"
    assert query["KeyConditionExpression"] == "ownerId = :owner"
    assert "#status IN (" in cast(str, query["FilterExpression"])
    values = cast(dict[str, dict[str, str]], query["ExpressionAttributeValues"])
    assert values[":owner"]["S"] == "user_demo"
    assert {value["S"] for key, value in values.items() if key != ":owner"} == {
        "requested",
        "creating",
        "ready",
        "active",
    }
