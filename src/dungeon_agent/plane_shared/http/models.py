from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from dungeon_agent.domain.game import LanguageCode
from dungeon_agent.plane_shared.domain.base import ContractModel
from dungeon_agent.plane_shared.domain.models import (
    CampaignEvent,
    CampaignId,
    CampaignRecord,
    ErrorEnvelope,
    OpeningDocument,
    SessionEvent,
    SessionId,
    SessionRecord,
    TurnId,
)


class AuthenticatedIdentity(ContractModel):
    owner_id: str = Field(min_length=3, max_length=100)


class CreateSessionRequest(ContractModel):
    language: LanguageCode
    campaign_id: CampaignId


class CreateCampaignRequest(ContractModel):
    language: LanguageCode


class SubmitActionRequest(ContractModel):
    action: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(ge=0)


class SpeechRequest(ContractModel):
    text: str = Field(min_length=1, max_length=4000)
    language: LanguageCode


class SessionEnvelope(ContractModel):
    version: Literal[1] = 1
    session: SessionRecord


class CampaignEnvelope(ContractModel):
    version: Literal[1] = 1
    campaign: CampaignRecord


class CampaignListEnvelope(ContractModel):
    version: Literal[1] = 1
    campaigns: tuple[CampaignRecord, ...]


class SessionListEnvelope(ContractModel):
    version: Literal[1] = 1
    sessions: tuple[SessionRecord, ...]


class OpeningEnvelope(ContractModel):
    version: Literal[1] = 1
    campaign_id: CampaignId
    opening: OpeningDocument
    portrait_url: str | None = None


class TurnAcceptedEnvelope(ContractModel):
    version: Literal[1] = 1
    session_id: SessionId
    turn_id: TurnId
    status: Literal["started", "duplicate"]


class EventListEnvelope(ContractModel):
    version: Literal[1] = 1
    session_id: SessionId
    events: tuple[SessionEvent, ...]
    next_sequence: int = Field(ge=0)


class CampaignEventListEnvelope(ContractModel):
    version: Literal[1] = 1
    campaign_id: CampaignId
    events: tuple[CampaignEvent, ...]
    next_sequence: int = Field(ge=0)


class SpeechEnvelope(ContractModel):
    version: Literal[1] = 1
    url: str = Field(min_length=1)
    expires_in_seconds: int = Field(ge=1, le=3600)
    cache_hit: bool


HttpBody = (
    SessionEnvelope
    | CampaignEnvelope
    | CampaignListEnvelope
    | SessionListEnvelope
    | OpeningEnvelope
    | TurnAcceptedEnvelope
    | EventListEnvelope
    | CampaignEventListEnvelope
    | SpeechEnvelope
    | ErrorEnvelope
)


@dataclass(frozen=True, slots=True)
class HttpResult:
    status_code: int
    body: HttpBody
    correlation_id: str
    location: str | None = None

    def headers(self) -> dict[str, str]:
        headers = {
            "cache-control": "no-store",
            "content-type": "application/json",
            "x-correlation-id": self.correlation_id,
        }
        if self.location is not None:
            headers["location"] = self.location
        return headers
