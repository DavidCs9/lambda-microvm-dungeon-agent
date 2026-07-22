from collections.abc import Callable
from datetime import datetime
from typing import Any

from dungeon_agent.control_plane.domain.enums import (
    CampaignStatus,
    ErrorCode,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.control_plane.domain.models import (
    CreateSessionWorkflowInput,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.http import actions
from dungeon_agent.control_plane.http.errors import (
    Clock,
    dependency_error,
    error_result,
    load_owned,
    owner_access_error,
    replay_events,
    utc_now,
)
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CreateSessionRequest,
    EventListEnvelope,
    HttpResult,
    SessionEnvelope,
    SessionListEnvelope,
    SubmitActionRequest,
)
from dungeon_agent.control_plane.http.workflows import ensure_workflow
from dungeon_agent.control_plane.identifiers import new_session_id


class SessionHttpHandlers:
    def __init__(
        self,
        store: Any,
        workflows: Any,
        campaigns: Any,
        *,
        turns: Any | None = None,
        delivery: Any | None = None,
        microvms: Any | None = None,
        clock: Clock | None = None,
        session_id_factory: Callable[[], SessionId] = new_session_id,
        max_active_sessions_per_owner: int = 3,
        max_sessions_per_campaign: int = 10,
    ) -> None:
        self._store, self._workflows, self._campaigns = store, workflows, campaigns
        self._turns, self._delivery, self._microvms = turns, delivery, microvms
        self._clock = clock or utc_now
        self._session_id_factory = session_id_factory
        self._max_active_sessions_per_owner = max_active_sessions_per_owner
        self._max_sessions_per_campaign = max_sessions_per_campaign

    def create_session(
        self,
        identity: AuthenticatedIdentity,
        request: CreateSessionRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        now = self._clock()
        try:
            existing = self._store.find_by_idempotency_key(identity.owner_id, idempotency_key)
            if existing is not None:
                session = self._ensure_workflow(
                    existing,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    now=now,
                )
                return self._accepted(session, correlation_id)
            campaign = self._campaigns.get(request.campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)

        access_error = owner_access_error(
            identity, campaign, "campaign", ErrorCode.CAMPAIGN_NOT_FOUND, correlation_id
        )
        if access_error is not None:
            return access_error
        assert campaign is not None
        if campaign.status is not CampaignStatus.READY:
            return error_result(
                409,
                ErrorCode.CAMPAIGN_CONFLICT,
                "The campaign is not ready for play.",
                True,
                correlation_id,
            )
        try:
            active = self._store.count_active_by_owner(identity.owner_id)
            replays = self._store.count_by_campaign(campaign.campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        if active >= self._max_active_sessions_per_owner:
            return error_result(
                429,
                ErrorCode.QUOTA_EXCEEDED,
                "Too many active sessions; complete one before starting another.",
                True,
                correlation_id,
            )
        if replays >= self._max_sessions_per_campaign:
            return error_result(
                429,
                ErrorCode.QUOTA_EXCEEDED,
                "This campaign reached its session limit.",
                False,
                correlation_id,
            )

        try:
            record = SessionRecord(
                session_id=self._session_id_factory(),
                owner_id=identity.owner_id,
                language=request.language,
                status=SessionStatus.REQUESTED,
                phase=SessionPhase.REQUESTED,
                revision=0,
                last_event_sequence=0,
                created_at=now,
                updated_at=now,
                campaign_id=campaign.campaign_id,
                campaign_revision=campaign.revision,
            )
            session = self._ensure_workflow(
                self._store.create(record, idempotency_key),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                now=now,
            )
            return self._accepted(session, correlation_id)
        except Exception:
            return self._dependency_error(correlation_id)

    def submit_action(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        request: SubmitActionRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        return actions.submit_action(
            self._store,
            self._turns,
            self._delivery,
            self._clock,
            identity,
            session_id,
            request,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def get_session(
        self, identity: AuthenticatedIdentity, session_id: SessionId, *, correlation_id: str
    ) -> HttpResult:
        session, error = self._load(identity, session_id, correlation_id)
        if error is not None:
            return error
        assert session is not None
        return HttpResult(200, SessionEnvelope(session=session), correlation_id)

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
            dependency_message=actions.SESSION_DEPENDENCY,
            envelope=lambda events, next_sequence: EventListEnvelope(
                session_id=session_id, events=events, next_sequence=next_sequence
            ),
        )

    def list_active_sessions(
        self, identity: AuthenticatedIdentity, *, correlation_id: str
    ) -> HttpResult:
        try:
            return HttpResult(
                200,
                SessionListEnvelope(sessions=self._store.list_active_by_owner(identity.owner_id)),
                correlation_id,
            )
        except Exception:
            return self._dependency_error(correlation_id)

    def abandon_session(
        self, identity: AuthenticatedIdentity, session_id: SessionId, *, correlation_id: str
    ) -> HttpResult:
        return actions.abandon_session(
            self._store,
            self._delivery,
            self._microvms,
            self._clock,
            identity,
            session_id,
            correlation_id=correlation_id,
        )

    def _accepted(self, session: SessionRecord, correlation_id: str) -> HttpResult:
        return HttpResult(
            202,
            SessionEnvelope(session=session),
            correlation_id,
            location=f"/sessions/{session.session_id}",
        )

    def _ensure_workflow(
        self, session: SessionRecord, *, idempotency_key: str, correlation_id: str, now: datetime
    ) -> SessionRecord:
        if session.workflow_execution_arn is not None:
            return session
        if session.campaign_id is None or session.campaign_revision is None:
            raise RuntimeError("session has no campaign snapshot reference")
        return SessionRecord.model_validate(
            ensure_workflow(
                session,
                store=self._store,
                aggregate_id=session.session_id,
                now=now,
                start=lambda: self._workflows.start_create_session(
                    CreateSessionWorkflowInput(
                        session_id=session.session_id,
                        owner_id=session.owner_id,
                        language=session.language,
                        campaign_id=session.campaign_id,
                        campaign_revision=session.campaign_revision,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        requested_at=session.created_at,
                    )
                ),
            )
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
            dependency_message=actions.SESSION_DEPENDENCY,
            correlation_id=correlation_id,
        )
        return SessionRecord.model_validate(session) if session is not None else None, error

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return dependency_error(actions.SESSION_DEPENDENCY, correlation_id)
