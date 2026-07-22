"""Campaign HTTP use cases for the lab control plane."""

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
from dungeon_agent.control_plane.http.errors import Clock, error_result, utc_now
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CampaignEnvelope,
    CampaignEventListEnvelope,
    CampaignListEnvelope,
    CreateCampaignRequest,
    HttpResult,
    OpeningEnvelope,
)
from dungeon_agent.control_plane.identifiers import new_campaign_id

LOGGER = logging.getLogger(__name__)


class CampaignHttpHandlers:
    """Short campaign control operations; generation remains in the async workflow."""

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
        self._store = store
        self._workflows = workflows
        self._openings = openings
        self._portrait_presigner = portrait_presigner
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
        """Persist intent and start paid generation once per idempotency key."""
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
            return self.error(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Campaign limit reached for this player.",
                retryable=False,
                correlation_id=correlation_id,
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
        """List an owner's campaigns for resume discovery, optionally filtered by status."""
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
        """Return a campaign only to its authenticated owner."""
        try:
            campaign = self._store.get(campaign_id)
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
            campaign = self._store.get(campaign_id)
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
        """Replay durable campaign events after a client-owned sequence number."""
        try:
            campaign = self._store.get(campaign_id)
        except Exception:
            return self._dependency_error(correlation_id)
        access_error = self._access_error(identity, campaign, correlation_id)
        if access_error is not None:
            return access_error
        try:
            events = self._store.list_after(campaign_id, after)
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
        return error_result(
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
        updated = campaign.model_copy(
            update={
                "workflow_execution_arn": workflow_arn,
                "revision": campaign.revision + 1,
                "updated_at": now,
            }
        )
        try:
            saved = self._store.save(updated, expected_revision=campaign.revision)
            return CampaignRecord.model_validate(saved)
        except Exception:
            current = self._store.get(campaign.campaign_id)
            if current is not None and current.workflow_execution_arn is not None:
                return CampaignRecord.model_validate(current)
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
