import argparse
import sys
from collections.abc import Sequence

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_bedrock_runtime import BedrockRuntimeClient
from mypy_boto3_lambda_microvms import LambdaMicroVMsClient

from scripts.dungeon.game import DungeonOrchestrator, play
from scripts.dungeon.locales import LOCALES, select_language
from scripts.dungeon.narrator import BedrockNarrator
from scripts.dungeon.session import MicrovmSession

DEFAULT_REGION = "us-east-2"
DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"


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
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument(
        "--language",
        choices=sorted(LOCALES),
        help="Skip the language menu: es (Español) or en (English).",
    )
    parser.add_argument("--turn", help="Run one player turn non-interactively, then terminate.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        locale = select_language(args.language)
        microvms, bedrock = create_clients(args.profile, args.region)
        print(f"\n{locale.starting}", flush=True)
        with MicrovmSession(microvms, args.image_arn) as microvm_session:
            print(f"{locale.ready}\n", flush=True)
            orchestrator = DungeonOrchestrator(
                microvm_session,
                BedrockNarrator(bedrock, args.model_id, locale),
                locale,
            )
            play(orchestrator, args.turn, locale)
        print(locale.terminated)
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
