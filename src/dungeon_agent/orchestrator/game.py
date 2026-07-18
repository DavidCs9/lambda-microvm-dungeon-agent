from dungeon_agent.api.models import AdventurePlan
from dungeon_agent.orchestrator.agents import AdventureArchitect, DungeonMaster
from dungeon_agent.orchestrator.contracts import GameSnapshot, TurnView, UsageSnapshot
from dungeon_agent.orchestrator.locales import ENGLISH, Locale
from dungeon_agent.orchestrator.observability import SessionMetrics
from dungeon_agent.orchestrator.session import MicrovmSession


def _integer(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


class DungeonOrchestrator:
    """Coordinate generated adventures, free-form adjudication, and validated state."""

    def __init__(
        self,
        session: MicrovmSession,
        architect: AdventureArchitect,
        dungeon_master: DungeonMaster,
        metrics: SessionMetrics,
        locale: Locale = ENGLISH,
    ) -> None:
        self.session = session
        self.architect = architect
        self.dungeon_master = dungeon_master
        self.metrics = metrics
        self.locale = locale
        self._world: dict[str, object] | None = None

    def opening_scene(self) -> str:
        plan = self.architect.create(self.locale.code)
        self._world = self.session.start_adventure(self.locale.code, plan)
        return plan.opening

    def take_turn(self, action: str) -> TurnView:
        normalized = action.strip()
        if not normalized:
            raise ValueError(self.locale.empty_action)
        if len(normalized) > 500:
            raise ValueError(self.locale.long_action)
        world = self._current_world()
        proposal = self.dungeon_master.adjudicate(normalized, world)
        self._world = self.session.apply_turn(normalized, proposal)
        result = self._world.get("last_result")
        if not isinstance(result, dict):
            raise RuntimeError("MicroVM returned no turn result")
        return TurnView(
            narration=str(result.get("narration", "")),
            success=result.get("success") is True,
            roll=_optional_integer(result.get("roll")),
            difficulty=_optional_integer(result.get("difficulty")),
            suggestions=tuple(
                str(item) for item in result.get("suggestions", []) if isinstance(item, str)
            ),
        )

    def snapshot(self) -> GameSnapshot:
        world = self._current_world()
        plan_data = world.get("plan")
        if not isinstance(plan_data, dict):
            return GameSnapshot(
                title=self.locale.game_title,
                location=self.locale.unknown_location,
                inventory=(),
                objective="-",
                health=_integer(world.get("health"), 3),
                turns_remaining=0,
                status=str(world.get("status", "planning")),
                turns=_integer(world.get("revision")),
            )
        plan = AdventurePlan.model_validate(plan_data)
        locations = {location.id: location.name for location in plan.locations}
        items = {item.id: item.name for item in plan.items}
        inventory = world.get("inventory")
        revision = _integer(world.get("revision"))
        facts = world.get("facts")
        return GameSnapshot(
            title=plan.title,
            location=locations.get(str(world.get("location_id")), self.locale.unknown_location),
            inventory=tuple(items.get(str(item), str(item)) for item in inventory)
            if isinstance(inventory, list)
            else (),
            objective=plan.objective,
            health=_integer(world.get("health")),
            turns_remaining=max(0, plan.max_turns - revision),
            status=str(world.get("status", "active")),
            turns=revision,
            facts=tuple(str(fact) for fact in facts) if isinstance(facts, list) else (),
        )

    def is_finished(self) -> bool:
        return self._current_world().get("status") in {"won", "lost"}

    def state_summary(self) -> str:
        snapshot = self.snapshot()
        inventory_text = ", ".join(snapshot.inventory) or self.locale.empty_inventory
        return (
            f"{self.locale.location_label}: {snapshot.location}\n"
            f"{self.locale.inventory_label}: {inventory_text}\n"
            f"{self.locale.objective_label}: {snapshot.objective}\n"
            f"{self.locale.health_label}: {snapshot.health}/3\n"
            f"{self.locale.danger_label}: {snapshot.turns_remaining}\n"
            f"{self.locale.status_label}: {snapshot.status}\n"
            f"{self.locale.turns_label}: {snapshot.turns}"
        )

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
        return UsageSnapshot(
            model_id=self.metrics.model_id,
            calls=self.metrics.calls,
            input_tokens=self.metrics.input_tokens,
            output_tokens=self.metrics.output_tokens,
            total_tokens=self.metrics.total_tokens,
            model_latency_ms=self.metrics.model_latency_ms,
            estimated_cost=self.metrics.estimated_cost,
        )

    def _current_world(self) -> dict[str, object]:
        if self._world is None:
            self._world = self.session.read_world()
        return self._world


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def play(orchestrator: DungeonOrchestrator, one_turn: str | None, locale: Locale) -> None:
    print(locale.welcome)
    print(orchestrator.opening_scene())
    if one_turn is not None:
        print(orchestrator.take_turn(one_turn).narration)
        return
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
            turn = orchestrator.take_turn(action)
            if turn.roll is not None:
                print(f"\n[d20: {turn.roll} / {turn.difficulty}]")
            print(f"\n{locale.narrator_label}:\n{turn.narration}\n")
            if orchestrator.is_finished():
                print(f"{orchestrator.state_summary()}\n")
                return
        except ValueError as error:
            print(f"\n{error}. {locale.invalid_action_hint}\n")
