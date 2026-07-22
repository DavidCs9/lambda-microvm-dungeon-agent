from __future__ import annotations

from datetime import UTC, datetime

from dungeon_agent.control_plane.domain.enums import EventType, SessionPhase, SessionStatus
from dungeon_agent.control_plane.domain.models import (
    MicrovmLaunchResult,
    SessionId,
    SessionRecord,
    SubmitTurnCommand,
    TurnId,
)
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    HttpResult,
    SubmitActionRequest,
)
from dungeon_agent.control_plane.http.sessions import SessionHttpHandlers
from dungeon_agent.control_plane.identifiers import new_turn_id
from dungeon_agent.control_plane.persistence.memory import (
    InMemoryCampaignRepository,
    InMemoryControlPlaneRepository,
)
from dungeon_agent.control_plane.turns import TurnWorker
from dungeon_agent.domain.game import (
    AdventurePlan,
    LanguageCode,
    PlayerCharacter,
    TurnProposal,
    TurnResult,
    WorldState,
)
from tests.test_adventure import proposal, sample_plan, sample_player

NOW = datetime(2026, 7, 18, 23, 0, tzinfo=UTC)
SESSION_ID: SessionId = "ses_01J00000000000000000000009"
OWNER = "player-1"
KEY = "action-key-0001"


class FakeInvoker:
    def __init__(self) -> None:
        self.commands: list[SubmitTurnCommand] = []

    def invoke_turn(self, command: SubmitTurnCommand) -> None:
        self.commands.append(command)


class FakeAgent:
    def __init__(self, output: TurnProposal) -> None:
        self.output = output

    def invoke(self, *, output_model: type[TurnProposal], **kwargs: object) -> TurnProposal:
        return output_model.model_validate(self.output.model_dump(mode="python"))


class FakeMicrovms:
    def __init__(self, world: WorldState, *, running: bool = True) -> None:
        self.world = world
        self.running = running
        self.apply_calls = 0
        self.rehydrate_calls = 0
        self.terminated: list[str] = []

    def launch(self, session_id: SessionId) -> MicrovmLaunchResult:
        raise AssertionError("not used in turn tests")

    def initialize(
        self,
        microvm_id: str,
        language: LanguageCode,
        adventure: AdventurePlan,
        character: PlayerCharacter,
    ) -> WorldState:
        raise AssertionError("not used in turn tests")

    def apply_turn(self, microvm_id: str, action: str, turn_proposal: TurnProposal) -> WorldState:
        self.apply_calls += 1
        return self.world

    def is_running(self, microvm_id: str) -> bool:
        return self.running

    def rehydrate(self, session_id: SessionId, state: WorldState) -> MicrovmLaunchResult:
        self.rehydrate_calls += 1
        self.running = True
        return MicrovmLaunchResult(microvm_id="mvm-2", ready_at=NOW)

    def terminate(self, microvm_id: str) -> None:
        self.terminated.append(microvm_id)


class FakeSnapshots:
    def __init__(self, world: WorldState) -> None:
        self.world = world
        self.saved: list[WorldState] = []

    def save(self, session_id: SessionId, world: WorldState) -> None:
        self.saved.append(world)

    def load(self, session_id: SessionId) -> WorldState:
        return self.world


class FakeWorkflows:
    def start_create_session(self, workflow_input: object) -> str:
        raise AssertionError("not used in turn tests")

    def start_create_campaign(self, workflow_input: object) -> str:
        raise AssertionError("not used in turn tests")


def _session(status: SessionStatus, phase: SessionPhase, revision: int = 3) -> SessionRecord:
    return SessionRecord(
        session_id=SESSION_ID,
        owner_id=OWNER,
        language="en",
        status=status,
        phase=phase,
        revision=revision,
        last_event_sequence=0,
        created_at=NOW,
        updated_at=NOW,
        active_microvm_id="mvm-1",
    )


def _repository() -> InMemoryControlPlaneRepository:
    repository = InMemoryControlPlaneRepository()
    repository.create(_session(SessionStatus.READY, SessionPhase.READY), "create-key-0001")
    return repository


def _handlers(
    repository: InMemoryControlPlaneRepository, invoker: FakeInvoker
) -> SessionHttpHandlers:
    return SessionHttpHandlers(
        repository,
        FakeWorkflows(),
        InMemoryCampaignRepository(),
        turns=invoker,
        clock=lambda: NOW,
    )


def _submit(handlers: SessionHttpHandlers, revision: int = 3, key: str = KEY) -> HttpResult:
    return handlers.submit_action(
        AuthenticatedIdentity(owner_id=OWNER),
        SESSION_ID,
        SubmitActionRequest(action="I open the tower door.", expected_revision=revision),
        idempotency_key=key,
        correlation_id="corr-turn-test",
    )


def _turn_world() -> WorldState:
    return WorldState(
        revision=1,
        language="en",
        plan=sample_plan(),
        player_character=sample_player(),
        location_id="tower",
        inventory=["key"],
        health=3,
        facts=["The door is open."],
        status="active",
        last_result=TurnResult(
            action="I open the tower door.",
            intent="Open the tower door.",
            success=True,
            narration="The key turns and the door swings open.",
            roll=14,
            difficulty=12,
            suggestions=["Enter the tower.", "Call out.", "Light a torch."],
        ),
    )


def _worker_command(turn_id: TurnId) -> SubmitTurnCommand:
    return SubmitTurnCommand(
        session_id=SESSION_ID,
        turn_id=turn_id,
        owner_id=OWNER,
        action="I open the tower door.",
        expected_revision=4,
        idempotency_key=KEY,
        correlation_id="corr-turn-test",
    )


def test_submit_action_checks_out_the_session_and_invokes_the_worker() -> None:
    repository = _repository()
    invoker = FakeInvoker()

    result = _submit(_handlers(repository, invoker))

    assert result.status_code == 202
    session = repository.get(SESSION_ID)
    assert session is not None
    assert session.status is SessionStatus.ACTIVE
    assert session.last_turn_id is not None
    assert len(invoker.commands) == 1
    events = repository.list_after(SESSION_ID, 0)
    assert [event.type for event in events] == [EventType.TURN_STARTED]


def test_submit_action_duplicate_key_returns_the_same_turn() -> None:
    repository = _repository()
    invoker = FakeInvoker()
    handlers = _handlers(repository, invoker)

    first = _submit(handlers)
    # The first turn is still in progress; a retry must not start another one.
    second = _submit(handlers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.body.model_dump()["status"] == "duplicate"
    assert second.body.model_dump()["turnId"] == first.body.model_dump()["turnId"]
    assert len(invoker.commands) == 1


def test_submit_action_rejects_stale_revision_and_busy_sessions() -> None:
    repository = _repository()
    handlers = _handlers(repository, FakeInvoker())

    stale = _submit(handlers, revision=1)
    assert stale.status_code == 409

    _submit(handlers)
    busy = _submit(handlers, revision=4, key="action-key-0002")
    assert busy.status_code == 409


def test_worker_applies_the_turn_and_emits_authoritative_events() -> None:
    repository = InMemoryControlPlaneRepository()
    turn_id = new_turn_id()
    repository.create(
        _session(SessionStatus.ACTIVE, SessionPhase.PLAYING, revision=4).model_copy(
            update={"last_turn_id": turn_id, "last_action_idempotency_key": KEY}
        ),
        "create-key-0001",
    )
    snapshots = FakeSnapshots(_turn_world().model_copy(update={"revision": 0}))
    microvms = FakeMicrovms(_turn_world())
    worker = TurnWorker(
        repository,
        snapshots,
        FakeAgent(proposal()),
        microvms,
        clock=lambda: NOW,
    )

    outcome = worker.handle(_worker_command(turn_id).model_dump(mode="json", by_alias=True))

    assert outcome["status"] == "completed"
    session = repository.get(SESSION_ID)
    assert session is not None and session.status is SessionStatus.READY
    assert [event.type for event in repository.list_after(SESSION_ID, 0)] == [
        EventType.DICE_ROLLED,
        EventType.TURN_COMPLETED,
    ]
    assert snapshots.saved[0].revision == 1
    assert microvms.apply_calls == 1


def test_worker_skips_a_duplicate_async_delivery() -> None:
    repository = _repository()  # READY, no matching checkout
    worker = TurnWorker(
        repository,
        FakeSnapshots(_turn_world()),
        FakeAgent(proposal()),
        FakeMicrovms(_turn_world()),
        clock=lambda: NOW,
    )

    assert (
        worker.handle(_worker_command(new_turn_id()).model_dump(mode="json", by_alias=True))[
            "status"
        ]
        == "skipped"
    )


def test_worker_failure_returns_the_session_to_ready() -> None:
    repository = InMemoryControlPlaneRepository()
    turn_id = new_turn_id()
    repository.create(
        _session(SessionStatus.ACTIVE, SessionPhase.PLAYING, revision=4).model_copy(
            update={"last_turn_id": turn_id, "last_action_idempotency_key": KEY}
        ),
        "create-key-0001",
    )

    class BrokenSnapshots(FakeSnapshots):
        def load(self, session_id: SessionId) -> WorldState:
            raise LookupError("missing snapshot")

    worker = TurnWorker(
        repository,
        BrokenSnapshots(_turn_world()),
        FakeAgent(proposal()),
        FakeMicrovms(_turn_world()),
        clock=lambda: NOW,
    )

    assert (
        worker.handle(_worker_command(turn_id).model_dump(mode="json", by_alias=True))["status"]
        == "failed"
    )
    session = repository.get(SESSION_ID)
    assert session is not None and session.status is SessionStatus.READY
