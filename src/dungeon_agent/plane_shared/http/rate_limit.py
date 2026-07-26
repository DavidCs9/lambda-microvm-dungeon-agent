"""Small per-user, fixed-window rate limiter for the HTTP Lambda."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int | None = None


class UserRateLimiter:
    """Best-effort per-user limiter scoped to a single Lambda execution environment."""

    def __init__(
        self,
        limits: Mapping[str, int],
        *,
        window_seconds: int = 60,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._limits = dict(limits)
        self._window_seconds = window_seconds
        self._monotonic = monotonic or time.monotonic
        self._windows: dict[tuple[str, str], tuple[int, float]] = {}

    def check(self, owner_id: str, scope: str) -> RateLimitDecision:
        limit = self._limits.get(scope)
        if limit is None:
            return RateLimitDecision(allowed=True)

        now = self._monotonic()
        self._prune(now)
        key = (owner_id, scope)
        count, window_start = self._windows.get(key, (0, now))
        if count >= limit:
            retry_after = max(1, int(self._window_seconds - (now - window_start) + 0.999))
            return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

        self._windows[key] = (count + 1, window_start)
        return RateLimitDecision(allowed=True)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, (_count, window_start) in self._windows.items()
            if now - window_start >= self._window_seconds
        ]
        for key in expired:
            del self._windows[key]
