"""Ratings between buyers and sellers ("vurderinger").

A rating belongs to a trade. The seller records, from a conversation in which both have written, that the
listing went to that person (record_trade); the listing is then marked as sold. Each of the two may rate the
other once, from 1 to 5 with an optional comment, within RATE_DAYS. A rating is shown when both have rated,
or REVEAL_DAYS after the trade, so nobody answers a rating they have read. Ratings by closed accounts and
ratings a moderator has removed are not shown or counted. Deleting an account deletes the trades and ratings
it took part in; deleting the listing does not.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta

from . import fraud, listings, messages
from .db import transaction
from .errors import Forbidden, NotFound, ValidationProblem
from .listings import CHANNELS, REPORT_REASONS
from .util import iso_ago, now_iso, parse_iso, to_iso

RATE_DAYS = 30
REVEAL_DAYS = 14
MAX_COMMENT = 500
SCORE_LABELS = {5: "Veldig bra", 4: "Bra", 3: "Helt greit", 2: "Dårlig", 1: "Veldig dårlig"}
# Comments are about the trade: no links or contact details (that would make them adverts or spam).
_CONTACT_CODES = {"contact_email", "foreign_phone", "short_link", "external_link", "offsite_contact"}
_NORWEGIAN_PHONE = re.compile(r"(?<![\d+])(?:\+47\s?)?[49]\d(?:\s?\d){6}(?!\d)")

# A rating counts when it was not removed, its author's account is open, and it has been revealed: the
# other person in the trade has rated too, or the trade is older than REVEAL_DAYS. Needs `r`, `t` (the trade)
# and `rater` (users) in the query, and the parameter :revealed (see _revealed).
_VISIBLE = (
    "r.removed_at IS NULL AND rater.banned_at IS NULL AND (t.created_at < :revealed OR EXISTS "
    "(SELECT 1 FROM ratings o WHERE o.trade_id = r.trade_id AND o.rater_id != r.rater_id))"
)
_RATING_SELECT = (
    "SELECT r.*, rater.name AS rater_name, t.listing_title, t.created_at AS traded_at FROM ratings r "
    "JOIN trades t ON t.id = r.trade_id JOIN users rater ON rater.id = r.rater_id"
)


@dataclass
class Rating:
    id: int
    trade_id: int
    rater_id: int
    rater_name: str
    rated_id: int
    score: int
    comment: str | None
    listing_title: str
    created_via: str
    created_at: str
    removed: bool = False


@dataclass
class Summary:
    count: int
    average: float | None

    @property
    def average_text(self) -> str:
        """The average with a decimal comma, e.g. "4,8"."""
        return f"{self.average:.1f}".replace(".", ",") if self.average is not None else ""


@dataclass
class Trade:
    id: int
    conversation_id: int | None
    listing_id: int | None
    listing_title: str
    seller_id: int
    seller_name: str
    buyer_id: int
    buyer_name: str
    created_at: str
    # For the person looking at it: their own rating, and the other's once it is revealed.
    mine: Rating | None = None
    theirs: Rating | None = None
    they_rated: bool = False
    viewer_id: int = 0
    ratings: list[Rating] = field(default_factory=list)

    def role(self, user_id: int) -> str:
        return "seller" if user_id == self.seller_id else "buyer"

    def other_id(self, user_id: int) -> int:
        return self.buyer_id if user_id == self.seller_id else self.seller_id

    def other_name(self, user_id: int) -> str:
        return self.buyer_name if user_id == self.seller_id else self.seller_name

    @property
    def rate_until(self) -> str:
        return to_iso(parse_iso(self.created_at) + timedelta(days=RATE_DAYS))

    @property
    def reveal_at(self) -> str:
        return to_iso(parse_iso(self.created_at) + timedelta(days=REVEAL_DAYS))

    @property
    def can_rate(self) -> bool:
        return self.mine is None and now_iso() < self.rate_until

    @property
    def mine_shown(self) -> bool:
        """Whether the viewer's own rating is shown to the other person yet."""
        return self.mine is not None and (self.they_rated or self.created_at < _revealed())


def _revealed() -> str:
    return iso_ago(days=REVEAL_DAYS)


def _rating(row: sqlite3.Row) -> Rating:
    return Rating(
        id=row["id"],
        trade_id=row["trade_id"],
        rater_id=row["rater_id"],
        rater_name=row["rater_name"],
        rated_id=row["rated_id"],
        score=row["score"],
        comment=row["comment"],
        listing_title=row["listing_title"],
        created_via=row["created_via"],
        created_at=row["created_at"],
        removed=row["removed_at"] is not None,
    )


# --- Trades ----------------------------------------------------------------------------------------

_TRADE_SELECT = (
    "SELECT t.*, s.name AS seller_name, b.name AS buyer_name FROM trades t "
    "JOIN users s ON s.id = t.seller_id JOIN users b ON b.id = t.buyer_id"
)


def _trade(conn: sqlite3.Connection, row: sqlite3.Row, viewer_id: int) -> Trade:
    trade = Trade(
        id=row["id"],
        conversation_id=row["conversation_id"],
        listing_id=row["listing_id"],
        listing_title=row["listing_title"],
        seller_id=row["seller_id"],
        seller_name=row["seller_name"],
        buyer_id=row["buyer_id"],
        buyer_name=row["buyer_name"],
        created_at=row["created_at"],
        viewer_id=viewer_id,
    )
    rows = conn.execute(f"{_RATING_SELECT} WHERE r.trade_id = ?", (trade.id,)).fetchall()
    trade.ratings = [_rating(r) for r in rows]
    trade.mine = next((r for r in trade.ratings if r.rater_id == viewer_id), None)
    theirs = next((r for r in trade.ratings if r.rater_id != viewer_id), None)
    trade.they_rated = theirs is not None
    if (
        theirs is not None
        and not theirs.removed
        and (trade.mine is not None or trade.created_at < _revealed())
    ):
        trade.theirs = theirs
    return trade


def tradeable(conn: sqlite3.Connection, conversation: messages.Conversation, user_id: int) -> bool:
    """Whether the seller may record a trade in this conversation (see record_trade)."""
    if user_id != conversation.seller_id or conversation.listing_id is None:
        return False
    row = conn.execute(
        "SELECT type, status FROM listings WHERE id = ?", (conversation.listing_id,)
    ).fetchone()
    if row is None or row["status"] not in ("active", "inactive", "sold"):
        return False
    if listings.TYPE_WORDS.get(row["type"], listings.TYPE_WORDS["sell"]).traded is None:
        return False
    writers = conn.execute(
        "SELECT COUNT(DISTINCT sender_id) FROM messages WHERE conversation_id = ?", (conversation.id,)
    ).fetchone()[0]
    return writers == 2


def record_trade(
    conn: sqlite3.Connection, conversation_id: int, seller_id: int, *, active_days: int = 60
) -> Trade:
    """The seller records that the listing went to the other person in the conversation, and it is marked as
    sold. Both may then rate each other. Recording it again changes nothing."""
    conversation = messages.get_conversation(conn, conversation_id, seller_id, mark_read=False)
    existing = trade_for_conversation(conn, conversation_id, seller_id)
    if existing is not None:
        return existing
    if seller_id != conversation.seller_id:
        raise Forbidden(
            "Bare den som la ut annonsen, kan registrere handelen.",
            hint="Only the listing's owner (the seller in the conversation) records a trade.",
        )
    if not tradeable(conn, conversation, seller_id):
        raise ValidationProblem.field(
            "conversation_id",
            "Handelen kan registreres når dere begge har skrevet i samtalen, og annonsen ikke er en stilling, "
            "til kontroll eller fjernet.",
            hint="Both people must have written in the conversation; job ads and listings in review or removed "
            "cannot be traded.",
        )
    assert conversation.listing_id is not None
    listing = listings.get_listing(conn, conversation.listing_id)
    if listing.status != "sold":
        listings.set_status(conn, seller_id, listing.id, "sold", active_days=active_days)
    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO trades (conversation_id, listing_id, listing_title, seller_id, buyer_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation.id,
                listing.id,
                listing.title,
                conversation.seller_id,
                conversation.buyer_id,
                now_iso(),
            ),
        )
    trade = trade_for_conversation(conn, conversation_id, seller_id)
    assert trade is not None
    return trade


def trade_for_conversation(conn: sqlite3.Connection, conversation_id: int, viewer_id: int) -> Trade | None:
    row = conn.execute(
        f"{_TRADE_SELECT} WHERE t.conversation_id = ? AND (t.seller_id = ? OR t.buyer_id = ?)",
        (conversation_id, viewer_id, viewer_id),
    ).fetchone()
    return _trade(conn, row, viewer_id) if row else None


def get_trade(conn: sqlite3.Connection, trade_id: int, viewer_id: int) -> Trade:
    row = conn.execute(
        f"{_TRADE_SELECT} WHERE t.id = ? AND (t.seller_id = ? OR t.buyer_id = ?)",
        (trade_id, viewer_id, viewer_id),
    ).fetchone()
    if row is None:
        raise NotFound(f"Handel {trade_id} finnes ikke.")
    return _trade(conn, row, viewer_id)


def trades_for_user(conn: sqlite3.Connection, user_id: int, limit: int = 100) -> list[Trade]:
    rows = conn.execute(
        f"{_TRADE_SELECT} WHERE t.seller_id = ? OR t.buyer_id = ? ORDER BY t.id DESC LIMIT ?",
        (user_id, user_id, limit),
    ).fetchall()
    return [_trade(conn, row, user_id) for row in rows]


# --- Ratings ---------------------------------------------------------------------------------------


def _clean_comment(comment: str | None) -> str | None:
    text = " ".join((comment or "").split())
    if len(text) > MAX_COMMENT:
        raise ValidationProblem.field("comment", f"Kommentaren kan ha maks {MAX_COMMENT} tegn.")
    if _CONTACT_CODES & set(fraud.text_codes(text)) or _NORWEGIAN_PHONE.search(text):
        raise ValidationProblem.field(
            "comment",
            "Kommentaren kan ikke inneholde lenker, e-postadresser eller telefonnumre.",
            hint="Remove links, e-mail addresses and phone numbers from the comment.",
        )
    return text or None


def rate(
    conn: sqlite3.Connection,
    trade_id: int,
    rater_id: int,
    score: int,
    comment: str | None = None,
    *,
    via: str = "web",
) -> Trade:
    """Rate the other person in a trade, once. Returns the trade as the rater sees it."""
    trade = get_trade(conn, trade_id, rater_id)
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
        raise ValidationProblem.field(
            "score", "Velg fra 1 til 5.", hint="score is a whole number from 1 to 5."
        )
    text = _clean_comment(comment)
    if trade.mine is not None:
        raise ValidationProblem.field(
            "score", "Du har allerede vurdert denne handelen.", hint="A rating cannot be changed."
        )
    if not trade.can_rate:
        raise ValidationProblem.field(
            "score",
            f"Fristen for å vurdere handelen gikk ut etter {RATE_DAYS} dager.",
            hint=f"Ratings must be given within {RATE_DAYS} days of the trade.",
        )
    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO ratings (trade_id, rater_id, rated_id, score, comment, created_via, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trade.id,
                rater_id,
                trade.other_id(rater_id),
                score,
                text,
                via if via in CHANNELS else "web",
                now_iso(),
            ),
        )
    return get_trade(conn, trade_id, rater_id)


def summary(conn: sqlite3.Connection, user_id: int) -> Summary:
    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(r.score) AS average FROM ratings r JOIN trades t ON t.id = r.trade_id "
        f"JOIN users rater ON rater.id = r.rater_id WHERE r.rated_id = :user AND {_VISIBLE}",
        {"user": user_id, "revealed": _revealed()},
    ).fetchone()
    return Summary(row["n"], round(row["average"], 1) if row["n"] else None)


def ratings_for_user(conn: sqlite3.Connection, user_id: int, limit: int = 50) -> list[Rating]:
    """The ratings shown on someone's profile, newest first."""
    rows = conn.execute(
        f"{_RATING_SELECT} WHERE r.rated_id = :user AND {_VISIBLE} ORDER BY r.id DESC LIMIT :limit",
        {"user": user_id, "revealed": _revealed(), "limit": limit},
    ).fetchall()
    return [_rating(row) for row in rows]


def get_visible_rating(conn: sqlite3.Connection, rating_id: int) -> Rating:
    row = conn.execute(
        f"{_RATING_SELECT} WHERE r.id = :id AND {_VISIBLE}", {"id": rating_id, "revealed": _revealed()}
    ).fetchone()
    if row is None:
        raise NotFound(f"Vurdering {rating_id} finnes ikke.")
    return _rating(row)


def report_rating(
    conn: sqlite3.Connection,
    rating_id: int,
    reason: str,
    comment: str | None,
    reporter_id: int | None,
    via: str = "web",
) -> int:
    """Report a rating, e.g. because it is false or abusive. A moderator decides (moderation.py)."""
    rating = get_visible_rating(conn, rating_id)
    listings.check_report_quota(conn, reporter_id)
    if reason not in REPORT_REASONS:
        raise ValidationProblem.field(
            "reason", "Ugyldig grunn.", hint=f"Valid reasons: {', '.join(REPORT_REASONS)}"
        )
    comment = (comment or "").strip()[:2000] or None
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO reports (listing_id, reported_user_id, reporter_id, reason, comment, created_via, created_at, "
            "rating_id) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
            (
                rating.rater_id,
                reporter_id,
                reason,
                comment,
                via if via in CHANNELS else "web",
                now_iso(),
                rating.id,
            ),
        )
    return cursor.lastrowid  # type: ignore[return-value]


def stars(score: int) -> str:
    return "★" * score + "☆" * (5 - score)
