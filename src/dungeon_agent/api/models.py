from pydantic import BaseModel, ConfigDict, Field

from dungeon_agent.domain.game import (
    AdventurePlan,
    Character,
    CharacterStats,
    GameStatus,
    Item,
    LanguageCode,
    Location,
    ObjectivePhase,
    PlayerCharacter,
    RecentTurn,
    StateChanges,
    StatName,
    TurnProposal,
    TurnResult,
    WorldState,
)

__all__ = [
    "AdventurePlan",
    "AdventureRequest",
    "Character",
    "CharacterStats",
    "GameStatus",
    "HealthResponse",
    "Item",
    "LanguageCode",
    "LanguageRequest",
    "Location",
    "ObjectivePhase",
    "PlayerCharacter",
    "RecentTurn",
    "StatName",
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
