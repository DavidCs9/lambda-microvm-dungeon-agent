# ruff: noqa: E501,I001
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from dungeon_agent.control_plane.domain.enums import CampaignPhase, CampaignStatus, ErrorCode, EventType
from dungeon_agent.control_plane.domain.models import ArtifactRef, CampaignCreationFailedPayload, CampaignCreationStartedPayload, CampaignId, CampaignPhaseChangedPayload, CampaignReadyPayload, CampaignRecord, CreateCampaignWorkflowInput, OpeningDocument
from dungeon_agent.control_plane.events import append_campaign_event
from dungeon_agent.control_plane.workflow.runner import elapsed_ms, mark_phase, prepare_run, required_record, update_record
from dungeon_agent.control_plane.workflow.util import required_string
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter
Clock = Callable[[], datetime]

class DurableCampaignWorkflowStub:

    def __init__(self, store: Any, *, adventure_architect: Any | None=None, character_architect: Any | None=None, adventures: Any | None=None, characters: Any | None=None, openings: Any | None=None, delivery: Any | None=None, clock: Clock | None=None, monotonic: Callable[[], float]=time.perf_counter) -> None:
        self._store = store
        self._adventure_architect, self._character_architect = (adventure_architect, character_architect)
        self._adventures, self._characters, self._openings = (adventures, characters, openings)
        self._delivery = delivery
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic

    def handle(self, event: Mapping[str, object]) -> dict[str, object]:
        validate = CreateCampaignWorkflowInput.model_validate if event.get('operation') == 'ValidateCampaign' else None
        run = prepare_run(event, self._clock, validate=validate)
        operation, state, now, workflow_arn, entered_at = (run.operation, run.state, run.now, run.workflow_arn, run.entered_at)
        if operation == 'CreateCampaignRecord':
            campaign = self._update_campaign(state, status=CampaignStatus.CREATING, workflow_arn=workflow_arn)
            started_payload = CampaignCreationStartedPayload(language=campaign.language)
            self._emit(campaign.campaign_id, EventType.CAMPAIGN_CREATION_STARTED, started_payload, state, now)
        raw_phase = event.get('phase')
        if isinstance(raw_phase, str):
            phase = CampaignPhase(raw_phase)
            campaign = self._update_campaign(state, phase=phase, workflow_arn=workflow_arn)
            mark_phase(state, phase, entered_at)
            phase_payload = CampaignPhaseChangedPayload(phase=phase, elapsed_ms=elapsed_ms(now, entered_at))
            self._emit(campaign.campaign_id, EventType.CAMPAIGN_PHASE_CHANGED, phase_payload, state, now)
        if operation == 'GenerateAdventure':
            adventure_ref, latency_ms = self._generate_adventure(_workflow_input(state))
            state['adventureRef'] = adventure_ref
            state['adventureLatencyMs'] = latency_ms
        elif operation == 'GenerateCharacter':
            character_ref, latency_ms = self._generate_character(campaign_id=required_string(state, 'campaignId'), language=cast(LanguageCode, required_string(state, 'language')), adventure_ref=required_string(state, 'adventureRef'))
            state['characterRef'] = character_ref
            state['characterLatencyMs'] = latency_ms
        elif operation == 'MarkCampaignReady':
            opening = self._load_opening(required_string(state, 'characterRef'))
            campaign = self._update_campaign(state, status=CampaignStatus.READY, phase=CampaignPhase.READY, workflow_arn=workflow_arn, adventure_ref=required_string(state, 'adventureRef'), character_ref=required_string(state, 'characterRef'), opening_title=opening.title)
            state['status'] = campaign.status.value
            state['phase'] = campaign.phase.value
            state['opening'] = opening.model_dump(by_alias=True)
        elif operation == 'EmitCampaignReady':
            campaign = self._required_campaign(state)
            opening_payload = state.get('opening')
            opening = OpeningDocument.model_validate(opening_payload) if opening_payload is not None else self._load_opening(required_string(state, 'characterRef'))
            ready_payload = CampaignReadyPayload(revision=campaign.revision, opening=opening)
            self._emit(campaign.campaign_id, EventType.CAMPAIGN_READY, ready_payload, state, now)
        elif operation == 'MarkCampaignFailed':
            campaign = self._update_campaign(state, status=CampaignStatus.FAILED, phase=CampaignPhase.FAILED, workflow_arn=workflow_arn)
            state['status'] = campaign.status.value
            state['phase'] = campaign.phase.value
        elif operation == 'EmitCampaignCreationFailed':
            campaign = self._required_campaign(state)
            failed_payload = CampaignCreationFailedPayload(code=ErrorCode.CAMPAIGN_CREATION_FAILED, retryable=False)
            self._emit(campaign.campaign_id, EventType.CAMPAIGN_CREATION_FAILED, failed_payload, state, now)
        return state

    def _generate_adventure(self, workflow_input: CreateCampaignWorkflowInput) -> tuple[str, int]:
        if self._adventure_architect is None or self._adventures is None:
            raise RuntimeError('campaign adventure generation is not configured')
        started = self._monotonic()
        generated = self._adventure_architect.create(workflow_input.language)
        adventure = AdventurePlan.model_validate(generated.model_dump(mode='python'))
        adventure_ref = self._adventures.save_adventure(workflow_input.campaign_id, adventure)
        return (str(adventure_ref), _elapsed_ms(self._monotonic, started))

    def _generate_character(self, *, campaign_id: CampaignId, language: LanguageCode, adventure_ref: ArtifactRef) -> tuple[str, int]:
        if self._character_architect is None or self._adventures is None or self._characters is None:
            raise RuntimeError('campaign character generation is not configured')
        started = self._monotonic()
        adventure = AdventurePlan.model_validate(self._adventures.load_adventure(adventure_ref).model_dump(mode='python'))
        generated = self._character_architect.create(language, adventure)
        character = PlayerCharacter.model_validate(generated.model_dump(mode='python'))
        opening = build_opening(language, adventure, character)
        character_ref = self._characters.save_character(campaign_id, character, opening)
        return (str(character_ref), _elapsed_ms(self._monotonic, started))

    def _load_opening(self, character_ref: str) -> OpeningDocument:
        if self._openings is None:
            raise RuntimeError('campaign opening storage is not configured')
        return OpeningDocument.model_validate(self._openings.load_opening(character_ref))

    def _required_campaign(self, state: Mapping[str, object]) -> CampaignRecord:
        return required_record(self._store, state, CampaignRecord, 'campaignId', 'campaign')

    def _emit(self, campaign_id: CampaignId, event_type: EventType, payload: Any, state: Mapping[str, object], now: datetime) -> None:
        append_campaign_event(self._store, self._delivery, campaign_id, event_type, payload, required_string(state, 'correlationId'), now)

    def _update_campaign(self, state: Mapping[str, object], *, status: CampaignStatus | None=None, phase: CampaignPhase | None=None, workflow_arn: str, adventure_ref: str | None=None, character_ref: str | None=None, opening_title: str | None=None) -> CampaignRecord:
        return update_record(self._store, state, CampaignRecord, 'campaignId', 'campaign', self._clock, workflow_arn, status=status, phase=phase, adventure_ref=adventure_ref, character_ref=character_ref, opening_title=opening_title)

def _workflow_input(state: Mapping[str, object]) -> CreateCampaignWorkflowInput:
    return CreateCampaignWorkflowInput.model_validate({'schemaVersion': state.get('schemaVersion', 1), 'campaignId': state.get('campaignId'), 'ownerId': state.get('ownerId'), 'language': state.get('language'), 'idempotencyKey': state.get('idempotencyKey'), 'correlationId': state.get('correlationId'), 'requestedAt': state.get('requestedAt')})

def _elapsed_ms(monotonic: Callable[[], float], started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))

def build_opening(language: LanguageCode, adventure: AdventurePlan, character: PlayerCharacter) -> OpeningDocument:
    from dungeon_agent.control_plane.domain.enums import OpeningBlockKind
    from dungeon_agent.control_plane.domain.models import OpeningBlock
    content = [('identity', OpeningBlockKind.IDENTITY, f'{character.name}. {character.pronouns}. {character.archetype}.', True), ('desire', OpeningBlockKind.MOTIVATION, character.desire, True), *((f'knowledge_{index}', OpeningBlockKind.KNOWLEDGE, fact, True) for index, fact in enumerate(character.known_facts, start=1)), ('situation', OpeningBlockKind.SITUATION, adventure.opening, True), *((f'action_{index}', OpeningBlockKind.POSSIBLE_ACTION, action, False) for index, action in enumerate(character.opening_choices, start=1))]
    return OpeningDocument(language=language, title=adventure.title, blocks=tuple((OpeningBlock(id=block_id, position=position, kind=kind, text=text, narratable=narratable) for position, (block_id, kind, text, narratable) in enumerate(content))))
