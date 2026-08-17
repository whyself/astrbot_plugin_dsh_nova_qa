from __future__ import annotations

import pytest

from rate_limit import SessionHourlyLimiter


def test_limit_is_independent_per_session_and_uses_sliding_hour() -> None:
    now = 1000.0
    limiter = SessionHourlyLimiter(2, clock=lambda: now)

    assert limiter.accept("group-1")
    assert limiter.accept("group-1")
    assert not limiter.accept("group-1")
    assert limiter.accept("group-2")

    now += 3600

    assert limiter.accept("group-1")


def test_zero_disables_limit() -> None:
    limiter = SessionHourlyLimiter(0)

    assert all(limiter.accept("group-1") for _ in range(100))


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_invalid_limit_is_rejected(limit: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        SessionHourlyLimiter(limit)  # type: ignore[arg-type]
