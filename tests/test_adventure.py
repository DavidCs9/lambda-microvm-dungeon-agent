import pytest

from dungeon_agent.api.adventure import initial_world, resolve_turn, start_adventure
from dungeon_agent.api.models import (
    AdventurePlan,
    Character,
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
        secrets=["Mara hid the bell in the mill."],
        max_turns=10,
    )


def proposal(**changes: object) -> TurnProposal:
    values: dict[str, object] = {
        "intent": "Try a creative approach",
        "requires_roll": True,
        "difficulty": 12,
        "success_narration": "Your clever plan works and opens a new path.",
        "failure_narration": "The attempt fails, but you notice a useful clue.",
        "success_changes": StateChanges(add_facts=["A new path is open"]),
        "failure_changes": StateChanges(health_delta=-1, add_facts=["The stones are slippery"]),
        "suggestions": ["Talk to Mara", "Explore the mill"],
    }
    values.update(changes)
    return TurnProposal.model_validate(values)


def test_generated_adventure_starts_from_validated_plan() -> None:
    world = start_adventure("en", sample_plan(), sample_player())

    assert world.status == "active"
    assert world.location_id == "square"
    assert world.plan is not None
    assert world.plan.title == "The Storm Bell"


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


def test_objective_completion_and_turn_limit_are_authoritative() -> None:
    world = start_adventure("en", sample_plan(), sample_player())
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
