"""AWS Lambda entry points for the sandbox control plane."""

import os
from collections.abc import Mapping
from typing import Any, cast

import boto3
from botocore.config import Config

from dungeon_agent.control_plane.application import DefaultSessionFactory
from dungeon_agent.control_plane.http import ApiGatewayHttpAdapter, SessionHttpHandlers
from dungeon_agent.control_plane.persistence.dynamodb import create_dynamodb_repository
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
_WORKFLOW = DurableSessionWorkflowStub(_REPOSITORY, _REPOSITORY)


def http_handler(event: Mapping[str, Any], context: object) -> dict[str, Any]:
    if _HTTP_ADAPTER is None:
        raise RuntimeError("HTTP adapter is not configured in this function")
    return _HTTP_ADAPTER(event, context)


def workflow_handler(event: Mapping[str, object], _context: object) -> dict[str, object]:
    return _WORKFLOW.handle(event)
