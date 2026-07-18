from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GameStatus = Literal["active", "won", "lost"]
ActionIntent = Literal["explore", "inspect", "talk", "take", "use", "escape", "unknown"]
LanguageCode = Literal["es", "en"]


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: ActionIntent
    success: bool
    summary: str
    consequence: str
    suggestions: list[str] = Field(min_length=1, max_length=3)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=500)


class LanguageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: LanguageCode


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    language: LanguageCode
    location: str
    inventory: list[str]
    story: list[str]
    health: int = Field(ge=0, le=3)
    danger: int = Field(ge=0, le=8)
    objective: str
    discovered_clues: list[str]
    npc_relationships: dict[str, int]
    completed_events: list[str]
    status: GameStatus
    ending: str | None = None
    last_result: ActionResult | None = None


class HealthResponse(BaseModel):
    status: str
