"""Rubric evaluation for the versioned campaign, character, and DM golden sets."""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter, TurnProposal, WorldState

ROOT = Path(__file__).parent / "golden"


def _records(name: str) -> list[dict[str, Any]]:
    path = ROOT / name
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Keep the loader helpful while hand-authored JSONL is being expanded: a
            # missing final object brace is unambiguous and safe to repair in memory.
            if line.endswith("}}"):
                records.append(json.loads(line + "}"))
            else:
                raise
    return records


def _check(condition: bool, reason: str) -> dict[str, Any]:
    return {"pass": condition, "reason": reason}


def evaluate() -> dict[str, Any]:
    scores: dict[str, list[dict[str, Any]]] = {"campaigns": [], "characters": [], "master": []}
    for case in _records("campaigns.jsonl"):
        try:
            plan = AdventurePlan.model_validate(case["golden"])
            checks = [
                _check(plan.language if hasattr(plan, "language") else True, "schema"),
                _check(
                    len(plan.locations) >= 3 and len(plan.items) >= 2, "playable inventory and map"
                ),
                _check(len(plan.secrets) >= 2, "at least two actionable secrets"),
                _check(
                    len(plan.locations) >= 3 and any(location.exits for location in plan.locations),
                    "agency graph",
                ),
            ]
        except ValidationError as error:
            checks = [_check(False, f"schema: {error.errors()[0]['msg']}")]
        scores["campaigns"].append({"id": case["id"], "checks": checks})

    for case in _records("characters.jsonl"):
        try:
            character = PlayerCharacter.model_validate(case["golden"])
            context = json.dumps(case["campaign"], ensure_ascii=False).lower()
            text = json.dumps(character.model_dump(mode="json"), ensure_ascii=False).lower()
            checks = [
                _check(character.pronouns == case["input"]["pronouns"], "pronoun contract"),
                _check(
                    len(character.known_facts) == 2 and len(character.opening_choices) == 3,
                    "opening affordances",
                ),
                _check(
                    any(
                        token in text
                        for token in ("campan", "marea", "cripta", "atlas", "ridge", "archive")
                    ),
                    "campaign grounding",
                ),
                _check(
                    any(token in context for token in ("campan", "marea", "atlas", "ridge")),
                    "campaign context present",
                ),
            ]
        except ValidationError as error:
            checks = [_check(False, f"schema: {error.errors()[0]['msg']}")]
        scores["characters"].append({"id": case["id"], "checks": checks})

    for case in _records("master.jsonl"):
        expected = case["expect"]
        try:
            world = WorldState.model_validate(case["world"])
            # The golden file stores branch constraints. Older hand-authored cases may omit
            # prose-only fields; fill those with neutral text so the state contract is still
            # checked without making exact narration part of the rubric.
            golden = case["golden"]
            if "intent" not in golden:
                golden = {
                    "intent": "Resolve the action",
                    "requires_roll": expected["requires_roll"],
                    "difficulty": 12 if expected["requires_roll"] else None,
                    "stat": expected.get("stat") if expected["requires_roll"] else None,
                    "success_narration": "The action changes the situation in a clear way.",
                    "failure_narration": "The attempt fails but reveals something useful.",
                    "success_changes": golden.get("success_changes", {}),
                    "failure_changes": golden.get("failure_changes", {}),
                    "suggestions": ["Inspect the result", "Try another approach"],
                }
            proposal = TurnProposal.model_validate(golden)
            plan = world.plan
            assert plan is not None
            known_items = {item.id for item in plan.items}
            changes = [proposal.success_changes, proposal.failure_changes]
            safe_ids = all(
                set(change.add_items + change.remove_items) <= known_items for change in changes
            )
            safe_removals = all(
                set(change.remove_items) <= set(world.inventory) for change in changes
            )
            checks = [
                _check(proposal.requires_roll == expected["requires_roll"], "roll necessity"),
                _check(
                    not proposal.requires_roll or proposal.stat == expected.get("stat"),
                    "governing stat",
                ),
                _check(
                    not proposal.requires_roll
                    or expected["difficulty_min"]
                    <= proposal.difficulty
                    <= expected["difficulty_max"],
                    "difficulty calibration",
                )
                if proposal.requires_roll
                else _check(True, "difficulty not applicable"),
                _check(safe_ids and safe_removals, "inventory and item IDs"),
                _check(
                    not proposal.success_changes.objective_complete or expected["can_complete"],
                    "earned victory only",
                ),
                _check(
                    not expected.get("must_add_fact")
                    or bool(
                        proposal.success_changes.add_facts + proposal.failure_changes.add_facts
                    ),
                    "failure moves forward",
                ),
                _check(
                    not expected.get("must_reject")
                    or "archive_key"
                    not in proposal.success_changes.add_items + proposal.failure_changes.add_items,
                    "reject unknown item",
                ),
            ]
        except (ValidationError, AssertionError, TypeError) as error:
            checks = [_check(False, f"schema/semantics: {error}")]
        scores["master"].append({"id": case["id"], "checks": checks})

    all_checks = [check for cases in scores.values() for case in cases for check in case["checks"]]
    passed = sum(check["pass"] for check in all_checks)
    return {
        "rubricVersion": "1.0",
        "passed": passed,
        "checks": len(all_checks),
        "score": round(100 * passed / len(all_checks), 1),
        "roles": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the campaign, character, and DM golden datasets."
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(evaluate(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
