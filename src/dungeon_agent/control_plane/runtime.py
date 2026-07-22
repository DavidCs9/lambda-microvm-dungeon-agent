import os
from collections.abc import Mapping
from importlib import import_module
from typing import Any, cast

from dungeon_agent.audio.polly import DEFAULT_VOICES, S3PollySpeechSynthesizer
from dungeon_agent.control_plane.agents.bedrock import StructuredBedrockAgent
from dungeon_agent.control_plane.agents.portrait import (
    DEFAULT_IMAGE_MODEL_ID,
    DEFAULT_IMAGE_REGION,
    BedrockPortraitGenerator,
)
from dungeon_agent.control_plane.agents.roles import (
    AdventureArchitect,
    CharacterArchitect,
)
from dungeon_agent.control_plane.domain.models import SubmitTurnCommand
from dungeon_agent.control_plane.http.api_gateway import ApiGatewayHttpAdapter
from dungeon_agent.control_plane.http.campaigns import CampaignHttpHandlers
from dungeon_agent.control_plane.http.sessions import SessionHttpHandlers
from dungeon_agent.control_plane.http.speech import SpeechHttpHandlers
from dungeon_agent.control_plane.microvms.manager import (
    LambdaMicrovmManager,
)
from dungeon_agent.control_plane.persistence.dynamodb import (
    create_dynamodb_campaign_repository,
    create_dynamodb_repository,
)
from dungeon_agent.control_plane.realtime.api_gateway import ApiGatewayWebSocketAdapter
from dungeon_agent.control_plane.realtime.delivery import BestEffortEventDelivery
from dungeon_agent.control_plane.realtime.dynamodb import (
    DynamoDbConnectionRepository,
)
from dungeon_agent.control_plane.realtime.service import RealtimeSessionService
from dungeon_agent.control_plane.steps.artifacts import ArtifactAggregate, DynamoDbArtifactStore
from dungeon_agent.control_plane.steps.portraits import S3PortraitStore
from dungeon_agent.control_plane.turns import TurnWorker
from dungeon_agent.control_plane.workflow.campaigns import DurableCampaignWorkflowStub
from dungeon_agent.control_plane.workflow.step_functions import StepFunctionsWorkflowStarter
from dungeon_agent.control_plane.workflow.stub import DurableSessionWorkflowStub


def _boto3() -> Any:
    return import_module("boto3")


def _client(service: str, **kwargs: Any) -> Any:
    kwargs.setdefault("config", _CONFIG)
    return _boto3().client(service, **kwargs)


def _artifacts(table_name: str, aggregate: ArtifactAggregate = "SESSION") -> DynamoDbArtifactStore:
    return DynamoDbArtifactStore(_client("dynamodb"), table_name, aggregate=aggregate)


def _aws_config(**kwargs: Any) -> Any:
    return cast(Any, import_module("botocore.config")).Config(**kwargs)


_CONFIG = _aws_config(
    retries={"total_max_attempts": 3, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=10,
)
_BEDROCK_CONFIG = _aws_config(
    retries={"total_max_attempts": 2, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=120,
)
_TABLE_NAME = os.environ["TABLE_NAME"]
_REPOSITORY = create_dynamodb_repository(_TABLE_NAME)
_CAMPAIGN_TABLE_NAME = os.environ["CAMPAIGN_TABLE_NAME"]
_CAMPAIGN_REPOSITORY = create_dynamodb_campaign_repository(_CAMPAIGN_TABLE_NAME)
_REGION = os.environ.get("AWS_REGION", "us-east-2")

_CAMPAIGN_OPERATIONS = {
    "ValidateCampaign",
    "CreateCampaignRecord",
    "GenerateAdventure",
    "GenerateCharacter",
    "MarkCampaignReady",
    "EmitCampaignReady",
    "MarkCampaignFailed",
    "EmitCampaignCreationFailed",
}


class LambdaTurnWorkerInvoker:
    def __init__(self, client: Any, function_name: str) -> None:
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
    return _client("apigatewaymanagementapi", endpoint_url=endpoint)


def _connection_repository() -> DynamoDbConnectionRepository:
    resource = _boto3().resource("dynamodb", region_name=_REGION, config=_CONFIG)
    return DynamoDbConnectionRepository(resource.Table(_TABLE_NAME))


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
        _client("lambda-microvms"),
        os.environ["MICROVM_IMAGE_NAME"],
        _REGION,
    )


def _build_speech_handlers() -> SpeechHttpHandlers | None:
    bucket = os.environ.get("SPEECH_CACHE_BUCKET")
    if bucket is None:
        return None
    polly_region = os.environ.get("POLLY_REGION", "us-east-1")
    polly = _client("polly", region_name=polly_region)
    # Regional endpoint so presigned URLs hit s3.<region>.amazonaws.com directly.
    # Global s3.amazonaws.com returns TemporaryRedirect (307), which breaks <audio> playback.
    s3 = _client(
        "s3",
        region_name=_REGION,
        endpoint_url=f"https://s3.{_REGION}.amazonaws.com",
    )
    return SpeechHttpHandlers(S3PollySpeechSynthesizer(polly, s3, bucket, DEFAULT_VOICES))


def _build_portrait_store() -> S3PortraitStore | None:
    bucket = os.environ.get("SPEECH_CACHE_BUCKET")
    if bucket is None:
        return None
    s3 = _client("s3", region_name=_REGION)
    return S3PortraitStore(s3, bucket)


def _build_portrait_generator() -> BedrockPortraitGenerator | None:
    if "SPEECH_CACHE_BUCKET" not in os.environ:
        return None
    model_id = os.environ.get("BEDROCK_IMAGE_MODEL_ID", DEFAULT_IMAGE_MODEL_ID)
    image_region = os.environ.get("BEDROCK_IMAGE_REGION", DEFAULT_IMAGE_REGION)
    image_config = _aws_config(
        retries={"total_max_attempts": 2, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=300,
    )
    bedrock_image = _client("bedrock-runtime", region_name=image_region, config=image_config)
    return BedrockPortraitGenerator(cast(Any, bedrock_image), model_id)


def _build_http_adapter() -> ApiGatewayHttpAdapter:
    starter = StepFunctionsWorkflowStarter(
        _client("stepfunctions"),
        os.environ["STATE_MACHINE_ARN"],
        campaign_state_machine_arn=os.environ["CAMPAIGN_STATE_MACHINE_ARN"],
    )
    sessions = SessionHttpHandlers(
        _REPOSITORY,
        starter,
        _CAMPAIGN_REPOSITORY,
        turns=_build_turn_invoker(),
        delivery=_build_delivery(),
        microvms=_microvm_manager() if "MICROVM_IMAGE_NAME" in os.environ else None,
    )
    campaigns = CampaignHttpHandlers(
        _CAMPAIGN_REPOSITORY,
        starter,
        openings=_artifacts(_CAMPAIGN_TABLE_NAME, "CAMPAIGN"),
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
    return LambdaTurnWorkerInvoker(_client("lambda"), function_name)


_HTTP_ADAPTER = (
    _build_http_adapter()
    if "STATE_MACHINE_ARN" in os.environ and "CAMPAIGN_STATE_MACHINE_ARN" in os.environ
    else None
)


def _structured_agent() -> StructuredBedrockAgent:
    return StructuredBedrockAgent(
        cast(Any, _client("bedrock-runtime", config=_BEDROCK_CONFIG)),
        os.environ["BEDROCK_MODEL_ID"],
    )


def _build_workflow() -> DurableSessionWorkflowStub:
    if "MICROVM_IMAGE_NAME" not in os.environ:
        return DurableSessionWorkflowStub(_REPOSITORY, delivery=_build_delivery())

    session_artifacts = _artifacts(_TABLE_NAME)
    campaign_artifacts = _artifacts(_CAMPAIGN_TABLE_NAME, "CAMPAIGN")
    return DurableSessionWorkflowStub(
        _REPOSITORY,
        campaigns=_CAMPAIGN_REPOSITORY,
        campaign_adventures=campaign_artifacts,
        campaign_characters=campaign_artifacts,
        adventures=session_artifacts,
        characters=session_artifacts,
        microvms=_microvm_manager(),
        snapshots=session_artifacts,
        delivery=_build_delivery(),
    )


_WORKFLOW = _build_workflow()


def _build_campaign_workflow() -> DurableCampaignWorkflowStub:
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if model_id is None:
        return DurableCampaignWorkflowStub(
            _CAMPAIGN_REPOSITORY,
            delivery=_build_delivery(),
        )

    artifacts = _artifacts(_CAMPAIGN_TABLE_NAME, "CAMPAIGN")
    return DurableCampaignWorkflowStub(
        _CAMPAIGN_REPOSITORY,
        adventure_architect=AdventureArchitect(_structured_agent()),
        character_architect=CharacterArchitect(_structured_agent()),
        adventures=artifacts,
        characters=artifacts,
        openings=artifacts,
        portrait_generator=_build_portrait_generator(),
        portrait_store=_build_portrait_store(),
        delivery=_build_delivery(),
    )


_CAMPAIGN_WORKFLOW = _build_campaign_workflow()


def _build_turn_worker() -> TurnWorker:
    return TurnWorker(
        _REPOSITORY,
        _artifacts(_TABLE_NAME),
        _structured_agent(),
        _microvm_manager(),
        delivery=_build_delivery(),
    )


_TURN_WORKER = _build_turn_worker() if "BEDROCK_MODEL_ID" in os.environ else None


def _build_websocket_adapter(endpoint: str) -> ApiGatewayWebSocketAdapter:
    client = _client("apigatewaymanagementapi", endpoint_url=endpoint)
    connections = _connection_repository()
    service = RealtimeSessionService(
        connections,
        _REPOSITORY,
        campaign_store=_CAMPAIGN_REPOSITORY,
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
