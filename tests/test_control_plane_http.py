import json
from datetime import UTC, datetime, timedelta
from typing import Any, Never, cast

from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    EventType,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    CampaignRecord,
    CreateCampaignWorkflowInput,
    CreateSessionWorkflowInput,
    OpeningDocument,
    PhaseChangedPayload,
    SessionCompletedPayload,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.http.api_gateway import ApiGatewayHttpAdapter
from dungeon_agent.control_plane.http.campaigns import CampaignHttpHandlers
from dungeon_agent.control_plane.http.sessions import SessionHttpHandlers
from dungeon_agent.control_plane.persistence.memory import (
    InMemoryCampaignRepository,
    InMemoryControlPlaneRepository,
)

NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)
SESSION_ID: SessionId = "ses_01J00000000000000000000000"
OTHER_SESSION_ID: SessionId = "ses_01J00000000000000000000001"
CAMPAIGN_ID: CampaignId = "cam_01J00000000000000000000000"
ADVENTURE_REF = f"dynamodb://CAMPAIGN#{CAMPAIGN_ID}/ARTIFACT#ADVENTURE"
CHARACTER_REF = f"dynamodb://CAMPAIGN#{CAMPAIGN_ID}/ARTIFACT#CHARACTER"


class FakeMicrovmManager:
    def __init__(self) -> None:
        self.terminated: list[str] = []
        self.fail_terminate = False

    def launch(self, session_id: SessionId) -> Never:
        raise AssertionError("not used in http tests")

    def initialize(
        self,
        microvm_id: str,
        language: object,
        adventure: object,
        character: object,
    ) -> Never:
        raise AssertionError("not used in http tests")

    def apply_turn(self, microvm_id: str, action: str, proposal: object) -> Never:
        raise AssertionError("not used in http tests")

    def is_running(self, microvm_id: str) -> bool:
        raise AssertionError("not used in http tests")

    def rehydrate(self, session_id: SessionId, state: object) -> Never:
        raise AssertionError("not used in http tests")

    def terminate(self, microvm_id: str) -> None:
        if self.fail_terminate:
            raise RuntimeError("microvm terminate unavailable")
        self.terminated.append(microvm_id)


class FakeOpeningLoader:
    def load_opening(self, character_ref: str) -> OpeningDocument:
        from dungeon_agent.control_plane.workflow.sandbox import sandbox_opening

        assert character_ref
        return sandbox_opening("es")

    def load_portrait_key(self, character_ref: str) -> str | None:
        assert character_ref
        return None


class FakeWorkflowStarter:
    def __init__(self) -> None:
        self.calls: list[CreateSessionWorkflowInput] = []
        self.campaign_calls: list[CreateCampaignWorkflowInput] = []
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

    def start_create_campaign(self, workflow_input: CreateCampaignWorkflowInput) -> str:
        self.campaign_calls.append(workflow_input)
        return (
            "arn:aws:states:us-east-2:123456789012:execution:"
            f"create-campaign:{workflow_input.campaign_id}"
        )


def ready_campaign(owner_id: str = "user_demo") -> CampaignRecord:
    return CampaignRecord(
        campaign_id=CAMPAIGN_ID,
        owner_id=owner_id,
        language="en",
        status=CampaignStatus.READY,
        phase=CampaignPhase.READY,
        revision=2,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
        adventure_ref=ADVENTURE_REF,
        character_ref=CHARACTER_REF,
    )


def _put_session(store: InMemoryControlPlaneRepository, session: SessionRecord) -> None:
    store._sessions[session.session_id] = session
    store._events.setdefault(session.session_id, {})


def _put_campaign(store: InMemoryCampaignRepository, campaign: CampaignRecord) -> None:
    store._campaigns[campaign.campaign_id] = campaign
    store._events.setdefault(campaign.campaign_id, {})


def _put_events(
    store: InMemoryControlPlaneRepository,
    session_id: SessionId,
    events: tuple[SessionEvent, ...],
) -> None:
    store._events[session_id] = {event.sequence: event for event in events}


def _session_events(
    store: InMemoryControlPlaneRepository,
    session_id: SessionId,
) -> tuple[SessionEvent, ...]:
    events = store._events.get(session_id, {})
    return tuple(events[index] for index in sorted(events))


def _adapter() -> tuple[
    ApiGatewayHttpAdapter,
    InMemoryControlPlaneRepository,
    InMemoryControlPlaneRepository,
    FakeWorkflowStarter,
    InMemoryCampaignRepository,
    FakeMicrovmManager,
]:
    sessions = InMemoryControlPlaneRepository()
    workflows = FakeWorkflowStarter()
    campaigns = InMemoryCampaignRepository()
    _put_campaign(campaigns, ready_campaign())
    microvms = FakeMicrovmManager()
    handlers = SessionHttpHandlers(
        sessions,
        workflows,
        campaigns,
        microvms=microvms,
        clock=lambda: NOW,
        session_id_factory=lambda: SESSION_ID,
    )
    campaign_handlers = CampaignHttpHandlers(
        campaigns,
        workflows,
        openings=FakeOpeningLoader(),
        clock=lambda: NOW,
        campaign_id_factory=lambda: CAMPAIGN_ID,
    )
    return (
        ApiGatewayHttpAdapter(handlers, campaign_handlers),
        sessions,
        sessions,
        workflows,
        campaigns,
        microvms,
    )


def _event(
    route_key: str,
    *,
    owner: str | None = "user_demo",
    body: dict[str, object] | None = None,
    session_id: str | None = None,
    campaign_id: str | None = None,
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
    path_parameters: dict[str, str] = {}
    if session_id is not None:
        path_parameters["sessionId"] = session_id
    if campaign_id is not None:
        path_parameters["campaignId"] = campaign_id
    if path_parameters:
        event["pathParameters"] = path_parameters
    if query is not None:
        event["queryStringParameters"] = query
    return event


def _body(response: dict[str, Any]) -> dict[str, Any]:
    decoded = json.loads(str(response["body"]))
    return cast(dict[str, Any], decoded)


def test_create_returns_202_and_starts_workflow_without_waiting() -> None:
    adapter, sessions, _, workflows, _, _ = _adapter()

    response = adapter(
        _event(
            "POST /sessions",
            body={"language": "es", "campaignId": CAMPAIGN_ID},
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
    assert session["campaignId"] == CAMPAIGN_ID
    assert session["campaignRevision"] == 2
    assert session["workflowExecutionArn"].endswith(SESSION_ID)
    assert len(workflows.calls) == 1
    workflow_input = workflows.calls[0]
    assert workflow_input.campaign_id == CAMPAIGN_ID
    assert workflow_input.campaign_revision == 2
    stored = sessions.get(SESSION_ID)
    assert stored is not None
    assert stored.workflow_execution_arn is not None
    assert "must-not-be-returned" not in json.dumps(response)


def test_repeated_create_returns_same_session_without_duplicate_workflow() -> None:
    adapter, sessions, _, workflows, _, _ = _adapter()
    event = _event(
        "POST /sessions",
        body={"language": "en", "campaignId": CAMPAIGN_ID},
        headers={"idempotency-key": "same-request-0001"},
    )

    first = adapter(event)
    second = adapter(event)

    assert first["statusCode"] == second["statusCode"] == 202
    assert _body(first)["session"]["sessionId"] == _body(second)["session"]["sessionId"]
    assert len(workflows.calls) == 1
    assert len(sessions._sessions) == 1


def test_create_can_retry_after_workflow_dependency_failure() -> None:
    adapter, sessions, _, workflows, _, _ = _adapter()
    workflows.failures_remaining = 1
    event = _event(
        "POST /sessions",
        body={"language": "en", "campaignId": CAMPAIGN_ID},
        headers={"idempotency-key": "retry-request-0001"},
    )

    first = adapter(event)
    second = adapter(event)

    assert first["statusCode"] == 503
    assert _body(first)["error"]["code"] == "dependency_unavailable"
    assert second["statusCode"] == 202
    assert len(workflows.calls) == 2
    assert len(sessions._sessions) == 1


def test_create_session_rejects_an_unknown_campaign() -> None:
    adapter, _, _, workflows, _, _ = _adapter()

    response = adapter(
        _event(
            "POST /sessions",
            body={"language": "en", "campaignId": "cam_01J00000000000000000000009"},
            headers={"idempotency-key": "unknown-campaign-01"},
        )
    )

    assert response["statusCode"] == 404
    assert _body(response)["error"]["code"] == "campaign_not_found"
    assert workflows.calls == []


def test_create_session_rejects_another_users_campaign() -> None:
    adapter, _, _, workflows, campaigns, _ = _adapter()
    _put_campaign(campaigns, ready_campaign(owner_id="user_owner"))

    response = adapter(
        _event(
            "POST /sessions",
            owner="user_intruder",
            body={"language": "en", "campaignId": CAMPAIGN_ID},
            headers={"idempotency-key": "cross-user-campaign1"},
        )
    )

    assert response["statusCode"] == 403
    assert _body(response)["error"]["code"] == "not_authorized"
    assert workflows.calls == []


def test_create_session_rejects_a_campaign_that_is_not_ready() -> None:
    adapter, _, _, workflows, campaigns, _ = _adapter()
    _put_campaign(
        campaigns,
        CampaignRecord(
            campaign_id=CAMPAIGN_ID,
            owner_id="user_demo",
            language="en",
            status=CampaignStatus.CREATING,
            phase=CampaignPhase.CREATING_ADVENTURE,
            revision=1,
            last_event_sequence=0,
            created_at=NOW,
            updated_at=NOW,
        ),
    )

    response = adapter(
        _event(
            "POST /sessions",
            body={"language": "en", "campaignId": CAMPAIGN_ID},
            headers={"idempotency-key": "campaign-not-ready1"},
        )
    )

    assert response["statusCode"] == 409
    assert _body(response)["error"]["code"] == "campaign_conflict"
    assert workflows.calls == []


def test_get_session_rejects_cross_user_access() -> None:
    adapter, sessions, _, _, _, _ = _adapter()
    _put_session(sessions, _record(SESSION_ID, "user_owner"))

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
    adapter, sessions, events, _, _, _ = _adapter()
    _put_session(sessions, _record(SESSION_ID, "user_demo"))
    _put_events(events, SESSION_ID, (_phase_event(1), _phase_event(2)))

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
    adapter, _, _, _, _, _ = _adapter()

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
    adapter, _, _, _, _, _ = _adapter()

    response = adapter(
        _event(
            "POST /sessions",
            body={"language": "fr", "campaignId": CAMPAIGN_ID},
            headers={"idempotency-key": "valid-key-0001"},
        )
    )

    assert response["statusCode"] == 400
    assert response["headers"]["x-correlation-id"] == "request-12345678"
    assert _body(response)["error"]["code"] == "validation_failed"


def test_unknown_session_returns_typed_404() -> None:
    adapter, _, _, _, _, _ = _adapter()

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
            phase=SessionPhase.STARTING_MICROVM,
            elapsed_ms=sequence * 100,
        ),
    )


def test_list_campaigns_returns_only_owner_campaigns() -> None:
    adapter, _, _, _, campaigns, _ = _adapter()
    other_id: CampaignId = "cam_01J00000000000000000000009"
    _put_campaign(
        campaigns,
        ready_campaign("other_user").model_copy(update={"campaign_id": other_id}),
    )

    response = adapter(_event("GET /campaigns"))
    assert response["statusCode"] == 200
    body = _body(response)
    ids = [campaign["campaignId"] for campaign in body["campaigns"]]
    assert ids == [CAMPAIGN_ID]
    listed = body["campaigns"][0]
    assert "openingTitle" in listed
    assert "createdAt" in listed


def test_get_campaign_opening_ready_and_not_ready() -> None:
    adapter, _, _, _, campaigns, _ = _adapter()

    ready = adapter(_event("GET /campaigns/{campaignId}/opening", campaign_id=CAMPAIGN_ID))
    assert ready["statusCode"] == 200
    ready_body = _body(ready)
    assert ready_body["campaignId"] == CAMPAIGN_ID
    assert ready_body["opening"]["title"]

    _put_campaign(
        campaigns,
        CampaignRecord(
            campaign_id=CAMPAIGN_ID,
            owner_id="user_demo",
            language="en",
            status=CampaignStatus.REQUESTED,
            phase=CampaignPhase.REQUESTED,
            revision=0,
            last_event_sequence=0,
            created_at=NOW,
            updated_at=NOW,
        ),
    )
    conflict = adapter(_event("GET /campaigns/{campaignId}/opening", campaign_id=CAMPAIGN_ID))
    assert conflict["statusCode"] == 409
    assert _body(conflict)["error"]["code"] == "campaign_conflict"


def test_list_campaigns_filters_by_ready_status() -> None:
    adapter, _, _, _, campaigns, _ = _adapter()
    creating_id: CampaignId = "cam_01J00000000000000000000088"
    _put_campaign(
        campaigns,
        CampaignRecord(
            campaign_id=creating_id,
            owner_id="user_demo",
            language="en",
            status=CampaignStatus.CREATING,
            phase=CampaignPhase.CREATING_ADVENTURE,
            revision=1,
            last_event_sequence=0,
            created_at=NOW + timedelta(seconds=5),
            updated_at=NOW + timedelta(seconds=5),
        ),
    )

    response = adapter(_event("GET /campaigns", query={"status": "ready"}))

    assert response["statusCode"] == 200
    ids = [campaign["campaignId"] for campaign in _body(response)["campaigns"]]
    assert ids == [CAMPAIGN_ID]


def test_list_campaigns_rejects_invalid_status() -> None:
    adapter, _, _, _, _, _ = _adapter()

    response = adapter(_event("GET /campaigns", query={"status": "bogus"}))

    assert response["statusCode"] == 400
    assert _body(response)["error"]["code"] == "validation_failed"


def test_get_campaign_opening_rejects_cross_user_access() -> None:
    adapter, _, _, _, _, _ = _adapter()

    response = adapter(
        _event(
            "GET /campaigns/{campaignId}/opening",
            owner="user_intruder",
            campaign_id=CAMPAIGN_ID,
        )
    )

    assert response["statusCode"] == 403
    assert _body(response)["error"]["code"] == "not_authorized"


def test_get_campaign_opening_unknown_campaign_returns_404() -> None:
    adapter, _, _, _, _, _ = _adapter()
    missing: CampaignId = "cam_01J00000000000000000000077"

    response = adapter(_event("GET /campaigns/{campaignId}/opening", campaign_id=missing))

    assert response["statusCode"] == 404
    assert _body(response)["error"]["code"] == "campaign_not_found"


_PHASE_BY_STATUS = {
    SessionStatus.REQUESTED: SessionPhase.REQUESTED,
    SessionStatus.CREATING: SessionPhase.STARTING_MICROVM,
    SessionStatus.READY: SessionPhase.READY,
    SessionStatus.ACTIVE: SessionPhase.PLAYING,
    SessionStatus.COMPLETED: SessionPhase.COMPLETED,
    SessionStatus.FAILED: SessionPhase.FAILED,
}


def _session_record(
    session_id: SessionId,
    owner_id: str,
    *,
    status: SessionStatus = SessionStatus.REQUESTED,
    active_microvm_id: str | None = None,
    created_at: datetime = NOW,
    revision: int = 0,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        owner_id=owner_id,
        language="en",
        status=status,
        phase=_PHASE_BY_STATUS[status],
        revision=revision,
        last_event_sequence=0,
        created_at=created_at,
        updated_at=created_at,
        active_microvm_id=active_microvm_id,
    )


def test_list_active_sessions_filters_orders_and_caps_at_ten() -> None:
    adapter, sessions, _, _, _, _ = _adapter()
    owner = "user_demo"
    other_owner = "user_other"

    # Finished sessions never count, regardless of owner.
    finished_id: SessionId = "ses_01J00000000000000000000F01"
    _put_session(
        sessions,
        _session_record(finished_id, owner, status=SessionStatus.COMPLETED),
    )
    other_id: SessionId = "ses_01J00000000000000000000F02"
    _put_session(
        sessions,
        _session_record(
            other_id,
            other_owner,
            status=SessionStatus.READY,
            active_microvm_id="mvm-other",
        ),
    )

    # 12 active sessions for the owner, newest first once sorted.
    active_ids: list[SessionId] = [f"ses_01J0000000000000000000{index:04d}" for index in range(12)]
    for offset, session_id in enumerate(active_ids):
        _put_session(
            sessions,
            _session_record(
                session_id,
                owner,
                status=SessionStatus.READY,
                active_microvm_id=f"mvm-{offset}",
                created_at=NOW - timedelta(minutes=offset),
            ),
        )

    response = adapter(_event("GET /sessions", owner=owner, query={"status": "active"}))

    assert response["statusCode"] == 200
    body = _body(response)
    listed_ids = [session["sessionId"] for session in body["sessions"]]
    assert len(listed_ids) == 10
    # Newest createdAt (offset 0) first, most negative offset last among the cap.
    assert listed_ids == active_ids[:10]
    assert other_owner not in json.dumps(body)


def test_list_active_sessions_requires_active_status_filter() -> None:
    adapter, _, _, _, _, _ = _adapter()

    response = adapter(_event("GET /sessions", query={"status": "completed"}))

    assert response["statusCode"] == 400
    assert _body(response)["error"]["code"] == "validation_failed"


def test_abandon_ready_session_completes_and_terminates_microvm() -> None:
    adapter, sessions, events, _, _, microvms = _adapter()
    _put_session(
        sessions,
        _session_record(
            SESSION_ID, "user_demo", status=SessionStatus.READY, active_microvm_id="mvm-ready"
        ),
    )

    response = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=SESSION_ID))

    assert response["statusCode"] == 200
    body = _body(response)
    assert body["session"]["status"] == "completed"
    assert body["session"]["activeMicrovmId"] is None
    assert microvms.terminated == ["mvm-ready"]
    emitted = _session_events(events, SESSION_ID)
    assert [event.type for event in emitted] == [EventType.SESSION_COMPLETED]
    assert isinstance(emitted[0].payload, SessionCompletedPayload)
    assert emitted[0].payload.outcome == "abandoned"


def test_abandon_active_session_completes_and_terminates_microvm() -> None:
    adapter, sessions, _, _, _, microvms = _adapter()
    _put_session(
        sessions,
        _session_record(
            SESSION_ID, "user_demo", status=SessionStatus.ACTIVE, active_microvm_id="mvm-active"
        ),
    )

    response = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=SESSION_ID))

    assert response["statusCode"] == 200
    assert _body(response)["session"]["status"] == "completed"
    assert microvms.terminated == ["mvm-active"]


def test_abandon_survives_microvm_terminate_failure() -> None:
    adapter, sessions, _, _, _, microvms = _adapter()
    microvms.fail_terminate = True
    _put_session(
        sessions,
        _session_record(
            SESSION_ID, "user_demo", status=SessionStatus.READY, active_microvm_id="mvm-flaky"
        ),
    )

    response = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=SESSION_ID))

    assert response["statusCode"] == 200
    assert _body(response)["session"]["status"] == "completed"


def test_abandon_is_idempotent_for_a_completed_session() -> None:
    adapter, sessions, _, _, _, microvms = _adapter()
    _put_session(
        sessions,
        _session_record(SESSION_ID, "user_demo", status=SessionStatus.COMPLETED, revision=5),
    )

    first = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=SESSION_ID))
    second = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=SESSION_ID))

    assert first["statusCode"] == second["statusCode"] == 200
    assert _body(first)["session"]["revision"] == 5
    assert _body(second)["session"]["revision"] == 5
    assert microvms.terminated == []


def test_abandon_returns_409_retryable_for_a_creating_session() -> None:
    adapter, sessions, _, _, _, _ = _adapter()
    _put_session(
        sessions,
        _session_record(SESSION_ID, "user_demo", status=SessionStatus.CREATING),
    )

    response = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=SESSION_ID))

    assert response["statusCode"] == 409
    body = _body(response)
    assert body["error"]["code"] == "session_conflict"
    assert body["error"]["retryable"] is True


def test_abandon_rejects_cross_user_access() -> None:
    adapter, sessions, _, _, _, _ = _adapter()
    _put_session(
        sessions,
        _session_record(
            SESSION_ID, "user_owner", status=SessionStatus.READY, active_microvm_id="mvm-owner"
        ),
    )

    response = adapter(
        _event(
            "POST /sessions/{sessionId}/abandon",
            owner="user_intruder",
            session_id=SESSION_ID,
        )
    )

    assert response["statusCode"] == 403
    assert _body(response)["error"]["code"] == "not_authorized"


def test_abandon_unknown_session_returns_404() -> None:
    adapter, _, _, _, _, _ = _adapter()

    response = adapter(_event("POST /sessions/{sessionId}/abandon", session_id=OTHER_SESSION_ID))

    assert response["statusCode"] == 404
    assert _body(response)["error"]["code"] == "session_not_found"
