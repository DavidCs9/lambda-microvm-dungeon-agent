from pydantic import BaseModel, ConfigDict, Field

from dungeon_agent.domain.game import (
    AdventurePlan,
    Character,
    GameStatus,
    Item,
    LanguageCode,
    Location,
    PlayerCharacter,
    StateChanges,
    TurnProposal,
    TurnResult,
    WorldState,
)

__all__ = [
    "AdventurePlan",
    "AdventureRequest",
    "Character",
    "GameStatus",
    "HealthResponse",
    "Item",
    "LanguageCode",
    "LanguageRequest",
    "Location",
    "PlayerCharacter",
    "StateChanges",
    "TurnProposal",
    "TurnRequest",
    "TurnResult",
    "WorldState",
]


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=500)
    proposal: TurnProposal


class LanguageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: LanguageCode


class AdventureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: LanguageCode
    plan: AdventurePlan
    player_character: PlayerCharacter


class HealthResponse(BaseModel):
    status: str
