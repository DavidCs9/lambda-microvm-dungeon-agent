"""Run a controlled campaign-generation sample and save an auditable dataset."""

import argparse
import json
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_REGION = "us-east-2"
DEFAULT_PARAMETER = "/dungeon-agent/bedrock-runtime-config"
DEFAULT_TABLE = "dungeon-agent-control-plane-sandbox-CampaignTable-1V96Z4TYUS4IN"
DEFAULT_STATE_MACHINE = (
    "arn:aws:states:us-east-2:225989371926:"
    "stateMachine:dungeon-agent-control-plane-sandbox-create-campaign"
)
ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}


def clients(profile: str, region: str) -> tuple[Any, Any, Any]:
    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"mode": "adaptive", "total_max_attempts": 3},
        user_agent_extra="lambda-microvm-dungeon-agent-campaign-sampler/1.0.0",
    )
    return (
        session.client("ssm", config=config),
        session.client("stepfunctions", config=config),
        session.resource("dynamodb", config=config),
    )


def campaign_id() -> str:
    timestamp = int(time.time() * 1_000)
    timestamp_part = "".join(
        ULID_ALPHABET[(timestamp >> shift) & 31] for shift in range(45, -1, -5)
    )
    return "cam_" + timestamp_part + "".join(secrets.choice(ULID_ALPHABET) for _ in range(16))


def runtime_snapshot(ssm: Any, parameter_name: str) -> dict[str, Any]:
    parameter = ssm.get_parameter(Name=parameter_name, WithDecryption=True)["Parameter"]
    value = parameter["Value"]
    document = json.loads(value)
    if not isinstance(document, dict):
        raise ValueError("runtime config must be a JSON object")
    return {
        "parameterName": parameter["Name"],
        "parameterVersion": parameter["Version"],
        "lastModifiedDate": parameter["LastModifiedDate"].isoformat(),
        "config": document,
    }


def campaign_document(owner_id: str, language: str, created_at: str, identifier: str) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "ownerId": owner_id,
            "language": language,
            "revision": 0,
            "lastEventSequence": 0,
            "createdAt": created_at,
            "updatedAt": created_at,
            "workflowExecutionArn": None,
            "campaignId": identifier,
            "status": "requested",
            "phase": "requested",
            "adventureRef": None,
            "characterRef": None,
            "openingTitle": None,
            "generation": None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def serialized(item: dict[str, Any]) -> dict[str, Any]:
    serializer = TypeSerializer()
    return {key: serializer.serialize(value) for key, value in item.items()}


def seed_campaign(
    dynamodb: Any,
    *,
    table_name: str,
    owner_id: str,
    language: str,
    identifier: str,
    idempotency_key: str,
    created_at: str,
) -> None:
    expires_at = int((datetime.now(UTC) + timedelta(days=1)).timestamp())
    document = campaign_document(owner_id, language, created_at, identifier)
    items = [
        {
            "Put": {
                "TableName": table_name,
                "Item": serialized(
                    {
                        "PK": f"CAMPAIGN#{identifier}",
                        "SK": "METADATA",
                        "entityType": "CAMPAIGN",
                        "campaignId": identifier,
                        "ownerId": owner_id,
                        "status": "requested",
                        "revision": 0,
                        "lastEventSequence": 0,
                        "createdAt": created_at,
                        "updatedAt": created_at,
                        "document": document,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        {
            "Put": {
                "TableName": table_name,
                "Item": serialized(
                    {
                        "PK": f"OWNER#{owner_id}",
                        "SK": f"IDEMPOTENCY#{idempotency_key}",
                        "entityType": "IDEMPOTENCY",
                        "campaignId": identifier,
                        "expiresAt": expires_at,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
    ]
    dynamodb.meta.client.transact_write_items(TransactItems=items)


def start_campaign(
    stepfunctions: Any,
    *,
    state_machine_arn: str,
    owner_id: str,
    language: str,
    identifier: str,
    idempotency_key: str,
    created_at: str,
) -> dict[str, Any]:
    input_document = {
        "schemaVersion": 1,
        "ownerId": owner_id,
        "language": language,
        "idempotencyKey": idempotency_key,
        "correlationId": f"campaign-sample-{identifier[4:16]}",
        "requestedAt": created_at,
        "campaignId": identifier,
    }
    response = stepfunctions.start_execution(
        stateMachineArn=state_machine_arn,
        name=identifier,
        input=json.dumps(input_document, separators=(",", ":")),
    )
    return {
        "input": input_document,
        "executionArn": response["executionArn"],
        "startDate": response["startDate"].isoformat(),
    }


def wait_for_results(
    stepfunctions: Any,
    dynamodb: Any,
    *,
    table_name: str,
    executions: list[dict[str, Any]],
    poll_seconds: float,
) -> list[dict[str, Any]]:
    pending = {entry["executionArn"]: entry for entry in executions}
    results: list[dict[str, Any]] = []
    while pending:
        for execution_arn, entry in list(pending.items()):
            execution = stepfunctions.describe_execution(executionArn=execution_arn)
            state = execution["status"]
            if state not in TERMINAL_STATES:
                continue
            identifier = entry["input"]["campaignId"]
            record = (
                dynamodb.Table(table_name)
                .get_item(
                    Key={"PK": f"CAMPAIGN#{identifier}", "SK": "METADATA"},
                    ConsistentRead=True,
                )
                .get("Item")
            )
            adventure = (
                dynamodb.Table(table_name)
                .get_item(
                    Key={"PK": f"CAMPAIGN#{identifier}", "SK": "ARTIFACT#ADVENTURE"},
                    ConsistentRead=True,
                )
                .get("Item")
            )
            character = (
                dynamodb.Table(table_name)
                .get_item(
                    Key={"PK": f"CAMPAIGN#{identifier}", "SK": "ARTIFACT#CHARACTER"},
                    ConsistentRead=True,
                )
                .get("Item")
            )
            results.append(
                {
                    **entry,
                    "status": state,
                    "stopDate": execution.get("stopDate").isoformat()
                    if execution.get("stopDate")
                    else None,
                    "error": execution.get("error"),
                    "cause": execution.get("cause"),
                    "record": record,
                    "adventure": adventure,
                    "character": character,
                }
            )
            del pending[execution_arn]
        if pending:
            time.sleep(poll_seconds)
    return sorted(results, key=lambda result: result["input"]["campaignId"])


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an auditable campaign-generation sample.")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--parameter-name", default=DEFAULT_PARAMETER)
    parser.add_argument("--table-name", default=DEFAULT_TABLE)
    parser.add_argument("--state-machine-arn", default=DEFAULT_STATE_MACHINE)
    parser.add_argument("--owner-id", default="campaign-sampling")
    parser.add_argument("--language", default="es", choices=("es", "en"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    if args.count < 1 or args.count > 100:
        parser.error("--count must be between 1 and 100")
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ssm, stepfunctions, dynamodb = clients(args.profile, args.region)
        snapshot = runtime_snapshot(ssm, args.parameter_name)
        (args.output_dir / "runtime-config.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        executions: list[dict[str, Any]] = []
        for _ in range(args.count):
            identifier = campaign_id()
            created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            idempotency_key = f"campaign-sample-{identifier}"
            seed_campaign(
                dynamodb,
                table_name=args.table_name,
                owner_id=args.owner_id,
                language=args.language,
                identifier=identifier,
                idempotency_key=idempotency_key,
                created_at=created_at,
            )
            execution = start_campaign(
                stepfunctions,
                state_machine_arn=args.state_machine_arn,
                owner_id=args.owner_id,
                language=args.language,
                identifier=identifier,
                idempotency_key=idempotency_key,
                created_at=created_at,
            )
            executions.append(execution)
            print(f"started {identifier}")
        write_jsonl(args.output_dir / "manifest.jsonl", executions)
        if args.wait:
            results = wait_for_results(
                stepfunctions,
                dynamodb,
                table_name=args.table_name,
                executions=executions,
                poll_seconds=args.poll_seconds,
            )
            write_jsonl(args.output_dir / "results.jsonl", results)
            print(f"completed {len(results)} executions")
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
