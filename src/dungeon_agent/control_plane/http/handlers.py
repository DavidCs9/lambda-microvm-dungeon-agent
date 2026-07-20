"""Session and campaign HTTP use cases expressed only in terms of domain ports."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from dungeon_agent.control_plane.application.events import append_session_event
from dungeon_agent.control_plane.application.turns import TurnWorkerInvoker
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
    CreateCampaignCommand,
    CreateCampaignWorkflowInput,
    CreateSessionCommand,
    CreateSessionWorkflowInput,
    ErrorDetail,
    ErrorEnvelope,
    OpeningDocument,
    SessionCompletedPayload,
    SessionId,
    SessionRecord,
    SubmitTurnCommand,
    TurnStartedPayload,
)
from dungeon_agent.control_plane.domain.ports import (
    CampaignEventRepository,
    CampaignFactoryPort,
    CampaignRepository,
    EventDeliveryPort,
    EventRepository,
    MicrovmManagerPort,
    SessionFactoryPort,
    SessionRepository,
    WorkflowStarterPort,
)
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CampaignEnvelope,
    CampaignEventListEnvelope,
    CampaignListEnvelope,
    CreateCampaignRequest,
    CreateSessionRequest,
    EventListEnvelope,
    HttpResult,
    OpeningEnvelope,
    SessionEnvelope,
    SessionListEnvelope,
    SpeechEnvelope,
    SpeechRequest,
    SubmitActionRequest,
    TurnAcceptedEnvelope,
)
from dungeon_agent.control_plane.identifiers import new_turn_id
from dungeon_agent.control_plane.persistence.errors import SessionRevisionConflictError
from dungeon_agent.domain.game import LanguageCode

Clock = Callable[[], datetime]


class SpeechSynthesizerPort(Protocol):
    def synthesize(self, text: str, language: LanguageCode) -> tuple[str, bool]: ...


class CampaignOpeningLoader(Protocol):
    def load_opening(self, character_ref: str) -> OpeningDocument: ...


class SessionHttpHandlers:
    """Short control operations; MicroVM work remains in the async workflow."""

    def __init__(
        self,
        sessions: SessionRepository,
        events: EventRepository,
        workflows: WorkflowStarterPort,
        session_factory: SessionFactoryPort,
        campaigns: CampaignRepository,
        *,
        turns: TurnWorkerInvoker | None = None,
        delivery: EventDeliveryPort | None = None,
        microvms: MicrovmManagerPort | None = None,
        clock: Clock | None = None,
        max_active_sessions_per_owner: int = 3,
        max_sessions_per_campaign: int = 10,
    ) -> None:
        self._sessions = sessions
        self._events = events
        self._workflows = workflows
        self._session_factory = session_factory
        self._campaigns = campaigns
        self._turns = turns
        self._delivery = delivery
        self._microvms = microvms
        self._clock = clock or _utc_now
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
        """Persist intent against a ready campaign and start the play workflow."""
        now = self._clock()
        try:
            existing = self._sessions.find_by_idempotency_key(identity.owner_id, idempotency_key)
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

        command = CreateSessionCommand(
            owner_id=identity.owner_id,
            language=request.language,
            campaign_id=campaign.campaign_id,
            campaign_revision=campaign.revision,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        try:
            candidate = self._session_factory.create(command, now)
            persisted = self._sessions.create(candidate, idempotency_key)
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
            return self.error(
                status_code=404,
                code=ErrorCode.CAMPAIGN_NOT_FOUND,
                message="Campaign not found.",
                retryable=False,
                correlation_id=correlation_id,
            )
        if campaign.owner_id != identity.owner_id:
            return self.error(
                status_code=403,
                code=ErrorCode.NOT_AUTHORIZED,
                message="You do not have access to this campaign.",
                retryable=False,
                correlation_id=correlation_id,
            )
        if campaign.status is not CampaignStatus.READY:
            return self.error(
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
            active = self._sessions.count_active_by_owner(identity.owner_id)
            replays = self._sessions.count_by_campaign(campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        if active >= self._max_active_sessions_per_owner:
            return self.error(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Too many active sessions; complete one before starting another.",
                retryable=True,
                correlation_id=correlation_id,
            )
        if replays >= self._max_sessions_per_campaign:
            return self.error(
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
        """Check out one action, emit ``turn.started``, and hand it to the turn worker."""
        if self._turns is None:
            return self._dependency_error(correlation_id)
        try:
            session = self._sessions.get(session_id)
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
        checked_out = SessionRecord.model_validate(
            {
                **session.model_dump(by_alias=False),
                "status": SessionStatus.ACTIVE,
                "phase": SessionPhase.PLAYING,
                "last_turn_id": turn_id,
                "last_action_idempotency_key": idempotency_key,
                "revision": session.revision + 1,
                "updated_at": self._clock(),
            }
        )
        try:
            self._sessions.save(checked_out, expected_revision=session.revision)
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
                self._sessions,
                self._events,
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
            current = self._sessions.get(session_id)
            if (
                current is None
                or current.status is not SessionStatus.ACTIVE
                or current.last_turn_id != turn_id
            ):
                return
            reverted = SessionRecord.model_validate(
                {
                    **current.model_dump(by_alias=False),
                    "status": SessionStatus.READY,
                    "phase": SessionPhase.READY,
                    "revision": current.revision + 1,
                    "updated_at": self._clock(),
                }
            )
            self._sessions.save(reverted, expected_revision=current.revision)
        except Exception:
            print(f"checkout rollback failed: {session_id}")

    def _conflict(self, message: str, correlation_id: str) -> HttpResult:
        return self.error(
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

    def list_active_sessions(
        self,
        identity: AuthenticatedIdentity,
        *,
        correlation_id: str,
    ) -> HttpResult:
        """List an owner's live sessions for the Continuar picker."""
        try:
            sessions = self._sessions.list_active_by_owner(identity.owner_id)
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
        """Free the owner's active slot and stop MicroVM cost for a live session."""
        try:
            session = self._sessions.get(session_id)
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
            return self.error(
                status_code=409,
                code=ErrorCode.SESSION_CONFLICT,
                message="The session is still being created; retry once it settles.",
                retryable=True,
                correlation_id=correlation_id,
            )

        microvm_id = session.active_microvm_id
        updated = SessionRecord.model_validate(
            {
                **session.model_dump(by_alias=False),
                "status": SessionStatus.COMPLETED,
                "phase": SessionPhase.COMPLETED,
                "active_microvm_id": None,
                "revision": session.revision + 1,
                "updated_at": self._clock(),
            }
        )
        try:
            saved = self._sessions.save(updated, expected_revision=session.revision)
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
                self._sessions,
                self._events,
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
        return _error_result(
            status_code=status_code,
            code=code,
            message=message,
            retryable=retryable,
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
        workflow_arn = self._workflows.start_create_session(
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


class SpeechHttpHandlers:
    """On-demand Polly narration with content-hash caching."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizerPort,
        *,
        expires_in_seconds: int = 300,
        max_requests_per_owner_per_minute: int = 60,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._synthesizer = synthesizer
        self._expires_in_seconds = expires_in_seconds
        self._max_requests_per_owner_per_minute = max_requests_per_owner_per_minute
        self._monotonic = monotonic or time.monotonic
        self._request_counts: dict[str, tuple[int, float]] = {}

    def synthesize_speech(
        self,
        identity: AuthenticatedIdentity,
        request: SpeechRequest,
        *,
        correlation_id: str,
    ) -> HttpResult:
        if not self._allow_request(identity.owner_id):
            return self.error(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Too many speech requests; retry shortly.",
                retryable=True,
                correlation_id=correlation_id,
            )
        try:
            url, cache_hit = self._synthesizer.synthesize(request.text, request.language)
        except Exception:
            return self._dependency_error(correlation_id)
        return HttpResult(
            status_code=200,
            body=SpeechEnvelope(
                url=url,
                expires_in_seconds=self._expires_in_seconds,
                cache_hit=cache_hit,
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
        return _error_result(
            status_code=status_code,
            code=code,
            message=message,
            retryable=retryable,
            correlation_id=correlation_id,
        )

    def _allow_request(self, owner_id: str) -> bool:
        now = self._monotonic()
        count, window_start = self._request_counts.get(owner_id, (0, now))
        if now - window_start >= 60:
            count, window_start = 0, now
        if count >= self._max_requests_per_owner_per_minute:
            self._request_counts[owner_id] = (count, window_start)
            return False
        self._request_counts[owner_id] = (count + 1, window_start)
        return True

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return self.error(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="Speech synthesis is temporarily unavailable.",
            retryable=True,
            correlation_id=correlation_id,
        )


class CampaignHttpHandlers:
    """Short campaign control operations; generation remains in the async workflow."""

    def __init__(
        self,
        campaigns: CampaignRepository,
        events: CampaignEventRepository,
        workflows: WorkflowStarterPort,
        campaign_factory: CampaignFactoryPort,
        *,
        openings: CampaignOpeningLoader | None = None,
        clock: Clock | None = None,
        max_campaigns_per_owner: int = 10,
    ) -> None:
        self._campaigns = campaigns
        self._events = events
        self._workflows = workflows
        self._campaign_factory = campaign_factory
        self._openings = openings
        self._clock = clock or _utc_now
        self._max_campaigns_per_owner = max_campaigns_per_owner

    def create_campaign(
        self,
        identity: AuthenticatedIdentity,
        request: CreateCampaignRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        """Persist intent and start paid generation once per idempotency key."""
        now = self._clock()
        try:
            existing = self._campaigns.find_by_idempotency_key(identity.owner_id, idempotency_key)
            if existing is not None:
                campaign = self._ensure_workflow(
                    existing,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    now=now,
                )
                return self._accepted(campaign, correlation_id)
            campaign_count = self._campaigns.count_by_owner(identity.owner_id)
        except Exception:
            return self._dependency_error(correlation_id)

        if campaign_count >= self._max_campaigns_per_owner:
            return self.error(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Campaign limit reached for this player.",
                retryable=False,
                correlation_id=correlation_id,
            )

        command = CreateCampaignCommand(
            owner_id=identity.owner_id,
            language=request.language,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        try:
            candidate = self._campaign_factory.create(command, now)
            persisted = self._campaigns.create(candidate, idempotency_key)
            campaign = self._ensure_workflow(
                persisted,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                now=now,
            )
        except Exception:
            return self._dependency_error(correlation_id)
        return self._accepted(campaign, correlation_id)

    def list_campaigns(
        self,
        identity: AuthenticatedIdentity,
        *,
        status: str | None = None,
        correlation_id: str,
    ) -> HttpResult:
        """List an owner's campaigns for resume discovery, optionally filtered by status."""
        try:
            campaigns = self._campaigns.list_by_owner(identity.owner_id, status=status)
        except Exception:
            return self._dependency_error(correlation_id)
        return HttpResult(
            status_code=200,
            body=CampaignListEnvelope(campaigns=campaigns),
            correlation_id=correlation_id,
        )

    def get_campaign(
        self,
        identity: AuthenticatedIdentity,
        campaign_id: CampaignId,
        *,
        correlation_id: str,
    ) -> HttpResult:
        """Return a campaign only to its authenticated owner."""
        try:
            campaign = self._campaigns.get(campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, campaign, correlation_id)
        if access_error is not None:
            return access_error
        assert campaign is not None
        return HttpResult(
            status_code=200,
            body=CampaignEnvelope(campaign=campaign),
            correlation_id=correlation_id,
        )

    def get_campaign_opening(
        self,
        identity: AuthenticatedIdentity,
        campaign_id: CampaignId,
        *,
        correlation_id: str,
    ) -> HttpResult:
        """Return the opening for a ready campaign without replaying event history."""
        try:
            campaign = self._campaigns.get(campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, campaign, correlation_id)
        if access_error is not None:
            return access_error
        assert campaign is not None
        if campaign.status is not CampaignStatus.READY:
            return self.error(
                status_code=409,
                code=ErrorCode.CAMPAIGN_CONFLICT,
                message="The campaign is not ready for play.",
                retryable=True,
                correlation_id=correlation_id,
            )
        if self._openings is None or campaign.character_ref is None:
            return self._dependency_error(correlation_id)
        try:
            opening = self._openings.load_opening(campaign.character_ref)
        except Exception:
            return self._dependency_error(correlation_id)
        return HttpResult(
            status_code=200,
            body=OpeningEnvelope(campaign_id=campaign_id, opening=opening),
            correlation_id=correlation_id,
        )

    def list_events(
        self,
        identity: AuthenticatedIdentity,
        campaign_id: CampaignId,
        *,
        after: int,
        correlation_id: str,
    ) -> HttpResult:
        """Replay durable campaign events after a client-owned sequence number."""
        try:
            campaign = self._campaigns.get(campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, campaign, correlation_id)
        if access_error is not None:
            return access_error
        try:
            events = self._events.list_after(campaign_id, after)
        except Exception:
            return self._dependency_error(correlation_id)
        next_sequence = events[-1].sequence if events else after
        return HttpResult(
            status_code=200,
            body=CampaignEventListEnvelope(
                campaign_id=campaign_id,
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
        return _error_result(
            status_code=status_code,
            code=code,
            message=message,
            retryable=retryable,
            correlation_id=correlation_id,
        )

    def _accepted(self, campaign: CampaignRecord, correlation_id: str) -> HttpResult:
        return HttpResult(
            status_code=202,
            body=CampaignEnvelope(campaign=campaign),
            correlation_id=correlation_id,
            location=f"/campaigns/{campaign.campaign_id}",
        )

    def _ensure_workflow(
        self,
        campaign: CampaignRecord,
        *,
        idempotency_key: str,
        correlation_id: str,
        now: datetime,
    ) -> CampaignRecord:
        if campaign.workflow_execution_arn is not None:
            return campaign
        workflow_arn = self._workflows.start_create_campaign(
            CreateCampaignWorkflowInput(
                campaign_id=campaign.campaign_id,
                owner_id=campaign.owner_id,
                language=campaign.language,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                requested_at=campaign.created_at,
            )
        )
        updated = CampaignRecord.model_validate(
            {
                **campaign.model_dump(by_alias=False),
                "workflow_execution_arn": workflow_arn,
                "revision": campaign.revision + 1,
                "updated_at": now,
            }
        )
        try:
            return self._campaigns.save(updated, expected_revision=campaign.revision)
        except Exception:
            current = self._campaigns.get(campaign.campaign_id)
            if current is not None and current.workflow_execution_arn is not None:
                return current
            raise

    def _access_error(
        self,
        identity: AuthenticatedIdentity,
        campaign: CampaignRecord | None,
        correlation_id: str,
    ) -> HttpResult | None:
        if campaign is None:
            return self.error(
                status_code=404,
                code=ErrorCode.CAMPAIGN_NOT_FOUND,
                message="Campaign not found.",
                retryable=False,
                correlation_id=correlation_id,
            )
        if campaign.owner_id != identity.owner_id:
            return self.error(
                status_code=403,
                code=ErrorCode.NOT_AUTHORIZED,
                message="You do not have access to this campaign.",
                retryable=False,
                correlation_id=correlation_id,
            )
        return None

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return self.error(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="A campaign dependency is temporarily unavailable.",
            retryable=True,
            correlation_id=correlation_id,
        )


def _error_result(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool,
    correlation_id: str,
) -> HttpResult:
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


def _utc_now() -> datetime:
    return datetime.now(UTC)
