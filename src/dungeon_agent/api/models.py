from pydantic import BaseModel, Field

from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, TurnProposal
from dungeon_agent.domain.game import Character as Character
from dungeon_agent.domain.game import Item as Item
from dungeon_agent.domain.game import Location as Location
from dungeon_agent.domain.game import StateChanges as StateChanges
from dungeon_agent.domain.game import TurnResult as TurnResult
from dungeon_agent.domain.game import WorldState as WorldState


class TurnRequest(BaseModel):
    action: str = Field(min_length=1, max_length=500)
    proposal: TurnProposal


class LanguageRequest(BaseModel):
    language: LanguageCode


class AdventureRequest(BaseModel):
    language: LanguageCode
    plan: AdventurePlan
    player_character: PlayerCharacter


class HealthResponse(BaseModel):
    status: str
