from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class GameSnapshot:
    """Presentation-neutral view of the current adventure state."""

    title: str
    location: str
    inventory: tuple[str, ...]
    objective: str
    health: int
    turns_remaining: int
    status: str
    turns: int
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnView:
    """Presentation-neutral result of one adjudicated player action."""

    narration: str
    success: bool
    roll: int | None
    difficulty: int | None
    suggestions: tuple[str, ...]


@dataclass(frozen=True)
class UsageSnapshot:
    """Presentation-neutral view of model usage for one game session."""

    model_id: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model_latency_ms: float
    estimated_cost: Decimal | None


class GamePort(Protocol):
    """Operations exposed to terminal, web, or other presentation clients."""

    def opening_scene(self) -> str: ...

    def take_turn(self, action: str) -> TurnView: ...

    def snapshot(self) -> GameSnapshot: ...

    def usage_snapshot(self) -> UsageSnapshot: ...

    def is_finished(self) -> bool: ...
