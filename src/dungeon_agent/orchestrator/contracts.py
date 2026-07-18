from typing import Protocol

from dungeon_agent.domain.views import GameSnapshot, OpeningView, TurnView, UsageSnapshot

__all__ = ["GamePort", "GameSnapshot", "OpeningView", "TurnView", "UsageSnapshot"]


class GamePort(Protocol):
    """Operations exposed to terminal, web, or other presentation clients."""

    def opening_scene(self) -> OpeningView: ...

    def take_turn(self, action: str) -> TurnView: ...

    def snapshot(self) -> GameSnapshot: ...

    def usage_snapshot(self) -> UsageSnapshot: ...

    def is_finished(self) -> bool: ...
