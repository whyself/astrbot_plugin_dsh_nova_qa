"""Per-Session sliding-window question limits."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SessionHourlyLimiter:
    """Track accepted questions independently for each runtime Session."""

    def __init__(
        self,
        limit: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        self.limit = limit
        self._clock = clock
        self._accepted_at: dict[str, deque[float]] = {}

    def accept(self, session_id: str) -> bool:
        """Accept one question when the Session remains below its hourly limit."""

        if self.limit == 0:
            return True

        now = self._clock()
        cutoff = now - 3600
        timestamps = self._accepted_at.setdefault(session_id, deque())
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        if len(timestamps) >= self.limit:
            return False

        timestamps.append(now)
        return True
