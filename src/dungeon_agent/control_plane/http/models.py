"""HTTP-specific request, response, and authentication models."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from dungeon_agent.control_plane.domain.base import ContractModel
from dungeon_agent.control_plane.domain.models import (
    ErrorEnvelope,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.domain.game import LanguageCode


class AuthenticatedIdentity(ContractModel):
    """Identity established by the API Gateway JWT authorizer."""

    owner_id: str = Field(min_length=3, max_length=100)


class CreateSessionRequest(ContractModel):
    """Player-controlled fields accepted by ``POST /sessions``."""

    language: LanguageCode


class SessionEnvelope(ContractModel):
    """Stable wrapper used by create and read responses."""

    version: Literal[1] = 1
    session: SessionRecord


class EventListEnvelope(ContractModel):
    """Ordered, reconnect-safe event replay response."""

    version: Literal[1] = 1
    session_id: SessionId
    events: tuple[SessionEvent, ...]
    next_sequence: int = Field(ge=0)


HttpBody = SessionEnvelope | EventListEnvelope | ErrorEnvelope


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
