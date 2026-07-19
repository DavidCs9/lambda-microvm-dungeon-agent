"""Campaign creation independent of HTTP and AWS transports."""

from collections.abc import Callable
from datetime import datetime

from dungeon_agent.control_plane.domain.enums import CampaignPhase, CampaignStatus
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    CampaignRecord,
    CreateCampaignCommand,
)
from dungeon_agent.control_plane.identifiers import new_campaign_id


class DefaultCampaignFactory:
    def __init__(self, id_factory: Callable[[], CampaignId] = new_campaign_id) -> None:
        self._id_factory = id_factory

    def create(self, command: CreateCampaignCommand, now: datetime) -> CampaignRecord:
        return CampaignRecord(
            campaign_id=self._id_factory(),
            owner_id=command.owner_id,
            language=command.language,
            status=CampaignStatus.REQUESTED,
            phase=CampaignPhase.REQUESTED,
            revision=0,
            last_event_sequence=0,
            created_at=now,
            updated_at=now,
        )
