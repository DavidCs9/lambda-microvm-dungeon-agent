"""Shared HTTP handler helpers."""

from collections.abc import Callable
from datetime import UTC, datetime

from dungeon_agent.control_plane.domain.enums import ErrorCode
from dungeon_agent.control_plane.domain.models import ErrorDetail, ErrorEnvelope
from dungeon_agent.control_plane.http.models import HttpResult

Clock = Callable[[], datetime]


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


def utc_now() -> datetime:
    return datetime.now(UTC)
