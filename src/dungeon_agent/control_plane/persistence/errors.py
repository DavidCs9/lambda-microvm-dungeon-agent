"""Concurrency errors shared by persistence adapters."""


class PersistenceConflictError(RuntimeError):
    """Base class for expected conditional-write conflicts."""


class SessionAlreadyExistsError(PersistenceConflictError):
    """Raised when a session ID already belongs to another creation request."""


class SessionRevisionConflictError(PersistenceConflictError):
    """Raised when a session update was based on a stale revision."""


class EventSequenceConflictError(PersistenceConflictError):
    """Raised when an event is not the next event for its session."""
