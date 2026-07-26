"""Authoritative, transport-neutral game schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GameStatus = Literal["planning", "active", "won", "lost"]
LanguageCode = Literal["es", "en"]
StatName = Literal["might", "agility", "wits", "charm", "resolve"]
ObjectivePhase = Literal["discovery", "complication", "resolution"]


class CharacterStats(BaseModel):
    """Five simple attributes (1-3). The value is the roll modifier it grants."""

    model_config = ConfigDict(extra="forbid")

    might: int = Field(ge=1, le=3)
    agility: int = Field(ge=1, le=3)
    wits: int = Field(ge=1, le=3)
    charm: int = Field(ge=1, le=3)
    resolve: int = Field(ge=1, le=3)

    def modifier(self, stat: StatName) -> int:
        value: int = getattr(self, stat)
        return value


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=10, max_length=160)
    exits: list[str] = Field(max_length=4)


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=2, max_length=50)
    description: str = Field(min_length=5, max_length=160)
    motivation: str = Field(min_length=5, max_length=300)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=2, max_length=50)
    description: str = Field(min_length=5, max_length=160)


class PlayerCharacter(BaseModel):
    """A playable identity deliberately connected to one adventure."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=50)
    pronouns: str = Field(min_length=2, max_length=30)
    archetype: str = Field(min_length=3, max_length=80)
    appearance: str = Field(min_length=10, max_length=300)
    background: str = Field(min_length=30, max_length=500)
    desire: str = Field(min_length=10, max_length=240)
    need: str = Field(min_length=10, max_length=240)
    connection_to_adventure: str = Field(min_length=20, max_length=300)
    strength: str = Field(min_length=5, max_length=200)
    flaw: str = Field(min_length=5, max_length=200)
    contradiction: str = Field(min_length=10, max_length=300)
    npc_connection: str = Field(min_length=10, max_length=300)
    meaningful_item: str = Field(min_length=5, max_length=200)
    open_question: str = Field(min_length=10, max_length=300)
    known_facts: list[str] = Field(min_length=2, max_length=3)
    opening_choices: list[str] = Field(min_length=3, max_length=3)
    stats: CharacterStats = Field(
        # Average default keeps older persisted characters loadable; new characters
        # are generated with varied values for weak/strong variety.
        default_factory=lambda: CharacterStats(might=2, agility=2, wits=2, charm=2, resolve=2),
        description=(
            "Five attributes (1-3 each), chosen freely to fit the archetype. Each value is the "
            "modifier added to the d20 when that attribute governs a risky action."
        ),
    )


class AdventurePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=70)
    premise: str = Field(min_length=20, max_length=200)
    objective: str = Field(min_length=10, max_length=120)
    opening: str = Field(min_length=20, max_length=180)
    starting_location_id: str
    locations: list[Location] = Field(min_length=3, max_length=5)
    characters: list[Character] = Field(min_length=1, max_length=2)
    items: list[Item] = Field(min_length=2, max_length=5)
    starting_inventory: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Item ids (from items) the protagonist already carries at the start. "
            "Keep it small and coherent with the character and premise."
        ),
    )
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
        item_ids = {item.id for item in self.items}
        if len(item_ids) != len(self.items):
            raise ValueError("item ids must be unique")
        if len(set(self.starting_inventory)) != len(self.starting_inventory):
            raise ValueError("starting inventory ids must be unique")
        if any(item_id not in item_ids for item_id in self.starting_inventory):
            raise ValueError("starting inventory references an unknown item")
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
    objective_phase: ObjectivePhase | None = None
    objective_complete: bool = False


class TurnProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=2, max_length=300)
    requires_roll: bool
    difficulty: int | None = Field(default=None, ge=5, le=20)
    stat: StatName | None = None
    success_narration: str = Field(min_length=10, max_length=500)
    failure_narration: str = Field(min_length=10, max_length=500)
    success_changes: StateChanges
    failure_changes: StateChanges
    suggestions: list[str] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_difficulty(self) -> TurnProposal:
        if self.requires_roll != (self.difficulty is not None):
            raise ValueError("difficulty is required exactly when a roll is required")
        if self.requires_roll != (self.stat is not None):
            raise ValueError("a governing stat is required exactly when a roll is required")
        return self


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    intent: str
    success: bool
    narration: str
    roll: int | None = Field(default=None, ge=1, le=20)
    difficulty: int | None = Field(default=None, ge=5, le=20)
    stat: StatName | None = None
    modifier: int | None = Field(default=None, ge=0, le=3)
    suggestions: list[str] = Field(min_length=1, max_length=3)


class RecentTurn(BaseModel):
    """Compact canonical memory for the last few turns."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    action: str = Field(min_length=1, max_length=500)
    narration: str = Field(min_length=1, max_length=500)
    success: bool
    location_id: str
    inventory: list[str]
    facts: list[str] = Field(max_length=20)


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    language: LanguageCode
    plan: AdventurePlan | None = None
    player_character: PlayerCharacter | None = None
    location_id: str | None = None
    inventory: list[str]
    health: int = Field(ge=0, le=3)
    facts: list[str]
    objective_phase: ObjectivePhase = "discovery"
    recent_turns: list[RecentTurn] = Field(default_factory=list, max_length=6)
    status: GameStatus
    last_result: TurnResult | None = None
