"""SQLite storage. Every fetch adds a new snapshot, so odds movement and closing odds can be
analysed later. The schema is created or upgraded when a connection is opened."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .sources import RawEvent

# Each step upgrades the schema from version i to i + 1 (PRAGMA user_version).
MIGRATIONS = [
    """
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        sport TEXT NOT NULL,
        league TEXT NOT NULL,
        home TEXT NOT NULL,
        away TEXT NOT NULL,
        kickoff_utc TEXT NOT NULL
    );
    CREATE INDEX events_kickoff ON events(kickoff_utc);

    CREATE TABLE source_events (
        source TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        raw_home TEXT NOT NULL,
        raw_away TEXT NOT NULL,
        PRIMARY KEY (source, source_event_id)
    );
    CREATE INDEX source_events_event ON source_events(event_id);

    CREATE TABLE odds_snapshots (
        id INTEGER PRIMARY KEY,
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        market TEXT NOT NULL,
        outcome TEXT NOT NULL,
        odds REAL NOT NULL,
        fetched_at_utc TEXT NOT NULL
    );
    -- Also keeps a snapshot from being stored twice (a cached answer reused within five minutes).
    CREATE UNIQUE INDEX odds_snapshots_lookup ON odds_snapshots(event_id, source, fetched_at_utc, market, outcome);

    CREATE TABLE unmatched (
        source TEXT NOT NULL,
        raw_home TEXT NOT NULL,
        raw_away TEXT NOT NULL,
        kickoff_utc TEXT NOT NULL,
        league TEXT NOT NULL DEFAULT '',
        best_candidate TEXT,
        score REAL,
        last_seen_utc TEXT NOT NULL,
        PRIMARY KEY (source, raw_home, raw_away, kickoff_utc)
    );

    CREATE TABLE fetch_log (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        started_at_utc TEXT NOT NULL,
        status TEXT NOT NULL,
        n_events INTEGER NOT NULL DEFAULT 0,
        error TEXT
    );
    CREATE INDEX fetch_log_source ON fetch_log(source, started_at_utc);

    -- When each source last had odds for each event, kept by a trigger. Without it, finding the newest
    -- snapshot means grouping the whole snapshot table (seconds after a few months of history).
    CREATE TABLE latest_fetch (
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        market TEXT NOT NULL,
        fetched_at_utc TEXT NOT NULL,
        PRIMARY KEY (event_id, source, market)
    );
    CREATE TRIGGER odds_snapshots_latest AFTER INSERT ON odds_snapshots BEGIN
        INSERT INTO latest_fetch (event_id, source, market, fetched_at_utc)
        VALUES (NEW.event_id, NEW.source, NEW.market, NEW.fetched_at_utc)
        ON CONFLICT (event_id, source, market) DO UPDATE SET
            fetched_at_utc = MAX(fetched_at_utc, excluded.fetched_at_utc);
    END;

    -- The newest snapshot of every source for every event (all outcomes of one fetch share a time).
    CREATE VIEW latest_odds AS
    SELECT s.event_id, s.source, s.market, s.outcome, s.odds, s.fetched_at_utc
    FROM latest_fetch f
    JOIN odds_snapshots s ON s.event_id = f.event_id AND s.source = f.source
        AND s.market = f.market AND s.fetched_at_utc = f.fetched_at_utc;
    """,
]


def iso(moment: datetime) -> str:
    """UTC, to the second, sortable as text."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # the dashboard reads while the fetcher writes
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with transaction(conn):
            conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def linked_event(conn: sqlite3.Connection, source: str, source_event_id: str) -> int | None:
    row = conn.execute(
        "SELECT event_id FROM source_events WHERE source = ? AND source_event_id = ?",
        (source, source_event_id),
    ).fetchone()
    return row[0] if row else None


def create_event(conn: sqlite3.Connection, raw: RawEvent, sport: str = "football") -> int:
    cur = conn.execute(
        "INSERT INTO events (sport, league, home, away, kickoff_utc) VALUES (?, ?, ?, ?, ?)",
        (sport, raw.league, raw.home, raw.away, iso(raw.kickoff_utc)),
    )
    return cur.lastrowid


def link(conn: sqlite3.Connection, raw: RawEvent, event_id: int) -> None:
    conn.execute(
        """INSERT INTO source_events (source, source_event_id, event_id, raw_home, raw_away)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (source, source_event_id) DO UPDATE SET
             event_id = excluded.event_id, raw_home = excluded.raw_home, raw_away = excluded.raw_away""",
        (raw.source, raw.source_event_id, event_id, raw.home, raw.away),
    )


def update_event(conn: sqlite3.Connection, event_id: int, raw: RawEvent) -> None:
    """Keep league and kick-off as the anchor source last reported them (kick-offs get moved)."""
    conn.execute(
        "UPDATE events SET league = ?, kickoff_utc = ? WHERE id = ?",
        (raw.league, iso(raw.kickoff_utc), event_id),
    )


def add_snapshot(conn: sqlite3.Connection, event_id: int, raw: RawEvent, fetched_at: datetime) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO odds_snapshots (event_id, source, market, outcome, odds, fetched_at_utc)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (event_id, raw.source, raw.market, outcome, odds, iso(fetched_at))
            for outcome, odds in raw.odds.items()
        ],
    )


def record_unmatched(
    conn: sqlite3.Connection,
    raw: RawEvent,
    best_candidate: str | None,
    score: float | None,
    seen_at: datetime,
) -> None:
    conn.execute(
        """INSERT INTO unmatched (source, raw_home, raw_away, kickoff_utc, league, best_candidate, score, last_seen_utc)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source, raw_home, raw_away, kickoff_utc) DO UPDATE SET
             league = excluded.league, best_candidate = excluded.best_candidate,
             score = excluded.score, last_seen_utc = excluded.last_seen_utc""",
        (
            raw.source,
            raw.home,
            raw.away,
            iso(raw.kickoff_utc),
            raw.league,
            best_candidate,
            score,
            iso(seen_at),
        ),
    )


def clear_unmatched(conn: sqlite3.Connection, source: str, keys: Iterable[tuple[str, str, datetime]]) -> None:
    """Forget events that have since found their match."""
    conn.executemany(
        "DELETE FROM unmatched WHERE source = ? AND raw_home = ? AND raw_away = ? AND kickoff_utc = ?",
        [(source, home, away, iso(kickoff)) for home, away, kickoff in keys],
    )


def log_fetch(
    conn: sqlite3.Connection,
    source: str,
    started_at: datetime,
    status: str,
    n_events: int = 0,
    error: str | None = None,
) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO fetch_log (source, started_at_utc, status, n_events, error) VALUES (?, ?, ?, ?, ?)",
            (source, iso(started_at), status, n_events, error),
        )


def source_events_since(conn: sqlite3.Connection, source: str, kickoff_from: datetime) -> list[sqlite3.Row]:
    """The source's linked events that have not kicked off yet, with their canonical names."""
    return conn.execute(
        """SELECT se.source_event_id, se.raw_home, se.raw_away, e.id AS event_id, e.league, e.kickoff_utc
           FROM source_events se JOIN events e ON e.id = se.event_id
           WHERE se.source = ? AND e.kickoff_utc >= ?""",
        (source, iso(kickoff_from)),
    ).fetchall()


def prune(conn: sqlite3.Connection, older_than_days: int = 90, now: datetime | None = None) -> int:
    """Delete events (with their snapshots and links) that kicked off more than older_than_days ago."""
    cutoff = iso((now or datetime.now(UTC)) - timedelta(days=older_than_days))
    with transaction(conn):
        deleted = conn.execute("DELETE FROM events WHERE kickoff_utc < ?", (cutoff,)).rowcount
        conn.execute("DELETE FROM unmatched WHERE kickoff_utc < ?", (cutoff,))
        conn.execute("DELETE FROM fetch_log WHERE started_at_utc < ?", (cutoff,))
    return deleted
