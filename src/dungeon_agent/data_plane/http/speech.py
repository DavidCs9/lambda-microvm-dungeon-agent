from typing import Any

from dungeon_agent.plane_shared.http.errors import dependency_error
from dungeon_agent.plane_shared.http.models import (
    AuthenticatedIdentity,
    HttpResult,
    SpeechEnvelope,
    SpeechRequest,
)
from dungeon_agent.plane_shared.logging import logger


class SpeechHttpHandlers:
    def __init__(
        self,
        synthesizer: Any,
        *,
        expires_in_seconds: int = 300,
    ) -> None:
        self._synthesizer = synthesizer
        self._expires_in_seconds = expires_in_seconds

    def synthesize_speech(
        self,
        identity: AuthenticatedIdentity,
        request: SpeechRequest,
        *,
        correlation_id: str,
    ) -> HttpResult:
        try:
            url, cache_hit = self._synthesizer.synthesize(request.text, request.language)
        except Exception:
            logger.exception(
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

    def _dependency_error(self, correlation_id: str) -> HttpResult:
        return dependency_error("Speech synthesis is temporarily unavailable.", correlation_id)
