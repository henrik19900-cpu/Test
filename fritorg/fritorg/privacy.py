"""A copy of everything the site stores about a person (GDPR articles 15 and 20)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import listings, messages, ratings, serializers, users
from .util import iso_ago, now_iso

ABOUT = (
    "Opplysningene vi har lagret om kontoen din. Passord, nøkler og mobilnummer lagres bare som kryptografiske "
    "hasher og kan derfor ikke tas med. Ikke med: svindelvurderingen av meldingene du har sendt (den beskytter mot "
    "svindel), hvem som har rapportert deg og hva de skrev, vurderinger du har fått som ikke vises ennå (de kommer "
    "med når du har vurdert den andre, eller når fristen er ute), og koder og lenker som slettes etter kort tid."
)


def export_user(conn: sqlite3.Connection, user: users.User, base: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    account: dict[str, Any] = {
        "id": row["id"],
        "email": row["email"],
        "email_verified_at": row["email_verified_at"],
        "name": row["name"],
        "created_at": row["created_at"],
        "created_via": row["created_via"],
        "last_active_at": row["last_active_at"],  # an account unused for long is deleted
        "deletion_notice_sent_at": row["inactivity_notice_at"],  # told it will be deleted for not being used
        "moderator": bool(row["is_admin"]),
        "price_drop_emails": bool(row["price_alerts"]),
        "last_price_alert_at": row["price_alerted_at"],
        "verification": user.verification,
        "verified_at": row["verified_at"],
        "verified_name": row["verified_name"],
        "phone": {"hint": row["phone_hint"], "verified_at": row["phone_verified_at"]}
        if row["phone_hint"]
        else None,
        "business": {
            "org_number": row["org_number"],
            "name": row["business_name"],
            "checked_at": row["business_checked_at"],
        }
        if row["org_number"]
        else None,
        "banned_at": row["banned_at"],
        "ban_reason": row["ban_reason"],
    }
    own = []
    for r in conn.execute(
        "SELECT id, reviewed_at, feed, external_id FROM listings WHERE user_id = ? ORDER BY id", (user.id,)
    ).fetchall():
        item = serializers.listing_detail(listings.get_listing(conn, r["id"]), base, owner_view=True)
        item["reviewed_by_moderator_at"] = r["reviewed_at"]
        item["feed"] = {"name": r["feed"], "external_id": r["external_id"]} if r["feed"] else None
        own.append(item)
    # When the person deleted a conversation from their own inbox (the other person may still have it).
    hidden = {
        r["id"]: r["buyer_hidden_at"] if r["buyer_id"] == user.id else r["seller_hidden_at"]
        for r in conn.execute(
            "SELECT id, buyer_id, buyer_hidden_at, seller_hidden_at FROM conversations "
            "WHERE buyer_id = ? OR seller_id = ?",
            (user.id, user.id),
        )
    }
    conversations = []
    for c in messages.list_conversations(conn, user.id, include_hidden=True):
        item = serializers.conversation_dict(
            messages.get_conversation(conn, c.id, user.id, mark_read=False), user.id, base, with_messages=True
        )
        item["deleted_from_your_inbox_at"] = hidden.get(c.id)
        conversations.append(item)
    # Keys, and for those an AI assistant got by signing in (MCP), which app has access to the account.
    tokens = [
        {
            "name": t["name"],
            "hint": t["token_hint"],
            "created_at": t["created_at"],
            "last_used_at": t["last_used_at"],
            "assistant": {
                "client_id": t["oauth_client_id"],
                "name": t["client_name"],
                "redirect_uris": json.loads(t["redirect_uris"] or "[]"),
                "registered_at": t["client_created_at"],
            }
            if t["oauth_client_id"]
            else None,
        }
        for t in conn.execute(
            "SELECT t.name, t.token_hint, t.created_at, t.last_used_at, t.oauth_client_id, c.name AS client_name, "
            "c.redirect_uris, c.created_at AS client_created_at FROM api_tokens t "
            "LEFT JOIN oauth_clients c ON c.client_id = t.oauth_client_id WHERE t.user_id = ? ORDER BY t.id DESC",
            (user.id,),
        )
    ]
    # Everything you rated, also ratings a moderator removed (the trades show the other person's rating).
    ratings_given = [
        dict(r)
        for r in conn.execute(
            "SELECT r.trade_id, t.listing_title, r.rated_id AS rated_user_id, r.score, r.comment, r.created_at, "
            "r.removed_at, r.removal_note FROM ratings r JOIN trades t ON t.id = r.trade_id "
            "WHERE r.rater_id = ? ORDER BY r.id",
            (user.id,),
        )
    ]
    # Ratings others gave you, also those a moderator removed, as soon as you may see them: when you have
    # rated the other person too, or when the time for rating is over (ratings.py).
    ratings_received = [
        {
            "trade_id": r["trade_id"],
            "listing_title": r["listing_title"],
            "rater": {"id": r["rater_id"], "name": r["rater_name"]},
            "score": r["score"],
            "comment": r["comment"],
            "created_at": r["created_at"],
            "removed_at": r["removed_at"],
        }
        for r in conn.execute(
            "SELECT r.*, t.listing_title, rater.name AS rater_name FROM ratings r JOIN trades t ON t.id = r.trade_id "
            "JOIN users rater ON rater.id = r.rater_id WHERE r.rated_id = :me AND (t.created_at < :revealed "
            "OR EXISTS (SELECT 1 FROM ratings o WHERE o.trade_id = r.trade_id AND o.rater_id = :me)) ORDER BY r.id",
            {"me": user.id, "revealed": iso_ago(days=ratings.REVEAL_DAYS)},
        )
    ]
    appeals = [
        dict(r)
        for r in conn.execute(
            "SELECT listing_id, text, created_at, decided_at, decision, decision_note AS answer FROM appeals "
            "WHERE user_id = ? ORDER BY id",
            (user.id,),
        )
    ]
    reports_made = [
        dict(r)
        for r in conn.execute(
            "SELECT listing_id, reported_user_id, conversation_id, rating_id, reason, comment, created_at, "
            "resolved_at, resolution FROM reports WHERE reporter_id = ? ORDER BY id",
            (user.id,),
        )
    ]
    # Reports about the person, without saying who made them or what they wrote.
    reports_about = [
        dict(r)
        for r in conn.execute(
            "SELECT r.listing_id, r.conversation_id, r.rating_id, r.reason, r.created_at, r.resolved_at, "
            "r.resolution FROM reports r LEFT JOIN listings l ON l.id = r.listing_id "
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
            "price_when_saved": r["price"],
        }
        for r in conn.execute(
            "SELECT listing_id, created_at, price FROM favorites WHERE user_id = ? ORDER BY created_at",
            (user.id,),
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
        "about": ABOUT,
        "account": account,
        "listings": own,
        "conversations": conversations,
        # Trades with your rating and the other person's (once you may see it).
        "trades": [
            serializers.trade_dict(t, user.id) for t in ratings.trades_for_user(conn, user.id, limit=10_000)
        ],
        "ratings_given": ratings_given,
        "ratings_received": ratings_received,
        "appeals": appeals,
        "api_tokens": tokens,
        "logged_in_sessions": sessions,
        "favorites": favorites,
        "blocked_users": [
            {"user_id": b["id"], "name": b["name"], "blocked_at": b["created_at"]}
            for b in messages.blocked_users(conn, user.id)
        ],
        "saved_searches": searches,
        "reports_made": reports_made,
        "reports_about_you": reports_about,
        "moderation_decisions": decisions,
    }
