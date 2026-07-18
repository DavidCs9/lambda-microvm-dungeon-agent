from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import ClassVar, cast

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, RichLog, Select, Static

from dungeon_agent.api.models import LanguageCode
from dungeon_agent.audio.contracts import AudioPort, SilentAudio
from dungeon_agent.orchestrator.contracts import GamePort, GameSnapshot, UsageSnapshot
from dungeon_agent.orchestrator.locales import LOCALES, Locale

RuntimeFactory = Callable[[Locale], AbstractContextManager[GamePort]]


class HelpScreen(ModalScreen[None]):
    """Display localized commands without replacing the game transcript."""

    BINDINGS: ClassVar = [
        Binding("escape", "close", "Close"),
        Binding("f1", "close", "Close"),
    ]

    def __init__(self, locale: Locale) -> None:
        super().__init__()
        self.locale = locale

    def compose(self) -> ComposeResult:
        yield Label(self.locale.help_text, id="help-content")

    def action_close(self) -> None:
        self.dismiss()


class EndingScreen(ModalScreen[None]):
    """Make the deterministic end of the adventure unmistakable."""

    BINDINGS: ClassVar = [
        Binding("enter", "close_game", "Close"),
        Binding("ctrl+q", "close_game", "Close"),
    ]

    def __init__(self, locale: Locale, state: GameSnapshot) -> None:
        super().__init__()
        self.locale = locale
        self.state = state

    def compose(self) -> ComposeResult:
        won = self.state.status == "won"
        title = self.locale.victory_title if won else self.locale.defeat_title
        message = self.locale.victory_message if won else self.locale.defeat_message
        yield Vertical(
            Label("◆", id="ending-crest"),
            Label(title, id="ending-title"),
            Label(message, id="ending-message"),
            Label(self.locale.close_game_hint, id="ending-hint"),
            id="ending-card",
        )

    def action_close_game(self) -> None:
        self.app.exit()


class DungeonApp(App[None]):
    """Full-screen, bilingual terminal client for one isolated game session."""

    CSS_PATH = "dungeon.tcss"
    TITLE = "The Locked Tavern"
    BINDINGS: ClassVar = [
        Binding("f1", "help", "Help"),
        Binding("f2", "state", "State"),
        Binding("f3", "stats", "Stats"),
        Binding("f4", "voice", "Voice/Voz"),
        Binding("f5", "music", "Music/Música"),
        Binding("ctrl+q", "quit_game", "Quit"),
    ]

    def __init__(
        self,
        runtime_factory: RuntimeFactory,
        selected_language: str | None = None,
        audio: AudioPort | None = None,
    ) -> None:
        super().__init__()
        self.runtime_factory = runtime_factory
        self.selected_language = selected_language
        self.audio = audio or SilentAudio()
        self.locale: Locale | None = None
        self.runtime: AbstractContextManager[GamePort] | None = None
        self.game: GamePort | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="language-view"):
            yield Static("◆", id="crest")
            yield Label("THE LOCKED TAVERN · LA TABERNA CERRADA", id="tavern-title")
            yield Label("Choose your language · Elige tu idioma", id="language-prompt")
            yield Select(
                ((locale.name, locale.code) for locale in LOCALES.values()),
                value=self.selected_language if self.selected_language is not None else Select.NULL,
                allow_blank=self.selected_language is None,
                id="language-select",
            )
            yield Label("Press Enter to begin · Presiona Enter para comenzar", id="start-hint")
        with Vertical(id="connecting-view", classes="hidden"):
            yield Static("◈", id="spinner-mark")
            yield Label("", id="connecting-message")
            yield Label("Creating an isolated, temporary world…", id="connecting-detail")
        with Vertical(id="game-view", classes="hidden"):
            with Horizontal(id="game-body"):
                with Vertical(id="story-pane"):
                    yield RichLog(id="story", wrap=True, markup=True, auto_scroll=True)
                    yield Input(id="command-input")
                with Vertical(id="sidebar"):
                    yield Static("", id="world-state", classes="side-section")
                    yield Static("", id="session-stats", classes="side-section")
            yield Static("", id="connection-status")
        yield Footer()

    def on_mount(self) -> None:
        if self.selected_language is not None:
            self._begin(self.selected_language)
        else:
            self.query_one("#language-select", Select).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#sidebar").set_class(event.size.width < 90, "hidden")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "language-select" and isinstance(event.value, str):
            should_begin = self.selected_language is None and self.locale is None
            self.selected_language = event.value
            if should_begin and self.query_one("#language-view").display:
                self._begin(event.value)

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", None)
        if (
            key == "enter"
            and self.query_one("#language-view").display
            and self.selected_language is not None
        ):
            self._begin(self.selected_language)

    def _begin(self, language: str) -> None:
        locale = LOCALES.get(cast(LanguageCode, language))
        if locale is None:
            return
        self.locale = locale
        self.title = locale.game_title
        self.query_one("#language-view").add_class("hidden")
        self.query_one("#connecting-view").remove_class("hidden")
        self.query_one("#connecting-message", Label).update(locale.starting)
        self.connect()

    @work(thread=True, exclusive=True, group="connection")
    def connect(self) -> None:
        assert self.locale is not None
        runtime: AbstractContextManager[GamePort] | None = None
        try:
            runtime = self.runtime_factory(self.locale)
            game = runtime.__enter__()
            opening = game.opening_scene()
        except Exception as error:  # Textual must restore the terminal for all provider failures.
            if runtime is not None:
                runtime.__exit__(type(error), error, error.__traceback__)
            self.call_from_thread(self._show_error, str(error))
            return
        self.runtime = runtime
        self.game = game
        self.call_from_thread(self._show_game, opening)

    def _show_error(self, message: str) -> None:
        self.query_one("#connecting-message", Label).update(f"Connection failed\n{message}")
        self.query_one("#connecting-detail", Label).update("Ctrl+Q to exit")

    def _show_game(self, opening: str) -> None:
        assert self.locale is not None
        self.query_one("#connecting-view").add_class("hidden")
        self.query_one("#game-view").remove_class("hidden")
        story = self.query_one("#story", RichLog)
        story.write(f"[bold cyan]{self.locale.narrator_label}[/bold cyan]")
        story.write(opening)
        self.audio.start()
        self.speak(opening)
        command_input = self.query_one("#command-input", Input)
        command_input.placeholder = self.locale.player_prompt.strip()
        command_input.focus()
        self._update_connection_status()
        self._refresh_sidebar()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-input":
            return
        action = event.value.strip()
        event.input.value = ""
        if not action:
            return
        command = action.casefold()
        if command in {"/quit", "/exit"}:
            self.action_quit_game()
        elif command == "/help":
            self.action_help()
        elif command == "/state":
            self.action_state()
        elif command == "/stats":
            self.action_stats()
        else:
            event.input.disabled = True
            self.query_one("#story", RichLog).write(f"\n[bold green]> {action}[/bold green]")
            self.take_turn(action)

    @work(thread=True, exclusive=True, group="turn")
    def take_turn(self, action: str) -> None:
        assert self.game is not None
        try:
            narration = self.game.take_turn(action)
            finished = self.game.is_finished()
        except (OSError, RuntimeError, ValueError) as error:
            self.call_from_thread(self._finish_turn, str(error), False, True)
            return
        self.call_from_thread(self._finish_turn, narration, finished, False)

    def _finish_turn(self, text: str, finished: bool, is_error: bool) -> None:
        assert self.locale is not None
        story = self.query_one("#story", RichLog)
        if is_error:
            story.write(f"[bold red]{text}[/bold red]\n{self.locale.invalid_action_hint}")
        else:
            story.write(f"[bold cyan]{self.locale.narrator_label}[/bold cyan]")
            story.write(text)
            self.speak(text)
        self._refresh_sidebar()
        command_input = self.query_one("#command-input", Input)
        command_input.disabled = finished
        if finished:
            assert self.game is not None
            state = self.game.snapshot()
            story.write(f"\n[bold]{self._format_state(state)}[/bold]")
            self.push_screen(EndingScreen(self.locale, state))
        else:
            command_input.focus()

    def _refresh_sidebar(self) -> None:
        if self.game is None or self.locale is None:
            return
        self.query_one("#world-state", Static).update(
            f"[bold]{self.locale.status_label.upper()}[/bold]\n\n"
            f"{self._format_state(self.game.snapshot())}"
        )
        self.query_one("#session-stats", Static).update(
            self._format_usage(self.game.usage_snapshot())
        )

    def _format_state(self, state: GameSnapshot) -> str:
        assert self.locale is not None
        inventory = ", ".join(state.inventory) or self.locale.empty_inventory
        return (
            f"{self.locale.location_label}: {state.location}\n"
            f"{self.locale.inventory_label}: {inventory}\n"
            f"{self.locale.objective_label}: {state.objective}\n"
            f"{self.locale.health_label}: {state.health}/3\n"
            f"{self.locale.danger_label}: {state.danger}/8\n"
            f"{self.locale.status_label}: {state.status}\n"
            f"{self.locale.turns_label}: {state.turns}"
        )

    def _format_usage(self, usage: UsageSnapshot) -> str:
        assert self.locale is not None
        cost = (
            f"${usage.estimated_cost:.8f} USD"
            if usage.estimated_cost is not None
            else self.locale.cost_unavailable
        )
        return (
            f"[bold]{self.locale.stats_title}[/bold]\n\n"
            f"{self.locale.model_label}: {usage.model_id}\n"
            f"{self.locale.calls_label}: {usage.calls}\n"
            f"{self.locale.total_tokens_label}: {usage.total_tokens:,}\n"
            f"{self.locale.model_latency_label}: {usage.model_latency_ms / 1_000:.2f} s\n"
            f"{self.locale.estimated_cost_label}: {cost}"
        )

    def action_help(self) -> None:
        if self.locale is not None and self.game is not None:
            self.push_screen(HelpScreen(self.locale))

    def action_state(self) -> None:
        self._refresh_sidebar()

    def action_stats(self) -> None:
        self._refresh_sidebar()

    @work(thread=True, group="audio")
    def speak(self, text: str) -> None:
        assert self.locale is not None
        try:
            self.audio.narrate(text, self.locale.code)
        except Exception:
            return

    def action_voice(self) -> None:
        self.audio.toggle_voice()
        self._update_connection_status()

    def action_music(self) -> None:
        self.audio.toggle_music()
        self._update_connection_status()

    def _update_connection_status(self) -> None:
        if self.locale is None:
            return
        voice = (
            self.locale.enabled_label if self.audio.voice_enabled else self.locale.disabled_label
        )
        music = (
            self.locale.enabled_label if self.audio.music_enabled else self.locale.disabled_label
        )
        self.query_one("#connection-status", Static).update(
            f"● {self.locale.ready}  ·  {self.locale.voice_label}: {voice}"
            f"  ·  {self.locale.music_label}: {music}"
        )

    def action_quit_game(self) -> None:
        self.exit()

    def on_unmount(self) -> None:
        try:
            self.audio.stop()
        finally:
            if self.runtime is not None:
                self.runtime.__exit__(None, None, None)
