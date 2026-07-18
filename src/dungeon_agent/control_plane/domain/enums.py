"""Lifecycle values shared by workflows, adapters, and clients."""

from enum import StrEnum


class SessionStatus(StrEnum):
    REQUESTED = "requested"
    CREATING = "creating"
    READY = "ready"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionPhase(StrEnum):
    REQUESTED = "requested"
    STARTING_MICROVM = "starting_microvm"
    WAITING_FOR_MICROVM = "waiting_for_microvm"
    CREATING_ADVENTURE = "creating_adventure"
    CREATING_CHARACTER = "creating_character"
    INITIALIZING_GAME = "initializing_game"
    READY = "ready"
    PLAYING = "playing"
    REHYDRATING = "rehydrating"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(StrEnum):
    SESSION_CREATION_STARTED = "session.creation.started"
    SESSION_PHASE_CHANGED = "session.phase.changed"
    SESSION_CREATION_FAILED = "session.creation.failed"
    SESSION_READY = "session.ready"
    TURN_STARTED = "turn.started"
    DICE_ROLLED = "dice.rolled"
    NARRATION_DELTA = "narration.delta"
    TURN_COMPLETED = "turn.completed"
    SESSION_COMPLETED = "session.completed"


class OpeningBlockKind(StrEnum):
    IDENTITY = "identity"
    BACKGROUND = "background"
    MOTIVATION = "motivation"
    KNOWLEDGE = "knowledge"
    SITUATION = "situation"
    POSSIBLE_ACTION = "possible_action"


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    NOT_AUTHENTICATED = "not_authenticated"
    NOT_AUTHORIZED = "not_authorized"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_CONFLICT = "session_conflict"
    SESSION_CREATION_FAILED = "session_creation_failed"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INTERNAL_ERROR = "internal_error"
