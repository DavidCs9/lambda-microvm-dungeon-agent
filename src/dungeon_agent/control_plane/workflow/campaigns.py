from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

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
    CampaignGenerationMetrics,
    CampaignId,
    CampaignPhaseChangedPayload,
    CampaignReadyPayload,
    CampaignRecord,
    CreateCampaignWorkflowInput,
    OpeningDocument,
)
from dungeon_agent.control_plane.events import append_campaign_event
from dungeon_agent.control_plane.steps.adventure import AdventureStep
from dungeon_agent.control_plane.steps.character import CharacterStep, CharacterStepInput
from dungeon_agent.control_plane.workflow.sandbox import sandbox_opening
from dungeon_agent.control_plane.workflow.util import parse_time, required_string, wire_time

Clock = Callable[[], datetime]


class DurableCampaignWorkflowStub:
    def __init__(
        self,
        store: Any,
        *,
        adventure_step: AdventureStep | None = None,
        character_step: CharacterStep | None = None,
        openings: Any | None = None,
        adventure_metrics: RoleMetricsCollector | None = None,
        character_metrics: RoleMetricsCollector | None = None,
        model_id: str | None = None,
        delivery: Any | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._adventure_step = adventure_step
        self._character_step = character_step
        self._openings = openings
        self._adventure_metrics = adventure_metrics
        self._character_metrics = character_metrics
        self._model_id = model_id
        self._delivery = delivery
        self._clock = clock or (lambda: datetime.now(UTC))

    def handle(self, event: Mapping[str, object]) -> dict[str, object]:
        operation = required_string(event, "operation")
        raw_state = event.get("state")
        if not isinstance(raw_state, Mapping):
            raise ValueError("workflow state must be an object")
        if operation == "ValidateCampaign":
            CreateCampaignWorkflowInput.model_validate(raw_state)
        state = dict(raw_state)
        now = self._clock()
        workflow_arn = required_string(event, "workflowExecutionArn")
        entered_at = parse_time(required_string(event, "stateEnteredAt"))

        state["workflowExecutionArn"] = workflow_arn
        state["updatedAt"] = wire_time(now)
        timestamps = dict(state.get("taskTimestamps", {}))
        timestamps[operation] = {
            "startedAt": wire_time(entered_at),
            "completedAt": wire_time(now),
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
            append_campaign_event(
                self._store,
                self._delivery,
                campaign.campaign_id,
                EventType.CAMPAIGN_CREATION_STARTED,
                CampaignCreationStartedPayload(language=campaign.language),
                required_string(state, "correlationId"),
                now,
            )

        raw_phase = event.get("phase")
        if isinstance(raw_phase, str):
            phase = CampaignPhase(raw_phase)
            campaign = self._update_campaign(state, phase=phase, workflow_arn=workflow_arn)
            phase_timestamps = dict(state.get("phaseTimestamps", {}))
            phase_timestamps[phase.value] = wire_time(entered_at)
            state["phaseTimestamps"] = phase_timestamps
            state["phase"] = phase.value
            append_campaign_event(
                self._store,
                self._delivery,
                campaign.campaign_id,
                EventType.CAMPAIGN_PHASE_CHANGED,
                CampaignPhaseChangedPayload(
                    phase=phase,
                    elapsed_ms=max(0, int((now - entered_at).total_seconds() * 1_000)),
                ),
                required_string(state, "correlationId"),
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
                        campaign_id=required_string(state, "campaignId"),
                        language=required_string(state, "language"),
                        correlation_id=required_string(state, "correlationId"),
                        adventure_ref=required_string(state, "adventureRef"),
                        adventure_latency_ms=_required_int(state, "adventureLatencyMs"),
                    )
                )
                state["characterRef"] = character_result.character_ref
                state["characterLatencyMs"] = character_result.latency_ms
        elif operation == "MarkCampaignReady":
            current = self._required_campaign(state)
            opening = (
                sandbox_opening(current.language)
                if self._openings is None
                else self._openings.load_opening(required_string(state, "characterRef"))
            )
            campaign = self._update_campaign(
                state,
                status=CampaignStatus.READY,
                phase=CampaignPhase.READY,
                workflow_arn=workflow_arn,
                adventure_ref=required_string(state, "adventureRef"),
                character_ref=required_string(state, "characterRef"),
                generation=self._generation_metrics(),
                opening_title=opening.title,
            )
            state["status"] = campaign.status.value
            state["phase"] = campaign.phase.value
            state["opening"] = opening.model_dump(by_alias=True)
        elif operation == "EmitCampaignReady":
            campaign = self._required_campaign(state)
            opening_payload = state.get("opening")
            opening = (
                OpeningDocument.model_validate(opening_payload)
                if opening_payload is not None
                else (
                    sandbox_opening(campaign.language)
                    if self._openings is None
                    else self._openings.load_opening(required_string(state, "characterRef"))
                )
            )
            append_campaign_event(
                self._store,
                self._delivery,
                campaign.campaign_id,
                EventType.CAMPAIGN_READY,
                CampaignReadyPayload(
                    revision=campaign.revision,
                    opening=opening,
                ),
                required_string(state, "correlationId"),
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
            append_campaign_event(
                self._store,
                self._delivery,
                campaign.campaign_id,
                EventType.CAMPAIGN_CREATION_FAILED,
                CampaignCreationFailedPayload(
                    code=ErrorCode.CAMPAIGN_CREATION_FAILED,
                    retryable=False,
                ),
                required_string(state, "correlationId"),
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
        campaign_id: CampaignId = required_string(state, "campaignId")
        campaign = self._store.get(campaign_id)
        if campaign is None:
            raise ValueError(f"campaign does not exist: {campaign_id}")
        return CampaignRecord.model_validate(campaign)

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
        opening_title: str | None = None,
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
                "opening_title": (
                    opening_title if opening_title is not None else current.opening_title
                ),
                "revision": current.revision + 1,
                "updated_at": self._clock(),
            }
        )
        validated = CampaignRecord.model_validate(updated)
        saved = self._store.save(validated, expected_revision=current.revision)
        return CampaignRecord.model_validate(saved)


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


def _required_int(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return result
