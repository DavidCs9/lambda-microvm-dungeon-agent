"""HTTP-specific request, response, and authentication models."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.models import (
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
from dungeon_agent.domain.game import LanguageCode


class AuthenticatedIdentity(ContractModel):
    """Identity established by the API Gateway JWT authorizer."""

    owner_id: str = Field(min_length=3, max_length=100)


class CreateSessionRequest(ContractModel):
    """Player-controlled fields accepted by ``POST /sessions``."""

    language: LanguageCode
    campaign_id: CampaignId


class CreateCampaignRequest(ContractModel):
    """Player-controlled fields accepted by ``POST /campaigns``."""

    language: LanguageCode


class SubmitActionRequest(ContractModel):
    """Player-controlled fields accepted by ``POST /sessions/{sessionId}/actions``."""

    action: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(ge=0)


class SessionEnvelope(ContractModel):
    """Stable wrapper used by create and read responses."""

    version: Literal[1] = 1
    session: SessionRecord


class CampaignEnvelope(ContractModel):
    """Stable wrapper used by campaign create and read responses."""

    version: Literal[1] = 1
    campaign: CampaignRecord


class CampaignListEnvelope(ContractModel):
    """Owner-scoped campaign list for resume discovery."""

    version: Literal[1] = 1
    campaigns: tuple[CampaignRecord, ...]


class SessionListEnvelope(ContractModel):
    """Owner-scoped active-session list for the Continuar picker."""

    version: Literal[1] = 1
    sessions: tuple[SessionRecord, ...]


class OpeningEnvelope(ContractModel):
    """Opening document for a ready campaign, loaded without event replay."""

    version: Literal[1] = 1
    campaign_id: CampaignId
    opening: OpeningDocument


class TurnAcceptedEnvelope(ContractModel):
    """Acknowledgement that an action was checked out for asynchronous adjudication."""

    version: Literal[1] = 1
    session_id: SessionId
    turn_id: TurnId
    status: Literal["started", "duplicate"]


class EventListEnvelope(ContractModel):
    """Ordered, reconnect-safe event replay response."""

    version: Literal[1] = 1
    session_id: SessionId
    events: tuple[SessionEvent, ...]
    next_sequence: int = Field(ge=0)


class CampaignEventListEnvelope(ContractModel):
    """Ordered, reconnect-safe campaign event replay response."""

    version: Literal[1] = 1
    campaign_id: CampaignId
    events: tuple[CampaignEvent, ...]
    next_sequence: int = Field(ge=0)


HttpBody = (
    SessionEnvelope
    | CampaignEnvelope
    | CampaignListEnvelope
    | SessionListEnvelope
    | OpeningEnvelope
    | TurnAcceptedEnvelope
    | EventListEnvelope
    | CampaignEventListEnvelope
    | ErrorEnvelope
)


@dataclass(frozen=True, slots=True)
class HttpResult:
    """Transport-neutral result that an adapter can map to API Gateway."""

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
