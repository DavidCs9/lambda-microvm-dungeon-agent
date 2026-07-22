from typing import Any, Literal

from dungeon_agent.control_plane.domain import models as dm
from dungeon_agent.control_plane.domain.enums import (
    ErrorCode,
    EventType,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.control_plane.events import append_session_event
from dungeon_agent.control_plane.http import errors as he
from dungeon_agent.control_plane.http import models as hm
from dungeon_agent.control_plane.identifiers import new_turn_id
from dungeon_agent.control_plane.persistence.errors import SessionRevisionConflictError

SESSION_DEPENDENCY = "A session dependency is temporarily unavailable."


def submit_action(
    store: Any,
    turns: Any | None,
    delivery: Any | None,
    clock: he.Clock,
    identity: hm.AuthenticatedIdentity,
    session_id: dm.SessionId,
    request: hm.SubmitActionRequest,
    *,
    idempotency_key: str,
    correlation_id: str,
) -> hm.HttpResult:
    if turns is None:
        return _dependency_error(correlation_id)
    session, error = _load(store, identity, session_id, correlation_id)
    if error is not None:
        return error
    assert session is not None

    turn_id = session.last_turn_id
    if session.last_action_idempotency_key == idempotency_key and turn_id is not None:
        return _turn_accepted(session_id, turn_id, "duplicate", correlation_id)
    if (conflict := _turn_conflict(session, request.expected_revision, correlation_id)) is not None:
        return conflict

    turn_id = new_turn_id()
    try:
        _save(
            store,
            clock,
            session,
            status=SessionStatus.ACTIVE,
            phase=SessionPhase.PLAYING,
            last_turn_id=turn_id,
            last_action_idempotency_key=idempotency_key,
        )
    except SessionRevisionConflictError:
        return _conflict("The session changed while accepting the action.", correlation_id)

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
        payload = dm.TurnStartedPayload(
            turn_id=turn_id, expected_revision=request.expected_revision, action=request.action
        )
        append_session_event(
            store, delivery, session_id, EventType.TURN_STARTED, payload, correlation_id, clock()
        )
        turns.invoke_turn(command)
    except Exception:
        _release_checkout(store, clock, session_id, turn_id)
        return _dependency_error(correlation_id)
    return _turn_accepted(session_id, turn_id, "started", correlation_id)


def abandon_session(
    store: Any,
    delivery: Any | None,
    microvms: Any | None,
    clock: he.Clock,
    identity: hm.AuthenticatedIdentity,
    session_id: dm.SessionId,
    *,
    correlation_id: str,
) -> hm.HttpResult:
    session, error = _load(store, identity, session_id, correlation_id)
    if error is not None:
        return error
    assert session is not None

    if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
        return hm.HttpResult(200, hm.SessionEnvelope(session=session), correlation_id)
    if session.status in (SessionStatus.REQUESTED, SessionStatus.CREATING):
        return he.error_result(
            409,
            ErrorCode.SESSION_CONFLICT,
            "The session is still being created; retry once it settles.",
            True,
            correlation_id,
        )

    microvm_id = session.active_microvm_id
    try:
        saved = _save(
            store,
            clock,
            session,
            status=SessionStatus.COMPLETED,
            phase=SessionPhase.COMPLETED,
            active_microvm_id=None,
        )
    except SessionRevisionConflictError:
        return _conflict("The session changed while abandoning it.", correlation_id)
    except Exception:
        return _dependency_error(correlation_id)

    if microvm_id is not None and microvms is not None:
        try:
            microvms.terminate(microvm_id)
        except Exception as error:
            print(f"microvm terminate failed on abandon: {type(error).__name__}")
    try:
        payload = dm.SessionCompletedPayload(outcome="abandoned", revision=saved.revision)
        append_session_event(
            store,
            delivery,
            session_id,
            EventType.SESSION_COMPLETED,
            payload,
            correlation_id,
            clock(),
        )
    except Exception as error:
        print(f"session.completed emission failed on abandon: {type(error).__name__}")
    return hm.HttpResult(200, hm.SessionEnvelope(session=saved), correlation_id)


def _load(
    store: Any, identity: hm.AuthenticatedIdentity, session_id: dm.SessionId, correlation_id: str
) -> tuple[dm.SessionRecord | None, hm.HttpResult | None]:
    session, error = he.load_owned(
        store,
        identity,
        session_id,
        resource_name="session",
        not_found_code=ErrorCode.SESSION_NOT_FOUND,
        dependency_message=SESSION_DEPENDENCY,
        correlation_id=correlation_id,
    )
    return dm.SessionRecord.model_validate(session) if session is not None else None, error


def _turn_conflict(
    session: dm.SessionRecord, expected_revision: int, correlation_id: str
) -> hm.HttpResult | None:
    if session.status is SessionStatus.ACTIVE:
        return _conflict("A turn is already in progress.", correlation_id)
    if session.status is not SessionStatus.READY:
        return _conflict("The session is not awaiting a player action.", correlation_id)
    if expected_revision != session.revision:
        return _conflict(
            f"Stale session revision; the current revision is {session.revision}.", correlation_id
        )
    return None


def _release_checkout(
    store: Any, clock: he.Clock, session_id: dm.SessionId, turn_id: dm.TurnId
) -> None:
    try:
        current = store.get(session_id)
        if (
            current is None
            or current.status is not SessionStatus.ACTIVE
            or current.last_turn_id != turn_id
        ):
            return
        _save(
            store,
            clock,
            dm.SessionRecord.model_validate(current),
            status=SessionStatus.READY,
            phase=SessionPhase.READY,
        )
    except Exception:
        print(f"checkout rollback failed: {session_id}")


def _save(
    store: Any, clock: he.Clock, session: dm.SessionRecord, **update: object
) -> dm.SessionRecord:
    update.update(revision=session.revision + 1, updated_at=clock())
    return dm.SessionRecord.model_validate(
        store.save(session.model_copy(update=update), expected_revision=session.revision)
    )


def _conflict(message: str, correlation_id: str) -> hm.HttpResult:
    return he.error_result(409, ErrorCode.SESSION_CONFLICT, message, False, correlation_id)


def _dependency_error(correlation_id: str) -> hm.HttpResult:
    return he.dependency_error(SESSION_DEPENDENCY, correlation_id)


def _turn_accepted(
    session_id: dm.SessionId,
    turn_id: dm.TurnId,
    status: Literal["started", "duplicate"],
    correlation_id: str,
) -> hm.HttpResult:
    body = hm.TurnAcceptedEnvelope(session_id=session_id, turn_id=turn_id, status=status)
    return hm.HttpResult(202, body, correlation_id)
