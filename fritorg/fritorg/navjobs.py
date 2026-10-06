"""Job ads from Nav's open job feed (arbeidsplassen.no, "pam-stilling-feed").

Nav's terms (https://arbeidsplassen.nav.no/vilkar-api) let anyone republish the ads for free on
their own service, on three conditions that this module takes care of:

1. Ads that become inactive or are deleted at Nav are removed at once.
2. Changed ads are updated at once.
3. "Søk på stillingen" links straight to the employer's application page.

The feed is a list of pages. Each line says that an ad changed (its uuid, status and time). The
importer reads new lines into import_queue, keeping the latest state per ad, and then applies the
queue: inactive ads are deleted, active ones are fetched in full and created or updated. Where it
is in the feed is kept in import_state, so every run continues where the last one stopped.

Contact persons are not imported (data minimisation): applicants find them in the original ad.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from email.utils import format_datetime
from html.parser import HTMLParser
from typing import Any

from . import __version__, listings
from .config import Settings
from .db import Database, transaction
from .errors import ValidationProblem
from .util import iso_in, now_iso, parse_iso, to_iso, utcnow

logger = logging.getLogger(__name__)

SOURCE = "nav"
SOURCE_EMAIL = "stillinger@arbeidsplassen.import.invalid"  # owner of imported ads; can never log in
SOURCE_NAME = "arbeidsplassen.no (Nav)"
BACKFILL_DAYS = 183  # Nav: an ad is never active for more than six months
LEASE_SECONDS = 1800  # one import at a time, also with several app processes
INDEXED_CHARS = 2500  # how much of an ad's text is full-text indexed


class FeedError(Exception):
    pass


# --- HTTP ------------------------------------------------------------------------------------


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


HttpFn = Callable[[str, dict[str, str]], HttpResponse]


def http_get(url: str, headers: dict[str, str]) -> HttpResponse:
    request = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - configured feed URL
            return HttpResponse(response.status, _lower(response.headers.items()), response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, _lower(exc.headers.items()), exc.read())


def _lower(items) -> dict[str, str]:
    return {key.lower(): value for key, value in items}


class FeedClient:
    """GET requests to the feed with a bearer token: the configured production token, or Nav's
    public test token, which rotates and is fetched again when it stops working."""

    def __init__(self, settings: Settings, conn: sqlite3.Connection, http: HttpFn | None = None):
        self.base = settings.nav_feed_url.rstrip("/")
        self.static_token = settings.nav_token
        self.conn = conn
        self.http = http or http_get
        contact = settings.contact_email or settings.base_url or "no contact configured"
        self.user_agent = f"Fritorg/{__version__} (job ad import; {contact})"

    def _token(self, refresh: bool = False) -> str:
        if self.static_token:
            return self.static_token
        if not refresh:
            row = self.conn.execute("SELECT token FROM import_state WHERE source = ?", (SOURCE,)).fetchone()
            if row and row["token"]:
                return row["token"]
        response = self.http(f"{self.base}/api/publicToken", {"User-Agent": self.user_agent})
        lines = response.body.decode("utf-8", "replace").strip().splitlines()
        if response.status != 200 or not lines:
            raise FeedError(f"Could not get Nav's public token (HTTP {response.status})")
        token = lines[-1].strip()
        self.conn.execute("UPDATE import_state SET token = ? WHERE source = ?", (token, SOURCE))
        return token

    def get(self, path: str, headers: dict[str, str] | None = None) -> HttpResponse:
        def send(token: str) -> HttpResponse:
            extra = {"Authorization": f"Bearer {token}", "User-Agent": self.user_agent}
            return self.http(self.base + path, {**(headers or {}), **extra})

        response = send(self._token())
        if response.status == 401 and not self.static_token:
            response = send(self._token(refresh=True))
        if response.status not in (200, 304, 404):
            raise FeedError(f"GET {path} answered HTTP {response.status}")
        return response


# --- Mapping a Nav ad to a listing -----------------------------------------------------------------

_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "tr", "blockquote",
}  # fmt: skip


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
        self.lists = 0  # open <ul>/<ol>
        self.items = 0  # open <li> inside them

    def _block(self) -> None:
        # Paragraphs inside a list item stay on the item's line.
        self.parts.append(" " if self.lists and self.items else "\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            self.lists += 1
            self.parts.append("\n\n")
        elif tag == "li":
            self.items += 1
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self._block()
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("ul", "ol"):
            self.lists = max(0, self.lists - 1)
            if not self.lists:
                self.items = 0  # also when items were never closed
            self.parts.append("\n\n")
        elif tag == "li":
            self.items = max(0, self.items - 1)
        elif tag in _BLOCK_TAGS:
            self._block()

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str | None) -> str:
    """Nav's ad texts are HTML; listings are plain text with paragraphs and '- ' bullets."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    lines = [line for line in lines if line != "-"]  # empty list items
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:-") + "…"


_LOWERCASE_WORDS = {"i", "og", "på", "ved", "under", "over", "til", "av"}


def place_name(value: str | None) -> str:
    """Nav writes places in capitals: 'MO I RANA' -> 'Mo i Rana', 'AURSKOG-HØLAND' -> 'Aurskog-Høland'."""
    words = re.split(r"(\s+|-)", _line(value).lower())
    out, first = [], True
    for word in words:
        if not word or word.isspace() or word == "-":
            out.append(word)
            continue
        out.append(word if not first and word in _LOWERCASE_WORDS else word[:1].upper() + word[1:])
        first = False
    return "".join(out)


# Nav's occupation groups (occupationCategories.level1) -> Fritorg job categories, first match wins.
_CATEGORY_KEYWORDS = (
    ("jobb-it", ("it", "ikt", "data", "utvikling")),
    ("jobb-helse", ("helse", "sosial", "omsorg", "pleie")),
    ("jobb-utdanning", ("utdanning", "undervisning", "barnehage", "skole")),
    ("jobb-bygg", ("bygg", "anlegg", "håndverk", "elektro")),
    ("jobb-transport", ("transport", "lager", "logistikk", "sjåfør")),
    ("jobb-industri", ("industri", "produksjon", "olje", "mekanikk")),
    ("jobb-kontor", ("kontor", "økonomi", "ledelse", "administrasjon", "finans", "jus")),
    ("jobb-handel", ("salg", "service", "butikk", "handel", "reiseliv", "mat", "restaurant")),
)


def category_for(ad: dict[str, Any]) -> str:
    groups = [oc for oc in ad.get("occupationCategories") or [] if isinstance(oc, dict)]
    for level in ("level1", "level2"):
        for group in groups:
            words = set(re.findall(r"\w+", str(group.get(level) or "").casefold()))
            for slug, keywords in _CATEGORY_KEYWORDS:
                if words & set(keywords):
                    return slug
    return "jobb-annet"


def employment_type(engagement: str | None, extent: str | None) -> str | None:
    kind, hours = (engagement or "").casefold(), (extent or "").casefold()
    if any(word in kind for word in ("vikar", "engasjement", "prosjekt", "åremål", "midlertidig")):
        return "temporary"
    if "sesong" in kind:
        return "seasonal"
    if any(word in kind for word in ("lærling", "trainee")):
        return "apprentice"
    if any(word in kind for word in ("selvstendig", "frilans", "oppdrag")):
        return "freelance"
    if "deltid" in hours:
        return "part_time"
    if "heltid" in hours:
        return "full_time"
    return None


def _deadline(value: Any) -> tuple[str | None, str | None]:
    """applicationDue is free text: '2026-10-19T00:00:00', '2026-10-31' or 'Snarest'."""
    text = _line(value)
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        try:
            return text, date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            pass
    return text or None, None


def _web_url(value: Any) -> str | None:
    url = _line(value)
    return url if re.match(r"https?://[^\s/]+\.[^\s]+", url) else None


def _location(ad: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """(county slug, place, postal code) from the first work location."""
    places = [w for w in ad.get("workLocations") or [] if isinstance(w, dict)]
    if not places:
        return None, None, None
    first = places[0]
    country = _line(first.get("country")).upper()
    names = []
    for work in places:
        name = place_name(work.get("city") or work.get("municipal"))
        if name and name not in names:
            names.append(name)
    place = ", ".join(names)
    if country and country not in ("NORGE", "NORWAY", "NO"):
        abroad = place_name(country)
        return None, _shorten(f"{place}, {abroad}" if place else abroad, 80), None
    county = None
    try:
        county = listings.resolve_county(place_name(first.get("county")) or None)
    except ValidationProblem:
        county = None
    postal = _line(first.get("postalCode"))
    return county, _shorten(place, 80) or None, postal if re.fullmatch(r"\d{4}", postal) else None


def map_ad(ad: dict[str, Any]) -> dict[str, Any]:
    """Listing fields for a Nav ad (ad_content of a feed entry)."""
    employer = ad.get("employer") if isinstance(ad.get("employer"), dict) else {}
    employer_name = _line(employer.get("name") or ad.get("businessName"))
    title = _line(ad.get("title")) or _line(ad.get("jobtitle"))
    if len(title) < 3:
        title = f"Ledig stilling hos {employer_name}" if employer_name else "Ledig stilling"

    deadline_text, deadline_date = _deadline(ad.get("applicationDue"))
    facts = []
    if _line(ad.get("starttime")):
        facts.append(f"Oppstart: {_line(ad.get('starttime'))}")
    positions = _line(ad.get("positioncount"))
    if positions.isdigit() and int(positions) > 1:
        facts.append(f"Antall stillinger: {positions}")
    if _line(ad.get("sector")):
        facts.append(f"Sektor: {_line(ad.get('sector'))}")
    if deadline_text and not deadline_date:
        facts.append(f"Søknadsfrist: {deadline_text}")
    parts = [html_to_text(ad.get("description"))]
    about = html_to_text(employer.get("description"))
    if about and about not in parts[0]:
        parts.append(f"Om arbeidsgiveren\n\n{about}")
    if facts:
        parts.append("\n".join(facts))
    text = "\n\n".join(part for part in parts if part).strip()
    if len(text) < 10:
        text = f"{title}. Les hele annonsen hos arbeidsplassen.no."

    attributes: dict[str, Any] = {}
    if employer_name:
        attributes["employer"] = _shorten(employer_name, 100)
    kind = employment_type(ad.get("engagementtype"), ad.get("extent"))
    if kind:
        attributes["employment_type"] = kind
    if deadline_date:
        attributes["deadline"] = deadline_date

    county, place, postal = _location(ad)
    return {
        "category": category_for(ad),
        "type": "job",
        "title": _shorten(title, 120),
        "description": _shorten(text, 10000),
        "price": None,
        "price_unit": "total",
        "county": county,
        "location": place,
        "postal_code": postal,
        "attributes": attributes,
    }


# --- Storage ------------------------------------------------------------------------------------


def _iso_precise(value: Any) -> str | None:
    """Nav's timestamps with offsets and fractions -> sortable UTC text with microseconds."""
    try:
        return parse_iso(str(value)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    try:
        return to_iso(parse_iso(str(value)))
    except (TypeError, ValueError):
        return None


def source_user(conn: sqlite3.Connection) -> int:
    """The account that owns imported ads. It has no password, so nobody can log in to it."""
    row = conn.execute("SELECT id FROM users WHERE email = ?", (SOURCE_EMAIL,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO users (email, name, password_hash, created_via, created_at) VALUES (?, ?, '!', 'import', ?)",
        (SOURCE_EMAIL, SOURCE_NAME, now_iso()),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _delete(conn: sqlite3.Connection, listing_id: int) -> None:
    conn.execute("DELETE FROM listings_fts WHERE rowid = ?", (listing_id,))
    conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))


def remove(conn: sqlite3.Connection, uuid: str) -> int:
    row = conn.execute(
        "SELECT id FROM listings WHERE source = ? AND source_id = ?", (SOURCE, uuid)
    ).fetchone()
    if row is None:
        return 0
    _delete(conn, row["id"])
    return 1


def remove_expired(conn: sqlite3.Connection) -> int:
    """Also hide ads whose time is up, in case the feed line that ends them was missed."""
    rows = conn.execute(
        "SELECT id FROM listings WHERE source = ? AND expires_at IS NOT NULL AND expires_at < ?",
        (SOURCE, now_iso()),
    ).fetchall()
    if rows:
        with transaction(conn):
            for row in rows:
                _delete(conn, row["id"])
    return len(rows)


def upsert(conn: sqlite3.Connection, owner_id: int, entry: dict[str, Any]) -> str | None:
    """Create or update the listing for an active feed entry. Returns 'created', 'updated' or None."""
    ad = entry.get("ad_content") or {}
    uuid = str(entry.get("uuid") or ad.get("uuid") or "")
    if not uuid:
        return None
    try:
        values = listings.validate_listing(map_ad(ad))
    except ValidationProblem as exc:
        logger.info("Skipping Nav ad %s: %s", uuid, exc.message)
        remove(conn, uuid)
        return None
    source_url = _web_url(ad.get("link")) or f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"
    apply_url = _web_url(ad.get("applicationUrl")) or _web_url(ad.get("sourceurl")) or source_url
    changed = _iso_precise(entry.get("sistEndret")) or _iso_precise(ad.get("updated")) or now_iso()
    published = _iso(ad.get("published")) or now_iso()
    updated = _iso(ad.get("updated")) or published
    expires = _iso(ad.get("expires"))
    if expires and expires < now_iso():
        remove(conn, uuid)
        return None
    common = (
        values["category"],
        values["title"],
        values["description"],
        values["county"],
        values["location"],
        values["postal_code"],
        json.dumps(values["attributes"], ensure_ascii=False),
    )
    existing = conn.execute(
        "SELECT id, status FROM listings WHERE source = ? AND source_id = ?", (SOURCE, uuid)
    ).fetchone()
    if existing:
        # An ad that a moderator removed, or that reports sent to review, stays hidden when Nav changes it.
        status = existing["status"] if existing["status"] in ("removed", "review") else "active"
        conn.execute(
            "UPDATE listings SET category = ?, title = ?, description = ?, county = ?, location = ?, "
            "postal_code = ?, attributes = ?, status = ?, updated_at = ?, source_url = ?, apply_url = ?, "
            "source_updated_at = ?, expires_at = ? WHERE id = ?",
            (*common, status, updated, source_url, apply_url, changed, expires, existing["id"]),
        )
        listings.index_listing(conn, existing["id"], _searchable(values))
        return "updated"
    cursor = conn.execute(
        "INSERT INTO listings (category, title, description, county, location, postal_code, attributes, "
        "user_id, type, price, status, created_via, created_at, updated_at, source, source_id, source_url, "
        "apply_url, source_updated_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'job', NULL, 'active', 'import', ?, ?, ?, ?, ?, ?, ?, ?)",
        (*common, owner_id, published, updated, SOURCE, uuid, source_url, apply_url, changed, expires),
    )
    assert cursor.lastrowid is not None
    listings.index_listing(conn, cursor.lastrowid, _searchable(values))
    return "created"


def _searchable(values: dict[str, Any]) -> dict[str, Any]:
    # Job ads are long; the start says what the job is. Indexing all of it would make the search
    # index several times larger and common words slower to look up.
    return {**values, "description": values["description"][:INDEXED_CHARS]}


# --- Sync ---------------------------------------------------------------------------------------


@dataclass
class SyncReport:
    pages: int = 0
    fetched: int = 0
    created: int = 0
    updated: int = 0
    removed: int = 0
    waiting: int = 0  # changes left in the queue for the next run
    caught_up: bool = False  # read up to the newest page of the feed
    skipped: bool = False  # another process was importing

    @property
    def done(self) -> bool:
        return self.caught_up and self.waiting == 0

    def __str__(self) -> str:
        return (
            f"{self.pages} sider lest, {self.fetched} annonser hentet: {self.created} nye, {self.updated} "
            f"endret, {self.removed} fjernet, {self.waiting} venter"
        )


def _state(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.execute("INSERT OR IGNORE INTO import_state (source) VALUES (?)", (SOURCE,))
    return conn.execute("SELECT * FROM import_state WHERE source = ?", (SOURCE,)).fetchone()


def _acquire(conn: sqlite3.Connection) -> bool:
    _state(conn)
    cursor = conn.execute(
        "UPDATE import_state SET lease_until = ? WHERE source = ? AND (lease_until IS NULL OR lease_until < ?)",
        (iso_in(seconds=LEASE_SECONDS), SOURCE, now_iso()),
    )
    return cursor.rowcount == 1


def _save_cursor(
    conn: sqlite3.Connection, page_id: str | None, etag: str | None, modified: str | None
) -> None:
    conn.execute(
        "UPDATE import_state SET page_id = ?, etag = ?, last_modified = ? WHERE source = ?",
        (page_id, etag, modified, SOURCE),
    )


def _enqueue(conn: sqlite3.Connection, items: list[Any]) -> None:
    with transaction(conn):
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = item.get("_feed_entry") if isinstance(item.get("_feed_entry"), dict) else {}
            uuid = entry.get("uuid") or item.get("id")
            if not uuid:
                continue
            changed = _iso_precise(entry.get("sistEndret") or item.get("date_modified")) or now_iso()
            # Lines are applied in feed order: the last line about an ad wins.
            conn.execute(
                "INSERT INTO import_queue (source, item_id, status, changed_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (source, item_id) DO UPDATE SET status = excluded.status, "
                "changed_at = excluded.changed_at",
                (SOURCE, str(uuid), str(entry.get("status") or "INACTIVE"), changed),
            )


def _scan(conn: sqlite3.Connection, client: FeedClient, report: SyncReport, max_pages: int) -> None:
    state = _state(conn)
    page_id = state["page_id"]
    if page_id is None:
        since = format_datetime(utcnow() - timedelta(days=BACKFILL_DAYS), usegmt=True)
        response = client.get("/api/v1/feed", {"If-Modified-Since": since})
    elif state["etag"] and state["last_modified"]:
        conditional = {"If-None-Match": state["etag"], "If-Modified-Since": state["last_modified"]}
        response = client.get(f"/api/v1/feed/{page_id}", conditional)
        if response.status == 304:
            report.caught_up = True
            return
        # The page has grown. A conditional answer leaves out lines older than If-Modified-Since, and
        # the feed's timestamps are not strictly increasing, so read the whole page.
        response = client.get(f"/api/v1/feed/{page_id}")
    else:
        response = client.get(f"/api/v1/feed/{page_id}")
    while True:
        if response.status == 304:
            report.caught_up = True
            return
        if response.status != 200:
            raise FeedError(f"Feed page {page_id} answered HTTP {response.status}")
        page = response.json()
        report.pages += 1
        _enqueue(conn, page.get("items") or [])
        next_id = page.get("next_id")
        if not next_id:  # the newest page: poll it with ETag and Last-Modified next time
            _save_cursor(
                conn,
                page.get("id") or page_id,
                response.headers.get("etag"),
                response.headers.get("last-modified"),
            )
            report.caught_up = True
            return
        page_id = next_id
        _save_cursor(conn, page_id, None, None)
        if report.pages >= max_pages:
            return
        response = client.get(f"/api/v1/feed/{page_id}")


def _dequeue(conn: sqlite3.Connection, uuid: str, changed_at: str) -> None:
    # Only if no newer line about the ad has been queued in the meantime.
    conn.execute(
        "DELETE FROM import_queue WHERE source = ? AND item_id = ? AND changed_at = ?",
        (SOURCE, uuid, changed_at),
    )


def _apply(
    conn: sqlite3.Connection,
    client: FeedClient,
    report: SyncReport,
    max_fetches: int,
    pause: float,
    should_stop: Callable[[], bool],
) -> None:
    owner_id = source_user(conn)
    # Removals first: they need no request, and Nav's terms want them at once.
    gone = conn.execute(
        "SELECT item_id, changed_at FROM import_queue WHERE source = ? AND status != 'ACTIVE'", (SOURCE,)
    ).fetchall()
    with transaction(conn):
        for row in gone:
            report.removed += remove(conn, row["item_id"])
            _dequeue(conn, row["item_id"], row["changed_at"])
    # Then new and changed ads, newest first.
    rows = conn.execute(
        "SELECT q.item_id, q.changed_at, l.source_updated_at FROM import_queue q "
        "LEFT JOIN listings l ON l.source = q.source AND l.source_id = q.item_id "
        "WHERE q.source = ? AND q.status = 'ACTIVE' ORDER BY q.changed_at DESC",
        (SOURCE,),
    ).fetchall()
    for row in rows:
        uuid, changed_at = row["item_id"], row["changed_at"]
        if row["source_updated_at"] and row["source_updated_at"] >= changed_at:
            _dequeue(conn, uuid, changed_at)  # already up to date
            continue
        if report.fetched >= max_fetches or should_stop():
            break
        response = client.get(f"/api/v1/feedentry/{uuid}")
        report.fetched += 1
        entry = response.json() if response.status == 200 else {}
        with transaction(conn):
            if entry.get("status") == "ACTIVE" and entry.get("ad_content"):
                outcome = upsert(conn, owner_id, entry)
                if outcome == "created":
                    report.created += 1
                elif outcome == "updated":
                    report.updated += 1
            else:
                report.removed += remove(conn, uuid)
            _dequeue(conn, uuid, changed_at)
        if pause:
            time.sleep(pause)


def sync(
    db: Database,
    settings: Settings,
    *,
    http: HttpFn | None = None,
    max_pages: int = 40,
    max_fetches: int = 500,
    pause: float = 0.0,
    should_stop: Callable[[], bool] = lambda: False,
) -> SyncReport:
    """One import run: read new feed pages, then apply up to `max_fetches` new or changed ads."""
    report = SyncReport()
    with db.session() as conn:
        if not _acquire(conn):
            report.skipped = True
            return report
        try:
            client = FeedClient(settings, conn, http)
            report.removed += remove_expired(conn)
            _scan(conn, client, report, max_pages)
            _apply(conn, client, report, max_fetches, pause, should_stop)
            report.waiting = conn.execute(
                "SELECT COUNT(*) FROM import_queue WHERE source = ?", (SOURCE,)
            ).fetchone()[0]
            conn.execute(
                "UPDATE import_state SET last_run_at = ?, last_error = NULL WHERE source = ?",
                (now_iso(), SOURCE),
            )
        except Exception as exc:
            conn.execute(
                "UPDATE import_state SET last_run_at = ?, last_error = ? WHERE source = ?",
                (now_iso(), f"{type(exc).__name__}: {exc}"[:500], SOURCE),
            )
            raise
        finally:
            conn.execute("UPDATE import_state SET lease_until = NULL WHERE source = ?", (SOURCE,))
    return report


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    state = _state(conn)
    count = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE source = ? AND status = 'active'", (SOURCE,)
    ).fetchone()[0]
    waiting = conn.execute("SELECT COUNT(*) FROM import_queue WHERE source = ?", (SOURCE,)).fetchone()[0]
    return {
        "active_listings": count,
        "waiting": waiting,
        "last_run_at": state["last_run_at"],
        "last_error": state["last_error"],
    }


class Importer:
    """Keeps the job ads up to date from a background thread while the app runs."""

    def __init__(self, db: Database, settings: Settings, http: HttpFn | None = None):
        self.db = db
        self.settings = settings
        self.http = http
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="nav-import", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        interval = max(30, self.settings.nav_import_interval)
        while not self._stop.is_set():
            try:
                report = sync(
                    self.db, self.settings, http=self.http, pause=0.1, should_stop=self._stop.is_set
                )
                if report.fetched or report.removed:
                    logger.info("Nav job import: %s", report)
                # While catching up (first start), continue soon; then poll at the normal interval.
                delay = interval if report.done or report.skipped else 5
            except Exception:
                logger.exception("Nav job import failed; trying again later")
                delay = max(interval, 300)
            self._stop.wait(delay)
