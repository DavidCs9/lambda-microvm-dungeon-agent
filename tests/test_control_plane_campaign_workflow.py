"""End-to-end campaign workflow behavior with in-memory adapters."""

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from dungeon_agent.control_plane.agents.metrics import RoleMetricsCollector
from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    EventType,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    CampaignRecord,
    CreateCampaignCommand,
    OpeningDocument,
)
from dungeon_agent.control_plane.application import DefaultCampaignFactory
from dungeon_agent.control_plane.domain.enums import OpeningBlockKind
from dungeon_agent.control_plane.persistence.memory import InMemoryCampaignRepository
from dungeon_agent.control_plane.steps.adventure import AdventureStep
from dungeon_agent.control_plane.steps.character import CharacterStep
from dungeon_agent.control_plane.workflow.campaigns import DurableCampaignWorkflowStub
from dungeon_agent.control_plane.workflow.sandbox import sandbox_opening
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter
from tests.test_adventure import sample_plan, sample_player

NOW = datetime(2026, 7, 18, 21, 0, tzinfo=UTC)
CAMPAIGN_ID: CampaignId = "cam_01J00000000000000000000000"
WORKFLOW_ARN = (
    "arn:aws:states:us-east-2:123456789012:execution:create-campaign:cam_01J00000000000000000000000"
)


class FakeArchitect:
    """Simulate a model adapter that reports usage like the Bedrock adapter."""

    def __init__(self, adventure: AdventurePlan, metrics: RoleMetricsCollector) -> None:
        self._adventure = adventure
        self._metrics = metrics

    def create(self, language: LanguageCode) -> AdventurePlan:
        self._metrics.record(input_tokens=1_000, output_tokens=400, latency_ms=900.0)
        return self._adventure


class FakeCharacterArchitect:
    def __init__(self, character: PlayerCharacter, metrics: RoleMetricsCollector) -> None:
        self._character = character
        self._metrics = metrics

    def create(self, language: LanguageCode, adventure: AdventurePlan) -> PlayerCharacter:
        self._metrics.record(input_tokens=700, output_tokens=300, latency_ms=600.0)
        self._metrics.record(input_tokens=650, output_tokens=290, latency_ms=550.0)
        return self._character


class MemoryCampaignAdventures:
    def __init__(self) -> None:
        self.saved: dict[str, AdventurePlan] = {}

    def save(self, campaign_id: CampaignId, adventure: AdventurePlan) -> str:
        self.saved[campaign_id] = adventure
        return f"dynamodb://CAMPAIGN#{campaign_id}/ARTIFACT#ADVENTURE"

    def load(self, adventure_ref: str) -> AdventurePlan:
        return self.saved[_campaign_key(adventure_ref)]


class MemoryCampaignCharacters:
    def __init__(self) -> None:
        self.saved: dict[str, tuple[PlayerCharacter, OpeningDocument]] = {}

    def save(
        self,
        campaign_id: CampaignId,
        character: PlayerCharacter,
        opening: OpeningDocument,
    ) -> str:
        self.saved[campaign_id] = (character, opening)
        return f"dynamodb://CAMPAIGN#{campaign_id}/ARTIFACT#CHARACTER"

    def load_character(self, character_ref: str) -> PlayerCharacter:
        return self.saved[_campaign_key(character_ref)][0]

    def load_opening(self, character_ref: str) -> OpeningDocument:
        return self.saved[_campaign_key(character_ref)][1]


def _campaign_key(reference: str) -> str:
    return reference.removeprefix("dynamodb://CAMPAIGN#").split("/ARTIFACT#", maxsplit=1)[0]


def _seed(repository: InMemoryCampaignRepository) -> CampaignRecord:
    command = CreateCampaignCommand(
        owner_id="user_demo",
        language="en",
        idempotency_key="campaign-workflow-001",
        correlation_id="corr-campaign-workflow",
    )
    return repository.create(DefaultCampaignFactory(id_factory=lambda: CAMPAIGN_ID).create(command, NOW), "campaign-workflow-001")


def _initial_state() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "campaignId": CAMPAIGN_ID,
        "ownerId": "user_demo",
        "language": "en",
        "idempotencyKey": "campaign-workflow-001",
        "correlationId": "corr-campaign-workflow",
        "requestedAt": "2026-07-18T21:00:00Z",
    }


def _op(
    operation: str, state: Mapping[str, object], *, phase: str | None = None
) -> dict[str, object]:
    event: dict[str, object] = {
        "operation": operation,
        "state": state,
        "workflowExecutionArn": WORKFLOW_ARN,
        "stateEnteredAt": "2026-07-18T21:00:00Z",
    }
    if phase is not None:
        event["phase"] = phase
    return event


def _stub() -> tuple[
    DurableCampaignWorkflowStub,
    InMemoryCampaignRepository,
    MemoryCampaignCharacters,
    RoleMetricsCollector,
    RoleMetricsCollector,
]:
    repository = InMemoryCampaignRepository()
    _seed(repository)
    adventure_metrics = RoleMetricsCollector()
    character_metrics = RoleMetricsCollector()
    adventures = MemoryCampaignAdventures()
    characters = MemoryCampaignCharacters()
    stub = DurableCampaignWorkflowStub(
        repository,
        repository,
        adventure_step=AdventureStep(FakeArchitect(sample_plan(), adventure_metrics), adventures),
        character_step=CharacterStep(
            FakeCharacterArchitect(sample_player(), character_metrics), adventures, characters
        ),
        openings=characters,
        adventure_metrics=adventure_metrics,
        character_metrics=character_metrics,
        model_id="test-model",
        clock=lambda: NOW,
    )
    return stub, repository, characters, adventure_metrics, character_metrics


def test_campaign_workflow_reaches_ready_with_metrics_and_ordered_events() -> None:
    stub, repository, characters, _, _ = _stub()
    # Warm-instance leakage from an earlier campaign must be reset by the workflow.
    stub._adventure_metrics.record(input_tokens=9, output_tokens=9, latency_ms=9.0)  # noqa: SLF001

    state = _initial_state()
    for event in (
        _op("ValidateCampaign", state),
        _op("CreateCampaignRecord", state),
        _op("EmitCreatingAdventure", state, phase="creating_adventure"),
        _op("GenerateAdventure", state),
        _op("PersistAdventure", state),
        _op("EmitCreatingCharacter", state, phase="creating_character"),
        _op("GenerateCharacter", state),
        _op("PersistCharacter", state),
        _op("MarkCampaignReady", state),
        _op("EmitCampaignReady", state),
    ):
        event["state"] = state
        state = stub.handle(event)

    campaign = repository.get(CAMPAIGN_ID)
    assert campaign is not None
    assert campaign.status is CampaignStatus.READY
    assert campaign.phase is CampaignPhase.READY
    assert campaign.adventure_ref == state["adventureRef"]
    assert campaign.character_ref == state["characterRef"]
    assert campaign.workflow_execution_arn == WORKFLOW_ARN

    generation = campaign.generation
    assert generation is not None
    adventure_metrics = generation.adventure_architect
    character_metrics = generation.character_architect
    assert adventure_metrics is not None
    assert adventure_metrics.model_id == "test-model"
    assert adventure_metrics.calls == 1
    assert adventure_metrics.repairs == 0
    assert character_metrics is not None
    assert character_metrics.calls == 2
    assert character_metrics.repairs == 1
    assert character_metrics.input_tokens == 1_350

    _, opening = characters.saved[CAMPAIGN_ID]
    assert opening.title == "The Storm Bell"

    events = repository.list_after(CAMPAIGN_ID, 0)
    assert [event.type for event in events] == [
        EventType.CAMPAIGN_CREATION_STARTED,
        EventType.CAMPAIGN_PHASE_CHANGED,
        EventType.CAMPAIGN_PHASE_CHANGED,
        EventType.CAMPAIGN_READY,
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    phases = [
        event.payload.phase
        for event in events
        if event.type is EventType.CAMPAIGN_PHASE_CHANGED
    ]
    assert phases == [CampaignPhase.CREATING_ADVENTURE, CampaignPhase.CREATING_CHARACTER]
    ready = events[-1]
    assert ready.type is EventType.CAMPAIGN_READY
    assert ready.payload.opening.title == "The Storm Bell"
    assert any(block.kind is OpeningBlockKind.SITUATION for block in ready.payload.opening.blocks)


def test_campaign_workflow_failure_marks_failed_and_emits_a_recoverable_event() -> None:
    stub, repository, _, _, _ = _stub()
    state = _initial_state()
    for operation in ("ValidateCampaign", "CreateCampaignRecord"):
        state = stub.handle(_op(operation, state))

    state = stub.handle(_op("MarkCampaignFailed", state))
    state = stub.handle(_op("EmitCampaignCreationFailed", state))

    campaign = repository.get(CAMPAIGN_ID)
    assert campaign is not None
    assert campaign.status is CampaignStatus.FAILED
    assert campaign.phase is CampaignPhase.FAILED
    events = repository.list_after(CAMPAIGN_ID, 0)
    assert events[-1].type is EventType.CAMPAIGN_CREATION_FAILED


def test_campaign_workflow_sandbox_mode_uses_deterministic_artifacts() -> None:
    repository = InMemoryCampaignRepository()
    _seed(repository)
    stub = DurableCampaignWorkflowStub(repository, repository, clock=lambda: NOW)

    state = _initial_state()
    for operation in (
        "ValidateCampaign",
        "CreateCampaignRecord",
        "GenerateAdventure",
        "GenerateCharacter",
        "MarkCampaignReady",
        "EmitCampaignReady",
    ):
        state = stub.handle(_op(operation, state))

    campaign = repository.get(CAMPAIGN_ID)
    assert campaign is not None
    assert campaign.status is CampaignStatus.READY
    assert campaign.adventure_ref == "sandbox://adventure"
    assert campaign.character_ref == "sandbox://character"
    events = repository.list_after(CAMPAIGN_ID, 0)
    ready = events[-1]
    assert ready.type is EventType.CAMPAIGN_READY
    assert ready.payload.opening == sandbox_opening("en")
