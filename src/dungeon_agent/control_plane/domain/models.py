"""Versioned session, event, opening, workflow, and error schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    ErrorCode,
    EventType,
    OpeningBlockKind,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.domain.game import LanguageCode

SessionId = Annotated[str, Field(pattern=r"^ses_[0-9A-HJKMNP-TV-Z]{26}$")]
EventId = Annotated[str, Field(pattern=r"^evt_[0-9A-HJKMNP-TV-Z]{26}$")]
TurnId = Annotated[str, Field(pattern=r"^trn_[0-9A-HJKMNP-TV-Z]{26}$")]
CampaignId = Annotated[str, Field(pattern=r"^cam_[0-9A-HJKMNP-TV-Z]{26}$")]
CorrelationId = Annotated[str, Field(min_length=8, max_length=100)]
OwnerId = Annotated[str, Field(min_length=3, max_length=100)]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=128)]
ArtifactRef = Annotated[str, Field(min_length=3, max_length=2_048)]


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


class CreateSessionCommand(ContractModel):
    schema_version: Literal[1] = 1
    owner_id: OwnerId
    language: LanguageCode
    campaign_id: CampaignId
    campaign_revision: int = Field(ge=0)
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId


class CreateSessionWorkflowInput(ContractModel):
    schema_version: Literal[1] = 1
    session_id: SessionId
    owner_id: OwnerId
    language: LanguageCode
    campaign_id: CampaignId
    campaign_revision: int = Field(ge=0)
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId
    requested_at: datetime

    @model_validator(mode="after")
    def validate_requested_at(self) -> CreateSessionWorkflowInput:
        _require_aware(self.requested_at, "requested_at")
        return self


class CreateCampaignCommand(ContractModel):
    schema_version: Literal[1] = 1
    owner_id: OwnerId
    language: LanguageCode
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId


class CreateCampaignWorkflowInput(ContractModel):
    schema_version: Literal[1] = 1
    campaign_id: CampaignId
    owner_id: OwnerId
    language: LanguageCode
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId
    requested_at: datetime

    @model_validator(mode="after")
    def validate_requested_at(self) -> CreateCampaignWorkflowInput:
        _require_aware(self.requested_at, "requested_at")
        return self


class SubmitTurnCommand(ContractModel):
    schema_version: Literal[1] = 1
    session_id: SessionId
    turn_id: TurnId
    owner_id: OwnerId
    action: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(ge=0)
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId


class SessionRecord(ContractModel):
    schema_version: Literal[1] = 1
    session_id: SessionId
    owner_id: OwnerId
    language: LanguageCode
    status: SessionStatus
    phase: SessionPhase
    revision: int = Field(ge=0)
    last_event_sequence: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    campaign_id: CampaignId | None = None
    campaign_revision: int | None = Field(default=None, ge=0)
    workflow_execution_arn: str | None = Field(default=None, min_length=20, max_length=2_048)
    active_microvm_id: str | None = Field(default=None, min_length=1, max_length=200)
    last_turn_id: TurnId | None = None
    last_action_idempotency_key: IdempotencyKey | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> SessionRecord:
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        expected_phase = {
            SessionStatus.REQUESTED: SessionPhase.REQUESTED,
            SessionStatus.READY: SessionPhase.READY,
            SessionStatus.ACTIVE: SessionPhase.PLAYING,
            SessionStatus.COMPLETED: SessionPhase.COMPLETED,
            SessionStatus.FAILED: SessionPhase.FAILED,
        }.get(self.status)
        if expected_phase is not None and self.phase is not expected_phase:
            raise ValueError(f"status {self.status} requires phase {expected_phase}")
        if (
            self.status in {SessionStatus.READY, SessionStatus.ACTIVE}
            and not self.active_microvm_id
        ):
            raise ValueError("ready or active sessions require an active MicroVM")
        return self


class RoleGenerationMetrics(ContractModel):
    """Recorded once per model role during campaign generation."""

    model_id: str = Field(min_length=1, max_length=200)
    calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    repairs: int = Field(ge=0)


class CampaignGenerationMetrics(ContractModel):
    adventure_architect: RoleGenerationMetrics | None = None
    character_architect: RoleGenerationMetrics | None = None


class CampaignRecord(ContractModel):
    """An immutable, owner-scoped, reusable game template."""

    schema_version: Literal[1] = 1
    campaign_id: CampaignId
    owner_id: OwnerId
    language: LanguageCode
    status: CampaignStatus
    phase: CampaignPhase
    revision: int = Field(ge=0)
    last_event_sequence: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    adventure_ref: ArtifactRef | None = None
    character_ref: ArtifactRef | None = None
    opening_title: str | None = None
    generation: CampaignGenerationMetrics | None = None
    workflow_execution_arn: str | None = Field(default=None, min_length=20, max_length=2_048)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> CampaignRecord:
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        expected_phase = {
            CampaignStatus.REQUESTED: CampaignPhase.REQUESTED,
            CampaignStatus.READY: CampaignPhase.READY,
            CampaignStatus.FAILED: CampaignPhase.FAILED,
        }.get(self.status)
        if expected_phase is not None and self.phase is not expected_phase:
            raise ValueError(f"status {self.status} requires phase {expected_phase}")
        if self.status is CampaignStatus.READY and (
            self.adventure_ref is None or self.character_ref is None
        ):
            raise ValueError("ready campaigns require persisted adventure and character")
        return self


class OpeningBlock(ContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    position: int = Field(ge=0, le=30)
    kind: OpeningBlockKind
    text: str = Field(min_length=2, max_length=1_000)
    narratable: bool = True


class OpeningDocument(ContractModel):
    schema_version: Literal[1] = 1
    language: LanguageCode
    title: str = Field(min_length=3, max_length=100)
    blocks: tuple[OpeningBlock, ...] = Field(min_length=8, max_length=20)

    @model_validator(mode="after")
    def validate_blocks(self) -> OpeningDocument:
        positions = [block.position for block in self.blocks]
        if positions != list(range(len(self.blocks))):
            raise ValueError("opening block positions must be contiguous and ordered")
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise ValueError("opening block ids must be unique")
        kinds = [block.kind for block in self.blocks]
        if kinds.count(OpeningBlockKind.IDENTITY) != 1:
            raise ValueError("opening requires exactly one identity block")
        if kinds.count(OpeningBlockKind.SITUATION) != 1:
            raise ValueError("opening requires exactly one situation block")
        if kinds.count(OpeningBlockKind.KNOWLEDGE) < 2:
            raise ValueError("opening requires at least two knowledge blocks")
        if kinds.count(OpeningBlockKind.POSSIBLE_ACTION) != 3:
            raise ValueError("opening requires exactly three possible actions")
        if not any(block.narratable for block in self.blocks):
            raise ValueError("opening requires narratable content")
        return self


class CreationStartedPayload(ContractModel):
    language: LanguageCode


class PhaseChangedPayload(ContractModel):
    phase: SessionPhase
    elapsed_ms: int = Field(ge=0)


class CreationFailedPayload(ContractModel):
    code: ErrorCode
    retryable: bool


class SessionReadyPayload(ContractModel):
    revision: int = Field(ge=0)
    opening: OpeningDocument


class TurnStartedPayload(ContractModel):
    turn_id: TurnId
    expected_revision: int = Field(ge=0)


class DiceRolledPayload(ContractModel):
    turn_id: TurnId
    roll: int = Field(ge=1, le=20)
    difficulty: int = Field(ge=5, le=20)
    success: bool


class NarrationDeltaPayload(ContractModel):
    turn_id: TurnId
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4_000)


class TurnCompletedPayload(ContractModel):
    turn_id: TurnId
    revision: int = Field(ge=1)
    narration: str = Field(min_length=1, max_length=4_000)


class SessionCompletedPayload(ContractModel):
    outcome: Literal["won", "lost", "abandoned"]
    revision: int = Field(ge=0)


class CampaignCreationStartedPayload(ContractModel):
    language: LanguageCode


class CampaignPhaseChangedPayload(ContractModel):
    phase: CampaignPhase
    elapsed_ms: int = Field(ge=0)


class CampaignCreationFailedPayload(ContractModel):
    code: ErrorCode
    retryable: bool


class CampaignReadyPayload(ContractModel):
    revision: int = Field(ge=0)
    opening: OpeningDocument


CampaignEventPayload = (
    CampaignCreationStartedPayload
    | CampaignPhaseChangedPayload
    | CampaignCreationFailedPayload
    | CampaignReadyPayload
)

_PAYLOAD_BY_CAMPAIGN_EVENT: dict[EventType, type[ContractModel]] = {
    EventType.CAMPAIGN_CREATION_STARTED: CampaignCreationStartedPayload,
    EventType.CAMPAIGN_PHASE_CHANGED: CampaignPhaseChangedPayload,
    EventType.CAMPAIGN_CREATION_FAILED: CampaignCreationFailedPayload,
    EventType.CAMPAIGN_READY: CampaignReadyPayload,
}


class CampaignEvent(ContractModel):
    version: Literal[1] = 1
    event_id: EventId
    campaign_id: CampaignId
    sequence: int = Field(ge=1)
    type: EventType
    occurred_at: datetime
    correlation_id: CorrelationId
    payload: CampaignEventPayload

    @model_validator(mode="after")
    def validate_event(self) -> CampaignEvent:
        _require_aware(self.occurred_at, "occurred_at")
        expected = _PAYLOAD_BY_CAMPAIGN_EVENT.get(self.type)
        if expected is None:
            raise ValueError(f"event {self.type} is not a campaign event")
        if not isinstance(self.payload, expected):
            raise ValueError(f"event {self.type} requires payload {expected.__name__}")
        return self


EventPayload = (
    CreationStartedPayload
    | PhaseChangedPayload
    | CreationFailedPayload
    | SessionReadyPayload
    | TurnStartedPayload
    | DiceRolledPayload
    | NarrationDeltaPayload
    | TurnCompletedPayload
    | SessionCompletedPayload
)

_PAYLOAD_BY_EVENT: dict[EventType, type[ContractModel]] = {
    EventType.SESSION_CREATION_STARTED: CreationStartedPayload,
    EventType.SESSION_PHASE_CHANGED: PhaseChangedPayload,
    EventType.SESSION_CREATION_FAILED: CreationFailedPayload,
    EventType.SESSION_READY: SessionReadyPayload,
    EventType.TURN_STARTED: TurnStartedPayload,
    EventType.DICE_ROLLED: DiceRolledPayload,
    EventType.NARRATION_DELTA: NarrationDeltaPayload,
    EventType.TURN_COMPLETED: TurnCompletedPayload,
    EventType.SESSION_COMPLETED: SessionCompletedPayload,
}


class SessionEvent(ContractModel):
    version: Literal[1] = 1
    event_id: EventId
    session_id: SessionId
    sequence: int = Field(ge=1)
    type: EventType
    occurred_at: datetime
    correlation_id: CorrelationId
    payload: EventPayload

    @model_validator(mode="after")
    def validate_event(self) -> SessionEvent:
        _require_aware(self.occurred_at, "occurred_at")
        expected = _PAYLOAD_BY_EVENT.get(self.type)
        if expected is None:
            raise ValueError(f"event {self.type} is not a session event")
        if not isinstance(self.payload, expected):
            raise ValueError(f"event {self.type} requires payload {expected.__name__}")
        return self


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool
    correlation_id: CorrelationId


class ErrorEnvelope(ContractModel):
    version: Literal[1] = 1
    error: ErrorDetail


class MicrovmLaunchResult(ContractModel):
    microvm_id: str = Field(min_length=1, max_length=200)
    ready_at: datetime

    @model_validator(mode="after")
    def validate_ready_at(self) -> MicrovmLaunchResult:
        _require_aware(self.ready_at, "ready_at")
        return self
