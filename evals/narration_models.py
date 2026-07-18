"""Compare Bedrock models as adventure architects and free-form Dungeon Masters."""

import argparse
import json
import statistics
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

from dungeon_agent.api.adventure import start_adventure
from dungeon_agent.api.models import LanguageCode
from dungeon_agent.orchestrator.agents import (
    AdventureArchitect,
    DungeonMaster,
    StructuredBedrockAgent,
)
from dungeon_agent.orchestrator.observability import SessionMetrics

DEFAULT_REGION = "us-east-2"


@dataclass(frozen=True)
class SampleScore:
    model_id: str
    language: LanguageCode
    title: str
    score: int
    adventure_structure: int
    player_agency: int
    turn_adjudication: int
    state_safety: int
    total_tokens: int
    latency_ms: float


def create_client(profile: str, region: str) -> BedrockRuntimeClient:
    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=5,
        read_timeout=90,
        retries={"mode": "adaptive", "total_max_attempts": 5},
        user_agent_extra="lambda-microvm-dungeon-agent-eval/0.2.0",
    )
    return session.client("bedrock-runtime", config=config)


def evaluate_models(client: BedrockRuntimeClient, model_ids: Sequence[str]) -> dict[str, object]:
    samples: list[SampleScore] = []
    for model_id in model_ids:
        for language in ("en", "es"):
            metrics = SessionMetrics.start(model_id)
            agent = StructuredBedrockAgent(client, model_id, metrics)
            plan = AdventureArchitect(agent).create(language)
            world = start_adventure(language, plan).model_dump(mode="json")
            action = (
                "Improviso un puente con muebles rotos para evitar al guardia"
                if language == "es"
                else "I improvise a bridge from broken furniture to avoid the guard"
            )
            turn = DungeonMaster(agent, language).adjudicate(action, world)
            structure = 25 if len(plan.locations) >= 3 and len(plan.items) >= 2 else 0
            agency = (
                25
                if len(plan.secrets) >= 2 and sum(bool(x.exits) for x in plan.locations) >= 3
                else 15
            )
            adjudication = 25 if turn.requires_roll and turn.difficulty is not None else 15
            known_locations = {location.id for location in plan.locations}
            known_items = {item.id for item in plan.items}
            changes = [turn.success_changes, turn.failure_changes]
            safe = all(
                (change.location_id is None or change.location_id in known_locations)
                and set(change.add_items + change.remove_items).issubset(known_items)
                for change in changes
            )
            safety = 25 if safe else 0
            samples.append(
                SampleScore(
                    model_id=model_id,
                    language=language,
                    title=plan.title,
                    score=structure + agency + adjudication + safety,
                    adventure_structure=structure,
                    player_agency=agency,
                    turn_adjudication=adjudication,
                    state_safety=safety,
                    total_tokens=metrics.total_tokens,
                    latency_ms=round(metrics.model_latency_ms, 1),
                )
            )
    rankings = []
    for model_id in model_ids:
        model_samples = [sample for sample in samples if sample.model_id == model_id]
        rankings.append(
            {
                "modelId": model_id,
                "qualityScore": round(statistics.mean(item.score for item in model_samples), 1),
                "medianLatencyMs": round(
                    statistics.median(item.latency_ms for item in model_samples), 1
                ),
                "averageTokens": round(
                    statistics.mean(item.total_tokens for item in model_samples), 1
                ),
            }
        )
    rankings.sort(key=lambda item: (-float(item["qualityScore"]), float(item["medianLatencyMs"])))
    return {
        "rubricVersion": "2.0",
        "method": "One generated adventure and one identical creative action per language.",
        "rankings": rankings,
        "samples": [asdict(sample) for sample in samples],
        "humanPlaytestRecommended": True,
    }


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare Bedrock adventure models.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--model-id", action="append", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        report = evaluate_models(create_client(args.profile, args.region), args.model_id)
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    except (BotoCoreError, ClientError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
