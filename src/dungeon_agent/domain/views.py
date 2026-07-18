"""Presentation-neutral views shared by terminal and web clients."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FrozenView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GameSnapshot(FrozenView):
    title: str
    location: str
    inventory: tuple[str, ...]
    objective: str
    health: int
    turns_remaining: int
    status: str
    turns: int
    facts: tuple[str, ...] = ()


class OpeningView(FrozenView):
    title: str
    scene: str
    character_name: str
    pronouns: str
    archetype: str
    appearance: str
    background: str
    desire: str
    connection: str
    strength: str
    flaw: str
    meaningful_item: str
    known_facts: tuple[str, ...]
    opening_choices: tuple[str, ...]


class TurnView(FrozenView):
    narration: str
    success: bool
    roll: int | None = Field(default=None, ge=1, le=20)
    difficulty: int | None = Field(default=None, ge=5, le=20)
    suggestions: tuple[str, ...]


class UsageSnapshot(FrozenView):
    model_id: str
    calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    model_latency_ms: float = Field(ge=0)
    estimated_cost: Decimal | None
