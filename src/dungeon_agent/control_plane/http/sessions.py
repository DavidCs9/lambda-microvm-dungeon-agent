from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

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
    TurnId,
    TurnStartedPayload,
)
from dungeon_agent.control_plane.events import append_session_event
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
    TurnAcceptedEnvelope,
)
from dungeon_agent.control_plane.http.workflows import ensure_workflow
from dungeon_agent.control_plane.identifiers import new_session_id, new_turn_id
from dungeon_agent.control_plane.persistence.errors import SessionRevisionConflictError

SESSION_DEPENDENCY = "A session dependency is temporarily unavailable."


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
                return self._accepted(
                    self._ensure_workflow(
                        existing,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        now=now,
                    ),
                    correlation_id,
                )
            campaign = self._campaigns.get(request.campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)

        campaign_error = self._campaign_error(identity, campaign, correlation_id)
        if campaign_error is not None:
            return campaign_error
        assert campaign is not None

        quota_error = self._quota_error(identity, campaign.campaign_id, correlation_id)
        if quota_error is not None:
            return quota_error

        try:
            return self._accepted(
                self._ensure_workflow(
                    self._store.create(
                        SessionRecord(
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
                        ),
                        idempotency_key,
                    ),
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    now=now,
                ),
                correlation_id,
            )
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
        if self._turns is None:
            return self._dependency_error(correlation_id)
        session, error = self._load(identity, session_id, correlation_id)
        if error is not None:
            return error
        assert session is not None

        turn_id = session.last_turn_id
        if session.last_action_idempotency_key == idempotency_key and turn_id is not None:
            return self._turn_accepted(session_id, turn_id, "duplicate", correlation_id)

        conflict = self._turn_conflict(session, request.expected_revision, correlation_id)
        if conflict is not None:
            return conflict

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
            self._append(
                session_id,
                EventType.TURN_STARTED,
                TurnStartedPayload(
                    turn_id=turn_id,
                    expected_revision=request.expected_revision,
                    action=request.action,
                ),
                correlation_id,
            )
            self._turns.invoke_turn(command)
        except Exception:
            self._release_checkout(session_id, turn_id)
            return self._dependency_error(correlation_id)
        return self._turn_accepted(session_id, turn_id, "started", correlation_id)

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
            dependency_message=SESSION_DEPENDENCY,
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
        session, error = self._load(identity, session_id, correlation_id)
        if error is not None:
            return error
        assert session is not None

        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            return HttpResult(200, SessionEnvelope(session=session), correlation_id)
        if session.status in (SessionStatus.REQUESTED, SessionStatus.CREATING):
            return error_result(
                409,
                ErrorCode.SESSION_CONFLICT,
                "The session is still being created; retry once it settles.",
                True,
                correlation_id,
            )

        microvm_id = session.active_microvm_id
        try:
            saved = self._save(
                session,
                status=SessionStatus.COMPLETED,
                phase=SessionPhase.COMPLETED,
                active_microvm_id=None,
            )
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
            self._append(
                session_id,
                EventType.SESSION_COMPLETED,
                SessionCompletedPayload(outcome="abandoned", revision=saved.revision),
                correlation_id,
            )
        except Exception as error:
            print(f"session.completed emission failed on abandon: {type(error).__name__}")

        return HttpResult(200, SessionEnvelope(session=saved), correlation_id)

    def _accepted(self, session: SessionRecord, correlation_id: str) -> HttpResult:
        return HttpResult(
            202,
            SessionEnvelope(session=session),
            correlation_id,
            location=f"/sessions/{session.session_id}",
        )

    def _campaign_error(
        self, identity: AuthenticatedIdentity, campaign: CampaignRecord | None, correlation_id: str
    ) -> HttpResult | None:
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
        return None

    def _quota_error(
        self, identity: AuthenticatedIdentity, campaign_id: CampaignId, correlation_id: str
    ) -> HttpResult | None:
        try:
            active = self._store.count_active_by_owner(identity.owner_id)
            replays = self._store.count_by_campaign(campaign_id)
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
        return None

    def _turn_conflict(
        self, session: SessionRecord, expected_revision: int, correlation_id: str
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

    def _release_checkout(self, session_id: SessionId, turn_id: TurnId) -> None:
        try:
            current = self._store.get(session_id)
            if (
                current is None
                or current.status is not SessionStatus.ACTIVE
                or current.last_turn_id != turn_id
            ):
                return
            self._save(
                SessionRecord.model_validate(current),
                status=SessionStatus.READY,
                phase=SessionPhase.READY,
            )
        except Exception:
            print(f"checkout rollback failed: {session_id}")

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
            dependency_message=SESSION_DEPENDENCY,
            correlation_id=correlation_id,
        )
        return SessionRecord.model_validate(session) if session is not None else None, error

    def _conflict(self, message: str, correlation_id: str) -> HttpResult:
        return error_result(409, ErrorCode.SESSION_CONFLICT, message, False, correlation_id)

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return dependency_error(SESSION_DEPENDENCY, correlation_id)

    def _save(self, session: SessionRecord, **update: object) -> SessionRecord:
        update.update(revision=session.revision + 1, updated_at=self._clock())
        return SessionRecord.model_validate(
            self._store.save(session.model_copy(update=update), expected_revision=session.revision)
        )

    def _append(self, session_id: SessionId, event_type: EventType, payload: Any, cid: str) -> None:
        append_session_event(
            self._store, self._delivery, session_id, event_type, payload, cid, self._clock()
        )

    @staticmethod
    def _turn_accepted(
        session_id: SessionId,
        turn_id: TurnId,
        status: Literal["started", "duplicate"],
        correlation_id: str,
    ) -> HttpResult:
        return HttpResult(
            202,
            TurnAcceptedEnvelope(session_id=session_id, turn_id=turn_id, status=status),
            correlation_id,
        )
