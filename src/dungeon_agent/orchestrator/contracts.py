from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class GameSnapshot:
    """Presentation-neutral view of the current adventure state."""

    location: str
    inventory: tuple[str, ...]
    objective: str
    health: int
    danger: int
    status: str
    turns: int


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

    def take_turn(self, action: str) -> str: ...

    def snapshot(self) -> GameSnapshot: ...

    def usage_snapshot(self) -> UsageSnapshot: ...

    def is_finished(self) -> bool: ...
