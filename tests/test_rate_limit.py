from dungeon_agent.plane_shared.http.rate_limit import UserRateLimiter


def test_user_rate_limiter_is_scoped_by_user_and_route() -> None:
    now = 100.0
    limiter = UserRateLimiter({"POST /speech": 1}, monotonic=lambda: now)

    assert limiter.check("user_a", "POST /speech").allowed
    assert not limiter.check("user_a", "POST /speech").allowed
    assert limiter.check("user_b", "POST /speech").allowed
    assert limiter.check("user_a", "GET /campaigns").allowed


def test_user_rate_limiter_exposes_remaining_window() -> None:
    now = 100.0
    limiter = UserRateLimiter({"POST /speech": 1}, monotonic=lambda: now)
    assert limiter.check("user_a", "POST /speech").allowed

    now = 110.2
    blocked = limiter.check("user_a", "POST /speech")
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 50

    now = 160.0
    assert limiter.check("user_a", "POST /speech").allowed
