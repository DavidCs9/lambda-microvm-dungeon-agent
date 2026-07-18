from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GameStatus = Literal["planning", "active", "won", "lost"]
LanguageCode = Literal["es", "en"]


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=10, max_length=300)
    exits: list[str] = Field(max_length=4)


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=2, max_length=50)
    description: str = Field(min_length=5, max_length=300)
    motivation: str = Field(min_length=5, max_length=300)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=2, max_length=50)
    description: str = Field(min_length=5, max_length=300)


class AdventurePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=70)
    premise: str = Field(min_length=20, max_length=400)
    objective: str = Field(min_length=10, max_length=180)
    opening: str = Field(min_length=20, max_length=500)
    starting_location_id: str
    locations: list[Location] = Field(min_length=3, max_length=5)
    characters: list[Character] = Field(min_length=1, max_length=2)
    items: list[Item] = Field(min_length=2, max_length=5)
    secrets: list[str] = Field(min_length=1, max_length=3)
    max_turns: int = Field(ge=8, le=15)

    @model_validator(mode="after")
    def validate_graph(self) -> AdventurePlan:
        location_ids = {location.id for location in self.locations}
        if len(location_ids) != len(self.locations):
            raise ValueError("location ids must be unique")
        if self.starting_location_id not in location_ids:
            raise ValueError("starting location must exist")
        for location in self.locations:
            if any(exit_id not in location_ids for exit_id in location.exits):
                raise ValueError(f"location {location.id} has an unknown exit")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("item ids must be unique")
        if len({character.id for character in self.characters}) != len(self.characters):
            raise ValueError("character ids must be unique")
        return self


class StateChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: str | None = None
    add_items: list[str] = Field(default_factory=list, max_length=2)
    remove_items: list[str] = Field(default_factory=list, max_length=2)
    add_facts: list[str] = Field(default_factory=list, max_length=3)
    health_delta: int = Field(default=0, ge=-2, le=1)
    objective_complete: bool = False


class TurnProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=2, max_length=300)
    requires_roll: bool
    difficulty: int | None = Field(default=None, ge=5, le=20)
    success_narration: str = Field(min_length=10, max_length=500)
    failure_narration: str = Field(min_length=10, max_length=500)
    success_changes: StateChanges
    failure_changes: StateChanges
    suggestions: list[str] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_difficulty(self) -> TurnProposal:
        if self.requires_roll != (self.difficulty is not None):
            raise ValueError("difficulty is required exactly when a roll is required")
        return self


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


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    intent: str
    success: bool
    narration: str
    roll: int | None = Field(default=None, ge=1, le=20)
    difficulty: int | None = Field(default=None, ge=5, le=20)
    suggestions: list[str] = Field(min_length=1, max_length=3)


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    language: LanguageCode
    plan: AdventurePlan | None = None
    location_id: str | None = None
    inventory: list[str]
    health: int = Field(ge=0, le=3)
    facts: list[str]
    status: GameStatus
    last_result: TurnResult | None = None


class HealthResponse(BaseModel):
    status: str
