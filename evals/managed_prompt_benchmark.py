"""Benchmark versioned Bedrock managed prompts against the golden dataset."""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ValidationError

from dungeon_agent.data_plane.agents.roles import _unknown_item_proposal
from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter, TurnProposal, WorldState
from dungeon_agent.orchestrator.observability import SessionMetrics

ROOT = Path(__file__).parent / "golden"
DEFAULT_REGION = "us-east-2"


def _records(name: str) -> list[dict[str, Any]]:
    path = ROOT / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def create_client(profile: str, region: str) -> Any:
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=90,
            retries={"mode": "adaptive", "total_max_attempts": 5},
            user_agent_extra="lambda-microvm-dungeon-agent-managed-eval/1.0.0",
        ),
    )


def invoke_managed(
    client: Any,
    prompt: dict[str, str],
    variables: dict[str, str],
    output_model: type[BaseModel],
    tool_name: str,
    metrics: SessionMetrics,
) -> BaseModel:
    current = {**variables, "repair_feedback": "No repair is available in evaluation."}
    started = time.perf_counter()
    response = client.converse(
        modelId=prompt["promptArn"],
        promptVariables={name: {"text": value} for name, value in current.items()},
        requestMetadata={
            "project": "lambda-microvm-dungeon-agent",
            "eval": "golden-first-pass",
            "role": prompt["role"],
        },
    )
    usage = response["usage"]
    metrics.record(
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
        latency_ms=(time.perf_counter() - started) * 1_000,
    )
    for block in response["output"]["message"]["content"]:
        tool_use = block.get("toolUse")
        if tool_use is not None and tool_use["name"] == tool_name:
            return output_model.model_validate(tool_use["input"])
    raise RuntimeError(f"managed prompt did not call required tool {tool_name}")


def _sample(
    case_id: str,
    role: str,
    checks: dict[str, bool],
    critical: tuple[str, ...],
    metrics: SessionMetrics,
    error: str | None = None,
) -> dict[str, Any]:
    passed = sum(checks.values())
    return {
        "caseId": case_id,
        "role": role,
        "score": round(100 * passed / len(checks), 1) if checks else 0,
        "checks": checks,
        "criticalPass": error is None and all(checks.get(name, False) for name in critical),
        "error": error,
        "metrics": metrics.snapshot(),
    }


def _campaign_case(client: Any, prompt: dict[str, str], case: dict[str, Any]) -> dict[str, Any]:
    metrics = SessionMetrics.start(prompt["modelId"])
    try:
        plan = invoke_managed(
            client,
            prompt,
            {
                "language_name": "Spanish" if case["language"] == "es" else "English",
                "theme": case["input"]["theme"],
            },
            AdventurePlan,
            "create_adventure",
            metrics,
        )
        assert isinstance(plan, AdventurePlan)
        checks = {
            "valid_structure": len(plan.locations) >= 3 and len(plan.items) >= 2,
            "actionable_secrets": len(plan.secrets) >= 2,
            "agency_graph": sum(bool(location.exits) for location in plan.locations) >= 3,
            "valid_start": plan.starting_location_id
            in {location.id for location in plan.locations},
        }
        return _sample(
            case["id"],
            "campaign",
            checks,
            ("valid_structure", "valid_start"),
            metrics,
        )
    except (BotoCoreError, ClientError, RuntimeError, ValidationError, ValueError) as error:
        return _sample(
            case["id"],
            "campaign",
            {"valid_output": False},
            ("valid_output",),
            metrics,
            str(error),
        )


def _character_case(
    client: Any,
    prompt: dict[str, str],
    case: dict[str, Any],
    campaigns: dict[str, AdventurePlan],
) -> dict[str, Any]:
    metrics = SessionMetrics.start(prompt["modelId"])
    try:
        character = invoke_managed(
            client,
            prompt,
            {
                "language_name": "Spanish" if case["language"] == "es" else "English",
                "pronouns": case["input"]["pronouns"],
                "adventure_json": campaigns[case["campaign_id"]].model_dump_json(),
            },
            PlayerCharacter,
            "create_player_character",
            metrics,
        )
        assert isinstance(character, PlayerCharacter)
        text = character.model_dump_json().lower()
        checks = {
            "valid_identity": bool(character.name and character.archetype),
            "pronoun_contract": character.pronouns == case["input"]["pronouns"],
            "opening_affordances": len(character.known_facts) >= 2
            and len(character.opening_choices) == 3,
            "campaign_grounding": any(
                token in text
                for token in ("campan", "marea", "cripta", "atlas", "ridge", "archive")
            ),
        }
        return _sample(
            case["id"],
            "character",
            checks,
            ("valid_identity", "pronoun_contract", "opening_affordances"),
            metrics,
        )
    except (
        BotoCoreError,
        ClientError,
        KeyError,
        RuntimeError,
        ValidationError,
        ValueError,
    ) as error:
        return _sample(
            case["id"],
            "character",
            {"valid_output": False},
            ("valid_output",),
            metrics,
            str(error),
        )


def _master_case(client: Any, prompt: dict[str, str], case: dict[str, Any]) -> dict[str, Any]:
    metrics = SessionMetrics.start(prompt["modelId"])
    try:
        world = WorldState.model_validate(case["world"])
        proposal = _unknown_item_proposal(
            case["action"], world.model_dump(mode="json"), case["language"]
        )
        if proposal is None:
            proposal = invoke_managed(
                client,
                prompt,
                {
                    "language_name": "Spanish" if case["language"] == "es" else "English",
                    "action": case["action"],
                    "world_json": world.model_dump_json(),
                    "rejection_feedback": "No previous proposal rejection.",
                },
                TurnProposal,
                "resolve_turn",
                metrics,
            )
        assert isinstance(proposal, TurnProposal)
        assert world.plan is not None
        expected = case["expect"]
        changes = (proposal.success_changes, proposal.failure_changes)
        known_items = {item.id for item in world.plan.items}
        safe_items = all(
            set(change.add_items + change.remove_items) <= known_items for change in changes
        ) and all(set(change.remove_items) <= set(world.inventory) for change in changes)
        checks = {
            "roll_necessity": proposal.requires_roll == expected["requires_roll"],
            "governing_stat": not proposal.requires_roll or proposal.stat == expected.get("stat"),
            "difficulty": not proposal.requires_roll
            or expected["difficulty_min"] <= proposal.difficulty <= expected["difficulty_max"],
            "safe_items": safe_items,
            "earned_victory": not proposal.success_changes.objective_complete
            or expected["can_complete"],
            "failure_moves_forward": not expected.get("must_add_fact")
            or bool(proposal.success_changes.add_facts + proposal.failure_changes.add_facts),
        }
        return _sample(
            case["id"],
            "master",
            checks,
            ("safe_items", "earned_victory"),
            metrics,
        )
    except (
        BotoCoreError,
        ClientError,
        AssertionError,
        RuntimeError,
        TypeError,
        ValidationError,
        ValueError,
    ) as error:
        return _sample(
            case["id"],
            "master",
            {"valid_output": False},
            ("valid_output",),
            metrics,
            str(error),
        )


def _evaluate_case(
    client: Any,
    prompts: dict[str, dict[str, str]],
    campaigns: dict[str, AdventurePlan],
    role: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    if role == "campaign":
        return _campaign_case(client, prompts[role], case)
    if role == "character":
        return _character_case(client, prompts[role], case, campaigns)
    if role == "master":
        return _master_case(client, prompts[role], case)
    raise ValueError(f"unknown evaluation role: {role}")


def evaluate_candidate(
    client: Any,
    manifest: dict[str, Any],
    case_ids: set[str] | None = None,
    max_workers: int = 6,
) -> dict[str, Any]:
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    prompts = manifest["prompts"]
    campaign_cases = _records("campaigns.jsonl")
    character_cases = _records("characters.jsonl")
    master_cases = _records("master.jsonl")
    if case_ids:
        campaign_cases = [case for case in campaign_cases if case["id"] in case_ids]
        character_cases = [case for case in character_cases if case["id"] in case_ids]
        master_cases = [case for case in master_cases if case["id"] in case_ids]
        found = {case["id"] for case in campaign_cases + character_cases + master_cases}
        missing = case_ids - found
        if missing:
            raise ValueError(f"unknown case ids: {', '.join(sorted(missing))}")
    all_campaigns = _records("campaigns.jsonl")
    campaigns = {case["id"]: AdventurePlan.model_validate(case["golden"]) for case in all_campaigns}
    jobs = [
        *(("campaign", case) for case in campaign_cases),
        *(("character", case) for case in character_cases),
        *(("master", case) for case in master_cases),
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        samples = list(
            executor.map(
                lambda job: _evaluate_case(client, prompts, campaigns, job[0], job[1]),
                jobs,
            )
        )
    role_scores = {
        role: round(
            statistics.mean(sample["score"] for sample in samples if sample["role"] == role),
            1,
        )
        for role in ("campaign", "character", "master")
        if any(sample["role"] == role for sample in samples)
    }
    costs = [
        float(sample["metrics"]["estimated_cost_usd"])
        for sample in samples
        if sample["metrics"]["estimated_cost_usd"] is not None
    ]
    return {
        "candidate": manifest["candidate"],
        "qualityScore": round(statistics.mean(sample["score"] for sample in samples), 1),
        "criticalPass": all(sample["criticalPass"] for sample in samples),
        "estimatedCostUsd": round(sum(costs), 8) if len(costs) == len(samples) else None,
        "roleScores": role_scores,
        "samples": samples,
    }


def compare(candidates: list[dict[str, Any]], max_quality_drop: float) -> dict[str, Any]:
    baseline = candidates[0]
    for candidate in candidates:
        candidate["qualityDrop"] = round(baseline["qualityScore"] - candidate["qualityScore"], 1)
        candidate["eligible"] = (
            candidate["criticalPass"] and candidate["qualityDrop"] <= max_quality_drop
        )
    eligible = [
        candidate
        for candidate in candidates
        if candidate["eligible"] and candidate["estimatedCostUsd"] is not None
    ]
    eligible.sort(key=lambda candidate: candidate["estimatedCostUsd"])
    return {
        "rubricVersion": "1.0",
        "baseline": baseline["candidate"],
        "maxQualityDrop": max_quality_drop,
        "recommendation": eligible[0]["candidate"] if eligible else None,
        "candidates": candidates,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare managed prompt candidates on quality and cost."
    )
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--candidate", action="append", type=Path, required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--max-quality-drop", type=float, default=5.0)
    parser.add_argument(
        "--max-workers",
        type=int,
        default=6,
        help="Maximum number of cases to invoke concurrently per candidate (default: 6).",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        client = create_client(args.profile, args.region)
        manifests = [json.loads(path.read_text(encoding="utf-8")) for path in args.candidate]
        report = compare(
            [
                evaluate_candidate(
                    client,
                    manifest,
                    set(args.case_id) if args.case_id else None,
                    args.max_workers,
                )
                for manifest in manifests
            ],
            args.max_quality_drop,
        )
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
