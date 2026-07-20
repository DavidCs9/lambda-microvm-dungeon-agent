import argparse
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_bedrock_runtime import BedrockRuntimeClient
from mypy_boto3_lambda_microvms import LambdaMicroVMsClient

from dungeon_agent.api.models import LanguageCode
from dungeon_agent.audio.local import LocalAudioExperience
from dungeon_agent.audio.polly import PollySpeechSynthesizer
from dungeon_agent.orchestrator.agents import (
    AdventureArchitect,
    CharacterArchitect,
    DungeonMaster,
    StructuredBedrockAgent,
)
from dungeon_agent.orchestrator.game import DungeonOrchestrator, play
from dungeon_agent.orchestrator.locales import LOCALES, Locale, select_language
from dungeon_agent.orchestrator.observability import SessionMetrics
from dungeon_agent.orchestrator.session import MicrovmSession
from dungeon_agent.tui.app import DungeonApp

DEFAULT_REGION = "us-east-2"
# Sonnet 5 is supported via --model-id once account access is granted.
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_POLLY_REGION = "us-east-1"


def create_clients(profile: str, region: str) -> tuple[LambdaMicroVMsClient, BedrockRuntimeClient]:
    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=5,
        read_timeout=60,
        retries={"mode": "adaptive", "total_max_attempts": 5},
        user_agent_extra="lambda-microvm-dungeon-agent/0.1.0",
    )
    return (
        session.client("lambda-microvms", config=config),
        session.client("bedrock-runtime", config=config),
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play the MicroVM dungeon with Bedrock.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--image-arn", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--polly-region", default=DEFAULT_POLLY_REGION)
    parser.add_argument("--no-voice", action="store_true", help="Disable Dungeon Master speech.")
    parser.add_argument("--no-music", action="store_true", help="Disable tavern ambience.")
    parser.add_argument(
        "--audio-cache",
        type=Path,
        default=Path("dist/audio-cache"),
        help="Cache synthesized speech and original ambience here.",
    )
    parser.add_argument(
        "--language",
        choices=sorted(LOCALES),
        help="Skip the language menu: "
        + ", ".join(f"{code} ({LOCALES[code].name})" for code in sorted(LOCALES)),
    )
    parser.add_argument("--turn", help="Run one player turn non-interactively, then terminate.")
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Use the stream-based interface instead of the full-screen TUI.",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=Path("dist/session-metrics.jsonl"),
        help="Append privacy-safe session metrics as JSONL.",
    )
    return parser


def create_audio(args: argparse.Namespace) -> LocalAudioExperience:
    session = boto3.Session(profile_name=args.profile, region_name=args.polly_region)
    config = Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"mode": "adaptive", "total_max_attempts": 4},
        user_agent_extra="lambda-microvm-dungeon-agent-audio/0.1.0",
    )
    voices: dict[LanguageCode, str] = {"en": "Matthew", "es": "Andres"}
    synthesizer = PollySpeechSynthesizer(
        session.client("polly", config=config),
        args.audio_cache / "speech",
        voices,
    )
    return LocalAudioExperience(
        synthesizer,
        args.audio_cache,
        voice_enabled=not args.no_voice,
        music_enabled=not args.no_music,
    )


@contextmanager
def create_runtime(args: argparse.Namespace, locale: Locale) -> Iterator[DungeonOrchestrator]:
    microvms, bedrock = create_clients(args.profile, args.region)
    with MicrovmSession(microvms, args.image_arn, args.image_version) as microvm_session:
        microvm_session.set_language(locale.code)
        metrics = SessionMetrics.start(args.model_id)
        agent = StructuredBedrockAgent(bedrock, args.model_id, metrics)
        orchestrator = DungeonOrchestrator(
            microvm_session,
            AdventureArchitect(agent),
            CharacterArchitect(agent),
            DungeonMaster(agent, locale.code),
            metrics,
            locale,
        )
        try:
            yield orchestrator
        finally:
            metrics.append_jsonl(args.metrics_output)


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    if not args.plain and args.turn is None:
        app = DungeonApp(
            lambda locale: create_runtime(args, locale),
            selected_language=args.language,
            audio=create_audio(args),
        )
        app.run()
        return 0
    try:
        locale = select_language(args.language)
        microvms, bedrock = create_clients(args.profile, args.region)
        print(f"\n{locale.starting}", flush=True)
        with MicrovmSession(microvms, args.image_arn, args.image_version) as microvm_session:
            microvm_session.set_language(locale.code)
            print(f"{locale.ready}\n", flush=True)
            metrics = SessionMetrics.start(args.model_id)
            agent = StructuredBedrockAgent(bedrock, args.model_id, metrics)
            orchestrator = DungeonOrchestrator(
                microvm_session,
                AdventureArchitect(agent),
                CharacterArchitect(agent),
                DungeonMaster(agent, locale.code),
                metrics,
                locale,
            )
            try:
                play(orchestrator, args.turn, locale)
            finally:
                metrics.append_jsonl(args.metrics_output)
                print(f"\n{orchestrator.stats_summary()}")
        print(locale.terminated)
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
