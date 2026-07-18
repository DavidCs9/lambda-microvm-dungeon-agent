"""Session HTTP use cases expressed only in terms of domain ports."""

from collections.abc import Callable
from datetime import UTC, datetime

from dungeon_agent.control_plane.domain.enums import ErrorCode
from dungeon_agent.control_plane.domain.models import (
    CreateSessionCommand,
    CreateSessionWorkflowInput,
    ErrorDetail,
    ErrorEnvelope,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.domain.ports import (
    EventRepository,
    SessionFactoryPort,
    SessionRepository,
    WorkflowStarterPort,
)
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CreateSessionRequest,
    EventListEnvelope,
    HttpResult,
    SessionEnvelope,
)

Clock = Callable[[], datetime]


class SessionHttpHandlers:
    """Short control operations; generation remains in the async workflow."""

    def __init__(
        self,
        sessions: SessionRepository,
        events: EventRepository,
        workflows: WorkflowStarterPort,
        session_factory: SessionFactoryPort,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._sessions = sessions
        self._events = events
        self._workflows = workflows
        self._session_factory = session_factory
        self._clock = clock or _utc_now

    def create_session(
        self,
        identity: AuthenticatedIdentity,
        request: CreateSessionRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        """Persist intent and start one idempotently named workflow execution."""
        now = self._clock()
        command = CreateSessionCommand(
            owner_id=identity.owner_id,
            language=request.language,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

        try:
            existing = self._sessions.find_by_idempotency_key(identity.owner_id, idempotency_key)
            if existing is not None:
                session = self._ensure_workflow(existing, command, now)
            else:
                candidate = self._session_factory.create(command, now)
                persisted = self._sessions.create(candidate, idempotency_key)
                session = self._ensure_workflow(persisted, command, now)
        except Exception:
            return self.error(
                status_code=503,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="Session creation is temporarily unavailable.",
                retryable=True,
                correlation_id=correlation_id,
            )

        return HttpResult(
            status_code=202,
            body=SessionEnvelope(session=session),
            correlation_id=correlation_id,
            location=f"/sessions/{session.session_id}",
        )

    def get_session(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        *,
        correlation_id: str,
    ) -> HttpResult:
        """Return a session only to its authenticated owner."""
        try:
            session = self._sessions.get(session_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, session, correlation_id)
        if access_error is not None:
            return access_error
        assert session is not None
        return HttpResult(
            status_code=200,
            body=SessionEnvelope(session=session),
            correlation_id=correlation_id,
        )

    def list_events(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        *,
        after: int,
        correlation_id: str,
    ) -> HttpResult:
        """Replay durable events after a client-owned sequence number."""
        try:
            session = self._sessions.get(session_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, session, correlation_id)
        if access_error is not None:
            return access_error
        try:
            events = self._events.list_after(session_id, after)
        except Exception:
            return self._dependency_error(correlation_id)
        next_sequence = events[-1].sequence if events else after
        return HttpResult(
            status_code=200,
            body=EventListEnvelope(
                session_id=session_id,
                events=events,
                next_sequence=next_sequence,
            ),
            correlation_id=correlation_id,
        )

    def error(
        self,
        *,
        status_code: int,
        code: ErrorCode,
        message: str,
        retryable: bool,
        correlation_id: str,
    ) -> HttpResult:
        """Build the one error representation shared by all HTTP adapters."""
        return HttpResult(
            status_code=status_code,
            body=ErrorEnvelope(
                error=ErrorDetail(
                    code=code,
                    message=message,
                    retryable=retryable,
                    correlation_id=correlation_id,
                )
            ),
            correlation_id=correlation_id,
        )

    def _ensure_workflow(
        self,
        session: SessionRecord,
        command: CreateSessionCommand,
        now: datetime,
    ) -> SessionRecord:
        if session.workflow_execution_arn is not None:
            return session
        workflow_arn = self._workflows.start_create_session(
            CreateSessionWorkflowInput(
                session_id=session.session_id,
                owner_id=session.owner_id,
                language=session.language,
                idempotency_key=command.idempotency_key,
                correlation_id=command.correlation_id,
                requested_at=session.created_at,
            )
        )
        updated = SessionRecord.model_validate(
            {
                **session.model_dump(by_alias=False),
                "workflow_execution_arn": workflow_arn,
                "revision": session.revision + 1,
                "updated_at": now,
            }
        )
        try:
            return self._sessions.save(updated, expected_revision=session.revision)
        except Exception:
            # A concurrent duplicate may have started the same idempotently named
            # execution and persisted it first. A consistent read turns that race
            # into the same successful response without coupling to adapter errors.
            current = self._sessions.get(session.session_id)
            if current is not None and current.workflow_execution_arn is not None:
                return current
            raise

    def _access_error(
        self,
        identity: AuthenticatedIdentity,
        session: SessionRecord | None,
        correlation_id: str,
    ) -> HttpResult | None:
        if session is None:
            return self.error(
                status_code=404,
                code=ErrorCode.SESSION_NOT_FOUND,
                message="Session not found.",
                retryable=False,
                correlation_id=correlation_id,
            )
        if session.owner_id != identity.owner_id:
            return self.error(
                status_code=403,
                code=ErrorCode.NOT_AUTHORIZED,
                message="You do not have access to this session.",
                retryable=False,
                correlation_id=correlation_id,
            )
        return None

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return self.error(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="A session dependency is temporarily unavailable.",
            retryable=True,
            correlation_id=correlation_id,
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)
