"""Allowed lifecycle transitions enforced consistently by every adapter."""

from dungeon_agent.control_plane.domain.enums import SessionPhase, SessionStatus

STATUS_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.REQUESTED: frozenset({SessionStatus.CREATING, SessionStatus.FAILED}),
    SessionStatus.CREATING: frozenset({SessionStatus.READY, SessionStatus.FAILED}),
    SessionStatus.READY: frozenset(
        {SessionStatus.ACTIVE, SessionStatus.COMPLETED, SessionStatus.FAILED}
    ),
    SessionStatus.ACTIVE: frozenset(
        {SessionStatus.READY, SessionStatus.COMPLETED, SessionStatus.FAILED}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.FAILED: frozenset(),
}

PHASE_TRANSITIONS: dict[SessionPhase, frozenset[SessionPhase]] = {
    SessionPhase.REQUESTED: frozenset({SessionPhase.STARTING_MICROVM, SessionPhase.FAILED}),
    SessionPhase.STARTING_MICROVM: frozenset(
        {SessionPhase.WAITING_FOR_MICROVM, SessionPhase.FAILED}
    ),
    SessionPhase.WAITING_FOR_MICROVM: frozenset(
        {SessionPhase.CREATING_ADVENTURE, SessionPhase.FAILED}
    ),
    SessionPhase.CREATING_ADVENTURE: frozenset(
        {SessionPhase.CREATING_CHARACTER, SessionPhase.FAILED}
    ),
    SessionPhase.CREATING_CHARACTER: frozenset(
        {SessionPhase.INITIALIZING_GAME, SessionPhase.FAILED}
    ),
    SessionPhase.INITIALIZING_GAME: frozenset({SessionPhase.READY, SessionPhase.FAILED}),
    SessionPhase.READY: frozenset(
        {
            SessionPhase.PLAYING,
            SessionPhase.REHYDRATING,
            SessionPhase.COMPLETED,
            SessionPhase.FAILED,
        }
    ),
    SessionPhase.PLAYING: frozenset(
        {SessionPhase.READY, SessionPhase.REHYDRATING, SessionPhase.COMPLETED, SessionPhase.FAILED}
    ),
    SessionPhase.REHYDRATING: frozenset({SessionPhase.READY, SessionPhase.FAILED}),
    SessionPhase.COMPLETED: frozenset(),
    SessionPhase.FAILED: frozenset(),
}


def require_status_transition(current: SessionStatus, target: SessionStatus) -> None:
    if target not in STATUS_TRANSITIONS[current]:
        raise ValueError(f"invalid session status transition: {current} -> {target}")


def require_phase_transition(current: SessionPhase, target: SessionPhase) -> None:
    if target not in PHASE_TRANSITIONS[current]:
        raise ValueError(f"invalid session phase transition: {current} -> {target}")
