from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from dungeon_agent.control_plane.domain.models import SessionId
from dungeon_agent.control_plane.microvms import (
    LambdaMicrovmManager,
    TurnRejectedError,
)
from dungeon_agent.domain.game import (
    AdventurePlan,
    Character,
    Item,
    Location,
    PlayerCharacter,
    StateChanges,
    TurnProposal,
    WorldState,
)
from dungeon_agent.microvm import HttpResult

SESSION_ID: SessionId = "ses_01J00000000000000000000002"
IMAGE_ARN = "arn:aws:lambda:us-east-2:225989371926:microvm-image:dungeon-agent-fastapi"


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        self.value += 0.001
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class FakeMetrics:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def record(self, operation: str, latency_ms: float) -> None:
        assert latency_ms >= 0
        self.operations.append(operation)


class FakeMicrovmClient:
    def __init__(self, states: Sequence[str] = ("RUNNING",)) -> None:
        self.states = list(states)
        self.list_calls: list[dict[str, object]] = []
        self.image_calls: list[str] = []
        self.run_calls: list[dict[str, object]] = []
        self.auth_calls: list[str] = []
        self.terminate_calls: list[str] = []

    def list_microvm_images(self, *, nameFilter: str, maxResults: int) -> Mapping[str, object]:
        self.list_calls.append({"nameFilter": nameFilter, "maxResults": maxResults})
        return {
            "items": [
                {
                    "name": "dungeon-agent-fastapi",
                    "imageArn": IMAGE_ARN,
                    "latestActiveImageVersion": "9.0",
                }
            ]
        }

    def get_microvm_image(self, *, imageIdentifier: str) -> Mapping[str, object]:
        self.image_calls.append(imageIdentifier)
        return {
            "imageArn": IMAGE_ARN,
            "latestActiveImageVersion": "9.0",
        }

    def run_microvm(
        self,
        *,
        imageIdentifier: str,
        imageVersion: str,
        ingressNetworkConnectors: Sequence[str],
        egressNetworkConnectors: Sequence[str],
        idlePolicy: Mapping[str, object],
        maximumDurationInSeconds: int,
        logging: Mapping[str, object],
        clientToken: str,
    ) -> Mapping[str, object]:
        self.run_calls.append(
            {
                "imageIdentifier": imageIdentifier,
                "imageVersion": imageVersion,
                "ingressNetworkConnectors": list(ingressNetworkConnectors),
                "egressNetworkConnectors": list(egressNetworkConnectors),
                "idlePolicy": dict(idlePolicy),
                "maximumDurationInSeconds": maximumDurationInSeconds,
                "logging": dict(logging),
                "clientToken": clientToken,
            }
        )
        return {"microvmId": "mvm-123", "endpoint": "microvm.example"}

    def get_microvm(self, *, microvmIdentifier: str) -> Mapping[str, object]:
        assert microvmIdentifier == "mvm-123"
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {
            "microvmId": microvmIdentifier,
            "state": state,
            "endpoint": "microvm.example",
            "stateReason": "test terminal state",
        }

    def create_microvm_auth_token(
        self,
        *,
        microvmIdentifier: str,
        expirationInMinutes: int,
        allowedPorts: Sequence[Mapping[str, int]],
    ) -> Mapping[str, object]:
        assert expirationInMinutes == 30
        assert list(allowedPorts) == [{"port": 8080}]
        self.auth_calls.append(microvmIdentifier)
        return {"authToken": {"X-aws-proxy-auth": "secret-token"}}

    def terminate_microvm(self, *, microvmIdentifier: str) -> Mapping[str, object]:
        self.terminate_calls.append(microvmIdentifier)
        self.states = ["TERMINATED"]
        return {}


class FakeRequester:
    def __init__(self, world: WorldState) -> None:
        self.world = world
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        endpoint: str,
        token: str,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> HttpResult:
        self.calls.append(
            {
                "endpoint": endpoint,
                "token": token,
                "method": method,
                "path": path,
                "payload": payload,
            }
        )
        return HttpResult(status=200, body=self.world.model_dump(mode="json"), latency_ms=4)


def _adventure() -> AdventurePlan:
    return AdventurePlan(
        title="The Quiet Bell",
        premise="A storm has silenced the village bell before nightfall.",
        objective="Restore the bell before the storm arrives.",
        opening="Rain begins as you reach the locked bell tower.",
        starting_location_id="square",
        locations=[
            Location(
                id="square",
                name="Village Square",
                description="A flooded square below the silent bell tower.",
                exits=["tower", "mill"],
            ),
            Location(
                id="tower",
                name="Bell Tower",
                description="An old tower filled with rusted gears and rope.",
                exits=["square"],
            ),
            Location(
                id="mill",
                name="Old Mill",
                description="A dark mill where spare tools are stored.",
                exits=["square"],
            ),
        ],
        characters=[
            Character(
                id="mara",
                name="Mara",
                description="The worried keeper of the village mill.",
                motivation="Keep the village safe from the storm.",
            )
        ],
        items=[
            Item(id="key", name="Iron Key", description="A heavy key for the bell tower."),
            Item(id="oil", name="Gear Oil", description="A flask of oil for old machinery."),
        ],
        secrets=["Mara hid the key in the mill."],
        max_turns=8,
    )


def _character() -> PlayerCharacter:
    return PlayerCharacter(
        name="Elia Vale",
        pronouns="she/her",
        archetype="Exiled bell keeper",
        appearance="A rain-soaked traveler carrying a coil of old rope.",
        background="Elia left the village after failing to warn it during the last storm.",
        desire="Find her missing brother and restore her reputation.",
        need="Accept help instead of carrying every burden alone.",
        connection_to_adventure="Her family maintained the silent bell for generations.",
        strength="She understands old mechanical systems.",
        flaw="She distrusts anyone who questions her judgment.",
        contradiction="She seeks forgiveness but refuses to discuss her mistake.",
        npc_connection="Mara was her closest friend before the exile.",
        meaningful_item="Her father's worn bell hammer.",
        open_question="Why did her brother enter the tower alone?",
        known_facts=["The tower needs its iron key.", "Mara knows the old machinery."],
        opening_choices=["Inspect the tower.", "Question Mara.", "Search the mill."],
    )


def _world() -> WorldState:
    plan = _adventure()
    return WorldState(
        revision=0,
        language="es",
        plan=plan,
        player_character=_character(),
        location_id=plan.starting_location_id,
        inventory=[],
        health=3,
        facts=[],
        status="active",
    )


def _manager(
    client: FakeMicrovmClient,
    *,
    requester: FakeRequester | None = None,
    metrics: FakeMetrics | None = None,
    image: str = "dungeon-agent-fastapi",
) -> LambdaMicrovmManager:
    clock = FakeClock()
    return LambdaMicrovmManager(
        client,
        image,
        "us-east-2",
        requester=requester or FakeRequester(_world()),
        metrics=metrics,
        timeout_seconds=5,
        poll_interval_seconds=0.1,
        now=lambda: datetime(2026, 7, 18, 22, 0, tzinfo=UTC),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_launch_resolves_latest_active_version_and_waits_until_running() -> None:
    client = FakeMicrovmClient(("PENDING", "RUNNING"))
    metrics = FakeMetrics()

    result = _manager(client, metrics=metrics).launch(SESSION_ID)

    assert result.microvm_id == "mvm-123"
    assert result.ready_at == datetime(2026, 7, 18, 22, 0, tzinfo=UTC)
    assert client.list_calls == [{"nameFilter": "dungeon-agent-fastapi", "maxResults": 50}]
    assert client.image_calls == [IMAGE_ARN]
    assert client.run_calls[0]["imageVersion"] == "9.0"
    assert str(client.run_calls[0]["clientToken"]).startswith(f"{SESSION_ID}-")
    assert metrics.operations == ["image_resolution", "launch", "readiness"]


def test_launch_accepts_an_image_arn_without_listing() -> None:
    client = FakeMicrovmClient()

    _manager(client, image=IMAGE_ARN).launch(SESSION_ID)

    assert client.list_calls == []
    assert client.image_calls == [IMAGE_ARN]


def test_initialize_authenticates_temporarily_and_returns_validated_world() -> None:
    client = FakeMicrovmClient()
    world = _world()
    requester = FakeRequester(world)

    result = _manager(client, requester=requester).initialize(
        "mvm-123", "es", _adventure(), _character()
    )

    assert result == world
    assert client.auth_calls == ["mvm-123"]
    assert requester.calls[0]["endpoint"] == "microvm.example"
    assert requester.calls[0]["token"] == "secret-token"
    assert requester.calls[0]["path"] == "/v1/adventure"


def test_failed_readiness_terminates_the_partial_microvm() -> None:
    client = FakeMicrovmClient(("TERMINATED",))

    with pytest.raises(RuntimeError, match="entered TERMINATED"):
        _manager(client).launch(SESSION_ID)

    assert client.terminate_calls == ["mvm-123"]


def test_terminate_waits_for_the_terminal_state() -> None:
    client = FakeMicrovmClient(("RUNNING",))

    _manager(client).terminate("mvm-123")

    assert client.terminate_calls == ["mvm-123"]


def test_rehydrate_recreates_an_initial_snapshot() -> None:
    client = FakeMicrovmClient()
    world = _world()
    requester = FakeRequester(world)

    result = _manager(client, requester=requester).rehydrate(SESSION_ID, world)

    assert result.microvm_id == "mvm-123"
    assert client.auth_calls == ["mvm-123"]
    assert requester.calls[0]["method"] == "PUT"
    assert requester.calls[0]["path"] == "/v1/state"


def test_rehydrate_restores_an_advanced_snapshot() -> None:
    client = FakeMicrovmClient()
    advanced = _world().model_copy(update={"revision": 1, "facts": ["The key was found."]})
    requester = FakeRequester(advanced)

    result = _manager(client, requester=requester).rehydrate(SESSION_ID, advanced)

    assert result.microvm_id == "mvm-123"
    assert requester.calls[0]["path"] == "/v1/state"
    assert requester.calls[0]["payload"] == advanced.model_dump(mode="json")


def test_apply_turn_returns_the_authoritative_world() -> None:
    client = FakeMicrovmClient()
    world = _world().model_copy(update={"revision": 1})
    requester = FakeRequester(world)

    result = _manager(client, requester=requester).apply_turn(
        "mvm-123", "Open the tower door.", _proposal()
    )

    assert result.revision == 1
    assert client.auth_calls == ["mvm-123"]
    assert requester.calls[0]["method"] == "POST"
    assert requester.calls[0]["path"] == "/v1/turns"


def test_apply_turn_rejection_is_repairable_feedback() -> None:
    class RejectingRequester(FakeRequester):
        def __call__(
            self,
            endpoint: str,
            token: str,
            method: str,
            path: str,
            payload: dict[str, object] | None = None,
        ) -> HttpResult:
            super().__call__(endpoint, token, method, path, payload)
            return HttpResult(status=409, body={"detail": "unknown location"}, latency_ms=4)

    client = FakeMicrovmClient()

    with pytest.raises(TurnRejectedError, match="unknown location"):
        _manager(client, requester=RejectingRequester(_world())).apply_turn(
            "mvm-123", "Teleport home.", _proposal()
        )


def test_is_running_reflects_the_microvm_state() -> None:
    assert _manager(FakeMicrovmClient(("RUNNING",))).is_running("mvm-123") is True
    assert _manager(FakeMicrovmClient(("TERMINATED",))).is_running("mvm-123") is False


def _proposal() -> TurnProposal:
    return TurnProposal(
        intent="Open the locked bell tower door.",
        requires_roll=True,
        difficulty=12,
        success_narration="The iron key turns and the door swings open.",
        failure_narration="The key jams and the noise echoes across the square.",
        success_changes=StateChanges(location_id="tower"),
        failure_changes=StateChanges(add_facts=["The tower door sticks in damp weather."]),
        suggestions=["Try the key again.", "Ask Mara for help.", "Search the mill for oil."],
    )
