"""Thin AWS API Gateway HTTP API v2 transport adapter."""

import base64
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from dungeon_agent.control_plane.domain.enums import ErrorCode
from dungeon_agent.control_plane.domain.models import CampaignId, SessionId
from dungeon_agent.control_plane.http.handlers import (
    CampaignHttpHandlers,
    SessionHttpHandlers,
)
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CreateCampaignRequest,
    CreateSessionRequest,
    HttpResult,
    SubmitActionRequest,
)

SESSION_ID_ADAPTER = TypeAdapter(SessionId)
CAMPAIGN_ID_ADAPTER = TypeAdapter(CampaignId)
SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


class ApiGatewayHttpAdapter:
    """Map HTTP API v2 proxy events onto framework-neutral control-plane handlers."""

    def __init__(
        self,
        handlers: SessionHttpHandlers,
        campaigns: CampaignHttpHandlers,
        *,
        allow_sandbox_identity: bool = False,
    ) -> None:
        self._handlers = handlers
        self._campaigns = campaigns
        self._allow_sandbox_identity = allow_sandbox_identity

    def __call__(self, event: Mapping[str, Any], _context: object = None) -> dict[str, Any]:
        headers = _normalized_headers(event.get("headers"))
        correlation_id = _correlation_id(headers, event)
        identity = _identity(event)
        if identity is None and self._allow_sandbox_identity:
            identity = _sandbox_identity(headers)
        if identity is None:
            return self._serialize(
                self._handlers.error(
                    status_code=401,
                    code=ErrorCode.NOT_AUTHENTICATED,
                    message="Authentication is required.",
                    retryable=False,
                    correlation_id=correlation_id,
                )
            )

        route_key = str(event.get("routeKey", ""))
        try:
            if route_key == "POST /sessions":
                result = self._create(event, headers, identity, correlation_id)
            elif route_key == "POST /sessions/{sessionId}/actions":
                result = self._submit_action(event, headers, identity, correlation_id)
            elif route_key == "GET /sessions/{sessionId}":
                result = self._get_session(event, identity, correlation_id)
            elif route_key == "GET /sessions/{sessionId}/events":
                result = self._list_events(event, identity, correlation_id)
            elif route_key == "POST /campaigns":
                result = self._create_campaign(event, headers, identity, correlation_id)
            elif route_key == "GET /campaigns/{campaignId}":
                result = self._get_campaign(event, identity, correlation_id)
            elif route_key == "GET /campaigns/{campaignId}/events":
                result = self._list_campaign_events(event, identity, correlation_id)
            else:
                result = self._handlers.error(
                    status_code=404,
                    code=ErrorCode.SESSION_NOT_FOUND,
                    message="Route not found.",
                    retryable=False,
                    correlation_id=correlation_id,
                )
        except TypeError, ValueError, ValidationError, json.JSONDecodeError:
            result = self._handlers.error(
                status_code=400,
                code=ErrorCode.VALIDATION_FAILED,
                message="The request is invalid.",
                retryable=False,
                correlation_id=correlation_id,
            )
        return self._serialize(result)

    def _create(
        self,
        event: Mapping[str, Any],
        headers: Mapping[str, str],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        idempotency_key = headers.get("idempotency-key", "")
        payload = _json_body(event)
        request = CreateSessionRequest.model_validate(payload)
        return self._handlers.create_session(
            identity,
            request,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _create_campaign(
        self,
        event: Mapping[str, Any],
        headers: Mapping[str, str],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        idempotency_key = headers.get("idempotency-key", "")
        payload = _json_body(event)
        request = CreateCampaignRequest.model_validate(payload)
        return self._campaigns.create_campaign(
            identity,
            request,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _get_session(
        self,
        event: Mapping[str, Any],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        session_id = _path_parameter(event, "sessionId", SESSION_ID_ADAPTER)
        return self._handlers.get_session(
            identity,
            session_id,
            correlation_id=correlation_id,
        )

    def _get_campaign(
        self,
        event: Mapping[str, Any],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        campaign_id = _path_parameter(event, "campaignId", CAMPAIGN_ID_ADAPTER)
        return self._campaigns.get_campaign(
            identity,
            campaign_id,
            correlation_id=correlation_id,
        )

    def _submit_action(
        self,
        event: Mapping[str, Any],
        headers: Mapping[str, str],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        session_id = _path_parameter(event, "sessionId", SESSION_ID_ADAPTER)
        idempotency_key = headers.get("idempotency-key", "")
        request = SubmitActionRequest.model_validate(_json_body(event))
        return self._handlers.submit_action(
            identity,
            session_id,
            request,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _list_events(
        self,
        event: Mapping[str, Any],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        session_id = _path_parameter(event, "sessionId", SESSION_ID_ADAPTER)
        after = _replay_after(event)
        return self._handlers.list_events(
            identity,
            session_id,
            after=after,
            correlation_id=correlation_id,
        )

    def _list_campaign_events(
        self,
        event: Mapping[str, Any],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        campaign_id = _path_parameter(event, "campaignId", CAMPAIGN_ID_ADAPTER)
        after = _replay_after(event)
        return self._campaigns.list_events(
            identity,
            campaign_id,
            after=after,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _serialize(result: HttpResult) -> dict[str, Any]:
        return {
            "statusCode": result.status_code,
            "headers": result.headers(),
            "body": result.body.model_dump_json(by_alias=True),
            "isBase64Encoded": False,
        }


def _normalized_headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key).lower(): str(header) for key, header in value.items()}


def _correlation_id(headers: Mapping[str, str], event: Mapping[str, Any]) -> str:
    candidates = [headers.get("x-correlation-id"), _request_id(event)]
    for candidate in candidates:
        if candidate is not None and SAFE_CORRELATION_ID.fullmatch(candidate):
            return candidate
    return f"corr_{uuid4().hex}"


def _request_id(event: Mapping[str, Any]) -> str | None:
    request_context = event.get("requestContext")
    if not isinstance(request_context, Mapping):
        return None
    request_id = request_context.get("requestId")
    return str(request_id) if request_id is not None else None


def _identity(event: Mapping[str, Any]) -> AuthenticatedIdentity | None:
    request_context = event.get("requestContext")
    if not isinstance(request_context, Mapping):
        return None
    authorizer = request_context.get("authorizer")
    if not isinstance(authorizer, Mapping):
        return None
    jwt = authorizer.get("jwt")
    if not isinstance(jwt, Mapping):
        return None
    claims = jwt.get("claims")
    if not isinstance(claims, Mapping):
        return None
    subject = claims.get("sub")
    if not isinstance(subject, str):
        return None
    try:
        return AuthenticatedIdentity(owner_id=subject)
    except ValidationError:
        return None


def _sandbox_identity(headers: Mapping[str, str]) -> AuthenticatedIdentity | None:
    player_id = headers.get("x-player-id")
    if player_id is None:
        return None
    try:
        return AuthenticatedIdentity(owner_id=player_id)
    except ValidationError:
        return None


def _json_body(event: Mapping[str, Any]) -> object:
    body = event.get("body")
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    if event.get("isBase64Encoded") is True:
        body = base64.b64decode(body, validate=True).decode("utf-8")
    return json.loads(body)


def _path_parameter[T](event: Mapping[str, Any], name: str, adapter: TypeAdapter[T]) -> T:
    parameters = event.get("pathParameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("pathParameters must be an object")
    return adapter.validate_python(parameters.get(name))


def _replay_after(event: Mapping[str, Any]) -> int:
    query = event.get("queryStringParameters") or {}
    if not isinstance(query, Mapping):
        raise ValueError("queryStringParameters must be an object")
    after = int(query.get("after", 0))
    if after < 0:
        raise ValueError("after must be non-negative")
    return after
