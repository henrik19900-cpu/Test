"""Inventory sync for businesses: dealers, estate agents, shops and employers publish their own
listings here from their own systems, with one call.

They send everything that should be on Fritorg for one feed (a name of their choice), each item with
their own id. Fritorg creates what is new, updates what changed, and removes what is no longer in
the feed. Unchanged items cost nothing, so the same call can simply be repeated, e.g. every hour.
Synced listings follow the same rules as all others (verified account, fraud checks, moderation),
and every sync renews them, so they only expire if the business stops syncing.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import images, listings
from .config import Settings
from .errors import AppError, ValidationProblem
from .users import User
from .util import iso_in

FEED_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_ITEMS_PER_CALL = 1000
KEEP_STATUSES = ("review", "removed", "sold")  # set by moderators or the owner; a sync leaves them alone


@dataclass
class SyncResult:
    feed: str
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: list[dict[str, Any]] = field(default_factory=list)
    listings: list[dict[str, Any]] = field(default_factory=list)


def check_feed_name(feed: str) -> str:
    if not FEED_RE.match(feed or ""):
        raise ValidationProblem.field(
            "feed",
            "Navnet på feeden kan ha små bokstaver, tall og bindestrek (maks 40 tegn).",
            hint="Use a slug such as 'default', 'bruktbiler' or 'oslo-butikken'.",
        )
    return feed


def _fingerprint(values: dict[str, Any], status: str) -> str:
    text = json.dumps({**values, "status": status}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def feed_listings(conn: sqlite3.Connection, user_id: int, feed: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, external_id, sync_hash, status FROM listings WHERE user_id = ? AND feed = ? ORDER BY id",
        (user_id, feed),
    ).fetchall()


def _settle(conn: sqlite3.Connection, listing_id: int, wanted: str, fingerprint: str, days: int) -> str:
    """Status, period and fingerprint after a sync; returns the listing's status."""
    status = conn.execute("SELECT status FROM listings WHERE id = ?", (listing_id,)).fetchone()["status"]
    if status not in KEEP_STATUSES:
        status = wanted
    conn.execute(
        "UPDATE listings SET status = ?, sync_hash = ?, expires_at = ? WHERE id = ?",
        (status, fingerprint, iso_in(days=days) if days else None, listing_id),
    )
    return status


def sync(
    conn: sqlite3.Connection,
    settings: Settings,
    user: User,
    feed: str,
    items: list[dict[str, Any]],
    *,
    remove_missing: bool = True,
    via: str = "api",
) -> SyncResult:
    check_feed_name(feed)
    if len(items) > MAX_ITEMS_PER_CALL:
        raise ValidationProblem.field(
            "listings",
            f"Maks {MAX_ITEMS_PER_CALL} annonser per kall. Del lageret i flere feeder.",
            hint="Split the inventory into several feeds, e.g. one per department.",
        )
    seen: set[str] = set()
    for item in items:
        external_id = str(item.get("external_id") or "")
        if external_id in seen:
            raise ValidationProblem.field("listings", f"external_id {external_id!r} finnes flere ganger.")
        seen.add(external_id)

    existing = {row["external_id"]: row for row in feed_listings(conn, user.id, feed)}
    elsewhere = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE user_id = ? AND external_id IS NOT NULL AND feed != ?",
        (user.id, feed),
    ).fetchone()[0]
    after = elsewhere + len(items) + (0 if remove_missing else len(set(existing) - seen))
    if after > settings.max_synced_listings:
        raise ValidationProblem.field(
            "listings",
            f"En konto kan ha maks {settings.max_synced_listings} synkroniserte annonser.",
            hint="Contact the site operator for a higher limit.",
        )

    result = SyncResult(feed=feed)
    days = settings.listing_days
    for item in items:
        external_id = str(item["external_id"])
        wanted = "inactive" if item.get("status") == "inactive" else "active"
        data = {k: v for k, v in item.items() if k not in ("external_id", "status")}
        row = existing.get(external_id)
        try:
            values = listings.validate_listing(data)
            fingerprint = _fingerprint(values, wanted)
            if row is None:
                listing_id = listings.create_listing(
                    conn,
                    user.id,
                    {**values, "status": wanted},
                    via=via,
                    max_per_day=settings.max_synced_listings,
                    new_account_max_per_day=settings.max_synced_listings,
                    active_days=days,
                )
                conn.execute(
                    "UPDATE listings SET feed = ?, external_id = ? WHERE id = ?",
                    (feed, external_id, listing_id),
                )
                result.created += 1
            else:
                listing_id = row["id"]
                if row["sync_hash"] == fingerprint:
                    result.unchanged += 1
                else:
                    listings.update_listing(
                        conn, user.id, listing_id, values, merge_attributes=False, active_days=days
                    )
                    result.updated += 1
            status = _settle(conn, listing_id, wanted, fingerprint, days)
        except AppError as exc:
            result.failed.append({"external_id": external_id, "detail": exc.message, "errors": exc.errors})
            continue
        result.listings.append({"external_id": external_id, "id": listing_id, "status": status})

    if remove_missing:
        for external_id, row in existing.items():
            if external_id not in seen:
                remove_files(settings.uploads_dir, listings.delete_listing(conn, user.id, row["id"]))
                result.removed += 1
    return result


def remove_feed(conn: sqlite3.Connection, settings: Settings, user: User, feed: str) -> int:
    check_feed_name(feed)
    rows = feed_listings(conn, user.id, feed)
    for row in rows:
        remove_files(settings.uploads_dir, listings.delete_listing(conn, user.id, row["id"]))
    return len(rows)


def feeds(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    return [
        {"feed": row["feed"], "listings": row["n"], "active": row["active"]}
        for row in conn.execute(
            "SELECT feed, COUNT(*) AS n, SUM(status = 'active') AS active FROM listings "
            "WHERE user_id = ? AND feed IS NOT NULL GROUP BY feed ORDER BY feed",
            (user_id,),
        )
    ]


def remove_files(uploads_dir: Path, filenames: list[str]) -> None:
    images.remove_files(uploads_dir, filenames)
