"""Moderation: the review queue, user reports, flagged messages and account bans.

Moderators are users with is_admin set (`python -m fritorg make-admin EMAIL`). Every decision
is written to moderation_log.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import fraud, users
from .db import transaction
from .errors import NotFound, ValidationProblem
from .listings import REPORT_REASONS, Listing, SearchParams, get_listing, search
from .util import iso_ago, now_iso


@dataclass
class ReportCase:
    """Open reports about one listing or one user."""

    listing_id: int | None
    listing_title: str | None
    listing_status: str | None
    reported_user_id: int | None
    reported_user_name: str | None
    reports: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"l{self.listing_id}" if self.listing_id else f"u{self.reported_user_id}"


def _log(
    conn: sqlite3.Connection,
    moderator_id: int,
    action: str,
    *,
    listing_id: int | None = None,
    user_id: int | None = None,
    note: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO moderation_log (moderator_id, listing_id, user_id, action, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (moderator_id, listing_id, user_id, action, note, now_iso()),
    )


def stats(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Key numbers for running the site (accounts that own imported listings are left out)."""
    day, week = iso_ago(days=1), iso_ago(days=7)
    queries = [
        ("Brukere", "SELECT COUNT(*) FROM users WHERE created_via != 'import'", ()),
        (
            "Nye brukere siste 7 dager",
            "SELECT COUNT(*) FROM users WHERE created_via != 'import' AND created_at > ?",
            (week,),
        ),
        (
            "Bekreftede brukere",
            "SELECT COUNT(*) FROM users WHERE created_via != 'import' AND verified_at IS NOT NULL",
            (),
        ),
        ("Aktive annonser", "SELECT COUNT(*) FROM listings WHERE status = 'active' AND source IS NULL", ()),
        (
            "Nye annonser siste døgn",
            "SELECT COUNT(*) FROM listings WHERE source IS NULL AND created_at > ?",
            (day,),
        ),
        (
            "Hentede annonser",
            "SELECT COUNT(*) FROM listings WHERE status = 'active' AND source IS NOT NULL",
            (),
        ),
        ("Meldinger siste døgn", "SELECT COUNT(*) FROM messages WHERE created_at > ?", (day,)),
        ("Til kontroll", "SELECT COUNT(*) FROM listings WHERE status = 'review'", ()),
        ("Åpne rapporter", "SELECT COUNT(*) FROM reports WHERE resolved_at IS NULL", ()),
        ("Stengte kontoer", "SELECT COUNT(*) FROM users WHERE banned_at IS NOT NULL", ()),
    ]
    return [(label, conn.execute(sql, args).fetchone()[0]) for label, sql, args in queries]


def review_queue(conn: sqlite3.Connection) -> list[Listing]:
    params = SearchParams(status="review", include_hidden=True, sort="oldest", limit=100)
    return search(conn, params).items


def open_reports(conn: sqlite3.Connection) -> list[ReportCase]:
    rows = conn.execute(
        "SELECT r.*, l.title AS listing_title, l.status AS listing_status, ru.name AS reported_user_name, "
        "rep.name AS reporter_name FROM reports r "
        "LEFT JOIN listings l ON l.id = r.listing_id "
        "LEFT JOIN users ru ON ru.id = r.reported_user_id "
        "LEFT JOIN users rep ON rep.id = r.reporter_id "
        "WHERE r.resolved_at IS NULL ORDER BY r.created_at"
    ).fetchall()
    cases: dict[str, ReportCase] = {}
    for row in rows:
        conversation_report = row["conversation_id"] is not None
        listing_id = None if conversation_report else row["listing_id"]
        case = ReportCase(
            listing_id,
            row["listing_title"],
            row["listing_status"],
            row["reported_user_id"],
            row["reported_user_name"],
        )
        case = cases.setdefault(case.key, case)
        case.reports.append(
            {
                "id": row["id"],
                "reason": REPORT_REASONS.get(row["reason"], row["reason"]),
                "comment": row["comment"],
                "reporter": row["reporter_name"] or "Anonym",
                "conversation_id": row["conversation_id"],
                "created_at": row["created_at"],
            }
        )
    return sorted(cases.values(), key=lambda c: -len(c.reports))


def flagged_messages(conn: sqlite3.Connection, days: int = 14) -> list[dict[str, Any]]:
    """Recent messages with strong fraud signals, so moderators can spot scammers early."""
    rows = conn.execute(
        "SELECT m.id, m.body, m.created_at, m.risk_flags, m.conversation_id, u.id AS sender_id, "
        "u.name AS sender_name, u.banned_at FROM messages m JOIN users u ON u.id = m.sender_id "
        "WHERE m.risk_score >= ? AND m.created_at > ? ORDER BY m.id DESC LIMIT 100",
        (fraud.REVIEW_THRESHOLD, iso_ago(days=days)),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "body": row["body"],
            "created_at": row["created_at"],
            "conversation_id": row["conversation_id"],
            "sender_id": row["sender_id"],
            "sender_name": row["sender_name"],
            "sender_banned": bool(row["banned_at"]),
            "reasons": fraud.reasons(json.loads(row["risk_flags"])),
        }
        for row in rows
    ]


def _resolve_listing_reports(
    conn: sqlite3.Connection, listing_id: int, moderator_id: int, resolution: str
) -> None:
    conn.execute(
        "UPDATE reports SET resolved_at = ?, resolution = ?, resolved_by = ? WHERE listing_id = ? AND resolved_at IS NULL",
        (now_iso(), resolution, moderator_id, listing_id),
    )


def approve_listing(conn: sqlite3.Connection, moderator: users.User, listing_id: int) -> None:
    get_listing(conn, listing_id)
    with transaction(conn):
        conn.execute(
            "UPDATE listings SET status = 'active', reviewed_at = ?, moderation_note = NULL, updated_at = ? WHERE id = ?",
            (now_iso(), now_iso(), listing_id),
        )
        _resolve_listing_reports(conn, listing_id, moderator.id, "dismissed")
        _log(conn, moderator.id, "approve_listing", listing_id=listing_id)


def remove_listing(conn: sqlite3.Connection, moderator: users.User, listing_id: int, note: str) -> None:
    note = " ".join(note.split())[:500]
    if not note:
        raise ValidationProblem.field("note", "Skriv en kort begrunnelse. Den vises for annonsøren.")
    get_listing(conn, listing_id)
    with transaction(conn):
        conn.execute(
            "UPDATE listings SET status = 'removed', moderation_note = ?, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (note, now_iso(), now_iso(), listing_id),
        )
        _resolve_listing_reports(conn, listing_id, moderator.id, "removed")
        _log(conn, moderator.id, "remove_listing", listing_id=listing_id, note=note)


def dismiss_reports(conn: sqlite3.Connection, moderator: users.User, report_ids: list[int]) -> None:
    with transaction(conn):
        for report_id in report_ids:
            conn.execute(
                "UPDATE reports SET resolved_at = ?, resolution = 'dismissed', resolved_by = ? "
                "WHERE id = ? AND resolved_at IS NULL",
                (now_iso(), moderator.id, report_id),
            )
        _log(conn, moderator.id, "dismiss_reports", note=",".join(str(i) for i in report_ids))


def ban_user(conn: sqlite3.Connection, moderator: users.User, user_id: int, reason: str) -> None:
    target = users.get_user(conn, user_id)
    if target is None:
        raise NotFound(f"Bruker {user_id} finnes ikke.")
    if target.is_admin:
        raise ValidationProblem.field("user_id", "Moderatorer kan ikke stenges her.")
    reason = " ".join(reason.split()) or "Brudd på vilkårene"
    users.ban_user(conn, user_id, reason)
    with transaction(conn):
        conn.execute(
            "UPDATE reports SET resolved_at = ?, resolution = 'banned', resolved_by = ? "
            "WHERE reported_user_id = ? AND resolved_at IS NULL",
            (now_iso(), moderator.id, user_id),
        )
        _log(conn, moderator.id, "ban_user", user_id=user_id, note=reason)
