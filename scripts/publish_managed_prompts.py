"""Publish the current role prompts as versioned Bedrock Prompt Management resources."""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter, TurnProposal

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = "us-east-2"


@dataclass(frozen=True)
class PromptDefinition:
    role: str
    name: str
    description: str
    system: str
    user_template: str
    variables: tuple[str, ...]
    tool_name: str
    tool_description: str
    output_model: type[BaseModel]
    max_tokens: int
    temperature: float


PROMPTS = (
    PromptDefinition(
        role="campaign",
        name="dungeon-campaign-architect",
        description="Creates a compact validated one-shot campaign.",
        system=(
            "Design a compact fantasy one-shot with declared exits, snake_case IDs, at least "
            "three solution paths, no commercial-fiction copies, and no silent bell/tower. "
            "All IDs must use lowercase ASCII letters, digits, and underscores only. Treat every "
            "tool-schema maxLength as a hard limit. Use one short sentence per field: premise at "
            "most 120 characters, objective 70, opening 100, and every description 90."
        ),
        user_template=(
            "Create a 10-15 minute {{language_name}} adventure inspired by {{theme}}: objective, "
            "3-5 locations, 1-2 NPCs, useful items, secrets, max_turns, and short opening. "
            "Also pick a small, coherent starting_inventory (0-2 item ids from items) that the "
            "protagonist plausibly already carries given the premise.\n"
            "{{repair_feedback}}"
        ),
        variables=("language_name", "theme", "repair_feedback"),
        tool_name="create_adventure",
        tool_description="Return the complete validated adventure plan.",
        output_model=AdventurePlan,
        max_tokens=3_000,
        temperature=0.9,
    ),
    PromptDefinition(
        role="character",
        name="dungeon-character-architect",
        description="Creates a protagonist grounded in a supplied campaign.",
        system=(
            "Design one concise protagonist tied to the adventure, vary gender/presentation, "
            "hide secrets, and make choices investigative, social, and risky."
        ),
        user_template=(
            "Create one concise protagonist in {{language_name}}: identity, desire, personal "
            "stake, known facts, and three ways to begin. Put exactly these pronouns in the "
            "pronouns field: {{pronouns}}. Align name, appearance, and grammar with that identity. "
            "Set stats (might, agility, wits, charm, resolve) to a value of 1-3 each, chosen "
            "freely and independently to fit the archetype. Do not balance them. Keep every "
            "string field short enough for the tool schema.\nAdventure JSON:\n"
            "{{adventure_json}}\n"
            "{{repair_feedback}}"
        ),
        variables=("language_name", "pronouns", "adventure_json", "repair_feedback"),
        tool_name="create_player_character",
        tool_description="Return a complete protagonist grounded in the supplied adventure.",
        output_model=PlayerCharacter,
        max_tokens=2_000,
        temperature=0.85,
    ),
    PromptDefinition(
        role="master",
        name="dungeon-master",
        description="Adjudicates one turn against the authoritative world state.",
        system=(
            "Be a fair dungeon master. Roll only for risk, use declared IDs in changes, move "
            "failures forward, set earned victory only, and narrate in 1-3 vivid sentences. "
            "Respect the current inventory: only add_items/remove_items that exist in plan.items, "
            "never remove an item the player is not carrying, and reference carried items "
            "naturally in the narration. When a roll is required, set stat to the attribute that "
            "governs the action (might, agility, wits, charm, or resolve); the hero's stat value "
            "in player_character.stats is added to the d20, so weigh it when setting difficulty."
        ),
        user_template=(
            "Resolve this turn entirely in {{language_name}}.\nPlayer action:\n{{action}}\n"
            "World JSON:\n{{world_json}}\nPrevious proposal rejection:\n{{rejection_feedback}}\n"
            "{{repair_feedback}}"
        ),
        variables=(
            "language_name",
            "action",
            "world_json",
            "rejection_feedback",
            "repair_feedback",
        ),
        tool_name="resolve_turn",
        tool_description="Return the success and failure branches for this player action.",
        output_model=TurnProposal,
        max_tokens=1_200,
        temperature=0.65,
    ),
)


def create_client(profile: str, region: str) -> Any:
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(
        "bedrock-agent",
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"mode": "adaptive", "total_max_attempts": 5},
            user_agent_extra="lambda-microvm-dungeon-agent-prompts/1.0.0",
        ),
    )


def _variant(definition: PromptDefinition, model_id: str) -> dict[str, Any]:
    return {
        "name": "default",
        "templateType": "CHAT",
        "templateConfiguration": {
            "chat": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": definition.user_template}],
                    }
                ],
                "system": [{"text": definition.system}],
                "inputVariables": [{"name": name} for name in definition.variables],
                "toolConfiguration": {
                    "tools": [
                        {
                            "toolSpec": {
                                "name": definition.tool_name,
                                "description": definition.tool_description,
                                "inputSchema": {
                                    "json": definition.output_model.model_json_schema()
                                },
                            }
                        }
                    ],
                    "toolChoice": {"tool": {"name": definition.tool_name}},
                },
            }
        },
        "modelId": model_id,
        "inferenceConfiguration": {
            "text": {
                "maxTokens": definition.max_tokens,
                "temperature": definition.temperature,
            }
        },
        "metadata": [
            {"key": "project", "value": "lambda-microvm-dungeon-agent"},
            {"key": "role", "value": definition.role},
        ],
    }


def _find_prompt(client: Any, name: str) -> dict[str, Any] | None:
    matches = [
        prompt
        for prompt in client.get_paginator("list_prompts")
        .paginate()
        .search(f"promptSummaries[?name == '{name}'][]")
    ]
    if len(matches) > 1:
        raise RuntimeError(f"multiple managed prompts named {name}")
    return matches[0] if matches else None


def publish_prompt(client: Any, definition: PromptDefinition, model_id: str) -> dict[str, str]:
    variant = _variant(definition, model_id)
    existing = _find_prompt(client, definition.name)
    common = {
        "name": definition.name,
        "description": definition.description,
        "defaultVariant": "default",
        "variants": [variant],
    }
    if existing is None:
        draft = client.create_prompt(
            **common,
            tags={
                "project": "lambda-microvm-dungeon-agent",
                "role": definition.role,
            },
        )
    else:
        draft = client.update_prompt(
            **common,
            promptIdentifier=existing["id"],
        )
    version = client.create_prompt_version(
        promptIdentifier=draft["id"],
        description=f"Baseline production prompt using {model_id}",
        tags={
            "project": "lambda-microvm-dungeon-agent",
            "role": definition.role,
            "candidate": "baseline",
        },
    )
    version_number = str(version["version"])
    base_arn = str(version["arn"])
    version_arn = (
        base_arn if base_arn.endswith(f":{version_number}") else f"{base_arn}:{version_number}"
    )
    return {
        "role": definition.role,
        "promptId": str(version["id"]),
        "promptVersion": version_number,
        "promptArn": version_arn,
        "modelId": model_id,
    }


def publish_all(
    client: Any,
    model_id: str,
    candidate: str,
    selected_roles: set[str] | None = None,
    base_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompts = dict(base_manifest["prompts"]) if base_manifest else {}
    definitions = [
        definition
        for definition in PROMPTS
        if selected_roles is None or definition.role in selected_roles
    ]
    prompts.update(
        {
            definition.role: publish_prompt(client, definition, model_id)
            for definition in definitions
        }
    )
    missing = {"campaign", "character", "master"} - set(prompts)
    if missing:
        raise ValueError(
            f"candidate manifest is incomplete; missing roles: {', '.join(sorted(missing))}"
        )
    return {
        "schemaVersion": 1,
        "candidate": candidate,
        "prompts": prompts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish managed prompt baseline versions.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--role", action="append", choices=("campaign", "character", "master"))
    parser.add_argument("--candidate-name", default="baseline-sonnet46")
    parser.add_argument("--base-manifest", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/candidates/baseline-sonnet46.json"),
    )
    args = parser.parse_args()
    try:
        base_manifest = (
            json.loads(args.base_manifest.read_text(encoding="utf-8"))
            if args.base_manifest
            else None
        )
        manifest = publish_all(
            create_client(args.profile, args.region),
            args.model_id,
            args.candidate_name,
            set(args.role) if args.role else None,
            base_manifest,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (BotoCoreError, ClientError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
