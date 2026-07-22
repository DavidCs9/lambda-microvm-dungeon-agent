import logging
import time
from collections.abc import Callable
from typing import Any

from dungeon_agent.control_plane.domain.enums import ErrorCode
from dungeon_agent.control_plane.http.errors import dependency_error, error_result
from dungeon_agent.control_plane.http.models import (
    AuthenticatedIdentity,
    HttpResult,
    SpeechEnvelope,
    SpeechRequest,
)

LOGGER = logging.getLogger(__name__)


class SpeechHttpHandlers:
    def __init__(
        self,
        synthesizer: Any,
        *,
        expires_in_seconds: int = 300,
        max_requests_per_owner_per_minute: int = 60,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._synthesizer = synthesizer
        self._expires_in_seconds = expires_in_seconds
        self._max_requests_per_owner_per_minute = max_requests_per_owner_per_minute
        self._monotonic = monotonic or time.monotonic
        self._request_counts: dict[str, tuple[int, float]] = {}

    def synthesize_speech(
        self,
        identity: AuthenticatedIdentity,
        request: SpeechRequest,
        *,
        correlation_id: str,
    ) -> HttpResult:
        if not self._allow_request(identity.owner_id):
            return error_result(
                status_code=429,
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Too many speech requests; retry shortly.",
                retryable=True,
                correlation_id=correlation_id,
            )
        try:
            url, cache_hit = self._synthesizer.synthesize(request.text, request.language)
        except Exception:
            LOGGER.exception(
                "speech_synthesis_failed",
                extra={"correlation_id": correlation_id, "owner_id": identity.owner_id},
            )
            return self._dependency_error(correlation_id)
        return HttpResult(
            status_code=200,
            body=SpeechEnvelope(
                url=url,
                expires_in_seconds=self._expires_in_seconds,
                cache_hit=cache_hit,
            ),
            correlation_id=correlation_id,
        )

    def _allow_request(self, owner_id: str) -> bool:
        now = self._monotonic()
        count, window_start = self._request_counts.get(owner_id, (0, now))
        if now - window_start >= 60:
            count, window_start = 0, now
        if count >= self._max_requests_per_owner_per_minute:
            self._request_counts[owner_id] = (count, window_start)
            return False
        self._request_counts[owner_id] = (count + 1, window_start)
        return True

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return dependency_error("Speech synthesis is temporarily unavailable.", correlation_id)
