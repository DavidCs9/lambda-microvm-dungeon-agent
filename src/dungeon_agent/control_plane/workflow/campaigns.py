import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from dungeon_agent.control_plane.agents.roles import campaign_theme_seed
from dungeon_agent.control_plane.workflow.runner import (
    elapsed_ms,
    mark_phase,
    prepare_run,
    required_record,
    update_record,
)
from dungeon_agent.control_plane.workflow.util import required_string
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter
from dungeon_agent.plane_shared.agents.bedrock import InvocationMetrics
from dungeon_agent.plane_shared.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    ErrorCode,
    EventType,
)
from dungeon_agent.plane_shared.domain.models import (
    ArtifactRef,
    CampaignCreationFailedPayload,
    CampaignCreationStartedPayload,
    CampaignGenerationMetrics,
    CampaignId,
    CampaignPhaseChangedPayload,
    CampaignReadyPayload,
    CampaignRecord,
    CreateCampaignWorkflowInput,
    OpeningDocument,
    RoleGenerationMetrics,
)
from dungeon_agent.plane_shared.events import append_campaign_event

Clock = Callable[[], datetime]


class DurableCampaignWorkflowStub:
    def __init__(
        self,
        store: Any,
        *,
        adventure_architect: Any | None = None,
        character_architect: Any | None = None,
        adventures: Any | None = None,
        characters: Any | None = None,
        openings: Any | None = None,
        portrait_generator: Any | None = None,
        portrait_store: Any | None = None,
        delivery: Any | None = None,
        clock: Clock | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._store = store
        self._adventure_architect, self._character_architect = (
            adventure_architect,
            character_architect,
        )
        self._adventures, self._characters, self._openings = adventures, characters, openings
        self._portrait_generator, self._portrait_store = portrait_generator, portrait_store
        self._delivery = delivery
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic

    def handle(self, event: Mapping[str, object]) -> dict[str, object]:
        validate = (
            CreateCampaignWorkflowInput.model_validate
            if event.get("operation") == "ValidateCampaign"
            else None
        )
        run = prepare_run(event, self._clock, validate=validate)
        operation, state, now, workflow_arn, entered_at = (
            run.operation,
            run.state,
            run.now,
            run.workflow_arn,
            run.entered_at,
        )
        if operation == "CreateCampaignRecord":
            campaign = self._update_campaign(
                state, status=CampaignStatus.CREATING, workflow_arn=workflow_arn
            )
            started_payload = CampaignCreationStartedPayload(language=campaign.language)
            self._emit(
                campaign.campaign_id,
                EventType.CAMPAIGN_CREATION_STARTED,
                started_payload,
                state,
                now,
            )
        raw_phase = event.get("phase")
        if isinstance(raw_phase, str):
            phase = CampaignPhase(raw_phase)
            campaign = self._update_campaign(state, phase=phase, workflow_arn=workflow_arn)
            mark_phase(state, phase, entered_at)
            phase_payload = CampaignPhaseChangedPayload(
                phase=phase, elapsed_ms=elapsed_ms(now, entered_at)
            )
            self._emit(
                campaign.campaign_id, EventType.CAMPAIGN_PHASE_CHANGED, phase_payload, state, now
            )
        if operation == "GenerateAdventure":
            adventure_ref, latency_ms, generation = self._generate_adventure(_workflow_input(state))
            state["adventureRef"] = adventure_ref
            state["adventureLatencyMs"] = latency_ms
            state["adventureGeneration"] = generation
        elif operation == "GenerateCharacter":
            character_ref, latency_ms, generation = self._generate_character(
                campaign_id=required_string(state, "campaignId"),
                language=cast(LanguageCode, required_string(state, "language")),
                adventure_ref=required_string(state, "adventureRef"),
            )
            state["characterRef"] = character_ref
            state["characterLatencyMs"] = latency_ms
            state["characterGeneration"] = generation
        elif operation == "MarkCampaignReady":
            opening = self._load_opening(required_string(state, "characterRef"))
            campaign = self._update_campaign(
                state,
                status=CampaignStatus.READY,
                phase=CampaignPhase.READY,
                workflow_arn=workflow_arn,
                adventure_ref=required_string(state, "adventureRef"),
                character_ref=required_string(state, "characterRef"),
                opening_title=opening.title,
                generation=_campaign_generation_metrics(state),
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
                else self._load_opening(required_string(state, "characterRef"))
            )
            ready_payload = CampaignReadyPayload(revision=campaign.revision, opening=opening)
            self._emit(campaign.campaign_id, EventType.CAMPAIGN_READY, ready_payload, state, now)
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
            failed_payload = CampaignCreationFailedPayload(
                code=ErrorCode.CAMPAIGN_CREATION_FAILED, retryable=False
            )
            self._emit(
                campaign.campaign_id, EventType.CAMPAIGN_CREATION_FAILED, failed_payload, state, now
            )
        return state

    def _generate_adventure(
        self, workflow_input: CreateCampaignWorkflowInput
    ) -> tuple[str, int, dict[str, object]]:
        if self._adventure_architect is None or self._adventures is None:
            raise RuntimeError("campaign adventure generation is not configured")
        started = self._monotonic()
        metrics = InvocationMetrics()
        generated = self._adventure_architect.create(
            workflow_input.language,
            theme_seed=campaign_theme_seed(str(workflow_input.campaign_id)),
            campaign_id=str(workflow_input.campaign_id),
            metrics=metrics,
        )
        adventure = AdventurePlan.model_validate(generated.model_dump(mode="python"))
        adventure_ref = self._adventures.save_adventure(workflow_input.campaign_id, adventure)
        return (
            str(adventure_ref),
            _elapsed_ms(self._monotonic, started),
            _metrics_payload(metrics),
        )

    def _generate_character(
        self, *, campaign_id: CampaignId, language: LanguageCode, adventure_ref: ArtifactRef
    ) -> tuple[str, int, dict[str, object]]:
        if (
            self._character_architect is None
            or self._adventures is None
            or self._characters is None
        ):
            raise RuntimeError("campaign character generation is not configured")
        started = self._monotonic()
        metrics = InvocationMetrics()
        adventure = AdventurePlan.model_validate(
            self._adventures.load_adventure(adventure_ref).model_dump(mode="python")
        )
        generated = self._character_architect.create(
            language, adventure, campaign_id=str(campaign_id), metrics=metrics
        )
        character = PlayerCharacter.model_validate(generated.model_dump(mode="python"))
        opening = build_opening(language, adventure, character)
        character_ref = self._characters.save_character(
            campaign_id,
            character,
            opening,
            portrait_key=self._try_generate_portrait(campaign_id, character),
        )
        return (
            str(character_ref),
            _elapsed_ms(self._monotonic, started),
            _metrics_payload(metrics),
        )

    def _try_generate_portrait(
        self, campaign_id: CampaignId, character: PlayerCharacter
    ) -> str | None:
        if self._portrait_generator is None or self._portrait_store is None:
            return None
        try:
            image = self._portrait_generator.generate(character)
            return cast(str, self._portrait_store.save(campaign_id, image))
        except Exception:
            from dungeon_agent.plane_shared.logging import logger

            logger.exception("portrait_generation_failed", campaign_id=campaign_id)
            return None

    def _load_opening(self, character_ref: str) -> OpeningDocument:
        if self._openings is None:
            raise RuntimeError("campaign opening storage is not configured")
        return OpeningDocument.model_validate(self._openings.load_opening(character_ref))

    def _required_campaign(self, state: Mapping[str, object]) -> CampaignRecord:
        return required_record(self._store, state, CampaignRecord, "campaignId", "campaign")

    def _emit(
        self,
        campaign_id: CampaignId,
        event_type: EventType,
        payload: Any,
        state: Mapping[str, object],
        now: datetime,
    ) -> None:
        append_campaign_event(
            self._store,
            self._delivery,
            campaign_id,
            event_type,
            payload,
            required_string(state, "correlationId"),
            now,
        )

    def _update_campaign(
        self,
        state: Mapping[str, object],
        *,
        status: CampaignStatus | None = None,
        phase: CampaignPhase | None = None,
        workflow_arn: str,
        adventure_ref: str | None = None,
        character_ref: str | None = None,
        opening_title: str | None = None,
        generation: CampaignGenerationMetrics | None = None,
    ) -> CampaignRecord:
        return update_record(
            self._store,
            state,
            CampaignRecord,
            "campaignId",
            "campaign",
            self._clock,
            workflow_arn,
            status=status,
            phase=phase,
            adventure_ref=adventure_ref,
            character_ref=character_ref,
            opening_title=opening_title,
            generation=generation,
        )


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


def _elapsed_ms(monotonic: Callable[[], float], started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))


def _metrics_payload(metrics: InvocationMetrics) -> dict[str, object]:
    return {
        "modelId": metrics.model_id,
        "calls": metrics.calls,
        "inputTokens": metrics.input_tokens,
        "outputTokens": metrics.output_tokens,
        "latencyMs": metrics.latency_ms,
        "repairs": metrics.repairs,
    }


def _campaign_generation_metrics(state: Mapping[str, object]) -> CampaignGenerationMetrics | None:
    def role_metrics(key: str) -> RoleGenerationMetrics | None:
        value = state.get(key)
        if not isinstance(value, Mapping) or not value.get("modelId"):
            return None
        return RoleGenerationMetrics.model_validate(value)

    adventure = role_metrics("adventureGeneration")
    character = role_metrics("characterGeneration")
    if adventure is None and character is None:
        return None
    return CampaignGenerationMetrics(
        adventure_architect=adventure,
        character_architect=character,
    )


# Spanish display labels for the five character stats (order is stable for the UI).
_STAT_LABELS: dict[str, str] = {
    "might": "Fuerza",
    "agility": "Destreza",
    "wits": "Astucia",
    "charm": "Labia",
    "resolve": "Temple",
}


def build_opening(
    language: LanguageCode, adventure: AdventurePlan, character: PlayerCharacter
) -> OpeningDocument:
    from dungeon_agent.plane_shared.domain.enums import OpeningBlockKind
    from dungeon_agent.plane_shared.domain.models import OpeningBlock

    item_by_id = {item.id: item for item in adventure.items}
    content = [
        ("premise", OpeningBlockKind.PREMISE, adventure.premise, True),
        ("objective", OpeningBlockKind.OBJECTIVE, adventure.objective, True),
        (
            "identity",
            OpeningBlockKind.IDENTITY,
            f"{character.name}. {character.pronouns}. {character.archetype}.",
            True,
        ),
        ("desire", OpeningBlockKind.MOTIVATION, character.desire, True),
        *(
            (f"knowledge_{index}", OpeningBlockKind.KNOWLEDGE, fact, True)
            for index, fact in enumerate(character.known_facts, start=1)
        ),
        ("situation", OpeningBlockKind.SITUATION, adventure.opening, True),
        *(
            (f"action_{index}", OpeningBlockKind.POSSIBLE_ACTION, action, False)
            for index, action in enumerate(character.opening_choices, start=1)
        ),
        *(
            (
                f"inventory_{index}",
                OpeningBlockKind.INVENTORY,
                item_by_id[item_id].name,
                False,
            )
            for index, item_id in enumerate(adventure.starting_inventory, start=1)
            if item_id in item_by_id
        ),
        *(
            (
                f"stats_{stat_key}",
                OpeningBlockKind.STATS,
                f"{label} {getattr(character.stats, stat_key)}",
                False,
            )
            for stat_key, label in _STAT_LABELS.items()
        ),
    ]
    return OpeningDocument(
        language=language,
        title=adventure.title,
        blocks=tuple(
            (
                OpeningBlock(
                    id=block_id, position=position, kind=kind, text=text, narratable=narratable
                )
                for position, (block_id, kind, text, narratable) in enumerate(content)
            )
        ),
    )
