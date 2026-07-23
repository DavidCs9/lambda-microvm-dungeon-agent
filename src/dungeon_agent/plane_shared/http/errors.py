from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from dungeon_agent.plane_shared.domain.enums import ErrorCode
from dungeon_agent.plane_shared.domain.models import ErrorDetail, ErrorEnvelope
from dungeon_agent.plane_shared.http.models import AuthenticatedIdentity, HttpResult

Clock = Callable[[], datetime]


class OwnedResource(Protocol):
    owner_id: str


def error_result(
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
                code=code, message=message, retryable=retryable, correlation_id=correlation_id
            )
        ),
        correlation_id=correlation_id,
    )


def dependency_error(message: str, correlation_id: str) -> HttpResult:
    return error_result(503, ErrorCode.DEPENDENCY_UNAVAILABLE, message, True, correlation_id)


def owner_access_error(
    identity: AuthenticatedIdentity,
    resource: OwnedResource | None,
    resource_name: str,
    not_found_code: ErrorCode,
    correlation_id: str,
) -> HttpResult | None:
    if resource is None:
        return error_result(
            404, not_found_code, f"{resource_name.capitalize()} not found.", False, correlation_id
        )
    if resource.owner_id != identity.owner_id:
        return error_result(
            403,
            ErrorCode.NOT_AUTHORIZED,
            f"You do not have access to this {resource_name}.",
            False,
            correlation_id,
        )
    return None


def load_owned(
    store: Any,
    identity: AuthenticatedIdentity,
    resource_id: str,
    *,
    resource_name: str,
    not_found_code: ErrorCode,
    dependency_message: str,
    correlation_id: str,
) -> tuple[Any | None, HttpResult | None]:
    try:
        resource = store.get(resource_id)
    except Exception:
        return None, dependency_error(dependency_message, correlation_id)
    access_error = owner_access_error(
        identity,
        resource,
        resource_name=resource_name,
        not_found_code=not_found_code,
        correlation_id=correlation_id,
    )
    return resource, access_error


def replay_events(
    store: Any,
    aggregate_id: str,
    *,
    after: int,
    correlation_id: str,
    dependency_message: str,
    envelope: Callable[[tuple[Any, ...], int], Any],
) -> HttpResult:
    try:
        events = store.list_after(aggregate_id, after)
    except Exception:
        return dependency_error(dependency_message, correlation_id)
    return HttpResult(
        status_code=200,
        body=envelope(events, events[-1].sequence if events else after),
        correlation_id=correlation_id,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
