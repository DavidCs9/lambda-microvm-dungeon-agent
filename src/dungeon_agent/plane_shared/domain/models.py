from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from dungeon_agent.domain.game import LanguageCode
from dungeon_agent.plane_shared.domain.base import ContractModel
from dungeon_agent.plane_shared.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    ErrorCode,
    EventType,
    OpeningBlockKind,
    SessionPhase,
    SessionStatus,
)

SessionId = Annotated[str, Field(pattern="^ses_[0-9A-HJKMNP-TV-Z]{26}$")]
EventId = Annotated[str, Field(pattern="^evt_[0-9A-HJKMNP-TV-Z]{26}$")]
TurnId = Annotated[str, Field(pattern="^trn_[0-9A-HJKMNP-TV-Z]{26}$")]
CampaignId = Annotated[str, Field(pattern="^cam_[0-9A-HJKMNP-TV-Z]{26}$")]
CorrelationId = Annotated[str, Field(min_length=8, max_length=100)]
OwnerId = Annotated[str, Field(min_length=3, max_length=100)]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=128)]
ArtifactRef = Annotated[str, Field(min_length=3, max_length=2048)]
_SESSION_PHASE_BY_STATUS = {
    SessionStatus.REQUESTED: SessionPhase.REQUESTED,
    SessionStatus.READY: SessionPhase.READY,
    SessionStatus.ACTIVE: SessionPhase.PLAYING,
    SessionStatus.COMPLETED: SessionPhase.COMPLETED,
    SessionStatus.FAILED: SessionPhase.FAILED,
}
_CAMPAIGN_PHASE_BY_STATUS = {
    CampaignStatus.REQUESTED: CampaignPhase.REQUESTED,
    CampaignStatus.READY: CampaignPhase.READY,
    CampaignStatus.FAILED: CampaignPhase.FAILED,
}


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


def _validate_timestamps(created_at: datetime, updated_at: datetime) -> None:
    _require_aware(created_at, "created_at")
    _require_aware(updated_at, "updated_at")
    if updated_at < created_at:
        raise ValueError("updated_at cannot precede created_at")


def _validate_status_phase(status: object, phase: object, expected: Any) -> None:
    if (expected_phase := expected.get(status)) is not None and phase is not expected_phase:
        raise ValueError(f"status {status} requires phase {expected_phase}")


def _validate_event(
    event_type: EventType,
    payload: object,
    occurred_at: datetime,
    mapping: dict[EventType, type[ContractModel]],
    label: str,
) -> None:
    _require_aware(occurred_at, "occurred_at")
    expected = mapping.get(event_type)
    if expected is None:
        raise ValueError(f"event {event_type} is not a {label} event")
    if not isinstance(payload, expected):
        raise ValueError(f"event {event_type} requires payload {expected.__name__}")


class _WorkflowInput(ContractModel):
    schema_version: Literal[1] = 1
    owner_id: OwnerId
    language: LanguageCode
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId
    requested_at: datetime

    @model_validator(mode="after")
    def validate_requested_at(self) -> _WorkflowInput:
        _require_aware(self.requested_at, "requested_at")
        return self


class CreateSessionWorkflowInput(_WorkflowInput):
    session_id: SessionId
    campaign_id: CampaignId
    campaign_revision: int = Field(ge=0)


class CreateCampaignWorkflowInput(_WorkflowInput):
    campaign_id: CampaignId


class SubmitTurnCommand(ContractModel):
    schema_version: Literal[1] = 1
    session_id: SessionId
    turn_id: TurnId
    owner_id: OwnerId
    action: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(ge=0)
    idempotency_key: IdempotencyKey
    correlation_id: CorrelationId


class _AggregateRecord(ContractModel):
    schema_version: Literal[1] = 1
    owner_id: OwnerId
    language: LanguageCode
    revision: int = Field(ge=0)
    last_event_sequence: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    workflow_execution_arn: str | None = Field(default=None, min_length=20, max_length=2048)

    def _validate_timestamps(self) -> None:
        _validate_timestamps(self.created_at, self.updated_at)


class SessionRecord(_AggregateRecord):
    session_id: SessionId
    status: SessionStatus
    phase: SessionPhase
    campaign_id: CampaignId | None = None
    campaign_revision: int | None = Field(default=None, ge=0)
    active_microvm_id: str | None = Field(default=None, min_length=1, max_length=200)
    last_turn_id: TurnId | None = None
    last_action_idempotency_key: IdempotencyKey | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> SessionRecord:
        self._validate_timestamps()
        _validate_status_phase(self.status, self.phase, _SESSION_PHASE_BY_STATUS)
        if self.status in {SessionStatus.READY, SessionStatus.ACTIVE} and (
            not self.active_microvm_id
        ):
            raise ValueError("ready or active sessions require an active MicroVM")
        return self


class CampaignRecord(_AggregateRecord):
    campaign_id: CampaignId
    status: CampaignStatus
    phase: CampaignPhase
    adventure_ref: ArtifactRef | None = None
    character_ref: ArtifactRef | None = None
    opening_title: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> CampaignRecord:
        self._validate_timestamps()
        _validate_status_phase(self.status, self.phase, _CAMPAIGN_PHASE_BY_STATUS)
        if self.status is CampaignStatus.READY and (
            not (self.adventure_ref and self.character_ref)
        ):
            raise ValueError("ready campaigns require persisted adventure and character")
        return self


class OpeningBlock(ContractModel):
    id: str = Field(pattern="^[a-z][a-z0-9_]{1,39}$")
    position: int = Field(ge=0, le=30)
    kind: OpeningBlockKind
    text: str = Field(min_length=2, max_length=1000)
    narratable: bool = True


class OpeningDocument(ContractModel):
    schema_version: Literal[1] = 1
    language: LanguageCode
    title: str = Field(min_length=3, max_length=100)
    blocks: tuple[OpeningBlock, ...] = Field(min_length=8, max_length=20)

    @model_validator(mode="after")
    def validate_blocks(self) -> OpeningDocument:
        if [block.position for block in self.blocks] != list(range(len(self.blocks))):
            raise ValueError("opening block positions must be contiguous and ordered")
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise ValueError("opening block ids must be unique")
        counts = {
            kind: sum(block.kind is kind for block in self.blocks) for kind in OpeningBlockKind
        }
        required = {
            OpeningBlockKind.IDENTITY: 1,
            OpeningBlockKind.MOTIVATION: 1,
            OpeningBlockKind.SITUATION: 1,
            OpeningBlockKind.POSSIBLE_ACTION: 3,
        }
        for kind, expected in required.items():
            if counts[kind] != expected:
                raise ValueError(f"opening requires {expected} {kind.value} block(s)")
        if counts[OpeningBlockKind.KNOWLEDGE] < 2:
            raise ValueError("opening requires at least two knowledge blocks")
        if not any(block.narratable for block in self.blocks):
            raise ValueError("opening requires narratable content")
        return self


class CreationStartedPayload(ContractModel):
    language: LanguageCode


class PhaseChangedPayload(ContractModel):
    phase: SessionPhase | CampaignPhase
    elapsed_ms: int = Field(ge=0)
    revision: int | None = Field(default=None, ge=0)


class CreationFailedPayload(ContractModel):
    code: ErrorCode
    retryable: bool


class ReadyPayload(ContractModel):
    revision: int = Field(ge=0)
    opening: OpeningDocument


SessionReadyPayload = ReadyPayload


class TurnStartedPayload(ContractModel):
    turn_id: TurnId
    expected_revision: int = Field(ge=0)
    action: str | None = Field(default=None, min_length=1, max_length=500)


class DiceRolledPayload(ContractModel):
    turn_id: TurnId
    roll: int = Field(ge=1, le=20)
    difficulty: int = Field(ge=5, le=20)
    success: bool


class NarrationDeltaPayload(ContractModel):
    turn_id: TurnId
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4000)


class TurnCompletedPayload(ContractModel):
    turn_id: TurnId
    revision: int = Field(ge=1)
    narration: str = Field(min_length=1, max_length=4000)
    action: str | None = Field(default=None, min_length=1, max_length=500)


class SessionCompletedPayload(ContractModel):
    outcome: Literal["won", "lost", "abandoned"]
    revision: int = Field(ge=0)


CampaignCreationStartedPayload = CreationStartedPayload
CampaignPhaseChangedPayload = PhaseChangedPayload
CampaignCreationFailedPayload = CreationFailedPayload
CampaignReadyPayload = ReadyPayload
CampaignEventPayload = (
    CreationStartedPayload | PhaseChangedPayload | CreationFailedPayload | ReadyPayload
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
        _validate_event(
            self.type, self.payload, self.occurred_at, _PAYLOAD_BY_CAMPAIGN_EVENT, "campaign"
        )
        return self


EventPayload = (
    CreationStartedPayload
    | PhaseChangedPayload
    | CreationFailedPayload
    | ReadyPayload
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
        _validate_event(self.type, self.payload, self.occurred_at, _PAYLOAD_BY_EVENT, "session")
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
