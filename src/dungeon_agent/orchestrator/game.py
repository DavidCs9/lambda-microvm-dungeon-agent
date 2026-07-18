from dungeon_agent.localization import language_translation
from dungeon_agent.orchestrator.contracts import GameSnapshot, UsageSnapshot
from dungeon_agent.orchestrator.locales import ENGLISH, Locale
from dungeon_agent.orchestrator.narrator import BedrockNarrator
from dungeon_agent.orchestrator.session import MicrovmSession


def _integer(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


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
        world = self.session.read_world()
        story = world.get("story")
        if isinstance(story, list) and story and isinstance(story[0], str):
            return story[0]
        return self.narrator.narrate(self.locale.opening_action, world)

    def state_summary(self) -> str:
        snapshot = self.snapshot()
        inventory_text = ", ".join(snapshot.inventory) or self.locale.empty_inventory
        return (
            f"{self.locale.location_label}: {snapshot.location}\n"
            f"{self.locale.inventory_label}: {inventory_text}\n"
            f"{self.locale.objective_label}: {snapshot.objective}\n"
            f"{self.locale.health_label}: {snapshot.health}/3\n"
            f"{self.locale.danger_label}: {snapshot.danger}/8\n"
            f"{self.locale.status_label}: {snapshot.status}\n"
            f"{self.locale.turns_label}: {snapshot.turns}"
        )

    def snapshot(self) -> GameSnapshot:
        world = self.session.read_world()
        location = world.get("location", self.locale.unknown_location)
        if isinstance(location, str):
            location = language_translation(self.locale.code, "adventure", location)
        inventory = world.get("inventory")
        return GameSnapshot(
            location=str(location),
            inventory=tuple(
                language_translation(self.locale.code, "adventure", str(item)) for item in inventory
            )
            if isinstance(inventory, list)
            else (),
            objective=str(world.get("objective", "-")),
            health=_integer(world.get("health")),
            danger=_integer(world.get("danger")),
            status=str(world.get("status", "active")),
            turns=_integer(world.get("revision")),
        )

    def is_finished(self) -> bool:
        return self.session.read_world().get("status") in {"won", "lost"}

    def stats_summary(self) -> str:
        usage = self.usage_snapshot()
        cost_text = (
            f"${usage.estimated_cost:.8f} USD"
            if usage.estimated_cost is not None
            else self.locale.cost_unavailable
        )
        return (
            f"{self.locale.stats_title}\n"
            f"{self.locale.model_label}: {usage.model_id}\n"
            f"{self.locale.calls_label}: {usage.calls}\n"
            f"{self.locale.input_tokens_label}: {usage.input_tokens:,}\n"
            f"{self.locale.output_tokens_label}: {usage.output_tokens:,}\n"
            f"{self.locale.total_tokens_label}: {usage.total_tokens:,}\n"
            f"{self.locale.model_latency_label}: {usage.model_latency_ms / 1_000:.2f} s\n"
            f"{self.locale.estimated_cost_label}: {cost_text}"
        )

    def usage_snapshot(self) -> UsageSnapshot:
        metrics = self.narrator.metrics
        return UsageSnapshot(
            model_id=metrics.model_id,
            calls=metrics.calls,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            total_tokens=metrics.total_tokens,
            model_latency_ms=metrics.model_latency_ms,
            estimated_cost=metrics.estimated_cost,
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
        except EOFError, KeyboardInterrupt:
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
        if command == "/stats":
            print(f"\n{orchestrator.stats_summary()}\n")
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
