from dungeon_agent.localization import language_translation
from dungeon_agent.orchestrator.locales import ENGLISH, Locale
from dungeon_agent.orchestrator.narrator import BedrockNarrator
from dungeon_agent.orchestrator.session import MicrovmSession


class DungeonOrchestrator:
    """Coordinate player input, persistent world state, and narration."""

    def __init__(
        self,
        session: MicrovmSession,
        narrator: BedrockNarrator,
        locale: Locale = ENGLISH,
    ) -> None:
        self.session = session
        self.narrator = narrator
        self.locale = locale

    def take_turn(self, action: str) -> str:
        normalized = action.strip()
        if not normalized:
            raise ValueError(self.locale.empty_action)
        if len(normalized) > 500:
            raise ValueError(self.locale.long_action)
        world = self.session.apply_action(normalized)
        return self.narrator.narrate(normalized, world)

    def opening_scene(self) -> str:
        return self.narrator.narrate(self.locale.opening_action, self.session.read_world())

    def state_summary(self) -> str:
        world = self.session.read_world()
        location = world.get("location", self.locale.unknown_location)
        if isinstance(location, str):
            location = language_translation(self.locale.code, "adventure", location)
        revision = world.get("revision", 0)
        inventory = world.get("inventory", [])
        objective = world.get("objective", "-")
        health = world.get("health", "-")
        danger = world.get("danger", "-")
        status = world.get("status", "active")
        inventory_text = (
            ", ".join(str(item) for item in inventory)
            if isinstance(inventory, list) and inventory
            else self.locale.empty_inventory
        )
        return (
            f"{self.locale.location_label}: {location}\n"
            f"{self.locale.inventory_label}: {inventory_text}\n"
            f"{self.locale.objective_label}: {objective}\n"
            f"{self.locale.health_label}: {health}/3\n"
            f"{self.locale.danger_label}: {danger}/8\n"
            f"{self.locale.status_label}: {status}\n"
            f"{self.locale.turns_label}: {revision}"
        )

    def is_finished(self) -> bool:
        return self.session.read_world().get("status") in {"won", "lost"}


def play(orchestrator: DungeonOrchestrator, one_turn: str | None, locale: Locale) -> None:
    if one_turn is not None:
        print(orchestrator.take_turn(one_turn))
        return

    print(locale.welcome)
    print(orchestrator.opening_scene())
    print(f"\n{locale.help_text}")
    while True:
        try:
            action = input(locale.player_prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n{locale.ending}")
            return
        command = action.lower()
        if command in {"/quit", "/exit"}:
            print(f"\n{locale.ending}")
            return
        if command == "/help":
            print(f"\n{locale.help_text}")
            continue
        if command == "/state":
            print(f"\n{orchestrator.state_summary()}\n")
            continue
        if not action:
            continue
        try:
            print(f"\n{locale.narrator_label}:\n{orchestrator.take_turn(action)}\n")
            if orchestrator.is_finished():
                print(f"{orchestrator.state_summary()}\n")
                return
        except ValueError as error:
            print(f"\n{error}. {locale.invalid_action_hint}\n")
