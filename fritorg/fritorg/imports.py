"""Shared plumbing for listings imported from open sources (Nav, Stavanger kommune, Platsbanken).

Each source has its own module that fetches and maps the data; this module stores it: one account
per source owns the listings (it has no password, so nobody can log in to it), listings are keyed by
(source, source id), and a background scheduler runs every enabled source on its own interval.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from . import listings
from .db import transaction
from .errors import ValidationProblem
from .util import now_iso, parse_iso, to_iso

logger = logging.getLogger(__name__)

INDEXED_CHARS = 2500  # how much of an imported text is full-text indexed (long ads stay fast to search)


def source_user(conn: sqlite3.Connection, slug: str) -> int:
    """The account that owns a source's listings."""
    info = listings.SOURCES[slug]
    email = f"{slug}@import.fritorg.invalid"
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO users (email, name, password_hash, created_via, created_at) VALUES (?, ?, '!', 'import', ?)",
        (email, info.name, now_iso()),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def iso(value: Any) -> str | None:
    try:
        return to_iso(parse_iso(str(value)))
    except (TypeError, ValueError):
        return None


def iso_precise(value: Any) -> str | None:
    """Timestamps with offsets and fractions -> sortable UTC text with microseconds."""
    try:
        return parse_iso(str(value)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError):
        return None


def web_url(value: Any) -> str | None:
    """Only http(s) links are used (no javascript: or other schemes)."""
    url = " ".join(str(value or "").split())
    return url if re.match(r"https?://[^\s/]+\.[^\s]+", url) else None


def delete(conn: sqlite3.Connection, listing_id: int) -> None:
    conn.execute("DELETE FROM listings_fts WHERE rowid = ?", (listing_id,))
    conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))


def remove(conn: sqlite3.Connection, slug: str, source_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM listings WHERE source = ? AND source_id = ?", (slug, source_id)
    ).fetchone()
    if row is None:
        return 0
    delete(conn, row["id"])
    return 1


def remove_expired(conn: sqlite3.Connection, slug: str) -> int:
    """Hide ads whose time is up, also if the change that ends them was missed."""
    rows = conn.execute(
        "SELECT id FROM listings WHERE source = ? AND expires_at IS NOT NULL AND expires_at < ?",
        (slug, now_iso()),
    ).fetchall()
    if rows:
        with transaction(conn):
            for row in rows:
                delete(conn, row["id"])
    return len(rows)


@dataclass
class Item:
    """One listing from a source: listing fields plus where it comes from."""

    source_id: str
    values: dict[str, Any]
    source_url: str
    apply_url: str | None = None
    changed: str | None = None  # the source's change time, to skip unchanged items
    published: str | None = None
    updated: str | None = None
    expires: str | None = None


def upsert(conn: sqlite3.Connection, slug: str, owner_id: int, item: Item) -> str | None:
    """Create or update a listing. Returns 'created', 'updated' or None (unusable or already expired)."""
    try:
        values = listings.validate_listing(item.values)
    except ValidationProblem as exc:
        logger.info("Skipping %s item %s: %s", slug, item.source_id, exc.message)
        remove(conn, slug, item.source_id)
        return None
    if item.expires and item.expires < now_iso():
        remove(conn, slug, item.source_id)
        return None
    now = now_iso()
    changed = item.changed or now
    published = item.published or now
    updated = item.updated or published
    common = (
        values["category"],
        values["type"],
        values["title"],
        values["description"],
        values["price"],
        values["price_unit"],
        values["county"],
        values["location"],
        values["postal_code"],
        json.dumps(values["attributes"], ensure_ascii=False),
    )
    searchable = {**values, "description": values["description"][:INDEXED_CHARS]}
    existing = conn.execute(
        "SELECT id, status FROM listings WHERE source = ? AND source_id = ?", (slug, item.source_id)
    ).fetchone()
    if existing:
        # A listing a moderator removed, or that reports sent to review, stays hidden.
        status = existing["status"] if existing["status"] in ("removed", "review") else "active"
        conn.execute(
            "UPDATE listings SET category = ?, type = ?, title = ?, description = ?, price = ?, price_unit = ?, "
            "county = ?, location = ?, postal_code = ?, attributes = ?, status = ?, updated_at = ?, "
            "source_url = ?, apply_url = ?, source_updated_at = ?, expires_at = ? WHERE id = ?",
            (
                *common,
                status,
                updated,
                item.source_url,
                item.apply_url,
                changed,
                item.expires,
                existing["id"],
            ),
        )
        listings.index_listing(conn, existing["id"], searchable)
        return "updated"
    cursor = conn.execute(
        "INSERT INTO listings (category, type, title, description, price, price_unit, county, location, "
        "postal_code, attributes, user_id, status, created_via, created_at, updated_at, source, source_id, "
        "source_url, apply_url, source_updated_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'import', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            *common,
            owner_id,
            published,
            updated,
            slug,
            item.source_id,
            item.source_url,
            item.apply_url,
            changed,
            item.expires,
        ),
    )
    assert cursor.lastrowid is not None
    listings.index_listing(conn, cursor.lastrowid, searchable)
    return "created"


@dataclass
class SnapshotReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0

    def __str__(self) -> str:
        return f"{self.created} nye, {self.updated} endret, {self.unchanged} uendret, {self.removed} fjernet"


def apply_snapshot(conn: sqlite3.Connection, slug: str, items: list[Item]) -> SnapshotReport:
    """Make the source's listings match a complete list: create, update, and remove what is gone."""
    report = SnapshotReport()
    owner_id = source_user(conn, slug)
    known = {
        row["source_id"]: row["source_updated_at"]
        for row in conn.execute("SELECT source_id, source_updated_at FROM listings WHERE source = ?", (slug,))
    }
    seen = set()
    with transaction(conn):
        for item in items:
            seen.add(item.source_id)
            if item.changed and known.get(item.source_id) == item.changed:
                report.unchanged += 1
                continue
            outcome = upsert(conn, slug, owner_id, item)
            if outcome == "created":
                report.created += 1
            elif outcome == "updated":
                report.updated += 1
            else:
                report.skipped += 1
        for source_id in set(known) - seen:
            report.removed += remove(conn, slug, source_id)
    report.removed += remove_expired(conn, slug)
    return report


def status(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    conn.execute("INSERT OR IGNORE INTO import_state (source) VALUES (?)", (slug,))
    state = conn.execute("SELECT * FROM import_state WHERE source = ?", (slug,)).fetchone()
    count = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE source = ? AND status = 'active'", (slug,)
    ).fetchone()[0]
    return {"active_listings": count, "last_run_at": state["last_run_at"], "last_error": state["last_error"]}


def record_run(conn: sqlite3.Connection, slug: str, error: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO import_state (source) VALUES (?)", (slug,))
    conn.execute(
        "UPDATE import_state SET last_run_at = ?, last_error = ? WHERE source = ?",
        (now_iso(), error[:500] if error else None, slug),
    )


# --- Scheduling ---------------------------------------------------------------------------------


@dataclass
class Job:
    name: str
    interval: int  # seconds between runs
    run: Callable[[Callable[[], bool]], bool]  # gets should_stop; returns True while there is more to do
    next_run: float = field(default=0.0)


class Scheduler:
    """Runs every enabled import in one background thread while the app runs."""

    def __init__(self, jobs: list[Job]):
        self.jobs = jobs
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="imports", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            for job in self.jobs:
                if self._stop.is_set() or job.next_run > now:
                    continue
                try:
                    more = job.run(self._stop.is_set)
                    # Catching up (first start): continue soon. Otherwise wait for the job's interval.
                    job.next_run = time.monotonic() + (5 if more else job.interval)
                except Exception:
                    logger.exception("Import %s failed; trying again later", job.name)
                    job.next_run = time.monotonic() + max(job.interval, 300)
            upcoming = min((job.next_run for job in self.jobs), default=time.monotonic() + 60)
            self._stop.wait(max(1.0, upcoming - time.monotonic()))
