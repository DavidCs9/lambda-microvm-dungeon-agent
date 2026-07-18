"""Compare Bedrock narration models on identical bilingual game states."""

import argparse
import json
import re
import statistics
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

from dungeon_agent.api.adventure import initial_world, resolve_action
from dungeon_agent.api.models import LanguageCode, WorldState
from dungeon_agent.orchestrator.locales import load_locale
from dungeon_agent.orchestrator.narrator import BedrockNarrator, NarrationResult

DEFAULT_REGION = "us-east-2"


@dataclass(frozen=True)
class Scene:
    name: str
    action: str
    world: WorldState


@dataclass(frozen=True)
class SampleScore:
    model_id: str
    language: LanguageCode
    scene: str
    narration: str
    score: int
    language_adherence: int
    concise_format: int
    state_grounding: int
    agency_preservation: int
    presentation_safety: int
    latency_ms: float
    input_tokens: int
    output_tokens: int


def create_client(profile: str, region: str) -> BedrockRuntimeClient:
    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=5,
        read_timeout=60,
        retries={"mode": "adaptive", "total_max_attempts": 5},
        user_agent_extra="lambda-microvm-dungeon-agent-eval/0.1.0",
    )
    return session.client("bedrock-runtime", config=config)


def scenes(language: LanguageCode) -> tuple[Scene, ...]:
    if language == "es":
        actions = ("mirar alrededor", "hablar con Mira", "entrar al sótano")
    else:
        actions = ("look around", "talk to Mira", "enter the cellar")
    world = initial_world(language)
    prepared: list[Scene] = []
    for index, action in enumerate(actions, start=1):
        world = resolve_action(world, action)
        prepared.append(Scene(f"turn_{index}", action, world))
    return tuple(prepared)


def evaluate_models(
    client: BedrockRuntimeClient,
    model_ids: Sequence[str],
) -> dict[str, object]:
    samples: list[SampleScore] = []
    for model_id in model_ids:
        for language in ("en", "es"):
            narrator = BedrockNarrator(client, model_id, load_locale(language))
            for scene in scenes(language):
                result = narrator.narrate_with_metrics(scene.action, scene.world.model_dump())
                samples.append(_score_sample(model_id, language, scene, result))

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
                "averageOutputTokens": round(
                    statistics.mean(item.output_tokens for item in model_samples), 1
                ),
            }
        )
    rankings.sort(key=lambda item: (-float(item["qualityScore"]), float(item["medianLatencyMs"])))
    return {
        "rubricVersion": "1.0",
        "method": "Identical resolved scenes in English and Spanish; deterministic checks only.",
        "rankings": rankings,
        "samples": [asdict(sample) for sample in samples],
        "humanReviewRecommended": True,
    }


def _score_sample(
    model_id: str,
    language: LanguageCode,
    scene: Scene,
    result: NarrationResult,
) -> SampleScore:
    language_score = _language_score(result.text, language)
    sentence_count = len([part for part in re.split(r"[.!?]+", result.text) if part.strip()])
    format_score = 20 if 2 <= sentence_count <= 4 else 10 if 1 <= sentence_count <= 5 else 0
    grounding_score = _grounding_score(result.text, scene.world)
    agency_violations = (
        "you decide to",
        "you choose to",
        "you then proceed",
        "decides hacerlo",
        "eliges hacerlo",
        "luego procedes",
    )
    agency_score = (
        20 if not any(phrase in result.text.casefold() for phrase in agency_violations) else 0
    )
    forbidden = ("system prompt", "latestplayeraction", "currentworldstate", "```", "<tool")
    safety_score = 20 if not any(token in result.text.casefold() for token in forbidden) else 0
    return SampleScore(
        model_id=model_id,
        language=language,
        scene=scene.name,
        narration=result.text,
        score=language_score + format_score + grounding_score + agency_score + safety_score,
        language_adherence=language_score,
        concise_format=format_score,
        state_grounding=grounding_score,
        agency_preservation=agency_score,
        presentation_safety=safety_score,
        latency_ms=round(result.latency_ms, 1),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


def _language_score(text: str, language: LanguageCode) -> int:
    normalized = f" {text.casefold()} "
    spanish_markers = (" el ", " la ", " de ", " que ", " una ", " tu ", " y ")
    marker_count = sum(marker in normalized for marker in spanish_markers)
    if language == "es":
        return 20 if marker_count >= 3 else 10 if marker_count >= 1 else 0
    return 20 if marker_count <= 1 else 10 if marker_count <= 2 else 0


def _grounding_score(text: str, world: WorldState) -> int:
    if world.last_result is None:
        return 0
    source = f"{world.last_result.summary} {world.last_result.consequence}"
    ignored = {"the", "and", "you", "your", "with", "that", "una", "para", "con", "que", "los"}
    expected = {
        word
        for word in re.findall(r"\w+", source.casefold())
        if len(word) >= 5 and word not in ignored
    }
    observed = set(re.findall(r"\w+", text.casefold()))
    overlap = len(expected.intersection(observed))
    return 20 if overlap >= 2 else 10 if overlap == 1 else 0


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare Bedrock models for dungeon narration.")
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
