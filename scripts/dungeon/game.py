from scripts.dungeon.locales import ENGLISH, Locale
from scripts.dungeon.narrator import BedrockNarrator
from scripts.dungeon.session import MicrovmSession


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
        if self.locale.code == "es" and location == "The Snapshot Tavern":
            location = "La Taberna Snapshot"
        revision = world.get("revision", 0)
        inventory = world.get("inventory", [])
        inventory_text = (
            ", ".join(str(item) for item in inventory)
            if isinstance(inventory, list) and inventory
            else self.locale.empty_inventory
        )
        return (
            f"{self.locale.location_label}: {location}\n"
            f"{self.locale.inventory_label}: {inventory_text}\n"
            f"{self.locale.turns_label}: {revision}"
        )


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
        except ValueError as error:
            print(f"\n{error}. {locale.invalid_action_hint}\n")
