"""Data-plane HTTP: accept player actions and replay play events."""

from typing import Any, Literal

from dungeon_agent.plane_shared.domain import models as dm
from dungeon_agent.plane_shared.domain.enums import (
    ErrorCode,
    EventType,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.plane_shared.domain.models import SessionId, SessionRecord
from dungeon_agent.plane_shared.events import append_session_event
from dungeon_agent.plane_shared.http.errors import (
    Clock,
    dependency_error,
    error_result,
    load_owned,
    replay_events,
    utc_now,
)
from dungeon_agent.plane_shared.http.models import (
    AuthenticatedIdentity,
    EventListEnvelope,
    HttpResult,
    SubmitActionRequest,
    TurnAcceptedEnvelope,
)
from dungeon_agent.plane_shared.identifiers import new_turn_id
from dungeon_agent.plane_shared.persistence.errors import SessionRevisionConflictError

SESSION_DEPENDENCY = "A session dependency is temporarily unavailable."


class ActionHttpHandlers:
    """Live play path: checkout a turn and replay sequenced session events."""

    def __init__(
        self,
        store: Any,
        turns: Any,
        *,
        delivery: Any | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store, self._turns, self._delivery = store, turns, delivery
        self._clock = clock or utc_now

    def submit_action(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        request: SubmitActionRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        session, error = self._load(identity, session_id, correlation_id)
        if error is not None:
            return error
        assert session is not None
        if session.last_action_idempotency_key == idempotency_key and session.last_turn_id:
            return self._turn_accepted(
                session_id, session.last_turn_id, "duplicate", correlation_id
            )
        if session.status is SessionStatus.ACTIVE:
            return self._conflict("A turn is already in progress.", correlation_id)
        if session.status is not SessionStatus.READY:
            return self._conflict("The session is not awaiting a player action.", correlation_id)
        if request.expected_revision != session.revision:
            message = f"Stale session revision; the current revision is {session.revision}."
            return self._conflict(message, correlation_id)
        turn_id = new_turn_id()
        try:
            self._save(
                session,
                status=SessionStatus.ACTIVE,
                phase=SessionPhase.PLAYING,
                last_turn_id=turn_id,
                last_action_idempotency_key=idempotency_key,
            )
        except SessionRevisionConflictError:
            return self._conflict("The session changed while accepting the action.", correlation_id)
        command = dm.SubmitTurnCommand(
            session_id=session_id,
            turn_id=turn_id,
            owner_id=identity.owner_id,
            action=request.action,
            expected_revision=request.expected_revision,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        try:
            self._emit(
                session_id,
                EventType.TURN_STARTED,
                dm.TurnStartedPayload(
                    turn_id=turn_id,
                    expected_revision=request.expected_revision,
                    action=request.action,
                ),
                correlation_id,
            )
            self._turns.invoke_turn(command)
        except Exception:
            self._release_checkout(session_id, turn_id)
            return dependency_error(SESSION_DEPENDENCY, correlation_id)
        return self._turn_accepted(session_id, turn_id, "started", correlation_id)

    def list_events(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        *,
        after: int,
        correlation_id: str,
    ) -> HttpResult:
        _session, error = self._load(identity, session_id, correlation_id)
        if error is not None:
            return error
        return replay_events(
            self._store,
            session_id,
            after=after,
            correlation_id=correlation_id,
            dependency_message=SESSION_DEPENDENCY,
            envelope=lambda events, next_sequence: EventListEnvelope(
                session_id=session_id, events=events, next_sequence=next_sequence
            ),
        )

    def _load(
        self, identity: AuthenticatedIdentity, session_id: SessionId, correlation_id: str
    ) -> tuple[SessionRecord | None, HttpResult | None]:
        session, error = load_owned(
            self._store,
            identity,
            session_id,
            resource_name="session",
            not_found_code=ErrorCode.SESSION_NOT_FOUND,
            dependency_message=SESSION_DEPENDENCY,
            correlation_id=correlation_id,
        )
        return (SessionRecord.model_validate(session) if session is not None else None, error)

    def _save(self, session: SessionRecord, **update: object) -> SessionRecord:
        update.update(revision=session.revision + 1, updated_at=self._clock())
        saved = self._store.save(
            session.model_copy(update=update), expected_revision=session.revision
        )
        return SessionRecord.model_validate(saved)

    def _release_checkout(self, session_id: SessionId, turn_id: dm.TurnId) -> None:
        try:
            current = self._store.get(session_id)
            if current is None or current.status is not SessionStatus.ACTIVE:
                return
            if current.last_turn_id == turn_id:
                self._save(
                    SessionRecord.model_validate(current),
                    status=SessionStatus.READY,
                    phase=SessionPhase.READY,
                )
        except Exception:
            print(f"checkout rollback failed: {session_id}")

    def _emit(
        self,
        session_id: SessionId,
        event_type: EventType,
        payload: dm.EventPayload,
        correlation_id: str,
    ) -> None:
        append_session_event(
            self._store,
            self._delivery,
            session_id,
            event_type,
            payload,
            correlation_id,
            self._clock(),
        )

    @staticmethod
    def _conflict(message: str, correlation_id: str) -> HttpResult:
        return error_result(409, ErrorCode.SESSION_CONFLICT, message, False, correlation_id)

    @staticmethod
    def _turn_accepted(
        session_id: SessionId,
        turn_id: dm.TurnId,
        status: Literal["started", "duplicate"],
        correlation_id: str,
    ) -> HttpResult:
        return HttpResult(
            202,
            TurnAcceptedEnvelope(session_id=session_id, turn_id=turn_id, status=status),
            correlation_id,
        )
