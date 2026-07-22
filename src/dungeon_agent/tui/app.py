from dungeon_agent.orchestrator.game import play
from dungeon_agent.orchestrator.locales import select_language


class DungeonApp:
    def __init__(self, runtime_factory, selected_language: str | None = None, audio=None) -> None:
        self.runtime_factory = runtime_factory
        self.selected_language = selected_language

    def run(self) -> None:
        locale = select_language(self.selected_language)
        with self.runtime_factory(locale) as game:
            play(game, None, locale)
