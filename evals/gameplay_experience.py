"""Deterministic safety evaluation for generated adventure state transitions."""

import argparse
import json
from pathlib import Path

from dungeon_agent.api.adventure import resolve_turn, start_adventure
from dungeon_agent.api.models import (
    AdventurePlan,
    Character,
    Item,
    Location,
    PlayerCharacter,
    StateChanges,
    TurnProposal,
)


def _player() -> PlayerCharacter:
    return PlayerCharacter(
        name="Iria Vale",
        pronouns="she/her",
        archetype="Disgraced bell keeper",
        appearance="A rain-soaked traveler carrying an old brass tuning fork.",
        background="Iria fled after failing to warn the village during an earlier storm.",
        desire="Protect the village and earn another chance.",
        need="Learn to trust allies instead of carrying the danger alone.",
        connection_to_adventure="The missing bell embodies the failure that drove her away.",
        strength="She understands bells and ancient mechanisms.",
        flaw="Pride prevents her from asking for help.",
        contradiction="She resents the village but risks everything to save it.",
        npc_connection="Mara was her closest friend before she fled.",
        meaningful_item="Her father's cracked tuning fork.",
        open_question="Was the earlier disaster truly Iria's fault?",
        known_facts=["Mara knows the mill.", "The tower requires the real bell."],
        opening_choices=["Question Mara", "Inspect the tower", "Enter the flooded mill"],
    )


def _plan() -> AdventurePlan:
    return AdventurePlan(
        title="The Storm Bell",
        premise="A magical storm approaches a village whose warning bell is missing.",
        objective="Recover the storm bell and ring it from the old tower.",
        opening="Rain floods the square. Find and ring the stolen bell before the storm arrives.",
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
                description="A dark abandoned mill nearby.",
                exits=["square"],
            ),
            Location(
                id="tower",
                name="Tower",
                description="The warning tower above town.",
                exits=["square"],
            ),
        ],
        characters=[
            Character(
                id="mara",
                name="Mara",
                description="A worried miller.",
                motivation="Save the village.",
            )
        ],
        items=[
            Item(id="bell", name="Storm Bell", description="A rune-covered warning bell."),
            Item(id="rope", name="Rope", description="A sturdy coil of rope."),
        ],
        secrets=["Mara knows the bell is hidden in the mill."],
        max_turns=8,
    )


def _proposal(*, success: StateChanges, failure: StateChanges) -> TurnProposal:
    return TurnProposal(
        intent="Attempt a creative solution",
        requires_roll=True,
        difficulty=12,
        success_narration="The improvised solution works and changes the situation.",
        failure_narration="The attempt fails, but reveals useful information.",
        success_changes=success,
        failure_changes=failure,
        suggestions=["Try another approach", "Ask Mara for help"],
    )


def evaluate() -> dict[str, object]:
    initial = start_adventure("en", _plan(), _player())
    proposal = _proposal(
        success=StateChanges(add_items=["rope"], add_facts=["A safe crossing exists"]),
        failure=StateChanges(health_delta=-1, add_facts=["The flood is dangerous"]),
    )
    success = resolve_turn(initial, "build a bridge", proposal, roll=18)
    failure = resolve_turn(initial, "build a bridge", proposal, roll=4)
    victory = resolve_turn(
        success,
        "ring the bell",
        TurnProposal(
            intent="Complete the objective",
            requires_roll=False,
            difficulty=None,
            success_narration="The bell rings and the village prepares for the storm.",
            failure_narration="The bell remains silent for now.",
            success_changes=StateChanges(objective_complete=True),
            failure_changes=StateChanges(),
            suggestions=["Celebrate", "Help the villagers"],
        ),
    )
    dimensions = {
        "validated_generated_world": 15 if initial.plan is not None else 0,
        "roleplay_context_persisted": 25
        if initial.player_character is not None
        and len(initial.player_character.known_facts) >= 2
        and len(initial.player_character.opening_choices) == 3
        else 0,
        "d20_branching": 15 if success.health == 3 and failure.health == 2 else 0,
        "creative_state_progress": 15 if "A safe crossing exists" in success.facts else 0,
        "authoritative_victory": 15 if victory.status == "won" else 0,
        "state_consistency": 15 if victory.revision == 2 and "rope" in victory.inventory else 0,
    }
    return {
        "rubricVersion": "3.0",
        "score": sum(dimensions.values()),
        "maximumScore": 100,
        "dimensions": dimensions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate generated-adventure state safety.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    serialized = json.dumps(evaluate(), indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
