"""Durable campaign workflow tasks backed by the campaign repositories."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from dungeon_agent.control_plane.agents.metrics import RoleMetricsCollector
from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    ErrorCode,
    EventType,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignCreationFailedPayload,
    CampaignCreationStartedPayload,
    CampaignEvent,
    CampaignGenerationMetrics,
    CampaignId,
    CampaignPhaseChangedPayload,
    CampaignReadyPayload,
    CampaignRecord,
    CreateCampaignWorkflowInput,
    OpeningDocument,
)
from dungeon_agent.control_plane.domain.ports import (
    CampaignEventDeliveryPort,
    CampaignEventRepository,
    CampaignRepository,
)
from dungeon_agent.control_plane.identifiers import new_event_id
from dungeon_agent.control_plane.steps.adventure import AdventureStep
from dungeon_agent.control_plane.steps.character import CharacterStep, CharacterStepInput
from dungeon_agent.control_plane.workflow.sandbox import sandbox_opening
from dungeon_agent.domain.game import LanguageCode

Clock = Callable[[], datetime]


class CampaignOpeningLoader(Protocol):
    def load_opening(self, character_ref: str) -> OpeningDocument: ...


class DurableCampaignWorkflowStub:
    """Generate a world and protagonist once, with no MicroVM involvement."""

    def __init__(
        self,
        campaigns: CampaignRepository,
        events: CampaignEventRepository,
        *,
        adventure_step: AdventureStep | None = None,
        character_step: CharacterStep | None = None,
        openings: CampaignOpeningLoader | None = None,
        adventure_metrics: RoleMetricsCollector | None = None,
        character_metrics: RoleMetricsCollector | None = None,
        model_id: str | None = None,
        delivery: CampaignEventDeliveryPort | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._campaigns = campaigns
        self._events = events
        self._adventure_step = adventure_step
        self._character_step = character_step
        self._openings = openings
        self._adventure_metrics = adventure_metrics
        self._character_metrics = character_metrics
        self._model_id = model_id
        self._delivery = delivery
        self._clock = clock or (lambda: datetime.now(UTC))

    def handle(self, event: Mapping[str, object]) -> dict[str, object]:
        operation = _required_string(event, "operation")
        raw_state = event.get("state")
        if not isinstance(raw_state, Mapping):
            raise ValueError("workflow state must be an object")
        if operation == "ValidateCampaign":
            CreateCampaignWorkflowInput.model_validate(raw_state)
        state = dict(raw_state)
        now = self._clock()
        workflow_arn = _required_string(event, "workflowExecutionArn")
        entered_at = _parse_time(_required_string(event, "stateEnteredAt"))

        state["workflowExecutionArn"] = workflow_arn
        state["updatedAt"] = _wire_time(now)
        timestamps = dict(state.get("taskTimestamps", {}))
        timestamps[operation] = {
            "startedAt": _wire_time(entered_at),
            "completedAt": _wire_time(now),
        }
        state["taskTimestamps"] = timestamps

        if operation == "CreateCampaignRecord":
            if self._adventure_metrics is not None:
                self._adventure_metrics.reset()
            if self._character_metrics is not None:
                self._character_metrics.reset()
            campaign = self._update_campaign(
                state,
                status=CampaignStatus.CREATING,
                workflow_arn=workflow_arn,
            )
            self._append_event(
                campaign,
                state,
                EventType.CAMPAIGN_CREATION_STARTED,
                CampaignCreationStartedPayload(language=campaign.language),
                now,
            )

        raw_phase = event.get("phase")
        if isinstance(raw_phase, str):
            phase = CampaignPhase(raw_phase)
            campaign = self._update_campaign(state, phase=phase, workflow_arn=workflow_arn)
            phase_timestamps = dict(state.get("phaseTimestamps", {}))
            phase_timestamps[phase.value] = _wire_time(entered_at)
            state["phaseTimestamps"] = phase_timestamps
            state["phase"] = phase.value
            self._append_event(
                campaign,
                state,
                EventType.CAMPAIGN_PHASE_CHANGED,
                CampaignPhaseChangedPayload(
                    phase=phase,
                    elapsed_ms=max(0, int((now - entered_at).total_seconds() * 1_000)),
                ),
                now,
            )

        if operation == "GenerateAdventure":
            if self._adventure_step is None:
                state["adventureRef"] = "sandbox://adventure"
            else:
                adventure_result = self._adventure_step.execute(_workflow_input(state))
                state["adventureRef"] = adventure_result.adventure_ref
                state["adventureLatencyMs"] = adventure_result.latency_ms
        elif operation == "GenerateCharacter":
            if self._character_step is None:
                state["characterRef"] = "sandbox://character"
            else:
                character_result = self._character_step.execute(
                    CharacterStepInput(
                        campaign_id=_required_string(state, "campaignId"),
                        language=_required_string(state, "language"),
                        correlation_id=_required_string(state, "correlationId"),
                        adventure_ref=_required_string(state, "adventureRef"),
                        adventure_latency_ms=_required_int(state, "adventureLatencyMs"),
                    )
                )
                state["characterRef"] = character_result.character_ref
                state["characterLatencyMs"] = character_result.latency_ms
        elif operation == "MarkCampaignReady":
            campaign = self._update_campaign(
                state,
                status=CampaignStatus.READY,
                phase=CampaignPhase.READY,
                workflow_arn=workflow_arn,
                adventure_ref=_required_string(state, "adventureRef"),
                character_ref=_required_string(state, "characterRef"),
                generation=self._generation_metrics(),
            )
            state["status"] = campaign.status.value
            state["phase"] = campaign.phase.value
        elif operation == "EmitCampaignReady":
            campaign = self._required_campaign(state)
            opening = (
                sandbox_opening(campaign.language)
                if self._openings is None
                else self._openings.load_opening(_required_string(state, "characterRef"))
            )
            self._append_event(
                campaign,
                state,
                EventType.CAMPAIGN_READY,
                CampaignReadyPayload(
                    revision=campaign.revision,
                    opening=opening,
                ),
                now,
            )
        elif operation == "MarkCampaignFailed":
            campaign = self._update_campaign(
                state,
                status=CampaignStatus.FAILED,
                phase=CampaignPhase.FAILED,
                workflow_arn=workflow_arn,
            )
            state["status"] = campaign.status.value
            state["phase"] = campaign.phase.value
        elif operation == "EmitCampaignCreationFailed":
            campaign = self._required_campaign(state)
            self._append_event(
                campaign,
                state,
                EventType.CAMPAIGN_CREATION_FAILED,
                CampaignCreationFailedPayload(
                    code=ErrorCode.CAMPAIGN_CREATION_FAILED,
                    retryable=False,
                ),
                now,
            )
        return state

    def _generation_metrics(self) -> CampaignGenerationMetrics | None:
        if self._adventure_metrics is None or self._model_id is None:
            return None
        return CampaignGenerationMetrics(
            adventure_architect=self._adventure_metrics.snapshot(self._model_id),
            character_architect=(
                self._character_metrics.snapshot(self._model_id)
                if self._character_metrics is not None
                else None
            ),
        )

    def _required_campaign(self, state: Mapping[str, object]) -> CampaignRecord:
        campaign_id: CampaignId = _required_string(state, "campaignId")
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            raise ValueError(f"campaign does not exist: {campaign_id}")
        return campaign

    def _update_campaign(
        self,
        state: Mapping[str, object],
        *,
        status: CampaignStatus | None = None,
        phase: CampaignPhase | None = None,
        workflow_arn: str,
        adventure_ref: str | None = None,
        character_ref: str | None = None,
        generation: CampaignGenerationMetrics | None = None,
    ) -> CampaignRecord:
        current = self._required_campaign(state)
        updated = current.model_copy(
            update={
                "status": status or current.status,
                "phase": phase or current.phase,
                "workflow_execution_arn": workflow_arn,
                "adventure_ref": adventure_ref or current.adventure_ref,
                "character_ref": character_ref or current.character_ref,
                "generation": generation or current.generation,
                "revision": current.revision + 1,
                "updated_at": self._clock(),
            }
        )
        validated = CampaignRecord.model_validate(updated)
        return self._campaigns.save(validated, expected_revision=current.revision)

    def _append_event(
        self,
        campaign: CampaignRecord,
        state: Mapping[str, object],
        event_type: EventType,
        payload: CampaignCreationStartedPayload
        | CampaignPhaseChangedPayload
        | CampaignReadyPayload
        | CampaignCreationFailedPayload,
        now: datetime,
    ) -> None:
        current = self._campaigns.get(campaign.campaign_id)
        if current is None:
            raise ValueError(f"campaign does not exist: {campaign.campaign_id}")
        event = CampaignEvent(
            event_id=new_event_id(),
            campaign_id=campaign.campaign_id,
            sequence=current.last_event_sequence + 1,
            type=event_type,
            occurred_at=now,
            correlation_id=_required_string(state, "correlationId"),
            payload=payload,
        )
        self._events.append(event, expected_previous_sequence=current.last_event_sequence)
        if self._delivery is not None:
            try:
                self._delivery.deliver_campaign(current.owner_id, event)
            except Exception as delivery_error:
                print(f"event delivery failed: {type(delivery_error).__name__}")


def _workflow_input(state: Mapping[str, object]) -> CreateCampaignWorkflowInput:
    return CreateCampaignWorkflowInput.model_validate(
        {
            "schemaVersion": state.get("schemaVersion", 1),
            "campaignId": state.get("campaignId"),
            "ownerId": state.get("ownerId"),
            "language": state.get("language"),
            "idempotencyKey": state.get("idempotencyKey"),
            "correlationId": state.get("correlationId"),
            "requestedAt": state.get("requestedAt"),
        }
    )


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{key} must be a non-empty string")
    return result


def _required_int(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return result


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("workflow timestamps must include a timezone")
    return parsed


def _wire_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
