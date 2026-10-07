"""E-mail alerts people asked for, and the links that turn them off.

Every alert has a link that turns it off without logging in: "s<id>" for one saved search, "u<id>" for
all of a person's saved searches and "p<id>" for price drops on their favourites. The signed token only
allows that, so it does not expire.

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


def _signature(secret: str, subject: str) -> str:
    digest = hmac.new(secret.encode(), f"alerts-off:{subject}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode()


def unsubscribe_token(secret: str, kind: str, number: int) -> str:
    """kind: "search" (one saved search), "searches" or "prices" (all of a person's)."""
    letter = next(key for key, value in _KINDS.items() if value == kind)
    subject = f"{letter}{number}"
    return f"{subject}.{_signature(secret, subject)}"


def unsubscribe_url(base: str, secret: str, kind: str, number: int) -> str:
    return f"{base}/varsler/av?token={unsubscribe_token(secret, kind, number)}"


def unsubscribe_target(conn: sqlite3.Connection, secret: str, token: str) -> tuple[str, int, str] | None:
    """(kind, id, what it turns off) for a valid token, else None."""
    subject, _, signature = (token or "").partition(".")
    kind = _KINDS.get(subject[:1])
    if (
        kind is None
        or not subject[1:].isdigit()
        or not hmac.compare_digest(signature, _signature(secret, subject))
    ):
        return None
    number = int(subject[1:])
    if kind == "search":
        row = conn.execute("SELECT name FROM saved_searches WHERE id = ?", (number,)).fetchone()
        return (kind, number, f"e-post om nye treff for søket «{row['name']}»") if row else None
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


def _price_mail(base: str, site: str, secret: str, user_id: int, email: str, name: str, rows: list) -> Mail:
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
    off = unsubscribe_url(base, secret, "prices", user_id)
    lines += [
        "",
        f"Se alle favorittene dine: {base}/favoritter",
        "",
        f"Du får denne e-posten fordi du har lagret annonser som favoritter. Slå av e-post om prisendringer: {off}",
        "",
        f"Husk: {site} sender aldri betalingslenker. Se varen før du betaler.",
    ]
    return Mail(email, subject, "\n".join(lines) + "\n", headers=one_click_headers(off))


def send_price_drops(conn: sqlite3.Connection, mailer: Mailer, base: str, secret: str) -> int:
    """E-mail people whose favourites got cheaper (verified addresses only). Returns the number of e-mails."""
    if not mailer.enabled:
        return 0
    rows = conn.execute(
        "SELECT f.user_id, f.listing_id, f.notified_price, l.price, l.type, l.title, u.email, u.name "
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
        for row in found:
            conn.execute(
                "UPDATE favorites SET notified_price = ? WHERE user_id = ? AND listing_id = ?",
                (row["price"], user_id, row["listing_id"]),
            )
        conn.execute("UPDATE users SET price_alerted_at = ? WHERE id = ?", (now_iso(), user_id))
        mailer.send_later(
            _price_mail(base, site, secret, user_id, found[0]["email"], found[0]["name"], found)
        )
    return len(by_user)
