"""Saved searches ("lagrede søk"): people save a search and hear about new matches, on the site (how
many listings are new since they last looked) and, if they want, by e-mail.

A search is stored as its /sok query parameters, normalised, so the same search is saved once. New
matches are found by listing id: ids only grow, so everything above the newest id at the last look is
new. (A listing that waited for moderation is approved with its original id, so it is not announced.)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

from . import alerts, listings, taxonomy
from .errors import NotFound, ValidationProblem
from .listings import SearchParams, SearchResult
from .mailer import Mail, Mailer
from .util import format_number, iso_ago, now_iso

MAX_SAVED = 50
ALERT_INTERVAL_HOURS = 1  # at most one e-mail per saved search per hour; matches wait for the next one
ALERT_ITEMS = 10  # listings named per search in an e-mail
NBSP = "\u00a0"


@dataclass
class SavedSearch:
    id: int
    user_id: int
    name: str
    query: str
    notify: bool
    seen_id: int
    alerted_id: int
    created_at: str
    alerted_at: str | None
    new_count: int = 0

    @property
    def params(self) -> SearchParams:
        return listings.params_from_query(parse_qsl(self.query))

    @property
    def web_path(self) -> str:
        return f"/sok?{self.query}"


def _saved(row: sqlite3.Row) -> SavedSearch:
    return SavedSearch(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        query=row["query"],
        notify=bool(row["notify"]),
        seen_id=row["seen_id"],
        alerted_id=row["alerted_id"],
        created_at=row["created_at"],
        alerted_at=row["alerted_at"],
    )


def canonical_query(params: SearchParams) -> str:
    """The search's filters as query parameters, always in the same order (sorting and paging left out)."""
    items: list[tuple[str, str]] = []
    if params.q and params.q.strip():
        items.append(("q", " ".join(params.q.split())))
    for key in ("category", "type", "county", "location", "price_min", "price_max"):
        value = getattr(params, key)
        if value not in (None, ""):
            items.append((key, str(value).strip()))
    items += sorted(("attr", flt.to_expression()) for flt in params.attrs)
    if params.user_id is not None:
        items.append(("seller_id", str(params.user_id)))
    if params.has_images:
        items.append(("has_images", "1"))
    return urlencode(items)


def _price(value: int) -> str:
    return f"{format_number(value, NBSP)}{NBSP}kr"


def describe(params: SearchParams) -> str:
    """A short Norwegian name for a search, e.g. «sofa», Møbler, Oslo, under 2 000 kr."""
    parts: list[str] = []
    if params.q:
        parts.append(f"«{' '.join(params.q.split())}»")
    if params.category in taxonomy.CATEGORIES:
        parts.append(taxonomy.CATEGORIES[params.category].name)
    if params.type in taxonomy.LISTING_TYPES:
        parts.append(taxonomy.LISTING_TYPES[params.type].label)
    if params.county in taxonomy.COUNTIES:
        parts.append(taxonomy.COUNTIES[params.county].name)
    if params.location:
        parts.append(params.location)
    if params.price_min is not None and params.price_max is not None:
        parts.append(f"{format_number(params.price_min, NBSP)}–{_price(params.price_max)}")
    elif params.price_max is not None:
        parts.append(f"under {_price(params.price_max)}" if params.price_max else "gratis")
    elif params.price_min is not None:
        parts.append(f"over {_price(params.price_min)}")
    for flt in params.attrs:
        attr = taxonomy.ATTRIBUTES[flt.key]
        if flt.values:
            parts.append(f"{attr.label}: {', '.join(attr.display(v) for v in flt.values)}")
        elif flt.min is not None and flt.max is not None:
            parts.append(f"{attr.label} {attr.display(flt.min)}–{attr.display(flt.max)}")
        elif flt.min is not None:
            parts.append(f"{attr.label} fra {attr.display(flt.min)}")
        elif flt.max is not None:
            parts.append(f"{attr.label} til {attr.display(flt.max)}")
    if params.has_images:
        parts.append("med bilder")
    if params.user_id is not None:
        parts.append("fra én selger")
    name = ", ".join(parts) or "Alle annonser"
    return name if len(name) <= 120 else name[:119] + "…"


def get(conn: sqlite3.Connection, user_id: int, search_id: int) -> SavedSearch:
    row = conn.execute(
        "SELECT * FROM saved_searches WHERE id = ? AND user_id = ?", (search_id, user_id)
    ).fetchone()
    if row is None:
        raise NotFound(f"Lagret søk {search_id} finnes ikke.")
    return _saved(row)


def find(conn: sqlite3.Connection, user_id: int, params: SearchParams) -> SavedSearch | None:
    """The person's saved search with the same filters, if any."""
    row = conn.execute(
        "SELECT * FROM saved_searches WHERE user_id = ? AND query = ?", (user_id, canonical_query(params))
    ).fetchone()
    return _saved(row) if row else None


def create(
    conn: sqlite3.Connection, user_id: int, params: SearchParams, *, notify: bool | None = None
) -> tuple[SavedSearch, bool]:
    """Save a search (new matches count from now). Returns it and whether it was new; saving the same
    search again keeps the first one and only changes `notify` if given."""
    listings.validate_search(params)
    query = canonical_query(params)
    if not query:
        raise ValidationProblem.field(
            "query",
            "Skriv et søkeord eller velg minst ett filter før du lagrer søket.",
            hint="A saved search needs at least one filter, e.g. q, category or county.",
        )
    existing = find(conn, user_id, params)
    if existing is not None:
        if notify is not None and notify != existing.notify:
            set_notify(conn, user_id, existing.id, notify)
            existing.notify = notify
        return existing, False
    count = conn.execute("SELECT COUNT(*) FROM saved_searches WHERE user_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_SAVED:
        raise ValidationProblem(
            f"Du kan ha maks {MAX_SAVED} lagrede søk. Slett noen du ikke trenger lenger.",
            hint="Delete one with DELETE /api/v1/me/saved-searches/{id} (MCP: delete_saved_search).",
        )
    newest = listings.newest_id(conn)
    cursor = conn.execute(
        "INSERT INTO saved_searches (user_id, name, query, notify, seen_id, alerted_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, describe(params), query, int(notify is not False), newest, newest, now_iso()),
    )
    assert cursor.lastrowid is not None
    return get(conn, user_id, cursor.lastrowid), True


def new_matches(
    conn: sqlite3.Connection, saved: SavedSearch, limit: int = 10, up_to_id: int | None = None
) -> SearchResult:
    """Active listings added since the person last looked, newest first."""
    params = saved.params
    params.after_id, params.up_to_id, params.sort, params.limit = saved.seen_id, up_to_id, "newest", limit
    return listings.search(conn, params)


def list_for(conn: sqlite3.Connection, user_id: int) -> list[SavedSearch]:
    """The person's saved searches, newest first, each with its number of new matches."""
    items = [
        _saved(row)
        for row in conn.execute("SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id DESC", (user_id,))
    ]
    for saved in items:
        saved.new_count = new_matches(conn, saved, limit=1).total
    return items


def mark_seen(
    conn: sqlite3.Connection, user_id: int, search_id: int, up_to_id: int | None = None
) -> SavedSearch:
    """Everything up to now (or up to `up_to_id`) counts as seen."""
    saved = get(conn, user_id, search_id)
    saved.seen_id = max(saved.seen_id, listings.newest_id(conn) if up_to_id is None else up_to_id)
    conn.execute("UPDATE saved_searches SET seen_id = ? WHERE id = ?", (saved.seen_id, saved.id))
    saved.new_count = 0
    return saved


def set_notify(conn: sqlite3.Connection, user_id: int, search_id: int, notify: bool) -> SavedSearch:
    saved = get(conn, user_id, search_id)
    if notify and not saved.notify:
        # From now on: no e-mail about what came while alerts were off.
        saved.alerted_id = listings.newest_id(conn)
    conn.execute(
        "UPDATE saved_searches SET notify = ?, alerted_id = ? WHERE id = ?",
        (int(notify), saved.alerted_id, saved.id),
    )
    saved.notify = notify
    return saved


def delete(conn: sqlite3.Connection, user_id: int, search_id: int) -> None:
    if (
        conn.execute("DELETE FROM saved_searches WHERE id = ? AND user_id = ?", (search_id, user_id)).rowcount
        == 0
    ):
        raise NotFound(f"Lagret søk {search_id} finnes ikke.")


# --- E-mail alerts ------------------------------------------------------------------------------


def _count(n: int) -> str:
    return "1 nytt treff" if n == 1 else f"{format_number(n, NBSP)} nye treff"


def _alert_mail(
    base: str,
    site: str,
    secret: str,
    email: str,
    name: str,
    user_id: int,
    hits: list[tuple[SavedSearch, SearchResult]],
) -> Mail:
    if len(hits) == 1:
        subject = f"{_count(hits[0][1].total)}: {hits[0][0].name}"
    else:
        subject = f"Nye treff i {len(hits)} lagrede søk"
    lines = [f"Hei {name}!", "", f"Det har kommet nye annonser på {site} som passer søk du har lagret.", ""]
    for saved, result in hits:
        lines += [f"{saved.name} – {_count(result.total)}:", ""]
        for item in result.items:
            details = ", ".join(part for part in (item.price_text(), item.place) if part)
            lines += [f"- {item.title}" + (f" ({details})" if details else ""), f"  {base}/annonse/{item.id}"]
        rest = result.total - len(result.items)
        lines += [
            "",
            (f"Se alle, også {rest} til: " if rest > 0 else "Se søket: ") + f"{base}/lagrede-sok/{saved.id}",
            f"Slå av varsel for dette søket: {alerts.unsubscribe_url(base, secret, 'search', saved.id)}",
            "",
        ]
    off = alerts.unsubscribe_url(base, secret, "searches", user_id)
    lines += [
        f"Du får denne e-posten fordi du har lagret søk med e-postvarsel på {site}. "
        f"Endre varslene på {base}/lagrede-sok, eller slå av alle: {off}",
        "",
        f"Husk: {site} sender aldri betalingslenker. Se varen før du betaler.",
    ]
    return Mail(email, subject, "\n".join(lines) + "\n", headers=alerts.one_click_headers(off))


def send_alerts(conn: sqlite3.Connection, mailer: Mailer, base: str, secret: str) -> int:
    """E-mail people about new matches for their saved searches (verified addresses only). Returns the
    number of e-mails sent. Searches checked without a match just move on, so no listing is announced twice."""
    if not mailer.enabled:
        return 0
    newest = listings.newest_id(conn)
    rows = conn.execute(
        "SELECT s.*, u.email, u.name AS user_name FROM saved_searches s JOIN users u ON u.id = s.user_id "
        "WHERE s.notify = 1 AND s.alerted_id < ? AND (s.alerted_at IS NULL OR s.alerted_at < ?) "
        "AND u.email_verified_at IS NOT NULL AND u.banned_at IS NULL ORDER BY s.user_id, s.id",
        (newest, iso_ago(hours=ALERT_INTERVAL_HOURS)),
    ).fetchall()
    found: dict[int, tuple[str, str, list[tuple[SavedSearch, SearchResult]]]] = {}
    for row in rows:
        saved = _saved(row)
        params = saved.params
        params.after_id = max(saved.alerted_id, saved.seen_id)
        params.up_to_id, params.sort, params.limit = newest, "newest", ALERT_ITEMS
        result = listings.search(conn, params)
        if result.total:
            found.setdefault(saved.user_id, (row["email"], row["user_name"], []))[2].append((saved, result))
            conn.execute(
                "UPDATE saved_searches SET alerted_id = ?, alerted_at = ? WHERE id = ?",
                (newest, now_iso(), saved.id),
            )
        else:
            conn.execute("UPDATE saved_searches SET alerted_id = ? WHERE id = ?", (newest, saved.id))
    site = mailer.settings.site_name
    for user_id, (email, name, hits) in found.items():
        mailer.send_later(_alert_mail(base, site, secret, email, name, user_id, hits))
    return len(found)
