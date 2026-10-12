"""How many times people have looked at a listing, shown to its owner.

Views are counted in memory and written to the database every few minutes (by the maintenance worker
and when the app stops), so a page view never waits for a write. The same visitor reloading a page
counts once per round, and bots and link previews are not counted. Nothing about the visitor is stored.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections import Counter

from .db import transaction

_BOTS = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|curl|wget|python|httpx|go-http|java/|headless",
    re.IGNORECASE,
)
MAX_VISITORS = 200_000  # remembered per round, to count reloads once; the round ends at the next flush


class ViewCounter:
    def __init__(self) -> None:
        self._counts: Counter[int] = Counter()
        self._seen: set[bytes] = set()
        self._lock = threading.Lock()

    def add(self, listing_id: int, visitor: str, user_agent: str) -> None:
        if not user_agent or _BOTS.search(user_agent):
            return
        key = hashlib.blake2b(f"{listing_id}|{visitor}|{user_agent}".encode(), digest_size=12).digest()
        with self._lock:
            if key in self._seen:
                return
            if len(self._seen) < MAX_VISITORS:
                self._seen.add(key)
            self._counts[listing_id] += 1

    def pending(self, listing_id: int) -> int:
        with self._lock:
            return self._counts.get(listing_id, 0)

    def flush(self, conn: sqlite3.Connection) -> int:
        """Write the counted views. Returns how many listings got new views."""
        with self._lock:
            counts, self._counts = self._counts, Counter()
            self._seen = set()
        if counts:
            try:
                with transaction(conn):
                    conn.executemany(
                        "UPDATE listings SET views = views + ? WHERE id = ?",
                        [(count, listing_id) for listing_id, count in counts.items()],
                    )
            except Exception:
                with self._lock:  # keep them for the next round
                    self._counts.update(counts)
                raise
        return len(counts)
