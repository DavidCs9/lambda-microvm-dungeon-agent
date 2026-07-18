import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from textual.widgets import Label

from dungeon_agent.api.models import LanguageCode
from dungeon_agent.orchestrator.contracts import GamePort, GameSnapshot, UsageSnapshot
from dungeon_agent.orchestrator.locales import Locale
from dungeon_agent.tui.app import DungeonApp


class FakeGame:
    def __init__(self, status: str = "active") -> None:
        self.actions: list[str] = []
        self.status = status

    def opening_scene(self) -> str:
        return "Una puerta espera entre las sombras."

    def take_turn(self, action: str) -> str:
        self.actions.append(action)
        return "La puerta se abre."

    def snapshot(self) -> GameSnapshot:
        return GameSnapshot("Taberna", ("Llave",), "Escapar", 3, 2, self.status, 1)

    def usage_snapshot(self) -> UsageSnapshot:
        return UsageSnapshot("test-model", 1, 10, 5, 15, 20.0, Decimal("0.0001"))

    def is_finished(self) -> bool:
        return self.status in {"won", "lost"}


class FakeAudio:
    def __init__(self) -> None:
        self.voice_enabled = True
        self.music_enabled = True
        self.started = False
        self.stopped = False
        self.narrations: list[tuple[str, LanguageCode]] = []

    def start(self) -> None:
        self.started = True

    def narrate(self, text: str, language: LanguageCode) -> None:
        self.narrations.append((text, language))

    def toggle_voice(self) -> bool:
        self.voice_enabled = not self.voice_enabled
        return self.voice_enabled

    def toggle_music(self) -> bool:
        self.music_enabled = not self.music_enabled
        return self.music_enabled

    def stop(self) -> None:
        self.stopped = True


def test_tui_runs_game_through_presentation_port() -> None:
    game = FakeGame()
    audio = FakeAudio()
    closed = False

    @contextmanager
    def runtime(_locale: Locale) -> Iterator[GamePort]:
        nonlocal closed
        try:
            yield game
        finally:
            closed = True

    async def exercise() -> None:
        app = DungeonApp(runtime, selected_language="es", audio=audio)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#game-view").display
            await pilot.click("#command-input")
            await pilot.press(*"abrir puerta", "enter")
            await pilot.pause()
            assert game.actions == ["abrir puerta"]
            await pilot.press("f4", "f5")
            assert not audio.voice_enabled
            assert not audio.music_enabled

    asyncio.run(exercise())
    assert closed
    assert audio.started
    assert audio.stopped
    assert audio.narrations[0][1] == "es"


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


def test_tui_shows_ending_screen_and_disables_input_after_victory() -> None:
    game = FakeGame(status="won")

    @contextmanager
    def runtime(_locale: Locale) -> Iterator[GamePort]:
        yield game

    async def exercise() -> None:
        app = DungeonApp(runtime, selected_language="es")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#command-input")
            await pilot.press(*"abrir puerta", "enter")
            await pilot.pause()
            assert app.query_one("#command-input").disabled
            assert str(app.screen.query_one("#ending-title", Label).render()) == "¡ESCAPASTE!"

    asyncio.run(exercise())
