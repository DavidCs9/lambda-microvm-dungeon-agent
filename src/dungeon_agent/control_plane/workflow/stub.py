from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

from dungeon_agent.control_plane.domain.enums import (
    CampaignStatus,
    ErrorCode,
    EventType,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    CreateSessionWorkflowInput,
    CreationFailedPayload,
    CreationStartedPayload,
    PhaseChangedPayload,
    SessionId,
    SessionReadyPayload,
    SessionRecord,
)
from dungeon_agent.control_plane.events import append_session_event
from dungeon_agent.control_plane.workflow.runner import prepare_run
from dungeon_agent.control_plane.workflow.util import required_string, wire_time
from dungeon_agent.domain.game import LanguageCode

Clock = Callable[[], datetime]


class DurableSessionWorkflowStub:
    def __init__(
        self,
        store: Any,
        *,
        campaigns: Any | None = None,
        campaign_adventures: Any | None = None,
        campaign_characters: Any | None = None,
        adventures: Any | None = None,
        characters: Any | None = None,
        microvms: Any | None = None,
        snapshots: Any | None = None,
        delivery: Any | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._campaigns = campaigns
        self._campaign_adventures = campaign_adventures
        self._campaign_characters = campaign_characters
        self._adventures = adventures
        self._characters = characters
        self._microvms = microvms
        self._snapshots = snapshots
        self._delivery = delivery
        self._clock = clock or (lambda: datetime.now(UTC))

    def handle(self, event: Mapping[str, object]) -> dict[str, object]:
        run = prepare_run(
            event,
            self._clock,
            validate=(
                CreateSessionWorkflowInput.model_validate
                if event.get("operation") == "ValidateSession"
                else None
            ),
        )
        operation, state, now, workflow_arn, entered_at = (
            run.operation,
            run.state,
            run.now,
            run.workflow_arn,
            run.entered_at,
        )

        if operation == "CreateSessionRecord":
            session = self._update_session(
                state,
                status=SessionStatus.CREATING,
                workflow_arn=workflow_arn,
            )
            append_session_event(
                self._store,
                self._delivery,
                session.session_id,
                EventType.SESSION_CREATION_STARTED,
                CreationStartedPayload(language=session.language),
                required_string(state, "correlationId"),
                now,
            )

        raw_phase = event.get("phase")
        if isinstance(raw_phase, str):
            phase = SessionPhase(raw_phase)
            session = self._update_session(state, phase=phase, workflow_arn=workflow_arn)
            phase_timestamps = dict(cast(Mapping[str, object], state.get("phaseTimestamps", {})))
            phase_timestamps[phase.value] = wire_time(entered_at)
            state["phaseTimestamps"] = phase_timestamps
            state["phase"] = phase.value
            append_session_event(
                self._store,
                self._delivery,
                session.session_id,
                EventType.SESSION_PHASE_CHANGED,
                PhaseChangedPayload(
                    phase=phase,
                    elapsed_ms=max(0, int((now - entered_at).total_seconds() * 1_000)),
                ),
                required_string(state, "correlationId"),
                now,
            )

        if operation == "LaunchMicrovm":
            if self._microvms is None:
                _missing("MicroVM manager")
            session_id: SessionId = required_string(state, "sessionId")
            state["microvmRef"] = self._microvms.launch(session_id).microvm_id
        elif operation == "ForkCampaignIntoSession":
            if (
                self._campaigns is None
                or self._campaign_adventures is None
                or self._campaign_characters is None
                or self._adventures is None
                or self._characters is None
            ):
                _missing("campaign/session artifact stores")
            self._fork_campaign(state)
        elif operation == "InitializeMicrovmGame":
            if self._microvms is None or self._adventures is None or self._characters is None:
                _missing("MicroVM manager and artifact stores")
            world = self._microvms.initialize(
                required_string(state, "microvmRef"),
                cast(LanguageCode, required_string(state, "language")),
                self._adventures.load_adventure(required_string(state, "adventureRef")),
                self._characters.load_character(required_string(state, "characterRef")),
            )
            state["stateRevision"] = world.revision
            if self._snapshots is not None:
                self._snapshots.save_snapshot(required_string(state, "sessionId"), world)
        elif operation == "MarkSessionReady":
            session = self._update_session(
                state,
                status=SessionStatus.READY,
                phase=SessionPhase.READY,
                workflow_arn=workflow_arn,
                active_microvm_id=required_string(state, "microvmRef"),
            )
            state["status"] = session.status.value
            state["phase"] = session.phase.value
        elif operation == "EmitSessionReady":
            session = self._required_session(state)
            if self._characters is None:
                _missing("session character store")
            opening = self._characters.load_opening(required_string(state, "characterRef"))
            append_session_event(
                self._store,
                self._delivery,
                session.session_id,
                EventType.SESSION_READY,
                SessionReadyPayload(
                    revision=session.revision,
                    opening=opening,
                ),
                required_string(state, "correlationId"),
                now,
            )
        elif operation == "MarkSessionFailed":
            microvm_ref = state.get("microvmRef")
            if self._microvms is not None and isinstance(microvm_ref, str):
                try:
                    self._microvms.terminate(microvm_ref)
                except Exception as cleanup_error:
                    print(f"MicroVM cleanup failed: {cleanup_error}")
            session = self._update_session(
                state,
                status=SessionStatus.FAILED,
                phase=SessionPhase.FAILED,
                workflow_arn=workflow_arn,
            )
            state["status"] = session.status.value
            state["phase"] = session.phase.value
        elif operation == "EmitSessionCreationFailed":
            session = self._required_session(state)
            append_session_event(
                self._store,
                self._delivery,
                session.session_id,
                EventType.SESSION_CREATION_FAILED,
                CreationFailedPayload(
                    code=ErrorCode.SESSION_CREATION_FAILED,
                    retryable=False,
                ),
                required_string(state, "correlationId"),
                now,
            )
        return state

    def _fork_campaign(self, state: dict[str, object]) -> None:
        """Copy the campaign snapshot into session-owned artifacts exactly once."""
        assert self._campaigns is not None
        assert self._campaign_adventures is not None
        assert self._campaign_characters is not None
        assert self._adventures is not None
        assert self._characters is not None
        campaign_id: CampaignId = required_string(state, "campaignId")
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            raise ValueError(f"campaign does not exist: {campaign_id}")
        if campaign.owner_id != required_string(state, "ownerId"):
            raise PermissionError("campaign does not belong to this player")
        if campaign.status is not CampaignStatus.READY:
            raise ValueError(f"campaign is not ready: {campaign_id}")
        if campaign.adventure_ref is None or campaign.character_ref is None:
            raise ValueError(f"campaign is missing artifacts: {campaign_id}")
        session_id: SessionId = required_string(state, "sessionId")
        adventure = self._campaign_adventures.load_adventure(campaign.adventure_ref)
        character = self._campaign_characters.load_character(campaign.character_ref)
        opening = self._campaign_characters.load_opening(campaign.character_ref)
        state["adventureRef"] = self._adventures.save_adventure(session_id, adventure)
        state["characterRef"] = self._characters.save_character(session_id, character, opening)
        state["campaignRevision"] = campaign.revision

    def _required_session(self, state: Mapping[str, object]) -> SessionRecord:
        session_id: SessionId = required_string(state, "sessionId")
        session = self._store.get(session_id)
        if session is None:
            raise ValueError(f"session does not exist: {session_id}")
        return SessionRecord.model_validate(session)

    def _update_session(
        self,
        state: Mapping[str, object],
        *,
        status: SessionStatus | None = None,
        phase: SessionPhase | None = None,
        workflow_arn: str,
        active_microvm_id: str | None = None,
    ) -> SessionRecord:
        current = self._required_session(state)
        updated = current.model_copy(
            update={
                "status": status or current.status,
                "phase": phase or current.phase,
                "workflow_execution_arn": workflow_arn,
                "active_microvm_id": active_microvm_id or current.active_microvm_id,
                "revision": current.revision + 1,
                "updated_at": self._clock(),
            }
        )
        validated = SessionRecord.model_validate(updated)
        saved = self._store.save(validated, expected_revision=current.revision)
        return SessionRecord.model_validate(saved)


def _missing(dependency: str) -> NoReturn:
    raise RuntimeError(f"{dependency} is not configured for this workflow operation")
