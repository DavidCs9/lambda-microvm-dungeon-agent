"""Sortable identifiers used by control-plane adapters."""

from uuid import uuid7

from dungeon_agent.plane_shared.domain.models import CampaignId, EventId, SessionId, TurnId

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encoded_uuid() -> str:
    value = uuid7().int
    characters = ["0"] * 26
    for index in range(25, -1, -1):
        value, remainder = divmod(value, 32)
        characters[index] = _CROCKFORD[remainder]
    return "".join(characters)


def new_session_id() -> SessionId:
    return f"ses_{_encoded_uuid()}"


def new_event_id() -> EventId:
    return f"evt_{_encoded_uuid()}"


def new_turn_id() -> TurnId:
    return f"trn_{_encoded_uuid()}"


def new_campaign_id() -> CampaignId:
    return f"cam_{_encoded_uuid()}"
