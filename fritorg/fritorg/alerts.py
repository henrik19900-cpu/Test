"""E-mail alerts people asked for, and the links that turn them off.

Every alert has a link that turns it off without logging in: "s<id>" for one saved search, "u<id>" for
all of a person's saved searches and "p<id>" for price drops on their favourites. The signature also
covers when that search or account was created, so a link stops working if the row is deleted, and never
works for a later row that happens to get the same id. The link only allows turning alerts off, so it
does not expire.

Price drops: when the price of a favourite is lowered by at least 5 % (or it is given away), the person
gets an e-mail, at most one every 12 hours. Favourites remember the price they last heard about, so each
drop is announced once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import sqlite3

from .mailer import Mail, Mailer
from .util import format_number, iso_ago, now_iso

PRICE_DROP = 0.95  # the new price must be at most this share of the old one
PRICE_ALERT_HOURS = 12
NBSP = "\u00a0"

_KINDS = {"s": "search", "u": "searches", "p": "prices"}


def _signature(secret: str, subject: str, created_at: str) -> bytes:
    message = f"alerts-off:{subject}:{created_at}".encode()
    return base64.urlsafe_b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()[:18])


def unsubscribe_token(secret: str, kind: str, number: int, created_at: str) -> str:
    """kind: "search" (one saved search: its id and created_at), or "searches" or "prices" (all of a
    person's: the user's id and created_at)."""
    letter = next(key for key, value in _KINDS.items() if value == kind)
    subject = f"{letter}{number}"
    return f"{subject}.{_signature(secret, subject, created_at).decode()}"


def unsubscribe_url(base: str, secret: str, kind: str, number: int, created_at: str) -> str:
    return f"{base}/varsler/av?token={unsubscribe_token(secret, kind, number, created_at)}"


def unsubscribe_target(conn: sqlite3.Connection, secret: str, token: str) -> tuple[str, int, str] | None:
    """(kind, id, what it turns off) for a valid token, else None."""
    subject, _, signature = (token or "").partition(".")
    kind = _KINDS.get(subject[:1])
    if kind is None or not subject[1:].isdigit() or len(subject) > 20:
        return None
    number = int(subject[1:])
    if kind == "search":
        row = conn.execute("SELECT name, created_at FROM saved_searches WHERE id = ?", (number,)).fetchone()
    else:
        row = conn.execute("SELECT created_at FROM users WHERE id = ?", (number,)).fetchone()
    if row is None or not hmac.compare_digest(
        signature.encode("utf-8", "replace"), _signature(secret, subject, row["created_at"])
    ):
        return None
    if kind == "search":
        return kind, number, f"e-post om nye treff for søket «{row['name']}»"
    if kind == "searches":
        return kind, number, "e-post om nye treff for alle de lagrede søkene dine"
    return kind, number, "e-post når prisen settes ned på favorittene dine"


def unsubscribe(conn: sqlite3.Connection, secret: str, token: str) -> str | None:
    """Turn alerts off for a token. Returns what was turned off, or None for an invalid token."""
    target = unsubscribe_target(conn, secret, token)
    if target is None:
        return None
    kind, number, description = target
    if kind == "search":
        conn.execute("UPDATE saved_searches SET notify = 0 WHERE id = ?", (number,))
    elif kind == "searches":
        conn.execute("UPDATE saved_searches SET notify = 0 WHERE user_id = ?", (number,))
    else:
        conn.execute("UPDATE users SET price_alerts = 0 WHERE id = ?", (number,))
    return description


def one_click_headers(url: str) -> dict[str, str]:
    """List-Unsubscribe with one-click (RFC 8058): mail programs show an unsubscribe button."""
    return {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


# --- Price drops on favourites ---------------------------------------------------------------


def _nok(value: int) -> str:
    return "gratis" if value == 0 else f"{format_number(value, NBSP)}{NBSP}kr"


def _price_mail(
    base: str, site: str, secret: str, user_id: int, user_created: str, email: str, name: str, rows: list
) -> Mail:
    if len(rows) == 1:
        subject = f"Prisen er satt ned: «{rows[0]['title']}»"
        intro = "Prisen er satt ned på en annonse du har lagret som favoritt"
    else:
        subject = f"Prisen er satt ned på {len(rows)} favoritter"
        intro = f"Prisen er satt ned på {len(rows)} annonser du har lagret som favoritter"
    lines = [f"Hei {name}!", "", f"{intro} på {site}:", ""]
    for row in rows:
        new = "Gis bort" if row["type"] == "give" else _nok(row["price"])
        lines += [
            f"- {row['title']}: {new} (før {_nok(row['notified_price'])})",
            f"  {base}/annonse/{row['listing_id']}",
        ]
    off = unsubscribe_url(base, secret, "prices", user_id, user_created)
    lines += [
        "",
        f"Se alle favorittene dine: {base}/favoritter",
        "",
        f"Du får denne e-posten fordi du har lagret annonser som favoritter. Slå av e-post om prisendringer: {off}",
        "",
        f"Husk: {site} sender aldri betalingslenker. Se varen før du betaler.",
    ]
    return Mail(email, " ".join(subject.split()), "\n".join(lines) + "\n", headers=one_click_headers(off))


def send_price_drops(conn: sqlite3.Connection, mailer: Mailer, base: str, secret: str) -> int:
    """E-mail people whose favourites got cheaper (verified addresses only). Returns the number of e-mails."""
    if not mailer.enabled:
        return 0
    # Favourites saved while the listing had no price start counting from its first price.
    conn.execute(
        "UPDATE favorites SET price = COALESCE(price, (SELECT price FROM listings WHERE id = listing_id)), "
        "notified_price = COALESCE(notified_price, (SELECT price FROM listings WHERE id = listing_id)) "
        "WHERE price IS NULL OR notified_price IS NULL"
    )
    rows = conn.execute(
        "SELECT f.user_id, f.listing_id, f.notified_price, l.price, l.type, l.title, u.email, u.name, "
        "u.created_at AS user_created "
        "FROM favorites f JOIN listings l ON l.id = f.listing_id JOIN users s ON s.id = l.user_id "
        "JOIN users u ON u.id = f.user_id "
        "WHERE l.status = 'active' AND s.banned_at IS NULL AND l.user_id != f.user_id "
        "AND l.price IS NOT NULL AND f.notified_price > 0 AND l.price <= f.notified_price * ? "
        "AND u.price_alerts = 1 AND u.email_verified_at IS NOT NULL AND u.banned_at IS NULL "
        "AND (u.price_alerted_at IS NULL OR u.price_alerted_at < ?) ORDER BY f.user_id, l.id",
        (PRICE_DROP, iso_ago(hours=PRICE_ALERT_HOURS)),
    ).fetchall()
    by_user: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_user.setdefault(row["user_id"], []).append(row)
    site = mailer.settings.site_name
    for user_id, found in by_user.items():
        first = found[0]
        mailer.send_later(
            _price_mail(
                base, site, secret, user_id, first["user_created"], first["email"], first["name"], found
            )
        )
        conn.executemany(
            "UPDATE favorites SET notified_price = ? WHERE user_id = ? AND listing_id = ?",
            [(row["price"], user_id, row["listing_id"]) for row in found],
        )
        conn.execute("UPDATE users SET price_alerted_at = ? WHERE id = ?", (now_iso(), user_id))
    return len(by_user)
