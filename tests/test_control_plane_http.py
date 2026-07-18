import json
from datetime import UTC, datetime
from typing import Any, cast

from dungeon_agent.control_plane.domain.enums import EventType, SessionPhase, SessionStatus
from dungeon_agent.control_plane.domain.models import (
    CreateSessionCommand,
    CreateSessionWorkflowInput,
    PhaseChangedPayload,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.http.api_gateway import ApiGatewayHttpAdapter
from dungeon_agent.control_plane.http.handlers import SessionHttpHandlers

NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)
SESSION_ID: SessionId = "ses_01J00000000000000000000000"
OTHER_SESSION_ID: SessionId = "ses_01J00000000000000000000001"


class FakeSessionRepository:
    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}
        self.idempotency: dict[tuple[str, str], str] = {}

    def create(self, session: SessionRecord, idempotency_key: str) -> SessionRecord:
        key = (session.owner_id, idempotency_key)
        existing_id = self.idempotency.get(key)
        if existing_id is not None:
            return self.records[existing_id]
        self.records[session.session_id] = session
        self.idempotency[key] = session.session_id
        return session

    def get(self, session_id: SessionId) -> SessionRecord | None:
        return self.records.get(session_id)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> SessionRecord | None:
        session_id = self.idempotency.get((owner_id, idempotency_key))
        return self.records.get(session_id) if session_id is not None else None

    def save(self, session: SessionRecord, *, expected_revision: int) -> SessionRecord:
        current = self.records[session.session_id]
        assert current.revision == expected_revision
        self.records[session.session_id] = session
        return session


class FakeEventRepository:
    def __init__(self) -> None:
        self.events: dict[str, tuple[SessionEvent, ...]] = {}

    def append(self, event: SessionEvent, *, expected_previous_sequence: int) -> None:
        current = self.events.get(event.session_id, ())
        assert len(current) == expected_previous_sequence
        self.events[event.session_id] = (*current, event)

    def list_after(self, session_id: SessionId, sequence: int) -> tuple[SessionEvent, ...]:
        return tuple(
            event for event in self.events.get(session_id, ()) if event.sequence > sequence
        )


class FakeWorkflowStarter:
    def __init__(self) -> None:
        self.calls: list[CreateSessionWorkflowInput] = []
        self.failures_remaining = 0

    def start_create_session(self, workflow_input: CreateSessionWorkflowInput) -> str:
        self.calls.append(workflow_input)
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("workflow unavailable")
        return (
            "arn:aws:states:us-east-2:123456789012:execution:"
            f"create-session:{workflow_input.session_id}"
        )


class FakeSessionFactory:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, command: CreateSessionCommand, now: datetime) -> SessionRecord:
        self.calls += 1
        return SessionRecord(
            session_id=SESSION_ID,
            owner_id=command.owner_id,
            language=command.language,
            status=SessionStatus.REQUESTED,
            phase=SessionPhase.REQUESTED,
            revision=0,
            last_event_sequence=0,
            created_at=now,
            updated_at=now,
        )


def _adapter() -> tuple[
    ApiGatewayHttpAdapter,
    FakeSessionRepository,
    FakeEventRepository,
    FakeWorkflowStarter,
    FakeSessionFactory,
]:
    sessions = FakeSessionRepository()
    events = FakeEventRepository()
    workflows = FakeWorkflowStarter()
    factory = FakeSessionFactory()
    handlers = SessionHttpHandlers(
        sessions,
        events,
        workflows,
        factory,
        clock=lambda: NOW,
    )
    return ApiGatewayHttpAdapter(handlers), sessions, events, workflows, factory


def _event(
    route_key: str,
    *,
    owner: str | None = "user_demo",
    body: dict[str, object] | None = None,
    session_id: str | None = None,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    authorizer = {"jwt": {"claims": {"sub": owner}}} if owner is not None else {}
    event: dict[str, object] = {
        "version": "2.0",
        "routeKey": route_key,
        "headers": headers or {},
        "requestContext": {
            "requestId": "request-12345678",
            "authorizer": authorizer,
        },
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if session_id is not None:
        event["pathParameters"] = {"sessionId": session_id}
    if query is not None:
        event["queryStringParameters"] = query
    return event


def _body(response: dict[str, Any]) -> dict[str, Any]:
    decoded = json.loads(str(response["body"]))
    return cast(dict[str, Any], decoded)


def test_create_returns_202_and_starts_workflow_without_waiting() -> None:
    adapter, sessions, _, workflows, _ = _adapter()

    response = adapter(
        _event(
            "POST /sessions",
            body={"language": "es"},
            headers={
                "Idempotency-Key": "new-session-0001",
                "X-Correlation-Id": "corr-create-0001",
                "Authorization": "Bearer must-not-be-returned",
            },
        )
    )

    assert response["statusCode"] == 202
    assert response["headers"]["location"] == f"/sessions/{SESSION_ID}"
    assert response["headers"]["x-correlation-id"] == "corr-create-0001"
    body = _body(response)
    session = body["session"]
    assert session["status"] == "requested"
    assert session["workflowExecutionArn"].endswith(SESSION_ID)
    assert len(workflows.calls) == 1
    assert sessions.records[SESSION_ID].workflow_execution_arn is not None
    assert "must-not-be-returned" not in json.dumps(response)


def test_repeated_create_returns_same_session_without_duplicate_workflow() -> None:
    adapter, _, _, workflows, factory = _adapter()
    event = _event(
        "POST /sessions",
        body={"language": "en"},
        headers={"idempotency-key": "same-request-0001"},
    )

    first = adapter(event)
    second = adapter(event)

    assert first["statusCode"] == second["statusCode"] == 202
    assert _body(first)["session"]["sessionId"] == _body(second)["session"]["sessionId"]
    assert len(workflows.calls) == 1
    assert factory.calls == 1


def test_create_can_retry_after_workflow_dependency_failure() -> None:
    adapter, _, _, workflows, factory = _adapter()
    workflows.failures_remaining = 1
    event = _event(
        "POST /sessions",
        body={"language": "en"},
        headers={"idempotency-key": "retry-request-0001"},
    )

    first = adapter(event)
    second = adapter(event)

    assert first["statusCode"] == 503
    assert _body(first)["error"]["code"] == "dependency_unavailable"
    assert second["statusCode"] == 202
    assert len(workflows.calls) == 2
    assert factory.calls == 1


def test_get_session_rejects_cross_user_access() -> None:
    adapter, sessions, _, _, _ = _adapter()
    sessions.records[SESSION_ID] = _record(SESSION_ID, "user_owner")

    response = adapter(
        _event(
            "GET /sessions/{sessionId}",
            owner="user_intruder",
            session_id=SESSION_ID,
        )
    )

    assert response["statusCode"] == 403
    assert _body(response)["error"]["code"] == "not_authorized"


def test_get_events_replays_only_after_requested_sequence() -> None:
    adapter, sessions, events, _, _ = _adapter()
    sessions.records[SESSION_ID] = _record(SESSION_ID, "user_demo")
    events.events[SESSION_ID] = (_phase_event(1), _phase_event(2))

    response = adapter(
        _event(
            "GET /sessions/{sessionId}/events",
            session_id=SESSION_ID,
            query={"after": "1"},
        )
    )

    assert response["statusCode"] == 200
    body = _body(response)
    assert [event["sequence"] for event in body["events"]] == [2]
    assert body["nextSequence"] == 2


def test_missing_authentication_returns_typed_401() -> None:
    adapter, _, _, _, _ = _adapter()

    response = adapter(
        _event(
            "GET /sessions/{sessionId}",
            owner=None,
            session_id=SESSION_ID,
        )
    )

    assert response["statusCode"] == 401
    body = _body(response)
    assert body == {
        "version": 1,
        "error": {
            "code": "not_authenticated",
            "message": "Authentication is required.",
            "retryable": False,
            "correlationId": "request-12345678",
        },
    }


def test_invalid_input_returns_typed_400_with_correlation_id() -> None:
    adapter, _, _, _, _ = _adapter()

    response = adapter(
        _event(
            "POST /sessions",
            body={"language": "fr"},
            headers={"idempotency-key": "valid-key-0001"},
        )
    )

    assert response["statusCode"] == 400
    assert response["headers"]["x-correlation-id"] == "request-12345678"
    assert _body(response)["error"]["code"] == "validation_failed"


def test_unknown_session_returns_typed_404() -> None:
    adapter, _, _, _, _ = _adapter()

    response = adapter(
        _event(
            "GET /sessions/{sessionId}",
            session_id=OTHER_SESSION_ID,
        )
    )

    assert response["statusCode"] == 404
    assert _body(response)["error"]["code"] == "session_not_found"


def _record(session_id: SessionId, owner_id: str) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        owner_id=owner_id,
        language="en",
        status=SessionStatus.REQUESTED,
        phase=SessionPhase.REQUESTED,
        revision=0,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
    )


def _phase_event(sequence: int) -> SessionEvent:
    return SessionEvent(
        event_id=f"evt_01J0000000000000000000000{sequence + 3}",
        session_id=SESSION_ID,
        sequence=sequence,
        type=EventType.SESSION_PHASE_CHANGED,
        occurred_at=NOW,
        correlation_id="corr-events-0001",
        payload=PhaseChangedPayload(
            phase=SessionPhase.CREATING_ADVENTURE,
            elapsed_ms=sequence * 100,
        ),
    )
