from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from dungeon_agent.control_plane.domain.enums import ErrorCode
from dungeon_agent.control_plane.domain.models import ErrorDetail, ErrorEnvelope
from dungeon_agent.control_plane.http.models import AuthenticatedIdentity, HttpResult

Clock = Callable[[], datetime]


class OwnedResource(Protocol):
    owner_id: str


def error_result(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool,
    correlation_id: str,
) -> HttpResult:
    return HttpResult(
        status_code=status_code,
        body=ErrorEnvelope(
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=retryable,
                correlation_id=correlation_id,
            )
        ),
        correlation_id=correlation_id,
    )


def dependency_error(message: str, correlation_id: str) -> HttpResult:
    return error_result(
        status_code=503,
        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
        message=message,
        retryable=True,
        correlation_id=correlation_id,
    )


def owner_access_error(
    identity: AuthenticatedIdentity,
    resource: OwnedResource | None,
    *,
    resource_name: str,
    not_found_code: ErrorCode,
    correlation_id: str,
) -> HttpResult | None:
    if resource is None:
        return error_result(
            status_code=404,
            code=not_found_code,
            message=f"{resource_name.capitalize()} not found.",
            retryable=False,
            correlation_id=correlation_id,
        )
    if resource.owner_id != identity.owner_id:
        return error_result(
            status_code=403,
            code=ErrorCode.NOT_AUTHORIZED,
            message=f"You do not have access to this {resource_name}.",
            retryable=False,
            correlation_id=correlation_id,
        )
    return None


def utc_now() -> datetime:
    return datetime.now(UTC)
