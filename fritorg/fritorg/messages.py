"""Conversations between a buyer and a seller about one listing."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from statistics import median

from . import fraud
from .db import transaction
from .errors import Forbidden, NotFound, RateLimited, ValidationProblem
from .listings import CHANNELS, get_listing
from .util import iso_ago, now_iso, parse_iso

MAX_BODY = 5000
# Sending the same text again within this time sends nothing new: agents retry calls that timed out, and
# forms get sent twice.
REPEAT_MINUTES = 10


@dataclass
class Sent:
    conversation_id: int
    message_id: int
    repeated: bool = False  # the same text was already the latest message: nothing was sent or notified


@dataclass
class Message:
    id: int
    conversation_id: int
    sender_id: int
    sender_name: str
    body: str
    created_via: str
    created_at: str
    read_at: str | None
    risk_flags: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        """Fraud warnings for the recipient (never shown to the sender)."""
        return fraud.message_warnings(self.risk_flags)


@dataclass
class Conversation:
    id: int
    listing_id: int | None
    listing_title: str
    buyer_id: int
    buyer_name: str
    seller_id: int
    seller_name: str
    created_at: str
    last_message_at: str
    unread: int = 0
    last_message: str | None = None
    messages: list[Message] = field(default_factory=list)

    def role(self, user_id: int) -> str:
        return "seller" if user_id == self.seller_id else "buyer"

    def other_name(self, user_id: int) -> str:
        return self.buyer_name if user_id == self.seller_id else self.seller_name

    def other_id(self, user_id: int) -> int:
        return self.buyer_id if user_id == self.seller_id else self.seller_id


_SELECT = """
SELECT c.*, b.name AS buyer_name, s.name AS seller_name,
  (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.sender_id != :me AND m.read_at IS NULL)
    AS unread,
  (SELECT body FROM messages m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_message
FROM conversations c
JOIN users b ON b.id = c.buyer_id
JOIN users s ON s.id = c.seller_id
"""


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        listing_id=row["listing_id"],
        listing_title=row["listing_title"],
        buyer_id=row["buyer_id"],
        buyer_name=row["buyer_name"],
        seller_id=row["seller_id"],
        seller_name=row["seller_name"],
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
        unread=row["unread"],
        last_message=row["last_message"],
    )


def _clean_body(body: str) -> str:
    text = (body or "").replace("\r\n", "\n").strip()
    if not text:
        raise ValidationProblem.field("message", "Meldingen kan ikke være tom.")
    if len(text) > MAX_BODY:
        raise ValidationProblem.field("message", f"Meldingen kan ha maks {MAX_BODY} tegn.")
    return text


def _check_quota(
    conn: sqlite3.Connection, user_id: int, max_per_day: int, new_account_max: int | None
) -> None:
    limit = max_per_day
    row = conn.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if new_account_max is not None and row and row["created_at"] > iso_ago(days=1):
        limit = min(limit, new_account_max)
    sent = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE sender_id = ? AND created_at > ?", (user_id, iso_ago(days=1))
    ).fetchone()[0]
    if sent >= limit:
        raise RateLimited(
            f"Du har sendt {sent} meldinger siste døgn (maks {limit}). Prøv igjen senere.",
            retry_after=3600,
            hint="The daily message quota protects sellers against spam; new accounts get a lower quota.",
        )


def _insert_message(
    conn: sqlite3.Connection, conversation_id: int, sender_id: int, body: str, via: str
) -> int:
    now = now_iso()
    assessment = fraud.assess_message(body)
    cursor = conn.execute(
        "INSERT INTO messages (conversation_id, sender_id, body, created_via, created_at, risk_score, risk_flags) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id,
            sender_id,
            body,
            via if via in CHANNELS else "web",
            now,
            assessment.score,
            json.dumps(assessment.codes),
        ),
    )
    # A new message brings the conversation back to inboxes it was deleted from.
    conn.execute(
        "UPDATE conversations SET last_message_at = ?, buyer_hidden_at = NULL, seller_hidden_at = NULL WHERE id = ?",
        (now, conversation_id),
    )
    return cursor.lastrowid  # type: ignore[return-value]


# --- Blocking ------------------------------------------------------------------------------------


def block(conn: sqlite3.Connection, user_id: int, blocked_id: int) -> None:
    """Stop messages between two people, in both directions. Only the person who blocked can undo it."""
    if user_id == blocked_id:
        raise ValidationProblem.field("user_id", "Du kan ikke blokkere deg selv.")
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (blocked_id,)).fetchone() is None:
        raise NotFound(f"Bruker {blocked_id} finnes ikke.")
    conn.execute(
        "INSERT OR IGNORE INTO blocks (user_id, blocked_id, created_at) VALUES (?, ?, ?)",
        (user_id, blocked_id, now_iso()),
    )


def unblock(conn: sqlite3.Connection, user_id: int, blocked_id: int) -> None:
    conn.execute("DELETE FROM blocks WHERE user_id = ? AND blocked_id = ?", (user_id, blocked_id))


def has_blocked(conn: sqlite3.Connection, user_id: int, other_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM blocks WHERE user_id = ? AND blocked_id = ?", (user_id, other_id)
        ).fetchone()
        is not None
    )


def blocked_users(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT u.id, u.name, b.created_at FROM blocks b JOIN users u ON u.id = b.blocked_id "
            "WHERE b.user_id = ? ORDER BY b.created_at DESC",
            (user_id,),
        )
    ]


def _check_not_blocked(conn: sqlite3.Connection, sender_id: int, recipient_id: int) -> None:
    if has_blocked(conn, sender_id, recipient_id):
        raise Forbidden(
            "Du har blokkert denne brukeren. Opphev blokkeringen hvis du vil sende melding.",
            hint="The user blocked this person: unblock with DELETE /api/v1/me/blocks/{user_id} first.",
        )
    if has_blocked(conn, recipient_id, sender_id):
        raise Forbidden(
            "Du kan ikke sende meldinger til denne brukeren.",
            hint="The recipient does not accept messages from this account.",
        )


# --- Response time --------------------------------------------------------------------------------


def response_time_hours(conn: sqlite3.Connection, seller_id: int) -> float | None:
    """Median hours until the seller first answered a new conversation, over the last 50 in half a
    year. Unanswered ones older than a day count as slow. None with fewer than 3 to go by."""
    rows = conn.execute(
        "SELECT c.created_at AS asked, (SELECT MIN(m.created_at) FROM messages m "
        "WHERE m.conversation_id = c.id AND m.sender_id = c.seller_id) AS answered "
        "FROM conversations c WHERE c.seller_id = ? AND c.created_at > ? ORDER BY c.id DESC LIMIT 50",
        (seller_id, iso_ago(days=180)),
    ).fetchall()
    day_ago = iso_ago(days=1)
    hours = []
    for row in rows:
        if row["answered"]:
            hours.append((parse_iso(row["answered"]) - parse_iso(row["asked"])).total_seconds() / 3600)
        elif row["asked"] < day_ago:
            hours.append(float("inf"))
    return median(hours) if len(hours) >= 3 else None


def response_time_text(hours: float | None) -> str | None:
    """Shown to buyers when the seller usually answers within a day."""
    if hours is None or hours > 24:
        return None
    if hours <= 1:
        return "Svarer vanligvis innen en time"
    if hours <= 4:
        return "Svarer vanligvis innen noen timer"
    return "Svarer vanligvis innen et døgn"


def contact_seller(
    conn: sqlite3.Connection,
    listing_id: int,
    buyer_id: int,
    body: str,
    *,
    via: str = "web",
    max_per_day: int = 200,
    new_account_max_per_day: int | None = None,
) -> Sent:
    """Send a message about a listing, reusing the buyer's existing conversation."""
    text = _clean_body(body)
    listing = get_listing(conn, listing_id)
    if listing.status != "active" or not listing.is_public:
        raise ValidationProblem.field("listing_id", "Annonsen er ikke lenger aktiv.")
    if listing.is_imported:
        raise ValidationProblem.field(
            "listing_id",
            f"Denne annonsen er hentet fra {listing.source_name}. Bruk lenken i annonsen.",
            hint=f"Imported listing: send the user to {listing.apply_url or listing.source_url} (links.apply).",
        )
    if listing.user_id == buyer_id:
        raise ValidationProblem.field("listing_id", "Du kan ikke sende melding om din egen annonse.")
    _check_not_blocked(conn, buyer_id, listing.user_id)
    with transaction(conn):
        row = conn.execute(
            "SELECT id FROM conversations WHERE listing_id = ? AND buyer_id = ?", (listing_id, buyer_id)
        ).fetchone()
        repeated = _repeated_message(conn, row["id"], buyer_id, text) if row else None
        if repeated is not None:
            return Sent(row["id"], repeated, repeated=True)
        _check_quota(conn, buyer_id, max_per_day, new_account_max_per_day)
        if row:
            conversation_id = row["id"]
        else:
            now = now_iso()
            cursor = conn.execute(
                "INSERT INTO conversations (listing_id, listing_title, buyer_id, seller_id, created_at, last_message_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (listing_id, listing.title, buyer_id, listing.user_id, now, now),
            )
            conversation_id = cursor.lastrowid
        message_id = _insert_message(conn, conversation_id, buyer_id, text, via)
    return Sent(conversation_id, message_id)


def reply(
    conn: sqlite3.Connection,
    conversation_id: int,
    sender_id: int,
    body: str,
    *,
    via: str = "web",
    max_per_day: int = 200,
    new_account_max_per_day: int | None = None,
) -> Sent:
    text = _clean_body(body)
    conversation = _get(conn, conversation_id, sender_id)
    _check_not_blocked(conn, sender_id, conversation.other_id(sender_id))
    with transaction(conn):
        repeated = _repeated_message(conn, conversation.id, sender_id, text)
        if repeated is not None:
            return Sent(conversation.id, repeated, repeated=True)
        _check_quota(conn, sender_id, max_per_day, new_account_max_per_day)
        message_id = _insert_message(conn, conversation.id, sender_id, text, via)
    return Sent(conversation.id, message_id)


def _repeated_message(
    conn: sqlite3.Connection, conversation_id: int, sender_id: int, text: str
) -> int | None:
    """The latest message in the conversation, if the sender sent this same text a few minutes ago."""
    row = conn.execute(
        "SELECT id, sender_id, body, created_at FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if (
        row
        and row["sender_id"] == sender_id
        and row["body"] == text
        and row["created_at"] > iso_ago(minutes=REPEAT_MINUTES)
    ):
        return row["id"]
    return None


def _get(conn: sqlite3.Connection, conversation_id: int, user_id: int) -> Conversation:
    row = conn.execute(
        _SELECT + " WHERE c.id = :id AND (c.buyer_id = :me OR c.seller_id = :me)",
        {"id": conversation_id, "me": user_id},
    ).fetchone()
    if row is None:
        # Same answer whether it doesn't exist or isn't yours: don't leak conversation ids.
        raise NotFound(f"Samtale {conversation_id} finnes ikke.")
    return _conversation(row)


def get_conversation(
    conn: sqlite3.Connection, conversation_id: int, user_id: int, *, mark_read: bool = True
) -> Conversation:
    conversation = _get(conn, conversation_id, user_id)
    rows = conn.execute(
        "SELECT m.*, u.name AS sender_name FROM messages m JOIN users u ON u.id = m.sender_id "
        "WHERE m.conversation_id = ? ORDER BY m.id",
        (conversation_id,),
    ).fetchall()
    conversation.messages = [
        Message(
            r["id"],
            r["conversation_id"],
            r["sender_id"],
            r["sender_name"],
            r["body"],
            r["created_via"],
            r["created_at"],
            r["read_at"],
            json.loads(r["risk_flags"] or "[]"),
        )
        for r in rows
    ]
    if mark_read and conversation.unread:
        conn.execute(
            "UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL",
            (now_iso(), conversation_id, user_id),
        )
    return conversation


def list_conversations(
    conn: sqlite3.Connection, user_id: int, *, unread_only: bool = False, include_hidden: bool = False
) -> list[Conversation]:
    """The person's inbox, newest first, without the conversations they deleted (unless include_hidden)."""
    shown = (
        ""
        if include_hidden
        else " AND NOT ((c.buyer_id = :me AND c.buyer_hidden_at IS NOT NULL)"
        " OR (c.seller_id = :me AND c.seller_hidden_at IS NOT NULL))"
    )
    rows = conn.execute(
        _SELECT + f" WHERE (c.buyer_id = :me OR c.seller_id = :me){shown} "
        "ORDER BY c.last_message_at DESC, c.id DESC",
        {"me": user_id},
    ).fetchall()
    conversations = [_conversation(row) for row in rows]
    return [c for c in conversations if c.unread] if unread_only else conversations


def _kept(conversation: str) -> str:
    """SQL: a conversation both people have deleted is still stored while a report about it is open or a
    message in it has strong fraud signals (moderators may need those), and while the trade made in it can
    still be rated (the rating form and the e-mail about it link to the conversation). Needs _kept_params()."""
    return (
        f"EXISTS (SELECT 1 FROM reports r WHERE r.conversation_id = {conversation} AND r.resolved_at IS NULL) "
        f"OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = {conversation} "
        "AND m.risk_score >= :flagged) "
        f"OR EXISTS (SELECT 1 FROM trades t WHERE t.conversation_id = {conversation} AND t.created_at > :open)"
    )


def _kept_params() -> dict[str, object]:
    from .ratings import RATE_DAYS  # ratings builds on this module

    return {"flagged": fraud.REVIEW_THRESHOLD, "open": iso_ago(days=RATE_DAYS)}


def purge_deleted(conn: sqlite3.Connection) -> int:
    """Delete for good the conversations both people deleted, once nothing keeps them (see _kept)."""
    return conn.execute(
        "DELETE FROM conversations WHERE id IN (SELECT c.id FROM conversations c WHERE "
        f"c.buyer_hidden_at IS NOT NULL AND c.seller_hidden_at IS NOT NULL AND NOT ({_kept('c.id')}))",
        _kept_params(),
    ).rowcount


def hide_conversation(conn: sqlite3.Connection, conversation_id: int, user_id: int) -> bool:
    """Delete a conversation from the person's inbox. The other person keeps theirs, and a new message from
    either brings it back. Once both have deleted it, it is deleted for good, unless something still needs it
    (see _kept; it is deleted later then). Returns True when it was deleted for good."""
    conversation = _get(conn, conversation_id, user_id)
    column = "seller_hidden_at" if conversation.role(user_id) == "seller" else "buyer_hidden_at"
    other = "buyer_hidden_at" if column == "seller_hidden_at" else "seller_hidden_at"
    with transaction(conn):
        conn.execute(f"UPDATE conversations SET {column} = ? WHERE id = ?", (now_iso(), conversation_id))
        conn.execute(
            "UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL",
            (now_iso(), conversation_id, user_id),
        )
        gone = conn.execute(  # messages go with it
            f"DELETE FROM conversations WHERE id = :id AND {other} IS NOT NULL AND NOT ({_kept(':id')})",
            {"id": conversation_id, **_kept_params()},
        ).rowcount
    return gone == 1


def unread_count(conn: sqlite3.Connection, user_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE (c.buyer_id = ? OR c.seller_id = ?) AND m.sender_id != ? AND m.read_at IS NULL",
        (user_id, user_id, user_id),
    ).fetchone()[0]
