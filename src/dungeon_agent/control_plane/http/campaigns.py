import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from dungeon_agent.control_plane.domain.enums import (
    CampaignPhase,
    CampaignStatus,
    ErrorCode,
)
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    CampaignRecord,
    CreateCampaignWorkflowInput,
)
from dungeon_agent.control_plane.http.errors import (
    Clock,
    dependency_error,
    error_result,
    load_owned,
    replay_events,
    utc_now,
)
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CampaignEnvelope,
    CampaignEventListEnvelope,
    CampaignListEnvelope,
    CreateCampaignRequest,
    HttpResult,
    OpeningEnvelope,
)
from dungeon_agent.control_plane.http.workflows import ensure_workflow
from dungeon_agent.control_plane.identifiers import new_campaign_id

LOGGER = logging.getLogger(__name__)
CAMPAIGN_DEPENDENCY = "A campaign dependency is temporarily unavailable."


class CampaignHttpHandlers:
    def __init__(
        self,
        store: Any,
        workflows: Any,
        *,
        openings: Any | None = None,
        portrait_presigner: Any | None = None,
        clock: Clock | None = None,
        campaign_id_factory: Callable[[], CampaignId] = new_campaign_id,
        max_campaigns_per_owner: int = 10,
    ) -> None:
        self._store, self._workflows = store, workflows
        self._openings, self._portrait_presigner = openings, portrait_presigner
        self._clock = clock or utc_now
        self._campaign_id_factory = campaign_id_factory
        self._max_campaigns_per_owner = max_campaigns_per_owner

    def create_campaign(
        self,
        identity: AuthenticatedIdentity,
        request: CreateCampaignRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HttpResult:
        now = self._clock()
        try:
            existing = self._store.find_by_idempotency_key(identity.owner_id, idempotency_key)
            if existing is not None:
                campaign = self._ensure_workflow(
                    existing,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    now=now,
                )
                return self._accepted(campaign, correlation_id)
            campaign_count = self._store.count_by_owner(identity.owner_id)
        except Exception:
            return self._dependency_error(correlation_id)

        if campaign_count >= self._max_campaigns_per_owner:
            return error_result(
                429,
                ErrorCode.QUOTA_EXCEEDED,
                "Campaign limit reached for this player.",
                False,
                correlation_id,
            )

        try:
            candidate = CampaignRecord(
                campaign_id=self._campaign_id_factory(),
                owner_id=identity.owner_id,
                language=request.language,
                status=CampaignStatus.REQUESTED,
                phase=CampaignPhase.REQUESTED,
                revision=0,
                last_event_sequence=0,
                created_at=now,
                updated_at=now,
            )
            persisted = self._store.create(candidate, idempotency_key)
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
        try:
            campaigns = self._store.list_by_owner(identity.owner_id, status=status)
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
        campaign, error = self._load(identity, campaign_id, correlation_id)
        if error is not None:
            return error
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
        campaign, error = self._load(identity, campaign_id, correlation_id)
        if error is not None:
            return error
        assert campaign is not None
        if campaign.status is not CampaignStatus.READY:
            return error_result(
                409,
                ErrorCode.CAMPAIGN_CONFLICT,
                "The campaign is not ready for play.",
                True,
                correlation_id,
            )
        if self._openings is None or campaign.character_ref is None:
            return self._dependency_error(correlation_id)
        try:
            opening = self._openings.load_opening(campaign.character_ref)
        except Exception:
            return self._dependency_error(correlation_id)
        return HttpResult(
            status_code=200,
            body=OpeningEnvelope(
                campaign_id=campaign_id,
                opening=opening,
                portrait_url=self._resolve_portrait_url(campaign.character_ref, correlation_id),
            ),
            correlation_id=correlation_id,
        )

    def _resolve_portrait_url(self, character_ref: str, correlation_id: str) -> str | None:
        """Best-effort presign; a missing or broken portrait never fails the opening."""
        if self._openings is None or self._portrait_presigner is None:
            return None
        try:
            portrait_key = self._openings.load_portrait_key(character_ref)
            if portrait_key is None:
                return None
            return cast(str, self._portrait_presigner.presigned_url(portrait_key))
        except Exception:
            LOGGER.exception("portrait_presign_failed", extra={"correlation_id": correlation_id})
            return None

    def list_events(
        self,
        identity: AuthenticatedIdentity,
        campaign_id: CampaignId,
        *,
        after: int,
        correlation_id: str,
    ) -> HttpResult:
        _campaign, error = self._load(identity, campaign_id, correlation_id)
        if error is not None:
            return error
        return replay_events(
            self._store,
            campaign_id,
            after=after,
            correlation_id=correlation_id,
            dependency_message=CAMPAIGN_DEPENDENCY,
            envelope=lambda events, next_sequence: CampaignEventListEnvelope(
                campaign_id=campaign_id,
                events=events,
                next_sequence=next_sequence,
            ),
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
        return CampaignRecord.model_validate(
            ensure_workflow(
                campaign,
                store=self._store,
                aggregate_id=campaign.campaign_id,
                now=now,
                start=lambda: self._workflows.start_create_campaign(
                    CreateCampaignWorkflowInput(
                        campaign_id=campaign.campaign_id,
                        owner_id=campaign.owner_id,
                        language=campaign.language,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        requested_at=campaign.created_at,
                    )
                ),
            )
        )

    def _load(
        self,
        identity: AuthenticatedIdentity,
        campaign_id: CampaignId,
        correlation_id: str,
    ) -> tuple[CampaignRecord | None, HttpResult | None]:
        campaign, error = load_owned(
            self._store,
            identity,
            campaign_id,
            resource_name="campaign",
            not_found_code=ErrorCode.CAMPAIGN_NOT_FOUND,
            dependency_message=CAMPAIGN_DEPENDENCY,
            correlation_id=correlation_id,
        )
        return CampaignRecord.model_validate(campaign) if campaign is not None else None, error

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return dependency_error(CAMPAIGN_DEPENDENCY, correlation_id)
