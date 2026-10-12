"""Favourites ("favoritter"): listings a person has saved to look at again.

Saving is private: sellers only see how many have saved their listing, never who.
"""

from __future__ import annotations

import sqlite3

from . import listings
from .errors import ValidationProblem
from .listings import Listing
from .util import now_iso

MAX_FAVORITES = 1000

# Listings the person may still see: public ones, and their own.
_VISIBLE = "((l.status IN ('active', 'sold') AND u.banned_at IS NULL) OR l.user_id = f.user_id)"


def add(conn: sqlite3.Connection, user_id: int, listing_id: int) -> bool:
    """Save a listing. Returns False if it was already saved."""
    listing = listings.get_visible_listing(
        conn, listing_id, user_id
    )  # 404 for listings the person cannot see
    if conn.execute(
        "SELECT 1 FROM favorites WHERE user_id = ? AND listing_id = ?", (user_id, listing_id)
    ).fetchone():
        return False
    count = conn.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_FAVORITES:
        raise ValidationProblem(
            f"Du kan ha maks {MAX_FAVORITES} favoritter. Fjern noen du ikke trenger lenger.",
            hint="Remove favourites with DELETE /api/v1/me/favorites/{listing_id} (MCP: save_favorite remove=true).",
        )
    conn.execute(
        "INSERT OR IGNORE INTO favorites (user_id, listing_id, created_at, price, notified_price) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, listing_id, now_iso(), listing.price, listing.price),
    )
    return True


def remove(conn: sqlite3.Connection, user_id: int, listing_id: int) -> bool:
    cursor = conn.execute("DELETE FROM favorites WHERE user_id = ? AND listing_id = ?", (user_id, listing_id))
    return cursor.rowcount > 0


def ids(conn: sqlite3.Connection, user_id: int) -> set[int]:
    return {row[0] for row in conn.execute("SELECT listing_id FROM favorites WHERE user_id = ?", (user_id,))}


def saved_listings(
    conn: sqlite3.Connection, user_id: int, limit: int = 100, offset: int = 0
) -> tuple[list[Listing], int]:
    """The person's saved listings, most recently saved first, and how many there are in all."""
    join = "JOIN favorites f ON f.listing_id = l.id WHERE f.user_id = ? AND " + _VISIBLE
    total = conn.execute(
        f"SELECT COUNT(*) FROM listings l JOIN users u ON u.id = l.user_id {join}", (user_id,)
    ).fetchone()[0]
    items = listings.fetch(
        conn,
        f"{join} ORDER BY f.created_at DESC, l.id DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
        columns="f.price AS saved_price",
    )
    return items, total


def count_for(conn: sqlite3.Connection, listing_id: int) -> int:
    """How many have saved a listing (shown to its owner)."""
    return conn.execute("SELECT COUNT(*) FROM favorites WHERE listing_id = ?", (listing_id,)).fetchone()[0]


class FavoriteIds:
    """The logged-in person's favourites, loaded the first time a page asks (`id in favorite_ids`)."""

    def __init__(self, conn: sqlite3.Connection | None, user_id: int | None):
        self._conn, self._user_id = conn, user_id
        self._ids: set[int] | None = None

    def __contains__(self, listing_id: object) -> bool:
        if self._conn is None or self._user_id is None:
            return False
        if self._ids is None:
            self._ids = ids(self._conn, self._user_id)
        return listing_id in self._ids
