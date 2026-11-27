from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    """In-memory sliding-window rate limiter for single-administrator login protection."""

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: int = 900,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self._clock = clock or time.monotonic
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def check(self, key: str) -> tuple[bool, int]:
        """Return (is_allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            bucket = self._attempts[key]
            self._prune(bucket, now)
            if len(bucket) >= self.max_attempts:
                retry_after = math.ceil((bucket[0] + self.window_seconds) - now)
                return False, max(1, retry_after)
            return True, 0

    def record_failure(self, key: str) -> int:
        """Record a failed attempt and return current attempt count in the window."""
        now = self._clock()
        with self._lock:
            bucket = self._attempts[key]
            self._prune(bucket, now)
            bucket.append(now)
            return len(bucket)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._attempts.clear()
