"""AWS Lambda entry points for the sandbox control plane."""

import os
from collections.abc import Mapping
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config

from dungeon_agent.audio.polly import DEFAULT_VOICES, S3PollySpeechSynthesizer
from dungeon_agent.control_plane.agents import (
    DEFAULT_IMAGE_MODEL_ID,
    AdventureArchitect,
    BedrockPortraitGenerator,
    CharacterArchitect,
    StructuredBedrockAgent,
)
from dungeon_agent.control_plane.agents.metrics import AgentMetricsPort, RoleMetricsCollector
from dungeon_agent.control_plane.application import (
    DefaultCampaignFactory,
    DefaultSessionFactory,
    TurnWorker,
)
from dungeon_agent.control_plane.domain.models import SubmitTurnCommand
from dungeon_agent.control_plane.http import (
    ApiGatewayHttpAdapter,
    CampaignHttpHandlers,
    SessionHttpHandlers,
    SpeechHttpHandlers,
)
from dungeon_agent.control_plane.microvms.manager import (
    LambdaMicrovmManager,
    LambdaMicrovmsClient,
)
from dungeon_agent.control_plane.persistence.dynamodb import create_dynamodb_repository
from dungeon_agent.control_plane.persistence.dynamodb_campaigns import (
    create_dynamodb_campaign_repository,
)
from dungeon_agent.control_plane.realtime.api_gateway import ApiGatewayWebSocketAdapter
from dungeon_agent.control_plane.realtime.delivery import BestEffortEventDelivery
from dungeon_agent.control_plane.realtime.dynamodb import (
    DynamoDbConnectionRepository,
    DynamoTable,
)
from dungeon_agent.control_plane.realtime.service import RealtimeSessionService
from dungeon_agent.control_plane.steps import (
    AdventureStep,
    CharacterStep,
    DynamoDbAdventurePlans,
    DynamoDbCampaignAdventurePlans,
    DynamoDbCampaignCharacterBundles,
    DynamoDbCharacterBundles,
    DynamoDbWorldSnapshots,
)
from dungeon_agent.control_plane.steps.artifacts import DynamoDbArtifactClient
from dungeon_agent.control_plane.telemetry import EmfTelemetry
from dungeon_agent.control_plane.workflow import (
    DurableCampaignWorkflowStub,
    DurableSessionWorkflowStub,
    StepFunctionsWorkflowStarter,
)
from dungeon_agent.control_plane.workflow.step_functions import StepFunctionsClient
from dungeon_agent.images.portraits import S3PortraitStore

_CONFIG = Config(
    retries={"total_max_attempts": 3, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=10,
)
_BEDROCK_CONFIG = Config(
    retries={"total_max_attempts": 2, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=120,
)
_TABLE_NAME = os.environ["TABLE_NAME"]
_REPOSITORY = create_dynamodb_repository(_TABLE_NAME)
_CAMPAIGN_TABLE_NAME = os.environ["CAMPAIGN_TABLE_NAME"]
_CAMPAIGN_REPOSITORY = create_dynamodb_campaign_repository(_CAMPAIGN_TABLE_NAME)
_TELEMETRY = EmfTelemetry("session-creation")
_REGION = os.environ.get("AWS_REGION", "us-east-2")

_CAMPAIGN_OPERATIONS = frozenset(
    {
        "ValidateCampaign",
        "CreateCampaignRecord",
        "EmitCreatingAdventure",
        "GenerateAdventure",
        "PersistAdventure",
        "EmitCreatingCharacter",
        "GenerateCharacter",
        "PersistCharacter",
        "MarkCampaignReady",
        "EmitCampaignReady",
        "MarkCampaignFailed",
        "EmitCampaignCreationFailed",
    }
)


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


class _LambdaClient(Protocol):
    def invoke(self, **kwargs: object) -> Mapping[str, object]: ...


class LambdaTurnWorkerInvoker:
    """Hand one accepted action to the turn worker without blocking the HTTP call."""

    def __init__(self, client: _LambdaClient, function_name: str) -> None:
        self._client = client
        self._function_name = function_name

    def invoke_turn(self, command: SubmitTurnCommand) -> None:
        self._client.invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=command.model_dump_json(by_alias=True).encode(),
        )


def _management_client() -> Any:
    endpoint = os.environ.get("WS_MANAGEMENT_ENDPOINT")
    if endpoint is None:
        return None
    return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint, config=_CONFIG)


def _connection_repository() -> DynamoDbConnectionRepository:
    resource = boto3.resource("dynamodb", region_name=_REGION, config=_CONFIG)
    return DynamoDbConnectionRepository(cast(DynamoTable, resource.Table(_TABLE_NAME)))


def _build_delivery() -> BestEffortEventDelivery | None:
    client = _management_client()
    if client is None:
        return None
    return BestEffortEventDelivery(_connection_repository(), client)


class _ApiGatewaySender:
    def __init__(self, client: Any, connections: DynamoDbConnectionRepository) -> None:
        self._client = client
        self._connections = connections

    def send(self, connection_id: str, data: bytes) -> None:
        try:
            self._client.post_to_connection(ConnectionId=connection_id, Data=data)
        except self._client.exceptions.GoneException:
            self._connections.delete(connection_id)


def _microvm_manager() -> LambdaMicrovmManager:
    return LambdaMicrovmManager(
        cast(LambdaMicrovmsClient, boto3.client("lambda-microvms", config=_CONFIG)),
        os.environ["MICROVM_IMAGE_NAME"],
        _REGION,
        metrics=_MicrovmMetrics(),
    )


def _build_speech_handlers() -> SpeechHttpHandlers | None:
    bucket = os.environ.get("SPEECH_CACHE_BUCKET")
    if bucket is None:
        return None
    polly_region = os.environ.get("POLLY_REGION", "us-east-1")
    polly = boto3.client("polly", region_name=polly_region, config=_CONFIG)
    s3 = boto3.client("s3", region_name=_REGION, config=_CONFIG)
    synthesizer = S3PollySpeechSynthesizer(
        polly,
        s3,
        bucket,
        DEFAULT_VOICES,
    )
    return SpeechHttpHandlers(synthesizer)


def _build_portrait_store() -> S3PortraitStore | None:
    """Best-effort portrait persistence and presigning; absent bucket disables it."""
    bucket = os.environ.get("SPEECH_CACHE_BUCKET")
    if bucket is None:
        return None
    s3 = boto3.client("s3", region_name=_REGION, config=_CONFIG)
    return S3PortraitStore(s3, bucket)


def _build_portrait_generator() -> BedrockPortraitGenerator | None:
    """Best-effort Bedrock text-to-image; absent bucket disables generation too."""
    if "SPEECH_CACHE_BUCKET" not in os.environ:
        return None
    model_id = os.environ.get("BEDROCK_IMAGE_MODEL_ID", DEFAULT_IMAGE_MODEL_ID)
    bedrock_image = cast(Any, boto3.client("bedrock-runtime", config=_BEDROCK_CONFIG))
    return BedrockPortraitGenerator(bedrock_image, model_id)


def _build_http_adapter() -> ApiGatewayHttpAdapter:
    client = cast(StepFunctionsClient, boto3.client("stepfunctions", config=_CONFIG))
    starter = StepFunctionsWorkflowStarter(
        client,
        os.environ["STATE_MACHINE_ARN"],
        campaign_state_machine_arn=os.environ["CAMPAIGN_STATE_MACHINE_ARN"],
    )
    sessions = SessionHttpHandlers(
        _REPOSITORY,
        _REPOSITORY,
        starter,
        DefaultSessionFactory(),
        _CAMPAIGN_REPOSITORY,
        turns=_build_turn_invoker(),
        delivery=_build_delivery(),
        microvms=_microvm_manager() if "MICROVM_IMAGE_NAME" in os.environ else None,
    )
    artifact_client = cast(DynamoDbArtifactClient, boto3.client("dynamodb", config=_CONFIG))
    campaigns = CampaignHttpHandlers(
        _CAMPAIGN_REPOSITORY,
        _CAMPAIGN_REPOSITORY,
        starter,
        DefaultCampaignFactory(),
        openings=DynamoDbCampaignCharacterBundles(artifact_client, _CAMPAIGN_TABLE_NAME),
        portrait_presigner=_build_portrait_store(),
    )
    return ApiGatewayHttpAdapter(
        sessions,
        campaigns,
        speech=_build_speech_handlers(),
        allow_sandbox_identity=True,
    )


def _build_turn_invoker() -> LambdaTurnWorkerInvoker | None:
    function_name = os.environ.get("TURN_WORKER_FUNCTION_NAME")
    if function_name is None:
        return None
    client = cast(_LambdaClient, boto3.client("lambda", config=_CONFIG))
    return LambdaTurnWorkerInvoker(client, function_name)


_HTTP_ADAPTER = (
    _build_http_adapter()
    if "STATE_MACHINE_ARN" in os.environ and "CAMPAIGN_STATE_MACHINE_ARN" in os.environ
    else None
)


def _structured_agent(
    operation: str, metrics: AgentMetricsPort | None = None
) -> StructuredBedrockAgent:
    return StructuredBedrockAgent(
        cast(Any, boto3.client("bedrock-runtime", config=_BEDROCK_CONFIG)),
        os.environ["BEDROCK_MODEL_ID"],
        metrics if metrics is not None else _AgentMetrics(operation),
    )


def _build_workflow() -> DurableSessionWorkflowStub:
    image_name = os.environ.get("MICROVM_IMAGE_NAME")
    if image_name is None:
        return DurableSessionWorkflowStub(_REPOSITORY, _REPOSITORY, delivery=_build_delivery())

    artifact_client = cast(DynamoDbArtifactClient, boto3.client("dynamodb", config=_CONFIG))
    return DurableSessionWorkflowStub(
        _REPOSITORY,
        _REPOSITORY,
        campaigns=_CAMPAIGN_REPOSITORY,
        campaign_adventures=DynamoDbCampaignAdventurePlans(artifact_client, _CAMPAIGN_TABLE_NAME),
        campaign_characters=DynamoDbCampaignCharacterBundles(artifact_client, _CAMPAIGN_TABLE_NAME),
        adventures=DynamoDbAdventurePlans(artifact_client, _TABLE_NAME),
        characters=DynamoDbCharacterBundles(artifact_client, _TABLE_NAME),
        microvms=_microvm_manager(),
        snapshots=DynamoDbWorldSnapshots(artifact_client, _TABLE_NAME),
        delivery=_build_delivery(),
    )


_WORKFLOW = _build_workflow()


def _build_campaign_workflow() -> DurableCampaignWorkflowStub:
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if model_id is None:
        return DurableCampaignWorkflowStub(
            _CAMPAIGN_REPOSITORY,
            _CAMPAIGN_REPOSITORY,
            delivery=_build_delivery(),
        )

    artifact_client = cast(DynamoDbArtifactClient, boto3.client("dynamodb", config=_CONFIG))
    adventures = DynamoDbCampaignAdventurePlans(artifact_client, _CAMPAIGN_TABLE_NAME)
    characters = DynamoDbCampaignCharacterBundles(artifact_client, _CAMPAIGN_TABLE_NAME)
    adventure_metrics = RoleMetricsCollector(_AgentMetrics("AdventureArchitect"))
    character_metrics = RoleMetricsCollector(_AgentMetrics("CharacterArchitect"))
    return DurableCampaignWorkflowStub(
        _CAMPAIGN_REPOSITORY,
        _CAMPAIGN_REPOSITORY,
        adventure_step=AdventureStep(
            AdventureArchitect(_structured_agent("AdventureArchitect", adventure_metrics)),
            adventures,
        ),
        character_step=CharacterStep(
            CharacterArchitect(_structured_agent("CharacterArchitect", character_metrics)),
            adventures,
            characters,
            portrait_generator=_build_portrait_generator(),
            portrait_store=_build_portrait_store(),
        ),
        openings=characters,
        adventure_metrics=adventure_metrics,
        character_metrics=character_metrics,
        model_id=model_id,
        delivery=_build_delivery(),
    )


_CAMPAIGN_WORKFLOW = _build_campaign_workflow()


def _build_turn_worker() -> TurnWorker:
    artifact_client = cast(DynamoDbArtifactClient, boto3.client("dynamodb", config=_CONFIG))
    return TurnWorker(
        _REPOSITORY,
        _REPOSITORY,
        DynamoDbWorldSnapshots(artifact_client, _TABLE_NAME),
        _structured_agent("DungeonMaster"),
        _microvm_manager(),
        delivery=_build_delivery(),
        telemetry=_TELEMETRY,
    )


_TURN_WORKER = _build_turn_worker() if "BEDROCK_MODEL_ID" in os.environ else None


def _build_websocket_adapter(endpoint: str) -> ApiGatewayWebSocketAdapter:
    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint, config=_CONFIG)
    connections = _connection_repository()
    service = RealtimeSessionService(
        connections,
        _REPOSITORY,
        _REPOSITORY,
        campaigns=_CAMPAIGN_REPOSITORY,
        campaign_events=_CAMPAIGN_REPOSITORY,
    )
    return ApiGatewayWebSocketAdapter(service, _ApiGatewaySender(client, connections))


def http_handler(event: Mapping[str, Any], context: object) -> dict[str, Any]:
    if _HTTP_ADAPTER is None:
        raise RuntimeError("HTTP adapter is not configured in this function")
    return _HTTP_ADAPTER(event, context)


def workflow_handler(event: Mapping[str, object], _context: object) -> dict[str, object]:
    if event.get("operation") in _CAMPAIGN_OPERATIONS:
        return _CAMPAIGN_WORKFLOW.handle(event)
    return _WORKFLOW.handle(event)


def turn_handler(event: Mapping[str, object], _context: object) -> dict[str, object]:
    if _TURN_WORKER is None:
        raise RuntimeError("turn worker is not configured in this function")
    return _TURN_WORKER.handle(event)


def websocket_handler(event: Mapping[str, Any], context: object) -> dict[str, Any]:
    request_context = event.get("requestContext")
    if not isinstance(request_context, Mapping):
        return {"statusCode": 400}
    domain = request_context.get("domainName")
    stage = request_context.get("stage")
    if not isinstance(domain, str) or not isinstance(stage, str):
        return {"statusCode": 400}
    adapter = _build_websocket_adapter(f"https://{domain}/{stage}")
    return adapter(event, context)
