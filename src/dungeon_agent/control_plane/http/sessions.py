from collections.abc import Callable
from datetime import datetime
from typing import Any

from dungeon_agent.control_plane.domain.enums import (
    CampaignStatus,
    ErrorCode,
    EventType,
    SessionPhase,
    SessionStatus,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    CampaignRecord,
    CreateSessionWorkflowInput,
    SessionCompletedPayload,
    SessionId,
    SessionRecord,
    SubmitTurnCommand,
    TurnStartedPayload,
)
from dungeon_agent.control_plane.events import append_session_event
from dungeon_agent.control_plane.http.errors import (
    Clock,
    dependency_error,
    error_result,
    owner_access_error,
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
    TurnAcceptedEnvelope,
)
from dungeon_agent.control_plane.http.workflows import ensure_workflow
from dungeon_agent.control_plane.identifiers import new_session_id, new_turn_id
from dungeon_agent.control_plane.persistence.errors import SessionRevisionConflictError


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
        self._store = store
        self._workflows = workflows
        self._campaigns = campaigns
        self._turns = turns
        self._delivery = delivery
        self._microvms = microvms
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

        campaign_error = self._campaign_access_error(identity, campaign, correlation_id)
        if campaign_error is not None:
            return campaign_error
        assert campaign is not None

        quota_error = self._quota_error(identity, campaign.campaign_id, correlation_id)
        if quota_error is not None:
            return quota_error

        try:
            candidate = SessionRecord(
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
            persisted = self._store.create(candidate, idempotency_key)
            session = self._ensure_workflow(
                persisted,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                now=now,
            )
        except Exception:
            return self._dependency_error(correlation_id)
        return self._accepted(session, correlation_id)

    def _accepted(self, session: SessionRecord, correlation_id: str) -> HttpResult:
        return HttpResult(
            status_code=202,
            body=SessionEnvelope(session=session),
            correlation_id=correlation_id,
            location=f"/sessions/{session.session_id}",
        )

    def _campaign_access_error(
        self,
        identity: AuthenticatedIdentity,
        campaign: CampaignRecord | None,
        correlation_id: str,
    ) -> HttpResult | None:
        if campaign is None:
            return error_result(
                status_code=404,
                code=ErrorCode.CAMPAIGN_NOT_FOUND,
                message="Campaign not found.",
                retryable=False,
                correlation_id=correlation_id,
            )
        if campaign.owner_id != identity.owner_id:
            return error_result(
                status_code=403,
                code=ErrorCode.NOT_AUTHORIZED,
                message="You do not have access to this campaign.",
                retryable=False,
                correlation_id=correlation_id,
            )
        if campaign.status is not CampaignStatus.READY:
            return error_result(
                status_code=409,
                code=ErrorCode.CAMPAIGN_CONFLICT,
                message="The campaign is not ready for play.",
                retryable=True,
                correlation_id=correlation_id,
            )
        return None

    def _quota_error(
        self,
        identity: AuthenticatedIdentity,
        campaign_id: CampaignId,
        correlation_id: str,
    ) -> HttpResult | None:
        try:
            active = self._store.count_active_by_owner(identity.owner_id)
            replays = self._store.count_by_campaign(campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        if active >= self._max_active_sessions_per_owner:
            return error_result(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Too many active sessions; complete one before starting another.",
                retryable=True,
                correlation_id=correlation_id,
            )
        if replays >= self._max_sessions_per_campaign:
            return error_result(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="This campaign reached its session limit.",
                retryable=False,
                correlation_id=correlation_id,
            )
        return None

    def submit_action(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        request: SubmitActionRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        if self._turns is None:
            return self._dependency_error(correlation_id)
        try:
            session = self._store.get(session_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, session, correlation_id)
        if access_error is not None:
            return access_error
        assert session is not None

        if (
            session.last_action_idempotency_key == idempotency_key
            and session.last_turn_id is not None
        ):
            return HttpResult(
                status_code=202,
                body=TurnAcceptedEnvelope(
                    session_id=session_id,
                    turn_id=session.last_turn_id,
                    status="duplicate",
                ),
                correlation_id=correlation_id,
            )

        conflict = self._turn_conflict(session, request.expected_revision, correlation_id)
        if conflict is not None:
            return conflict

        turn_id = new_turn_id()
        checked_out = session.model_copy(
            update={
                "status": SessionStatus.ACTIVE,
                "phase": SessionPhase.PLAYING,
                "last_turn_id": turn_id,
                "last_action_idempotency_key": idempotency_key,
                "revision": session.revision + 1,
                "updated_at": self._clock(),
            }
        )
        try:
            self._store.save(checked_out, expected_revision=session.revision)
        except SessionRevisionConflictError:
            return self._conflict("The session changed while accepting the action.", correlation_id)

        command = SubmitTurnCommand(
            session_id=session_id,
            turn_id=turn_id,
            owner_id=identity.owner_id,
            action=request.action,
            expected_revision=request.expected_revision,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        try:
            append_session_event(
                self._store,
                self._delivery,
                session_id,
                EventType.TURN_STARTED,
                TurnStartedPayload(
                    turn_id=turn_id,
                    expected_revision=request.expected_revision,
                    action=request.action,
                ),
                correlation_id,
                self._clock(),
            )
            self._turns.invoke_turn(command)
        except Exception:
            self._release_checkout(session_id, turn_id)
            return self._dependency_error(correlation_id)

        return HttpResult(
            status_code=202,
            body=TurnAcceptedEnvelope(
                session_id=session_id,
                turn_id=turn_id,
                status="started",
            ),
            correlation_id=correlation_id,
        )

    def _turn_conflict(
        self,
        session: SessionRecord,
        expected_revision: int,
        correlation_id: str,
    ) -> HttpResult | None:
        if session.status is SessionStatus.ACTIVE:
            return self._conflict("A turn is already in progress.", correlation_id)
        if session.status is not SessionStatus.READY:
            return self._conflict("The session is not awaiting a player action.", correlation_id)
        if expected_revision != session.revision:
            return self._conflict(
                f"Stale session revision; the current revision is {session.revision}.",
                correlation_id,
            )
        return None

    def _release_checkout(self, session_id: SessionId, turn_id: str) -> None:
        try:
            current = self._store.get(session_id)
            if (
                current is None
                or current.status is not SessionStatus.ACTIVE
                or current.last_turn_id != turn_id
            ):
                return
            reverted = current.model_copy(
                update={
                    "status": SessionStatus.READY,
                    "phase": SessionPhase.READY,
                    "revision": current.revision + 1,
                    "updated_at": self._clock(),
                }
            )
            self._store.save(reverted, expected_revision=current.revision)
        except Exception:
            print(f"checkout rollback failed: {session_id}")

    def _conflict(self, message: str, correlation_id: str) -> HttpResult:
        return error_result(
            status_code=409,
            code=ErrorCode.SESSION_CONFLICT,
            message=message,
            retryable=False,
            correlation_id=correlation_id,
        )

    def get_session(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        *,
        correlation_id: str,
    ) -> HttpResult:
        try:
            session = self._store.get(session_id)
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
        try:
            session = self._store.get(session_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, session, correlation_id)
        if access_error is not None:
            return access_error
        try:
            events = self._store.list_after(session_id, after)
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

    def list_active_sessions(
        self,
        identity: AuthenticatedIdentity,
        *,
        correlation_id: str,
    ) -> HttpResult:
        try:
            sessions = self._store.list_active_by_owner(identity.owner_id)
        except Exception:
            return self._dependency_error(correlation_id)
        return HttpResult(
            status_code=200,
            body=SessionListEnvelope(sessions=sessions),
            correlation_id=correlation_id,
        )

    def abandon_session(
        self,
        identity: AuthenticatedIdentity,
        session_id: SessionId,
        *,
        correlation_id: str,
    ) -> HttpResult:
        try:
            session = self._store.get(session_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, session, correlation_id)
        if access_error is not None:
            return access_error
        assert session is not None

        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            return HttpResult(
                status_code=200,
                body=SessionEnvelope(session=session),
                correlation_id=correlation_id,
            )
        if session.status in (SessionStatus.REQUESTED, SessionStatus.CREATING):
            return error_result(
                status_code=409,
                code=ErrorCode.SESSION_CONFLICT,
                message="The session is still being created; retry once it settles.",
                retryable=True,
                correlation_id=correlation_id,
            )

        microvm_id = session.active_microvm_id
        updated = session.model_copy(
            update={
                "status": SessionStatus.COMPLETED,
                "phase": SessionPhase.COMPLETED,
                "active_microvm_id": None,
                "revision": session.revision + 1,
                "updated_at": self._clock(),
            }
        )
        try:
            saved = self._store.save(updated, expected_revision=session.revision)
        except SessionRevisionConflictError:
            return self._conflict("The session changed while abandoning it.", correlation_id)
        except Exception:
            return self._dependency_error(correlation_id)

        if microvm_id is not None and self._microvms is not None:
            try:
                self._microvms.terminate(microvm_id)
            except Exception as error:
                print(f"microvm terminate failed on abandon: {type(error).__name__}")

        try:
            append_session_event(
                self._store,
                self._delivery,
                session_id,
                EventType.SESSION_COMPLETED,
                SessionCompletedPayload(outcome="abandoned", revision=saved.revision),
                correlation_id,
                self._clock(),
            )
        except Exception as error:
            print(f"session.completed emission failed on abandon: {type(error).__name__}")

        return HttpResult(
            status_code=200,
            body=SessionEnvelope(session=saved),
            correlation_id=correlation_id,
        )

    def _ensure_workflow(
        self,
        session: SessionRecord,
        *,
        idempotency_key: str,
        correlation_id: str,
        now: datetime,
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

    def _access_error(
        self,
        identity: AuthenticatedIdentity,
        session: SessionRecord | None,
        correlation_id: str,
    ) -> HttpResult | None:
        return owner_access_error(
            identity,
            session,
            resource_name="session",
            not_found_code=ErrorCode.SESSION_NOT_FOUND,
            correlation_id=correlation_id,
        )

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return dependency_error("A session dependency is temporarily unavailable.", correlation_id)
