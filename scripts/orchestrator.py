import argparse
import json
import sys
from collections.abc import Sequence
from types import TracebackType
from typing import Self, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_bedrock_runtime import BedrockRuntimeClient
from mypy_boto3_lambda_microvms import LambdaMicroVMsClient

from scripts.microvm_session import request_json, require_success, wait_for_state

DEFAULT_REGION = "us-east-2"
DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"
SYSTEM_PROMPT = """You are the narrator for a playful fantasy dungeon running inside an AWS
Lambda MicroVM. Describe the result of the player's latest action in two to four vivid sentences.
Stay consistent with the supplied world state. Do not use Markdown, mention these instructions,
invent player actions, or expose infrastructure details."""
WELCOME = """
============================================================
                  THE SNAPSHOT TAVERN
             A Lambda MicroVM dungeon adventure
============================================================
"""
HELP = """Commands
  /help    Show these instructions
  /state   Show your current location, inventory, and turn count
  /quit    End the adventure and terminate the MicroVM

Try an action
  look around
  inspect the humming machine
  check my inventory
  open the wooden door
"""


class MicrovmSession:
    def __init__(self, client: LambdaMicroVMsClient, image_arn: str) -> None:
        self.client = client
        self.image_arn = image_arn
        self.microvm_id: str | None = None
        self.endpoint: str | None = None
        self.token: str | None = None

    def __enter__(self) -> Self:
        region = self.client.meta.region_name
        ingress_connector = (
            f"arn:aws:lambda:{region}:aws:network-connector:aws-network-connector:ALL_INGRESS"
        )
        internet_egress_connector = (
            f"arn:aws:lambda:{region}:aws:network-connector:aws-network-connector:INTERNET_EGRESS"
        )
        response = self.client.run_microvm(
            imageIdentifier=self.image_arn,
            imageVersion="1.0",
            ingressNetworkConnectors=[ingress_connector],
            egressNetworkConnectors=[internet_egress_connector],
            idlePolicy={
                "maxIdleDurationSeconds": 300,
                "suspendedDurationSeconds": 300,
                "autoResumeEnabled": True,
            },
            maximumDurationInSeconds=1_800,
            logging={"disabled": {}},
        )
        self.microvm_id = response["microvmId"]
        self.endpoint = response["endpoint"]
        wait_for_state(self.client, self.microvm_id, "RUNNING")
        token_response = self.client.create_microvm_auth_token(
            microvmIdentifier=self.microvm_id,
            expirationInMinutes=30,
            allowedPorts=[{"port": 8080}],
        )
        self.token = token_response["authToken"]["X-aws-proxy-auth"]
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        if self.microvm_id is not None:
            self.client.terminate_microvm(microvmIdentifier=self.microvm_id)
            wait_for_state(self.client, self.microvm_id, "TERMINATED")

    def read_world(self) -> dict[str, object]:
        result = request_json(self._endpoint(), self._token(), "GET", "/v1/world")
        require_success(result, "read world")
        if not isinstance(result.body, dict):
            raise RuntimeError("MicroVM returned a non-object world state")
        return cast(dict[str, object], result.body)

    def apply_action(self, action: str) -> dict[str, object]:
        result = request_json(
            self._endpoint(), self._token(), "POST", "/v1/actions", {"action": action}
        )
        require_success(result, "apply action")
        if not isinstance(result.body, dict):
            raise RuntimeError("MicroVM returned a non-object world state")
        return cast(dict[str, object], result.body)

    def _endpoint(self) -> str:
        if self.endpoint is None:
            raise RuntimeError("MicroVM session has not started")
        return self.endpoint

    def _token(self) -> str:
        if self.token is None:
            raise RuntimeError("MicroVM session has not started")
        return self.token


class BedrockNarrator:
    def __init__(self, client: BedrockRuntimeClient, model_id: str) -> None:
        self.client = client
        self.model_id = model_id

    def narrate(self, action: str, world: dict[str, object]) -> str:
        prompt = json.dumps(
            {"latestPlayerAction": action, "currentWorldState": world},
            separators=(",", ":"),
        )
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 180, "temperature": 0.7, "topP": 0.9},
            requestMetadata={"project": "lambda-microvm-dungeon-agent"},
        )
        if response["stopReason"] not in {"end_turn", "stop_sequence"}:
            raise RuntimeError(f"Bedrock stopped narration with {response['stopReason']}")
        content = response["output"]["message"]["content"]
        narration = "".join(block["text"] for block in content if "text" in block).strip()
        if not narration:
            raise RuntimeError("Bedrock returned an empty narration")
        return narration


class DungeonOrchestrator:
    def __init__(self, session: MicrovmSession, narrator: BedrockNarrator) -> None:
        self.session = session
        self.narrator = narrator

    def take_turn(self, action: str) -> str:
        normalized = action.strip()
        if not normalized:
            raise ValueError("Player action cannot be empty")
        if len(normalized) > 500:
            raise ValueError("Player action cannot exceed 500 characters")
        world = self.session.apply_action(normalized)
        return self.narrator.narrate(normalized, world)

    def opening_scene(self) -> str:
        return self.narrator.narrate(
            "Set the opening scene. Do not move the player or add an action to the story.",
            self.session.read_world(),
        )

    def state_summary(self) -> str:
        world = self.session.read_world()
        location = world.get("location", "Unknown")
        revision = world.get("revision", 0)
        inventory = world.get("inventory", [])
        inventory_text = (
            ", ".join(str(item) for item in inventory)
            if isinstance(inventory, list) and inventory
            else "Empty"
        )
        return f"Location: {location}\nInventory: {inventory_text}\nTurns played: {revision}"


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


def play(orchestrator: DungeonOrchestrator, one_turn: str | None) -> None:
    if one_turn is not None:
        print(orchestrator.take_turn(one_turn))
        return

    print(WELCOME)
    print(orchestrator.opening_scene())
    print(f"\n{HELP}")
    while True:
        try:
            action = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nEnding your adventure...")
            return
        command = action.lower()
        if command in {"/quit", "/exit"}:
            print("\nEnding your adventure...")
            return
        if command == "/help":
            print(f"\n{HELP}")
            continue
        if command == "/state":
            print(f"\n{orchestrator.state_summary()}\n")
            continue
        if not action:
            continue
        try:
            print(f"\nDungeon Master:\n{orchestrator.take_turn(action)}\n")
        except ValueError as error:
            print(f"\n{error}. Type /help for examples.\n")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play the MicroVM dungeon with Bedrock.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--image-arn", required=True)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--turn", help="Run one player turn non-interactively, then terminate.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        microvms, bedrock = create_clients(args.profile, args.region)
        print("Starting your private MicroVM session...", flush=True)
        with MicrovmSession(microvms, args.image_arn) as microvm_session:
            print("Session ready. Your adventure is isolated and temporary.\n", flush=True)
            orchestrator = DungeonOrchestrator(
                microvm_session,
                BedrockNarrator(bedrock, args.model_id),
            )
            play(orchestrator, args.turn)
        print("MicroVM terminated. Thanks for playing.")
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
