"""Thin API Gateway WebSocket transport adapter for the sandbox realtime channel."""

import json
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import TypeAdapter, ValidationError

from dungeon_agent.control_plane.domain.models import CampaignId, OwnerId, SessionId
from dungeon_agent.control_plane.realtime.service import RealtimeSessionService

_OWNER_ID = TypeAdapter(OwnerId)
_SESSION_ID = TypeAdapter(SessionId)
_CAMPAIGN_ID = TypeAdapter(CampaignId)


class ConnectionSender(Protocol):
    """Push bytes to one live API Gateway connection."""

    def send(self, connection_id: str, data: bytes) -> None: ...


class ApiGatewayWebSocketAdapter:
    """Map connection routes onto the framework-neutral realtime service."""

    def __init__(self, service: RealtimeSessionService, sender: ConnectionSender) -> None:
        self._service = service
        self._sender = sender

    def __call__(self, event: Mapping[str, Any], _context: object = None) -> dict[str, Any]:
        request_context = event.get("requestContext")
        if not isinstance(request_context, Mapping):
            return _response(400)
        connection_id = request_context.get("connectionId")
        route_key = request_context.get("routeKey")
        if not isinstance(connection_id, str) or not connection_id:
            return _response(400)
        try:
            if route_key == "$connect":
                return self._connect(event, connection_id)
            if route_key == "$disconnect":
                self._service.disconnect(connection_id)
                return _response(200)
            if route_key == "subscribe":
                return self._subscribe(event, connection_id)
            if route_key == "ping":
                self._sender.send(connection_id, b'{"type":"pong"}')
                return _response(200)
            return _response(404)
        except TypeError, ValueError, ValidationError, json.JSONDecodeError:
            return _response(400)
        except PermissionError:
            return _response(403)

    def _connect(self, event: Mapping[str, Any], connection_id: str) -> dict[str, Any]:
        query = event.get("queryStringParameters") or {}
        if not isinstance(query, Mapping):
            return _response(400)
        owner_id = _OWNER_ID.validate_python(query.get("playerId"))
        self._service.connect(connection_id, owner_id)
        return _response(200)

    def _subscribe(self, event: Mapping[str, Any], connection_id: str) -> dict[str, Any]:
        body = event.get("body")
        if not isinstance(body, str):
            raise ValueError("body must be a string")
        message = json.loads(body)
        if not isinstance(message, Mapping):
            raise ValueError("message must be an object")
        owner_id = _OWNER_ID.validate_python(message.get("playerId"))
        after = message.get("afterSequence", 0)
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise ValueError("afterSequence must be a non-negative integer")
        raw_session_id = message.get("sessionId")
        raw_campaign_id = message.get("campaignId")
        if (raw_session_id is None) == (raw_campaign_id is None):
            raise ValueError("exactly one of sessionId or campaignId is required")
        if raw_session_id is not None:
            session_id = _SESSION_ID.validate_python(raw_session_id)
            missed = self._service.subscribe(
                connection_id,
                owner_id,
                session_id,
                after_sequence=after,
            )
            for missed_event in missed:
                self._sender.send(
                    connection_id, missed_event.model_dump_json(by_alias=True).encode()
                )
            return _response(200)
        campaign_id = _CAMPAIGN_ID.validate_python(raw_campaign_id)
        missed = self._service.subscribe_campaign(
            connection_id,
            owner_id,
            campaign_id,
            after_sequence=after,
        )
        for missed_event in missed:
            self._sender.send(connection_id, missed_event.model_dump_json(by_alias=True).encode())
        return _response(200)


def _response(status_code: int) -> dict[str, Any]:
    return {"statusCode": status_code}
