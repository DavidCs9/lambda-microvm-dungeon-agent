"""AWS Lambda entry points for the sandbox control plane."""

import os
from collections.abc import Mapping
from typing import Any, cast

import boto3
from botocore.config import Config

from dungeon_agent.control_plane.agents import (
    AdventureArchitect,
    CharacterArchitect,
    StructuredBedrockAgent,
)
from dungeon_agent.control_plane.application import DefaultSessionFactory
from dungeon_agent.control_plane.http import ApiGatewayHttpAdapter, SessionHttpHandlers
from dungeon_agent.control_plane.microvms.manager import (
    LambdaMicrovmManager,
    LambdaMicrovmsClient,
)
from dungeon_agent.control_plane.persistence.dynamodb import create_dynamodb_repository
from dungeon_agent.control_plane.steps import (
    AdventureStep,
    CharacterStep,
    DynamoDbAdventurePlans,
    DynamoDbCharacterBundles,
)
from dungeon_agent.control_plane.steps.artifacts import DynamoDbArtifactClient
from dungeon_agent.control_plane.telemetry import EmfTelemetry
from dungeon_agent.control_plane.workflow import (
    DurableSessionWorkflowStub,
    StepFunctionsWorkflowStarter,
)
from dungeon_agent.control_plane.workflow.step_functions import StepFunctionsClient

_CONFIG = Config(
    retries={"total_max_attempts": 3, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=10,
)
_TABLE_NAME = os.environ["TABLE_NAME"]
_REPOSITORY = create_dynamodb_repository(_TABLE_NAME)
_TELEMETRY = EmfTelemetry("session-creation")


class _AgentMetrics:
    def __init__(self, operation: str) -> None:
        self._operation = operation

    def record(self, *, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
        _TELEMETRY.model(
            self._operation,
            "success",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class _MicrovmMetrics:
    def record(self, operation: str, latency_ms: float) -> None:
        _TELEMETRY.microvm(operation, "success", latency_ms)


def _build_http_adapter() -> ApiGatewayHttpAdapter:
    client = cast(StepFunctionsClient, boto3.client("stepfunctions", config=_CONFIG))
    starter = StepFunctionsWorkflowStarter(client, os.environ["STATE_MACHINE_ARN"])
    handlers = SessionHttpHandlers(
        _REPOSITORY,
        _REPOSITORY,
        starter,
        DefaultSessionFactory(),
    )
    return ApiGatewayHttpAdapter(handlers, allow_sandbox_identity=True)


_HTTP_ADAPTER = _build_http_adapter() if "STATE_MACHINE_ARN" in os.environ else None


def _build_workflow() -> DurableSessionWorkflowStub:
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    image_name = os.environ.get("MICROVM_IMAGE_NAME")
    if model_id is None or image_name is None:
        return DurableSessionWorkflowStub(_REPOSITORY, _REPOSITORY)

    bedrock_client = cast(Any, boto3.client("bedrock-runtime", config=_CONFIG))
    artifact_client = cast(DynamoDbArtifactClient, boto3.client("dynamodb", config=_CONFIG))
    microvm_client = cast(LambdaMicrovmsClient, boto3.client("lambda-microvms", config=_CONFIG))
    adventures = DynamoDbAdventurePlans(artifact_client, _TABLE_NAME)
    characters = DynamoDbCharacterBundles(artifact_client, _TABLE_NAME)
    adventure_agent = StructuredBedrockAgent(
        bedrock_client,
        model_id,
        _AgentMetrics("AdventureArchitect"),
    )
    character_agent = StructuredBedrockAgent(
        bedrock_client,
        model_id,
        _AgentMetrics("CharacterArchitect"),
    )
    microvms = LambdaMicrovmManager(
        microvm_client,
        image_name,
        os.environ.get("AWS_REGION", "us-east-2"),
        metrics=_MicrovmMetrics(),
    )
    return DurableSessionWorkflowStub(
        _REPOSITORY,
        _REPOSITORY,
        adventure_step=AdventureStep(AdventureArchitect(adventure_agent), adventures),
        character_step=CharacterStep(CharacterArchitect(character_agent), adventures, characters),
        adventures=adventures,
        characters=characters,
        microvms=microvms,
    )


_WORKFLOW = _build_workflow()


def http_handler(event: Mapping[str, Any], context: object) -> dict[str, Any]:
    if _HTTP_ADAPTER is None:
        raise RuntimeError("HTTP adapter is not configured in this function")
    return _HTTP_ADAPTER(event, context)


def workflow_handler(event: Mapping[str, object], _context: object) -> dict[str, object]:
    return _WORKFLOW.handle(event)
