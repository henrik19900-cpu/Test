"""A lasting copy of the bet log in a Postgres database, such as Neon's free plan.

Streamlit Cloud starts the app with an empty disk after a restart, so the SQLite database, bet log
included, is gone. With DATABASE_URL set (a Postgres connection string), the bet log is kept as CSV
(bets.to_csv) in one table there: it is read back once when the app starts, and written whenever it
changes. The previous version is kept too, in case a change was a mistake.
"""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from typing import Protocol

from . import bets, config

BETS = "bets.csv"
PREVIOUS = "bets.previous.csv"

SCHEMA = """CREATE TABLE IF NOT EXISTS oddscompare_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""


class Store(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...


class PostgresStore:
    """Text values by key in the table oddscompare_store, made on first use."""

    def __init__(self, url: str, timeout_seconds: float = 20):
        self.url = url
        self.timeout_seconds = timeout_seconds

    def _connect(self):
        import psycopg  # only needed with DATABASE_URL

        conn = psycopg.connect(self.url, connect_timeout=int(self.timeout_seconds), autocommit=True)
        conn.execute(SCHEMA)
        return conn

    def get(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM oddscompare_store WHERE key = %s", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO oddscompare_store (key, value) VALUES (%s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""",
                (key, value),
            )


def store_from_env() -> PostgresStore | None:
    """The store named by DATABASE_URL (from .env or Streamlit's secrets), or None without one."""
    url = config.api_key("DATABASE_URL")
    return PostgresStore(url) if url else None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def restore_bets(conn: sqlite3.Connection, store: Store) -> int:
    """Read the stored bet log back: the bets the local log does not have (after a restart, all of them).
    A bet in both is left as the local log has it. Returns how many bets were added."""
    text = store.get(BETS)
    if not text:
        return 0
    local_ids = {b["id"] for b in bets.all_bets(conn)}
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = [row for row in reader if row.get("id") not in local_ids]
    if not missing:
        return 0
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
    writer.writeheader()
    writer.writerows(missing)
    return bets.from_csv(conn, out.getvalue())


def backup_bets(conn: sqlite3.Connection, store: Store, last_digest: str | None) -> str:
    """Write the bet log when it changed since last_digest; returns its digest now. The version it
    replaces is kept as the previous one."""
    text = bets.to_csv(bets.all_bets(conn))
    now = digest(text)
    if now != last_digest:
        stored = store.get(BETS)
        if stored is not None and digest(stored) == now:
            return now  # already there, e.g. just restored
        if stored is not None:
            store.put(PREVIOUS, stored)
        store.put(BETS, text)
    return now
