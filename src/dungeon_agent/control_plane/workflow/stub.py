"""Durable session workflow tasks backed by the session repositories."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

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
    OpeningDocument,
    PhaseChangedPayload,
    SessionEvent,
    SessionId,
    SessionReadyPayload,
    SessionRecord,
)
from dungeon_agent.control_plane.domain.ports import (
    CampaignRepository,
    EventDeliveryPort,
    EventRepository,
    MicrovmManagerPort,
    SessionRepository,
)
from dungeon_agent.control_plane.identifiers import new_event_id
from dungeon_agent.control_plane.workflow.sandbox import sandbox_opening
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, WorldState

Clock = Callable[[], datetime]


class SessionAdventureStore(Protocol):
    """Save and load the session's forked adventure copy."""

    def save(self, session_id: SessionId, adventure: AdventurePlan) -> str: ...

    def load(self, adventure_ref: str) -> AdventurePlan: ...


class SessionCharacterStore(Protocol):
    """Save and load the session's forked character and opening copies."""

    def save(
        self,
        session_id: SessionId,
        character: PlayerCharacter,
        opening: OpeningDocument,
    ) -> str: ...

    def load_character(self, character_ref: str) -> PlayerCharacter: ...

    def load_opening(self, character_ref: str) -> OpeningDocument: ...


class CampaignAdventureLoader(Protocol):
    def load(self, adventure_ref: str) -> AdventurePlan: ...


class CampaignCharacterLoader(Protocol):
    def load_character(self, character_ref: str) -> PlayerCharacter: ...

    def load_opening(self, character_ref: str) -> OpeningDocument: ...


class WorldSnapshotStore(Protocol):
    def save(self, session_id: SessionId, world: WorldState) -> None: ...


class DurableSessionWorkflowStub:
    """Start a model-free play session by forking a ready campaign."""

    def __init__(
        self,
        sessions: SessionRepository,
        events: EventRepository,
        *,
        campaigns: CampaignRepository | None = None,
        campaign_adventures: CampaignAdventureLoader | None = None,
        campaign_characters: CampaignCharacterLoader | None = None,
        adventures: SessionAdventureStore | None = None,
        characters: SessionCharacterStore | None = None,
        microvms: MicrovmManagerPort | None = None,
        snapshots: WorldSnapshotStore | None = None,
        delivery: EventDeliveryPort | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._sessions = sessions
        self._events = events
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
        operation = _required_string(event, "operation")
        raw_state = event.get("state")
        if not isinstance(raw_state, Mapping):
            raise ValueError("workflow state must be an object")
        if operation == "ValidateSession":
            CreateSessionWorkflowInput.model_validate(raw_state)
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

        if operation == "CreateSessionRecord":
            session = self._update_session(
                state,
                status=SessionStatus.CREATING,
                workflow_arn=workflow_arn,
            )
            self._append_event(
                session,
                state,
                EventType.SESSION_CREATION_STARTED,
                CreationStartedPayload(language=session.language),
                now,
            )

        raw_phase = event.get("phase")
        if isinstance(raw_phase, str):
            phase = SessionPhase(raw_phase)
            session = self._update_session(state, phase=phase, workflow_arn=workflow_arn)
            phase_timestamps = dict(state.get("phaseTimestamps", {}))
            phase_timestamps[phase.value] = _wire_time(entered_at)
            state["phaseTimestamps"] = phase_timestamps
            state["phase"] = phase.value
            self._append_event(
                session,
                state,
                EventType.SESSION_PHASE_CHANGED,
                PhaseChangedPayload(
                    phase=phase,
                    elapsed_ms=max(0, int((now - entered_at).total_seconds() * 1_000)),
                ),
                now,
            )

        if operation == "LaunchMicrovm":
            if self._microvms is None:
                state["microvmRef"] = "sandbox-microvm"
            else:
                session_id: SessionId = _required_string(state, "sessionId")
                launched = self._microvms.launch(session_id)
                state["microvmRef"] = launched.microvm_id
        elif operation == "ForkCampaignIntoSession":
            if (
                self._campaigns is None
                or self._campaign_adventures is None
                or self._campaign_characters is None
                or self._adventures is None
                or self._characters is None
            ):
                state["adventureRef"] = "sandbox://adventure"
                state["characterRef"] = "sandbox://character"
            else:
                self._fork_campaign(state)
        elif operation == "InitializeMicrovmGame":
            if self._microvms is None or self._adventures is None or self._characters is None:
                state["stateRevision"] = 0
            else:
                world = self._microvms.initialize(
                    _required_string(state, "microvmRef"),
                    cast(LanguageCode, _required_string(state, "language")),
                    self._adventures.load(_required_string(state, "adventureRef")),
                    self._characters.load_character(_required_string(state, "characterRef")),
                )
                state["stateRevision"] = world.revision
                if self._snapshots is not None:
                    self._snapshots.save(_required_string(state, "sessionId"), world)
        elif operation == "MarkSessionReady":
            session = self._update_session(
                state,
                status=SessionStatus.READY,
                phase=SessionPhase.READY,
                workflow_arn=workflow_arn,
                active_microvm_id=_required_string(state, "microvmRef"),
            )
            state["status"] = session.status.value
            state["phase"] = session.phase.value
        elif operation == "EmitSessionReady":
            session = self._required_session(state)
            opening = (
                sandbox_opening(session.language)
                if self._characters is None
                else self._characters.load_opening(_required_string(state, "characterRef"))
            )
            self._append_event(
                session,
                state,
                EventType.SESSION_READY,
                SessionReadyPayload(
                    revision=session.revision,
                    opening=opening,
                ),
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
            self._append_event(
                session,
                state,
                EventType.SESSION_CREATION_FAILED,
                CreationFailedPayload(
                    code=ErrorCode.SESSION_CREATION_FAILED,
                    retryable=False,
                ),
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
        campaign_id: CampaignId = _required_string(state, "campaignId")
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            raise ValueError(f"campaign does not exist: {campaign_id}")
        if campaign.owner_id != _required_string(state, "ownerId"):
            raise PermissionError("campaign does not belong to this player")
        if campaign.status is not CampaignStatus.READY:
            raise ValueError(f"campaign is not ready: {campaign_id}")
        if campaign.adventure_ref is None or campaign.character_ref is None:
            raise ValueError(f"campaign is missing artifacts: {campaign_id}")
        session_id: SessionId = _required_string(state, "sessionId")
        adventure = self._campaign_adventures.load(campaign.adventure_ref)
        character = self._campaign_characters.load_character(campaign.character_ref)
        opening = self._campaign_characters.load_opening(campaign.character_ref)
        state["adventureRef"] = self._adventures.save(session_id, adventure)
        state["characterRef"] = self._characters.save(session_id, character, opening)
        state["campaignRevision"] = campaign.revision

    def _required_session(self, state: Mapping[str, object]) -> SessionRecord:
        session_id: SessionId = _required_string(state, "sessionId")
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"session does not exist: {session_id}")
        return session

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
        return self._sessions.save(validated, expected_revision=current.revision)

    def _append_event(
        self,
        session: SessionRecord,
        state: Mapping[str, object],
        event_type: EventType,
        payload: CreationStartedPayload
        | PhaseChangedPayload
        | SessionReadyPayload
        | CreationFailedPayload,
        now: datetime,
    ) -> None:
        current = self._sessions.get(session.session_id)
        if current is None:
            raise ValueError(f"session does not exist: {session.session_id}")
        event = SessionEvent(
            event_id=new_event_id(),
            session_id=session.session_id,
            sequence=current.last_event_sequence + 1,
            type=event_type,
            occurred_at=now,
            correlation_id=_required_string(state, "correlationId"),
            payload=payload,
        )
        self._events.append(event, expected_previous_sequence=current.last_event_sequence)
        if self._delivery is not None:
            try:
                self._delivery.deliver(current.owner_id, event)
            except Exception as delivery_error:
                print(f"event delivery failed: {type(delivery_error).__name__}")


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{key} must be a non-empty string")
    return result


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("workflow timestamps must include a timezone")
    return parsed


def _wire_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
