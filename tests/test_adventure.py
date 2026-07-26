import pytest

from dungeon_agent.api.adventure import initial_world, resolve_turn, start_adventure
from dungeon_agent.api.models import (
    AdventurePlan,
    Character,
    CharacterStats,
    Item,
    Location,
    PlayerCharacter,
    StateChanges,
    TurnProposal,
)


def sample_player() -> PlayerCharacter:
    return PlayerCharacter(
        name="Iria Vale",
        pronouns="she/her",
        archetype="Disgraced bell keeper",
        appearance="A rain-soaked traveler with silver-streaked hair and steady hands.",
        background="Iria left the village after failing to sound the warning bell years ago.",
        desire="Prove she can protect the village when it matters.",
        need="Accept help instead of carrying every failure alone.",
        connection_to_adventure="The stolen bell symbolizes the mistake that drove her away.",
        strength="She understands old mechanisms and keeps calm in danger.",
        flaw="Pride makes her hide uncertainty from potential allies.",
        contradiction="She distrusts authority but longs for the village's forgiveness.",
        npc_connection="Mara was her closest friend before Iria fled the village.",
        meaningful_item="Her father's cracked brass tuning fork.",
        open_question="Did someone deliberately stop her from sounding the bell years ago?",
        known_facts=["Mara knows the old mill.", "The tower needs the true bell."],
        opening_choices=["Question Mara", "Inspect the tower", "Brave the flooded mill"],
    )


def sample_plan() -> AdventurePlan:
    return AdventurePlan(
        title="The Storm Bell",
        premise="A magical storm surrounds a village whose warning bell was stolen.",
        objective="Recover the storm bell and ring it from the old tower.",
        opening="Rain lashes the village square. Find the stolen bell before the storm arrives.",
        starting_location_id="square",
        locations=[
            Location(
                id="square",
                name="Square",
                description="A flooded village square.",
                exits=["mill", "tower"],
            ),
            Location(
                id="mill",
                name="Mill",
                description="An abandoned mill creaks nearby.",
                exits=["square"],
            ),
            Location(
                id="tower",
                name="Tower",
                description="The old warning tower overlooks town.",
                exits=["square"],
            ),
        ],
        characters=[
            Character(
                id="mara",
                name="Mara",
                description="A worried miller.",
                motivation="Protect her village.",
            ),
        ],
        items=[
            Item(id="bell", name="Storm Bell", description="A small rune-covered bell."),
            Item(id="rope", name="Rope", description="A coil of sturdy rope."),
        ],
        starting_inventory=["rope"],
        secrets=["Mara hid the bell in the mill."],
        max_turns=10,
    )


def proposal(**changes: object) -> TurnProposal:
    values: dict[str, object] = {
        "intent": "Try a creative approach",
        "requires_roll": True,
        "difficulty": 12,
        "stat": "agility",
        "success_narration": "Your clever plan works and opens a new path.",
        "failure_narration": "The attempt fails, but you notice a useful clue.",
        "success_changes": StateChanges(add_facts=["A new path is open"]),
        "failure_changes": StateChanges(health_delta=-1, add_facts=["The stones are slippery"]),
        "suggestions": ["Talk to Mara", "Explore the mill"],
    }
    values.update(changes)
    # A governing stat is required exactly when a roll is required.
    if not values["requires_roll"]:
        values["stat"] = None
    return TurnProposal.model_validate(values)


def test_generated_adventure_starts_from_validated_plan() -> None:
    world = start_adventure("en", sample_plan(), sample_player())

    assert world.status == "active"
    assert world.location_id == "square"
    assert world.plan is not None
    assert world.plan.title == "The Storm Bell"


def test_start_adventure_seeds_the_declared_starting_inventory() -> None:
    world = start_adventure("en", sample_plan(), sample_player())

    assert world.inventory == ["rope"]


def test_start_adventure_defaults_to_an_empty_inventory() -> None:
    plan = sample_plan().model_copy(update={"starting_inventory": []})

    world = start_adventure("en", plan, sample_player())

    assert world.inventory == []


def test_plan_rejects_starting_inventory_with_unknown_item() -> None:
    payload = sample_plan().model_dump()
    payload["starting_inventory"] = ["ghost_key"]

    with pytest.raises(ValueError, match="unknown item"):
        AdventurePlan.model_validate(payload)


def test_d20_selects_and_applies_only_matching_branch() -> None:
    world = start_adventure("en", sample_plan(), sample_player())

    success = resolve_turn(world, "swing across", proposal(), roll=17)
    failure = resolve_turn(world, "swing across", proposal(), roll=4)

    assert success.last_result is not None and success.last_result.success
    assert "A new path is open" in success.facts
    assert success.health == 3
    assert failure.last_result is not None and not failure.last_result.success
    assert failure.health == 2
    assert "The stones are slippery" in failure.facts


def test_recent_turn_memory_is_bounded_and_carries_canonical_state() -> None:
    world = start_adventure("en", sample_plan(), sample_player())
    automatic = proposal(requires_roll=False, difficulty=None)

    for index in range(8):
        world = resolve_turn(world, f"wait {index}", automatic)

    assert len(world.recent_turns) == 6
    assert world.recent_turns[0].revision == 3
    assert world.recent_turns[-1].action == "wait 7"


def test_stat_modifier_shifts_the_outcome_of_the_same_roll() -> None:
    strong = sample_player().model_copy(
        update={"stats": CharacterStats(might=3, agility=3, wits=3, charm=3, resolve=3)}
    )
    weak = sample_player().model_copy(
        update={"stats": CharacterStats(might=1, agility=1, wits=1, charm=1, resolve=1)}
    )

    strong_turn = resolve_turn(
        start_adventure("en", sample_plan(), strong),
        "leap the gap",
        proposal(difficulty=12, stat="agility"),
        roll=9,
    )
    weak_turn = resolve_turn(
        start_adventure("en", sample_plan(), weak),
        "leap the gap",
        proposal(difficulty=12, stat="agility"),
        roll=9,
    )

    assert strong_turn.last_result is not None
    assert strong_turn.last_result.success  # 9 + 3 == 12 meets the difficulty
    assert strong_turn.last_result.roll == 9
    assert strong_turn.last_result.modifier == 3
    assert strong_turn.last_result.stat == "agility"
    assert weak_turn.last_result is not None
    assert not weak_turn.last_result.success  # 9 + 1 == 10 falls short
    assert weak_turn.last_result.modifier == 1


def test_turn_proposal_requires_a_governing_stat_when_rolling() -> None:
    with pytest.raises(ValueError, match="governing stat"):
        proposal(stat=None)


def test_model_cannot_invent_unknown_locations_or_items() -> None:
    world = start_adventure("en", sample_plan(), sample_player())

    with pytest.raises(ValueError, match="unknown location"):
        resolve_turn(
            world,
            "teleport",
            proposal(success_changes=StateChanges(location_id="moon")),
            roll=20,
        )
    with pytest.raises(ValueError, match="unknown item"):
        resolve_turn(
            world,
            "summon sword",
            proposal(success_changes=StateChanges(add_items=["magic_sword"])),
            roll=20,
        )


def test_model_cannot_teleport_through_an_undeclared_exit() -> None:
    world = start_adventure("en", sample_plan(), sample_player())
    world = resolve_turn(
        world,
        "walk to the tower",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(location_id="tower"),
        ),
    )

    with pytest.raises(ValueError, match="undeclared exit"):
        resolve_turn(
            world,
            "I teleport to the mill",
            proposal(success_changes=StateChanges(location_id="mill")),
            roll=20,
        )


def test_objective_phase_cannot_skip_or_regress() -> None:
    world = start_adventure("en", sample_plan(), sample_player())
    with pytest.raises(ValueError, match="skip an objective phase"):
        resolve_turn(
            world,
            "I solve everything",
            proposal(success_changes=StateChanges(objective_phase="resolution")),
            roll=20,
        )

    world = resolve_turn(
        world,
        "I find a clue",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(
                objective_phase="complication", add_facts=["A hidden cost appears"]
            ),
        ),
    )
    with pytest.raises(ValueError, match="phase backwards"):
        resolve_turn(
            world,
            "I ignore the complication",
            proposal(
                requires_roll=False,
                difficulty=None,
                success_changes=StateChanges(objective_phase="discovery"),
            ),
        )


def test_objective_completion_requires_progress_and_an_explicit_final_action() -> None:
    world = start_adventure("en", sample_plan(), sample_player())
    setup = proposal(
        requires_roll=False,
        difficulty=None,
        success_changes=StateChanges(add_facts=["The bell's hiding place is known"]),
    )
    premature = resolve_turn(world, "I resolve the problem", setup)
    developed = resolve_turn(
        premature,
        "I inspect the tower",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(
                objective_phase="complication", add_facts=["The tower is unstable"]
            ),
        ),
    )
    resolving = resolve_turn(
        developed,
        "I prepare the bell",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(objective_phase="resolution"),
        ),
    )
    victory = resolve_turn(
        resolving,
        "I ring the bell from the tower",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(objective_complete=True),
        ),
    )

    assert premature.status == "active"
    assert developed.status == "active"
    assert resolving.status == "active"
    assert victory.status == "won"


def test_objective_completion_and_turn_limit_are_authoritative() -> None:
    world = start_adventure("en", sample_plan(), sample_player())
    setup = proposal(
        requires_roll=False,
        difficulty=None,
        success_changes=StateChanges(
            objective_phase="complication", add_facts=["The tower is ready"]
        ),
    )
    world = resolve_turn(world, "inspect the tower", setup)
    world = resolve_turn(world, "ask Mara for the bell", setup)
    world = resolve_turn(
        world,
        "prepare the bell",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(objective_phase="resolution"),
        ),
    )
    victory = resolve_turn(
        world,
        "ring the bell",
        proposal(
            requires_roll=False,
            difficulty=None,
            success_changes=StateChanges(objective_complete=True),
        ),
    )
    assert victory.status == "won"

    current = world
    automatic = proposal(requires_roll=False, difficulty=None)
    for _ in range(10):
        current = resolve_turn(current, "wait", automatic)
        if current.status == "lost":
            break
    assert current.status == "lost"


def test_planning_world_rejects_turns() -> None:
    with pytest.raises(ValueError, match="not active"):
        resolve_turn(initial_world(), "anything", proposal(), roll=10)
