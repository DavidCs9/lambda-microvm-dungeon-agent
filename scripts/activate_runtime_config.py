"""Activate a tested Bedrock model/prompt manifest through SSM Parameter Store."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_REGION = "us-east-2"


def create_client(profile: str, region: str) -> Any:
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(
        "ssm",
        config=Config(
            connect_timeout=5,
            read_timeout=15,
            retries={"mode": "adaptive", "total_max_attempts": 3},
            user_agent_extra="lambda-microvm-dungeon-agent-runtime-config/1.0.0",
        ),
    )


def runtime_document(manifest: dict[str, Any]) -> dict[str, Any]:
    prompts = manifest.get("prompts")
    if not isinstance(prompts, dict):
        raise ValueError("manifest is missing prompts")
    roles: dict[str, dict[str, str]] = {}
    for role in ("campaign", "character", "master"):
        prompt = prompts.get(role)
        if not isinstance(prompt, dict):
            raise ValueError(f"manifest is missing role {role}")
        model_id = prompt.get("modelId")
        prompt_arn = prompt.get("promptArn")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError(f"manifest has no modelId for role {role}")
        if not isinstance(prompt_arn, str) or not prompt_arn:
            raise ValueError(f"manifest has no promptArn for role {role}")
        roles[role] = {"model_id": model_id, "prompt_arn": prompt_arn}
    return {
        "schema_version": 1,
        "candidate": str(manifest.get("candidate", "unknown")),
        "roles": roles,
    }


def activate(client: Any, parameter_name: str, document: dict[str, Any]) -> None:
    client.put_parameter(
        Name=parameter_name,
        Description="Active Bedrock model and managed prompt versions for the dungeon agent.",
        Type="String",
        Value=json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        Overwrite=True,
        Tier="Standard",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Activate a tested runtime Bedrock config.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--parameter-name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        document = runtime_document(manifest)
        activate(create_client(args.profile, args.region), args.parameter_name, document)
        print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (
        BotoCoreError,
        ClientError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
