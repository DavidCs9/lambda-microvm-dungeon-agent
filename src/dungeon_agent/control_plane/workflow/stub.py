"""Durable Wave 1 workflow tasks backed by the session repositories."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from dungeon_agent.control_plane.domain.enums import (
    ErrorCode,
    EventType,
    OpeningBlockKind,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.control_plane.domain.models import (
    CreateSessionWorkflowInput,
    CreationFailedPayload,
    CreationStartedPayload,
    OpeningBlock,
    OpeningDocument,
    PhaseChangedPayload,
    SessionEvent,
    SessionId,
    SessionReadyPayload,
    SessionRecord,
)
from dungeon_agent.control_plane.domain.ports import EventRepository, SessionRepository
from dungeon_agent.control_plane.identifiers import new_event_id
from dungeon_agent.domain.game import LanguageCode

Clock = Callable[[], datetime]


class DurableSessionWorkflowStub:
    """Persist workflow progress while expensive Wave 2 operations remain stubbed."""

    def __init__(
        self,
        sessions: SessionRepository,
        events: EventRepository,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._sessions = sessions
        self._events = events
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
            state["microvmRef"] = "sandbox-microvm"
        elif operation == "GenerateAdventure":
            state["adventureRef"] = "sandbox://adventure"
        elif operation == "GenerateCharacter":
            state["characterRef"] = "sandbox://character"
        elif operation == "InitializeMicrovmGame":
            state["stateRevision"] = 0
        elif operation == "MarkSessionReady":
            session = self._update_session(
                state,
                status=SessionStatus.READY,
                phase=SessionPhase.READY,
                workflow_arn=workflow_arn,
                active_microvm_id="sandbox-microvm",
            )
            state["status"] = session.status.value
            state["phase"] = session.phase.value
        elif operation == "EmitSessionReady":
            session = self._required_session(state)
            self._append_event(
                session,
                state,
                EventType.SESSION_READY,
                SessionReadyPayload(
                    revision=session.revision,
                    opening=_sandbox_opening(session.language),
                ),
                now,
            )
        elif operation == "MarkSessionFailed":
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


def _sandbox_opening(language: LanguageCode) -> OpeningDocument:
    if language == "es":
        title = "La torre silenciosa"
        texts = (
            (
                "identidad",
                OpeningBlockKind.IDENTITY,
                "Eres Elia, la antigua guardiana de la campana.",
            ),
            (
                "historia",
                OpeningBlockKind.BACKGROUND,
                "Regresaste al pueblo después de una larga ausencia.",
            ),
            (
                "motivacion",
                OpeningBlockKind.MOTIVATION,
                "Quieres encontrar a tu hermano antes de la tormenta.",
            ),
            ("pista_1", OpeningBlockKind.KNOWLEDGE, "La campana desapareció durante la noche."),
            ("pista_2", OpeningBlockKind.KNOWLEDGE, "Mara vio luces cerca del molino."),
            (
                "situacion",
                OpeningBlockKind.SITUATION,
                "La plaza se inunda y la torre permanece en silencio.",
            ),
            ("accion_1", OpeningBlockKind.POSSIBLE_ACTION, "Investigar la torre."),
            ("accion_2", OpeningBlockKind.POSSIBLE_ACTION, "Hablar con Mara."),
            ("accion_3", OpeningBlockKind.POSSIBLE_ACTION, "Cruzar hacia el molino."),
        )
    else:
        title = "The silent tower"
        texts = (
            ("identity", OpeningBlockKind.IDENTITY, "You are Elia, the former keeper of the bell."),
            (
                "background",
                OpeningBlockKind.BACKGROUND,
                "You returned to the village after a long absence.",
            ),
            (
                "motivation",
                OpeningBlockKind.MOTIVATION,
                "You want to find your brother before the storm.",
            ),
            ("clue_1", OpeningBlockKind.KNOWLEDGE, "The bell disappeared during the night."),
            ("clue_2", OpeningBlockKind.KNOWLEDGE, "Mara saw lights near the mill."),
            (
                "situation",
                OpeningBlockKind.SITUATION,
                "The square is flooding and the tower remains silent.",
            ),
            ("action_1", OpeningBlockKind.POSSIBLE_ACTION, "Investigate the tower."),
            ("action_2", OpeningBlockKind.POSSIBLE_ACTION, "Talk to Mara."),
            ("action_3", OpeningBlockKind.POSSIBLE_ACTION, "Cross toward the mill."),
        )
    return OpeningDocument(
        language=language,
        title=title,
        blocks=tuple(
            OpeningBlock(
                id=block_id,
                position=index,
                kind=kind,
                text=text,
                narratable=kind is not OpeningBlockKind.POSSIBLE_ACTION,
            )
            for index, (block_id, kind, text) in enumerate(texts)
        ),
    )


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
