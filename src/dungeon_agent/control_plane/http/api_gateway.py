import base64
import json
import re
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from dungeon_agent.control_plane.domain.enums import CampaignStatus, ErrorCode
from dungeon_agent.control_plane.domain.models import CampaignId, SessionId
from dungeon_agent.control_plane.http.campaigns import CampaignHttpHandlers
from dungeon_agent.control_plane.http.errors import dependency_error, error_result
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    CreateCampaignRequest,
    CreateSessionRequest,
    HttpResult,
    SpeechRequest,
    SubmitActionRequest,
)
from dungeon_agent.control_plane.http.sessions import SessionHttpHandlers
from dungeon_agent.control_plane.http.speech import SpeechHttpHandlers

SESSION_ID_ADAPTER = TypeAdapter(SessionId)
CAMPAIGN_ID_ADAPTER = TypeAdapter(CampaignId)
SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")
type RouteHandler = Callable[
    [Mapping[str, Any], Mapping[str, str], AuthenticatedIdentity, str], HttpResult
]


class ApiGatewayHttpAdapter:
    def __init__(
        self,
        handlers: SessionHttpHandlers,
        campaigns: CampaignHttpHandlers,
        *,
        speech: SpeechHttpHandlers | None = None,
        allow_sandbox_identity: bool = False,
    ) -> None:
        self._handlers = handlers
        self._campaigns = campaigns
        self._speech = speech
        self._allow_sandbox_identity = allow_sandbox_identity
        sessions, campaigns = self._handlers, self._campaigns
        self._routes: dict[str, RouteHandler] = {
            "POST /sessions": self._create,
            "POST /sessions/{sessionId}/actions": self._submit_action,
            "GET /sessions/{sessionId}": lambda e, _h, i, c: sessions.get_session(
                i, _session_id(e), correlation_id=c
            ),
            "GET /sessions/{sessionId}/events": lambda e, _h, i, c: sessions.list_events(
                i, _session_id(e), after=_replay_after(e), correlation_id=c
            ),
            "GET /sessions": self._list_active_sessions,
            "POST /sessions/{sessionId}/abandon": lambda e, _h, i, c: sessions.abandon_session(
                i, _session_id(e), correlation_id=c
            ),
            "POST /campaigns": self._create_campaign,
            "GET /campaigns": lambda e, _h, i, c: campaigns.list_campaigns(
                i, status=_campaign_status_filter(e), correlation_id=c
            ),
            "GET /campaigns/{campaignId}": lambda e, _h, i, c: campaigns.get_campaign(
                i, _campaign_id(e), correlation_id=c
            ),
            "GET /campaigns/{campaignId}/events": lambda e, _h, i, c: campaigns.list_events(
                i, _campaign_id(e), after=_replay_after(e), correlation_id=c
            ),
            "GET /campaigns/{campaignId}/opening": lambda e, _h, i, c: (
                campaigns.get_campaign_opening(i, _campaign_id(e), correlation_id=c)
            ),
            "POST /speech": self._synthesize_speech,
        }

    def __call__(self, event: Mapping[str, Any], _context: object = None) -> dict[str, Any]:
        headers = _normalized_headers(event.get("headers"))
        correlation_id = _correlation_id(headers, event)
        identity = _identity(event)
        if identity is None and self._allow_sandbox_identity:
            identity = _sandbox_identity(headers)
        if identity is None:
            return self._serialize(
                error_result(
                    401,
                    ErrorCode.NOT_AUTHENTICATED,
                    "Authentication is required.",
                    False,
                    correlation_id,
                )
            )

        route_key = str(event.get("routeKey", ""))
        route = self._routes.get(route_key)
        try:
            if route is None:
                result = error_result(
                    404, ErrorCode.SESSION_NOT_FOUND, "Route not found.", False, correlation_id
                )
            else:
                result = route(event, headers, identity, correlation_id)
        except TypeError, ValueError, ValidationError, json.JSONDecodeError:
            result = error_result(
                400, ErrorCode.VALIDATION_FAILED, "The request is invalid.", False, correlation_id
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
        request = CreateSessionRequest.model_validate(_json_body(event))
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
        request = CreateCampaignRequest.model_validate(_json_body(event))
        return self._campaigns.create_campaign(
            identity,
            request,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _submit_action(
        self,
        event: Mapping[str, Any],
        headers: Mapping[str, str],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        session_id = _session_id(event)
        idempotency_key = headers.get("idempotency-key", "")
        request = SubmitActionRequest.model_validate(_json_body(event))
        return self._handlers.submit_action(
            identity,
            session_id,
            request,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _list_active_sessions(
        self,
        event: Mapping[str, Any],
        _headers: Mapping[str, str],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        _require_active_status_filter(event)
        return self._handlers.list_active_sessions(
            identity,
            correlation_id=correlation_id,
        )

    def _synthesize_speech(
        self,
        event: Mapping[str, Any],
        _headers: Mapping[str, str],
        identity: AuthenticatedIdentity,
        correlation_id: str,
    ) -> HttpResult:
        if self._speech is None:
            return dependency_error("Speech synthesis is temporarily unavailable.", correlation_id)
        request = SpeechRequest.model_validate(_json_body(event))
        return self._speech.synthesize_speech(
            identity,
            request,
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


def _session_id(event: Mapping[str, Any]) -> SessionId:
    return _path_parameter(event, "sessionId", SESSION_ID_ADAPTER)


def _campaign_id(event: Mapping[str, Any]) -> CampaignId:
    return _path_parameter(event, "campaignId", CAMPAIGN_ID_ADAPTER)


def _replay_after(event: Mapping[str, Any]) -> int:
    query = event.get("queryStringParameters") or {}
    if not isinstance(query, Mapping):
        raise ValueError("queryStringParameters must be an object")
    after = int(query.get("after", 0))
    if after < 0:
        raise ValueError("after must be non-negative")
    return after


def _require_active_status_filter(event: Mapping[str, Any]) -> None:
    query = event.get("queryStringParameters") or {}
    if not isinstance(query, Mapping):
        raise ValueError("queryStringParameters must be an object")
    if query.get("status") != "active":
        raise ValueError("status must be 'active'")


def _campaign_status_filter(event: Mapping[str, Any]) -> str | None:
    query = event.get("queryStringParameters") or {}
    if not isinstance(query, Mapping):
        raise ValueError("queryStringParameters must be an object")
    status = query.get("status")
    if status is None or status == "":
        return None
    return CampaignStatus(str(status)).value
