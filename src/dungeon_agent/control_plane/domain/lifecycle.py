"""Allowed lifecycle transitions enforced consistently by every adapter."""

from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    SessionPhase,
    SessionStatus,
)

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

CAMPAIGN_STATUS_TRANSITIONS: dict[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.REQUESTED: frozenset({CampaignStatus.CREATING, CampaignStatus.FAILED}),
    CampaignStatus.CREATING: frozenset({CampaignStatus.READY, CampaignStatus.FAILED}),
    CampaignStatus.READY: frozenset(),
    CampaignStatus.FAILED: frozenset(),
}

CAMPAIGN_PHASE_TRANSITIONS: dict[CampaignPhase, frozenset[CampaignPhase]] = {
    CampaignPhase.REQUESTED: frozenset({CampaignPhase.CREATING_ADVENTURE, CampaignPhase.FAILED}),
    CampaignPhase.CREATING_ADVENTURE: frozenset(
        {CampaignPhase.CREATING_CHARACTER, CampaignPhase.FAILED}
    ),
    CampaignPhase.CREATING_CHARACTER: frozenset({CampaignPhase.READY, CampaignPhase.FAILED}),
    CampaignPhase.READY: frozenset(),
    CampaignPhase.FAILED: frozenset(),
}


def require_status_transition(current: SessionStatus, target: SessionStatus) -> None:
    if target not in STATUS_TRANSITIONS[current]:
        raise ValueError(f"invalid session status transition: {current} -> {target}")


def require_phase_transition(current: SessionPhase, target: SessionPhase) -> None:
    if target not in PHASE_TRANSITIONS[current]:
        raise ValueError(f"invalid session phase transition: {current} -> {target}")


def require_campaign_status_transition(current: CampaignStatus, target: CampaignStatus) -> None:
    if target not in CAMPAIGN_STATUS_TRANSITIONS[current]:
        raise ValueError(f"invalid campaign status transition: {current} -> {target}")


def require_campaign_phase_transition(current: CampaignPhase, target: CampaignPhase) -> None:
    if target not in CAMPAIGN_PHASE_TRANSITIONS[current]:
        raise ValueError(f"invalid campaign phase transition: {current} -> {target}")
