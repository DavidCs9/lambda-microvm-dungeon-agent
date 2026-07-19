"""Small connection records stored outside the game domain."""

from datetime import datetime

from pydantic import Field, model_validator

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.models import CampaignId, OwnerId, SessionId


class ConnectionRecord(ContractModel):
    connection_id: str = Field(min_length=1, max_length=128)
    owner_id: OwnerId
    connected_at: datetime
    expires_at: int = Field(gt=0)
    session_id: SessionId | None = None
    campaign_id: CampaignId | None = None
    after_sequence: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_aware_connected_at(self) -> ConnectionRecord:
        if self.connected_at.tzinfo is None or self.connected_at.utcoffset() is None:
            raise ValueError("connected_at must include a timezone")
        return self
