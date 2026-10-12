"""In-memory fixed-window rate limiter (per process).

Good enough for a single instance. Behind several instances, swap in a shared store. The keys are IP addresses
and, for wrong passwords, e-mail addresses: each is forgotten within MAX_WINDOW_SECONDS after its window ends.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

MAX_WINDOW_SECONDS = 3600  # the longest window any limit uses
PURGE_SECONDS = 60  # how often windows that are over are forgotten


@dataclass
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_in: int


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}
        self._purged_at = clock()

    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> Decision:
        now = self._clock()
        with self._lock:
            if len(self._windows) > 50_000 or now - self._purged_at >= PURGE_SECONDS:
                self._purge(now)
                self._purged_at = now
            start, count, reset_in = self._window(bucket, key, window_seconds, now)
            if count >= limit:
                return Decision(False, limit, 0, reset_in)
            self._windows[(bucket, key)] = (start, count + 1)
            return Decision(True, limit, limit - count - 1, reset_in)

    def peek(self, bucket: str, key: str, limit: int, window_seconds: int) -> Decision:
        """What hit() would decide, without counting."""
        with self._lock:
            _, count, reset_in = self._window(bucket, key, window_seconds, self._clock())
            return Decision(count < limit, limit, max(0, limit - count), reset_in)

    def clear(self, bucket: str, key: str) -> None:
        with self._lock:
            self._windows.pop((bucket, key), None)

    def _window(self, bucket: str, key: str, window_seconds: int, now: float) -> tuple[float, int, int]:
        start, count = self._windows.get((bucket, key), (now, 0))
        if now - start >= window_seconds:
            start, count = now, 0
        return start, count, max(1, int(window_seconds - (now - start)))

    def _purge(self, now: float, max_window: int = MAX_WINDOW_SECONDS) -> None:
        for key, (start, _) in list(self._windows.items()):
            if now - start >= max_window:
                del self._windows[key]

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
