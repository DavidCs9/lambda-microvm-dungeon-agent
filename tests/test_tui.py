import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from dungeon_agent.orchestrator.contracts import GamePort, GameSnapshot, UsageSnapshot
from dungeon_agent.orchestrator.locales import Locale
from dungeon_agent.tui.app import DungeonApp


class FakeGame:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def opening_scene(self) -> str:
        return "Una puerta espera entre las sombras."

    def take_turn(self, action: str) -> str:
        self.actions.append(action)
        return "La puerta se abre."

    def snapshot(self) -> GameSnapshot:
        return GameSnapshot("Taberna", ("Llave",), "Escapar", 3, 2, "active", 1)

    def usage_snapshot(self) -> UsageSnapshot:
        return UsageSnapshot("test-model", 1, 10, 5, 15, 20.0, Decimal("0.0001"))

    def is_finished(self) -> bool:
        return False


def test_tui_runs_game_through_presentation_port() -> None:
    game = FakeGame()
    closed = False

    @contextmanager
    def runtime(_locale: Locale) -> Iterator[GamePort]:
        nonlocal closed
        try:
            yield game
        finally:
            closed = True

    async def exercise() -> None:
        app = DungeonApp(runtime, selected_language="es")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#game-view").display
            await pilot.click("#command-input")
            await pilot.press(*"abrir puerta", "enter")
            await pilot.pause()
            assert game.actions == ["abrir puerta"]

    asyncio.run(exercise())
    assert closed


def test_tui_starts_with_blank_language_selection() -> None:
    @contextmanager
    def runtime(_locale: Locale) -> Iterator[GamePort]:
        yield FakeGame()

    async def exercise() -> None:
        app = DungeonApp(runtime)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#language-view").display
            assert not app.query_one("#game-view").display

    asyncio.run(exercise())
