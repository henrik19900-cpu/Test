"""A copy of everything Fritorg stores about a person (GDPR articles 15 and 20)."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import listings, messages, serializers, users
from .util import now_iso


def export_user(conn: sqlite3.Connection, user: users.User, base: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    account: dict[str, Any] = {
        "id": row["id"],
        "email": row["email"],
        "email_verified_at": row["email_verified_at"],
        "name": row["name"],
        "created_at": row["created_at"],
        "created_via": row["created_via"],
        "moderator": bool(row["is_admin"]),
        "verification": user.verification,
        "verified_at": row["verified_at"],
        "verified_name": row["verified_name"],
        "phone": {"hint": row["phone_hint"], "verified_at": row["phone_verified_at"]}
        if row["phone_hint"]
        else None,
        "banned_at": row["banned_at"],
        "ban_reason": row["ban_reason"],
    }
    own = [
        serializers.listing_detail(listings.get_listing(conn, r["id"]), base, owner_view=True)
        for r in conn.execute("SELECT id FROM listings WHERE user_id = ? ORDER BY id", (user.id,))
    ]
    conversations = [
        serializers.conversation_dict(
            messages.get_conversation(conn, c.id, user.id, mark_read=False), user.id, base, with_messages=True
        )
        for c in messages.list_conversations(conn, user.id)
    ]
    tokens = [
        {"name": t.name, "hint": t.hint, "created_at": t.created_at, "last_used_at": t.last_used_at}
        for t in users.list_api_tokens(conn, user.id)
    ]
    reports_made = [
        dict(r)
        for r in conn.execute(
            "SELECT listing_id, reported_user_id, conversation_id, reason, comment, created_at, resolved_at, "
            "resolution FROM reports WHERE reporter_id = ? ORDER BY id",
            (user.id,),
        )
    ]
    # Reports about the person, without saying who made them.
    reports_about = [
        dict(r)
        for r in conn.execute(
            "SELECT r.listing_id, r.reason, r.created_at, r.resolution FROM reports r "
            "LEFT JOIN listings l ON l.id = r.listing_id "
            "WHERE r.reported_user_id = ? OR l.user_id = ? ORDER BY r.id",
            (user.id, user.id),
        )
    ]
    decisions = [
        dict(r)
        for r in conn.execute(
            "SELECT m.action, m.listing_id, m.note, m.created_at FROM moderation_log m "
            "LEFT JOIN listings l ON l.id = m.listing_id WHERE m.user_id = ? OR l.user_id = ? ORDER BY m.id",
            (user.id, user.id),
        )
    ]
    sessions = [
        dict(r)
        for r in conn.execute(
            "SELECT created_at, expires_at FROM sessions WHERE user_id = ? ORDER BY created_at", (user.id,)
        )
    ]
    favorites = [
        {
            "listing_id": r["listing_id"],
            "url": serializers.listing_url(base, r["listing_id"]),
            "saved_at": r["created_at"],
        }
        for r in conn.execute(
            "SELECT listing_id, created_at FROM favorites WHERE user_id = ? ORDER BY created_at", (user.id,)
        )
    ]
    searches = [
        {
            "name": r["name"],
            "url": f"{base}/sok?{r['query']}",
            "email_alerts": bool(r["notify"]),
            "created_at": r["created_at"],
            "last_alert_at": r["alerted_at"],
        }
        for r in conn.execute("SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id", (user.id,))
    ]
    return {
        "exported_at": now_iso(),
        "site": base,
        "about": "Alt vi har lagret om kontoen din. Passord, nøkler og mobilnummer lagres bare som "
        "kryptografiske hasher og kan derfor ikke tas med.",
        "account": account,
        "listings": own,
        "conversations": conversations,
        "api_tokens": tokens,
        "logged_in_sessions": sessions,
        "favorites": favorites,
        "saved_searches": searches,
        "reports_made": reports_made,
        "reports_about_you": reports_about,
        "moderation_decisions": decisions,
    }
