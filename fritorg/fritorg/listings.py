"""Listings: validation, storage, full-text search and quotas.

Validation messages ("detail") are Norwegian because people see them in forms; "hint"
texts are English because they tell API/MCP clients how to fix the request.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from . import fraud, postcodes, taxonomy, users
from .db import transaction
from .errors import Forbidden, NotFound, RateLimited, ValidationProblem
from .taxonomy import (
    ATTRIBUTES,
    COUNTIES,
    LISTING_TYPES,
    OWNER_STATUSES,
    PRICE_UNITS,
    STATUSES,
    Attribute,
    Category,
)
from .util import format_number, iso_ago, iso_in, now_iso, parse_iso, to_iso

if TYPE_CHECKING:
    from .ratings import Summary

CHANNELS = ("web", "api", "mcp", "import")


@dataclass(frozen=True)
class Source:
    """An open source that listings are imported from (listings.source), and how to credit it."""

    slug: str
    name: str  # credit, e.g. "arbeidsplassen.no (Nav)"
    owner_label: str  # who offers it, shown above the owner's name
    action: str  # the button that takes people to the source
    homepage: str
    licence: str | None = None  # attribution the licence asks for
    licence_url: str | None = None


SOURCES = {
    "nav": Source(
        "nav", "arbeidsplassen.no (Nav)", "Arbeidsgiver", "Søk på stillingen", "https://arbeidsplassen.nav.no"
    ),
    "jobtech": Source(
        "jobtech",
        "Platsbanken (Arbetsförmedlingen, Sverige)",
        "Arbeidsgiver",
        "Søk på stillingen",
        "https://arbetsformedlingen.se/platsbanken",
        licence="Annonsedata fra Arbetsförmedlingen (JobTech), fritt tilgjengelig under CC0.",
        licence_url="https://creativecommons.org/publicdomain/zero/1.0/deed.no",
    ),
}
EDITABLE_FIELDS = (
    "category",
    "type",
    "title",
    "description",
    "price",
    "price_unit",
    "county",
    "location",
    "postal_code",
    "attributes",
)
MAX_PRICE = 1_000_000_000


class TypeWords(NamedTuple):
    """How a listing type is talked about: who posted it, how to contact them, a suggested first message,
    what "sold" means for it, the button that marks it so, quick replies for the poster, and the button that
    records a trade with the person in a conversation (None: no trades, e.g. for jobs; see ratings.py)."""

    role: str
    contact: str
    prefill: str
    done: str
    mark_done: str
    replies: tuple[str, ...]
    traded: str | None = None


TYPE_WORDS = {
    "sell": TypeWords(
        "Selger",
        "Kontakt selger",
        "Hei! Er «{title}» fortsatt til salgs?",
        "Solgt",
        "Merk som solgt",
        ("Ja, den er fortsatt til salgs.", "Beklager, den er solgt."),
        "Solgt til {name}",
    ),
    "give": TypeWords(
        "Gis bort av",
        "Kontakt giveren",
        "Hei! Er «{title}» fortsatt ledig? Jeg henter gjerne.",
        "Gitt bort",
        "Merk som gitt bort",
        ("Ja, den er fortsatt ledig. Når kan du hente?", "Beklager, den er gitt bort."),
        "Gitt bort til {name}",
    ),
    "wanted": TypeWords(
        "Ønskes av",
        "Svar på annonsen",
        "Hei! Jeg så at du ønsker «{title}». Jeg har noe som kan passe.",
        "Funnet",
        "Merk som funnet",
        ("Så bra! Har du bilder?", "Takk, men jeg har allerede funnet det jeg lette etter."),
        "Fikk det av {name}",
    ),
    "rent": TypeWords(
        "Utleier",
        "Kontakt utleier",
        "Hei! Er «{title}» fortsatt ledig?",
        "Utleid",
        "Merk som utleid",
        ("Ja, den er fortsatt ledig.", "Beklager, den er utleid."),
        "Utleid til {name}",
    ),
    "job": TypeWords(
        "Arbeidsgiver",
        "Kontakt arbeidsgiver",
        "Hei! Jeg er interessert i stillingen «{title}».",
        "Besatt",
        "Merk som besatt",
        ("Takk for interessen! Fortell gjerne litt om deg selv.", "Beklager, stillingen er besatt."),
    ),
    "service": TypeWords(
        "Tilbys av",
        "Kontakt tilbyderen",
        "Hei! Jeg er interessert i «{title}». Når har du tid?",
        "Avsluttet",
        "Merk som avsluttet",
        ("Ja, jeg har ledig kapasitet. Når passer det?", "Beklager, jeg har ikke kapasitet nå."),
        "Utført for {name}",
    ),
}

REPORT_REASONS = {
    "spam": "Spam eller duplikat",
    "fraud": "Mulig svindel",
    "illegal": "Ulovlig vare eller innhold",
    "offensive": "Støtende innhold",
    "wrong_category": "Feil kategori",
    "other": "Annet",
}


@dataclass
class Image:
    id: int
    listing_id: int
    filename: str
    content_type: str
    alt_text: str | None
    position: int
    width: int | None = None
    height: int | None = None

    @property
    def path(self) -> str:
        return f"/uploads/{self.filename}"

    @property
    def thumb_path(self) -> str:
        stem, _, suffix = self.filename.rpartition(".")
        return f"/uploads/{stem}-t.{suffix}"


@dataclass
class Listing:
    id: int
    user_id: int
    category: str
    type: str
    title: str
    description: str
    price: int | None
    price_unit: str
    county: str | None
    location: str | None
    postal_code: str | None
    attributes: dict[str, Any]
    status: str
    created_via: str
    created_at: str
    updated_at: str
    seller_name: str
    seller_since: str
    risk_score: int = 0
    risk_flags: list[str] = field(default_factory=list)
    reviewed_at: str | None = None
    moderation_note: str | None = None
    seller_banned: bool = False
    seller_verified: bool = False
    seller_verified_via: str | None = None
    images: list[Image] = field(default_factory=list)
    rank: float | None = None
    # Seller statistics, only loaded for single-listing views (get_listing).
    seller_active: int | None = None
    seller_sold: int | None = None
    seller_rating: Summary | None = None
    # Favourites: the price when the person saved it (only loaded for their favourites).
    saved_price: int | None = None
    views: int = 0  # how many times people looked at it (see views.py)
    # Imported listings (see SOURCES): where they come from and where to apply.
    source: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    apply_url: str | None = None
    expires_at: str | None = None
    deletion_notice_at: str | None = None  # when the owner was told it will be deleted (mark_for_deletion)

    @property
    def category_obj(self) -> Category:
        return taxonomy.CATEGORIES[self.category]

    @property
    def group(self) -> Category:
        return taxonomy.CATEGORIES[self.category_obj.group]

    @property
    def type_label(self) -> str:
        return LISTING_TYPES[self.type].label

    @property
    def status_label(self) -> str:
        return STATUSES[self.status]

    @property
    def county_name(self) -> str | None:
        return COUNTIES[self.county].name if self.county in COUNTIES else None

    @property
    def place(self) -> str:
        county = self.county_name
        if self.location and county and self.location.casefold() == county.casefold():
            return self.location
        return ", ".join(p for p in (self.location, county) if p)

    @property
    def thumbnail(self) -> Image | None:
        return self.images[0] if self.images else None

    @property
    def is_public(self) -> bool:
        return self.status in ("active", "sold") and not self.seller_banned

    @property
    def seller_is_new(self) -> bool:
        return not self.is_imported and self.seller_since > iso_ago(days=fraud.NEW_ACCOUNT_DAYS)

    @property
    def is_imported(self) -> bool:
        return self.source is not None

    @property
    def words(self) -> TypeWords:
        return TYPE_WORDS.get(self.type, TYPE_WORDS["sell"])

    @property
    def poster_role(self) -> str:
        return self.words.role

    @property
    def contact_label(self) -> str:
        return self.words.contact

    @property
    def contact_prefill(self) -> str:
        return self.words.prefill.format(title=self.title)

    @property
    def shown_status(self) -> str:
        """The status as people see it, e.g. "Utleid" for a sold rental."""
        return self.words.done if self.status == "sold" else self.status_label

    @property
    def price_drop(self) -> int | None:
        """For a favourite whose price was lowered since it was saved: the price then."""
        if self.saved_price is not None and self.price is not None and self.price < self.saved_price:
            return self.saved_price
        return None

    @property
    def expires_soon(self) -> bool:
        """Within a week of being hidden: the owner is offered to renew it."""
        return bool(self.expires_at) and not self.is_imported and self.expires_at < iso_in(days=7)

    @property
    def deletes_at(self) -> str | None:
        """When an old listing is deleted automatically: set when its owner is told, two weeks before."""
        if not self.deletion_notice_at or self.status == "active":
            return None
        return to_iso(parse_iso(self.deletion_notice_at) + timedelta(days=DELETION_NOTICE_DAYS))

    @property
    def source_info(self) -> Source | None:
        return SOURCES.get(self.source) if self.source else None

    @property
    def source_name(self) -> str | None:
        info = self.source_info
        return info.name if info else self.source

    @property
    def offered_by(self) -> str:
        """For imported listings: the employer, or else the source itself."""
        info = self.source_info
        return str(self.attributes.get("employer") or (info.name if info else self.seller_name))

    @property
    def seller_verification(self) -> str | None:
        return users.verification_kind(self.seller_verified_via) if self.seller_verified else None

    @property
    def seller_verification_label(self) -> str | None:
        return users.verification_label(self.seller_verified_via) if self.seller_verified else None

    @property
    def seller_verification_title(self) -> str | None:
        return users.verification_title(self.seller_verified_via) if self.seller_verified else None

    @property
    def safety_warnings(self) -> list[str]:
        """Neutral warnings for buyers, from content signals found on this listing."""
        return fraud.listing_warnings(self.risk_flags)

    @property
    def moderation_reasons(self) -> list[dict[str, str]]:
        return fraud.reasons(self.risk_flags)

    def price_text(self, sep: str = " ") -> str | None:
        if self.type == "give":
            return "Gis bort"
        if self.price is None:
            return None if self.type == "job" else "Pris ikke oppgitt"
        if self.price == 0:
            return "Gratis"
        return f"{format_number(self.price, sep)} kr{PRICE_UNITS.get(self.price_unit, '')}"

    @property
    def attribute_rows(self) -> list[tuple[Attribute, Any, str]]:
        rows = []
        for attr in self.category_obj.attributes:
            if attr.key in self.attributes:
                value = self.attributes[attr.key]
                rows.append((attr, value, attr.display(value)))
        return rows


# --- Validation -----------------------------------------------------------------------------

_TRUE = {"true", "1", "yes", "ja", "on", "y"}
_FALSE = {"false", "0", "no", "nei", "off", "n"}


def coerce_attribute(attr: Attribute, value: Any) -> Any:
    """Convert a raw value (from JSON or a form) to the attribute's type, or raise ValueError."""
    if attr.type == "integer":
        if isinstance(value, bool):
            raise ValueError("må være et heltall")
        if isinstance(value, str):
            cleaned = re.sub(r"\s", "", value)  # \s also covers no-break spaces
            if not re.fullmatch(r"-?\d+", cleaned):
                raise ValueError("må være et heltall")
            value = int(cleaned)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int):
            raise ValueError("må være et heltall")
        if attr.min is not None and value < attr.min:
            raise ValueError(f"må være minst {attr.min}")
        if attr.max is not None and value > attr.max:
            raise ValueError(f"kan være maks {attr.max}")
        return value
    if attr.type == "enum":
        text = str(value).strip()
        for option in attr.options:
            if text == option.value or text.lower() in (option.value.lower(), option.label.lower()):
                return option.value
        allowed = ", ".join(f"{o.value} ({o.label})" for o in attr.options)
        raise ValueError(f"ugyldig verdi {text!r}. Gyldige verdier: {allowed}")
    if attr.type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError("må være true eller false")
    if attr.type == "date":
        try:
            return date.fromisoformat(str(value).strip()[:10]).isoformat()
        except ValueError:
            raise ValueError("må være en dato på formen ÅÅÅÅ-MM-DD") from None
    text = " ".join(str(value).split())
    if len(text) > attr.max_length:
        raise ValueError(f"kan ha maks {attr.max_length} tegn")
    return text


def validate_attributes(category: Category, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationProblem.field("attributes", "må være et objekt med nøkkel/verdi-par")
    clean: dict[str, Any] = {}
    errors = []
    for key, value in raw.items():
        attr = category.attribute(key)
        if attr is None:
            valid = ", ".join(a.key for a in category.attributes) or "(ingen)"
            errors.append(
                {
                    "field": f"attributes.{key}",
                    "message": f"Ukjent felt «{key}» for kategorien {category.name}. Gyldige felt: {valid}",
                }
            )
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            clean[key] = coerce_attribute(attr, value)
        except ValueError as exc:
            errors.append({"field": f"attributes.{key}", "message": f"{attr.label}: {exc}"})
    if errors:
        raise ValidationProblem.from_errors(
            errors, hint=f"Attribute schema for this category: GET /api/v1/categories/{category.slug}"
        )
    return clean


def resolve_county(value: str | None) -> str | None:
    """Accept a county slug or its Norwegian name ("Trøndelag")."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if text in COUNTIES:
        return text
    for county in COUNTIES.values():
        if county.name.lower() == text.lower():
            return county.slug
    raise ValidationProblem.field(
        "county",
        f"Ukjent fylke {text!r}.",
        hint=taxonomy.suggest(text, list(COUNTIES)) + " See GET /api/v1/counties.",
    )


def validate_listing(values: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a complete set of listing fields."""
    slug = str(values.get("category") or "").strip()
    category = taxonomy.get_category(slug)
    if category is None or not category.is_leaf:
        message = (
            f"{slug!r} er en hovedkategori; velg en underkategori."
            if category
            else f"Ukjent kategori {slug!r}."
        )
        raise ValidationProblem.field(
            "category", message, hint=taxonomy.suggest_category(slug, leaf_only=True)
        )

    errors: list[dict[str, str]] = []

    def error(field_name: str, message: str) -> None:
        errors.append({"field": field_name, "message": message})

    listing_type = values.get("type") or category.types[0]
    if listing_type not in category.types:
        allowed = ", ".join(f"{t} ({LISTING_TYPES[t].label})" for t in category.types)
        error("type", f"Typen {listing_type!r} er ikke tillatt i {category.name}. Tillatt: {allowed}")

    title = " ".join(str(values.get("title") or "").split())
    if not 3 <= len(title) <= 120:
        error("title", "Overskriften må være mellom 3 og 120 tegn.")

    description = str(values.get("description") or "").replace("\r\n", "\n").strip()
    if not 10 <= len(description) <= 10_000:
        error("description", "Beskrivelsen må være mellom 10 og 10 000 tegn.")

    price = values.get("price")
    if isinstance(price, str):
        cleaned = re.sub(r"\s|kr|,-", "", price.strip().lower())
        price = int(cleaned) if cleaned.isdigit() else (None if cleaned == "" else price)
    if price is not None and (isinstance(price, bool) or not isinstance(price, int)):
        error("price", "Prisen må være et helt antall kroner.")
        price = None
    elif price is not None and not 0 <= price <= MAX_PRICE:
        error("price", "Prisen må være mellom 0 og 1 000 000 000 kr.")
    if listing_type == "give":
        price = 0
    elif listing_type == "job" and price is not None:
        error("price", "Stillingsannonser har ikke pris. Bruk feltet «Lønn» (attributes.salary).")

    price_unit = values.get("price_unit") or "total"
    if price_unit not in PRICE_UNITS:
        error("price_unit", f"Ugyldig prisenhet. Gyldige verdier: {', '.join(PRICE_UNITS)}")

    try:
        county = resolve_county(values.get("county"))
    except ValidationProblem as exc:
        errors.extend(exc.errors)
        county = None

    location = " ".join(str(values.get("location") or "").split()) or None
    if location and len(location) > 80:
        error("location", "Stedsnavnet kan ha maks 80 tegn.")

    postal_code = str(values.get("postal_code") or "").strip() or None
    if postal_code and not re.fullmatch(r"\d{4}", postal_code):
        error("postal_code", "Postnummeret må ha fire siffer.")
    elif postal_code and (place := postcodes.lookup(postal_code)):
        # A postal code is enough: the place and county come from the postal code register.
        location = location or place.place
        county = county or place.county

    try:
        attributes = validate_attributes(category, values.get("attributes"))
    except ValidationProblem as exc:
        errors.extend(exc.errors)
        attributes = {}

    if errors:
        raise ValidationProblem.from_errors(
            errors,
            hint=f"Field rules: GET /api/v1/categories/{category.slug} and the ListingCreate schema in /openapi.json",
        )
    return {
        "category": category.slug,
        "type": listing_type,
        "title": title,
        "description": description,
        "price": price,
        "price_unit": price_unit,
        "county": county,
        "location": location,
        "postal_code": postal_code,
        "attributes": attributes,
    }


# --- Storage ----------------------------------------------------------------------------------

_SELLER_COLUMNS = (
    "u.name AS seller_name, u.created_at AS seller_since, u.banned_at AS seller_banned_at, "
    "u.verified_at AS seller_verified_at, u.verified_via AS seller_verified_via"
)
_SELECT = f"SELECT l.*, {_SELLER_COLUMNS} FROM listings l JOIN users u ON u.id = l.user_id"


def _listing(row: sqlite3.Row) -> Listing:
    keys = row.keys()
    return Listing(
        id=row["id"],
        user_id=row["user_id"],
        category=row["category"],
        type=row["type"],
        title=row["title"],
        description=row["description"],
        price=row["price"],
        price_unit=row["price_unit"],
        county=row["county"],
        location=row["location"],
        postal_code=row["postal_code"],
        attributes=json.loads(row["attributes"] or "{}"),
        status=row["status"],
        created_via=row["created_via"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        seller_name=row["seller_name"],
        seller_since=row["seller_since"],
        risk_score=row["risk_score"],
        risk_flags=json.loads(row["risk_flags"] or "[]"),
        reviewed_at=row["reviewed_at"],
        moderation_note=row["moderation_note"],
        seller_banned=bool(row["seller_banned_at"]),
        seller_verified=bool(row["seller_verified_at"]),
        seller_verified_via=row["seller_verified_via"] if row["seller_verified_at"] else None,
        rank=row["rank"] if "rank" in keys else None,
        saved_price=row["saved_price"] if "saved_price" in keys else None,
        views=row["views"] if "views" in keys else 0,
        source=row["source"],
        source_id=row["source_id"],
        source_url=row["source_url"],
        apply_url=row["apply_url"],
        expires_at=row["expires_at"],
        deletion_notice_at=row["deletion_notice_at"],
    )


def _attach_images(conn: sqlite3.Connection, listings: list[Listing]) -> None:
    if not listings:
        return
    by_id = {listing.id: listing for listing in listings}
    marks = ",".join("?" * len(by_id))
    rows = conn.execute(
        f"SELECT * FROM listing_images WHERE listing_id IN ({marks}) ORDER BY listing_id, position, id",
        list(by_id),
    ).fetchall()
    for r in rows:
        by_id[r["listing_id"]].images.append(
            Image(
                r["id"],
                r["listing_id"],
                r["filename"],
                r["content_type"],
                r["alt_text"],
                r["position"],
                r["width"],
                r["height"],
            )
        )


_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")


def filter_tag(kind: str, slug: str) -> str:
    """A word in search_meta that only filters use: the slug written in private-use characters, which
    never occur in real text. The index finds it from a few rare trigrams, so the full-text query can apply
    the county ("f") or category ("k") filter itself at almost no cost."""
    base = {"f": 0xE000, "k": 0xE100}[kind]
    return chr(base + 0xFF) + "".join(chr(base + ord(char)) for char in slug) + chr(base + 0xFF)


def search_meta(values: dict[str, Any]) -> str:
    """Extra searchable text (listings.search_meta): category names in Norwegian and English, the place and
    attribute values, and filter tags for the county and the category (see filter_tag)."""
    category = taxonomy.CATEGORIES.get(values["category"])
    group = taxonomy.CATEGORIES.get(category.group) if category else None
    listing_type = LISTING_TYPES.get(values["type"])
    county = COUNTIES.get(values.get("county") or "")
    parts: list[Any] = [
        category and category.name,
        category and category.name_en,
        group and group.name,
        group and group.name_en,
        listing_type and listing_type.label,
        county and county.name,
        values.get("location"),
        values.get("postal_code"),
    ]
    for key, value in (values.get("attributes") or {}).items():
        attr = ATTRIBUTES.get(key)
        if attr is None:
            continue
        parts.append(attr.display(value))
        if attr.type == "enum":
            parts.append(str(value).replace("_", " "))
    words = [" ".join(_PRIVATE_USE.sub("", str(part)).split()) for part in parts if part]
    tags = [filter_tag("k", values["category"])] + ([filter_tag("f", values["county"])] if county else [])
    return " ".join([word for word in words if word] + tags)


def refresh_search_meta(conn: sqlite3.Connection) -> int:
    """Recompute search_meta for every listing (after changes to the taxonomy). Returns how many changed."""
    changed = 0
    last_id = 0
    while True:
        rows = conn.execute(
            "SELECT id, category, type, county, location, postal_code, attributes, search_meta FROM listings "
            "WHERE id > ? ORDER BY id LIMIT 1000",
            (last_id,),
        ).fetchall()
        if not rows:
            return changed
        updates = []
        for row in rows:
            try:
                attributes = json.loads(row["attributes"] or "{}")
            except ValueError:
                attributes = {}
            meta = search_meta(
                {**dict(row), "attributes": attributes if isinstance(attributes, dict) else {}}
            )
            if meta != row["search_meta"]:
                updates.append((meta, row["id"]))
        conn.executemany("UPDATE listings SET search_meta = ? WHERE id = ?", updates)
        changed += len(updates)
        last_id = rows[-1]["id"]


def fetch(
    conn: sqlite3.Connection, tail: str, args: Iterable[Any] = (), *, columns: str = ""
) -> list[Listing]:
    """Listings with seller fields and images: `SELECT ... FROM listings l JOIN users u` + tail
    (further joins, WHERE, ORDER BY, LIMIT). `columns` adds columns from those joins."""
    select = f"SELECT l.*, {_SELLER_COLUMNS}{', ' + columns if columns else ''} FROM listings l JOIN users u ON u.id = l.user_id"
    items = [_listing(row) for row in conn.execute(f"{select} {tail}", list(args))]
    _attach_images(conn, items)
    return items


def newest_id(conn: sqlite3.Connection) -> int:
    """The highest listing id handed out so far (ids are never reused)."""
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'listings'").fetchone()
    return int(row["seq"]) if row else 0


def newest_seq(conn: sqlite3.Connection) -> int:
    """Listings published from now on get a higher public_seq than this (see SCHEMA_V4)."""
    row = conn.execute("SELECT MAX(public_seq) FROM listings").fetchone()
    return max(row[0] or 0, newest_id(conn))


def get_listing(conn: sqlite3.Connection, listing_id: int) -> Listing:
    row = conn.execute(f"{_SELECT} WHERE l.id = ?", (listing_id,)).fetchone()
    if row is None:
        raise NotFound(f"Annonse {listing_id} finnes ikke.")
    listing = _listing(row)
    _attach_images(conn, [listing])
    stats = conn.execute(
        "SELECT SUM(status = 'active') AS active, SUM(status = 'sold') AS sold FROM listings WHERE user_id = ?",
        (listing.user_id,),
    ).fetchone()
    listing.seller_active, listing.seller_sold = stats["active"] or 0, stats["sold"] or 0
    from .ratings import summary  # ratings builds on this module

    listing.seller_rating = summary(conn, listing.user_id)
    return listing


def get_visible_listing(
    conn: sqlite3.Connection, listing_id: int, viewer_id: int | None = None, is_admin: bool = False
) -> Listing:
    """A listing as a given viewer may see it: hidden listings only for their owner."""
    listing = get_listing(conn, listing_id)
    if not listing.is_public and listing.user_id != viewer_id and not is_admin:
        raise NotFound(f"Annonse {listing_id} finnes ikke.")
    return listing


def check_owner(listing: Listing, user_id: int, is_admin: bool) -> None:
    if listing.user_id != user_id and not is_admin:
        raise Forbidden("Du kan bare endre dine egne annonser.")


def _check_owner_status(listing: Listing, status: str | None, is_admin: bool) -> None:
    """Owners choose between active, sold and inactive; review and removal belong to moderators."""
    if is_admin:
        if status is not None and status not in STATUSES:
            raise ValidationProblem.field("status", f"Ugyldig status. Gyldige verdier: {', '.join(STATUSES)}")
        return
    if listing.status == "removed":
        raise Forbidden(
            "Annonsen er fjernet av en moderator og kan ikke endres.",
            hint="Removed listings can only be deleted by their owner.",
        )
    if status is None:
        return
    if status not in OWNER_STATUSES:
        raise ValidationProblem.field(
            "status", f"Ugyldig status. Gyldige verdier: {', '.join(OWNER_STATUSES)}"
        )
    if listing.status == "review" and status != "inactive":
        raise Forbidden(
            "Annonsen er til kontroll hos en moderator og blir synlig når den er godkjent.",
            hint="Listings in review are published by a moderator; you can still edit or delete them.",
        )


def _quota(conn: sqlite3.Connection, user_id: int, max_per_day: int, new_account_max: int | None) -> None:
    row = conn.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    limit = max_per_day
    if new_account_max is not None and row and row["created_at"] > iso_ago(days=1):
        limit = min(limit, new_account_max)
    recent = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE user_id = ? AND created_at > ?", (user_id, iso_ago(days=1))
    ).fetchone()[0]
    if recent >= limit:
        raise RateLimited(
            f"Du har opprettet {recent} annonser siste døgn (maks {limit}). Prøv igjen senere.",
            retry_after=3600,
            hint="The daily listing quota protects the free service against spam; new accounts get a lower quota.",
        )


def create_listing(
    conn: sqlite3.Connection,
    user_id: int,
    data: dict[str, Any],
    *,
    via: str = "web",
    max_per_day: int = 50,
    new_account_max_per_day: int | None = None,
    active_days: int = 60,
) -> int:
    """Create a listing. Listings with strong fraud signals start in status "review".

    It is active for `active_days` (0 = no end); then it is hidden until the owner renews it.
    """
    values = validate_listing(data)
    status = data.get("status") or "active"
    if status not in OWNER_STATUSES:
        raise ValidationProblem.field(
            "status", f"Ugyldig status. Gyldige verdier: {', '.join(OWNER_STATUSES)}"
        )
    with transaction(conn):
        _quota(conn, user_id, max_per_day, new_account_max_per_day)
        assessment, fingerprint = fraud.assess_listing(conn, user_id, values)
        if assessment.needs_review:
            status = "review"
        now = now_iso()
        cursor = conn.execute(
            "INSERT INTO listings (user_id, category, type, title, description, price, price_unit, county, "
            "location, postal_code, attributes, status, created_via, created_at, updated_at, risk_score, "
            "risk_flags, text_hash, expires_at, search_meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                values["category"],
                values["type"],
                values["title"],
                values["description"],
                values["price"],
                values["price_unit"],
                values["county"],
                values["location"],
                values["postal_code"],
                json.dumps(values["attributes"], ensure_ascii=False),
                status,
                via if via in CHANNELS else "web",
                now,
                now,
                assessment.score,
                json.dumps(assessment.codes),
                fingerprint,
                iso_in(days=active_days) if active_days else None,
                search_meta(values),
            ),
        )
        listing_id = cursor.lastrowid
        assert listing_id is not None
    forget_counts()
    return listing_id


def update_listing(
    conn: sqlite3.Connection,
    user_id: int,
    listing_id: int,
    changes: dict[str, Any],
    *,
    merge_attributes: bool = True,
    is_admin: bool = False,
    active_days: int = 60,
) -> Listing:
    """Apply a partial update. Attributes are merged (null removes a key) unless merge_attributes=False.

    The changed listing is assessed again; new strong fraud signals send it back to review.
    """
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    changes = dict(changes)
    status = changes.pop("status", None)
    _check_owner_status(listing, status, is_admin)
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationProblem.field(
            sorted(unknown)[0],
            "Feltet kan ikke endres.",
            hint=f"Editable fields: {', '.join(EDITABLE_FIELDS)}, status",
        )
    values = {name: getattr(listing, name) for name in EDITABLE_FIELDS}
    if "attributes" in changes:
        incoming = changes.pop("attributes") or {}
        if not isinstance(incoming, dict):
            raise ValidationProblem.field("attributes", "må være et objekt med nøkkel/verdi-par")
        if merge_attributes:
            merged = dict(listing.attributes)
            for key, value in incoming.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
            values["attributes"] = merged
        else:
            values["attributes"] = incoming
    old_place = postcodes.lookup(listing.postal_code)
    values.update(changes)
    new_place = postcodes.lookup(values.get("postal_code"))
    if old_place and new_place and new_place != old_place:
        if values.get("location") == old_place.place:
            values["location"] = None
        if values.get("county") == old_place.county:
            values["county"] = None
    clean = validate_listing(values)
    new_status = status or listing.status
    with transaction(conn):
        assessment, fingerprint = fraud.assess_listing(conn, listing.user_id, clean, listing_id)
        # A moderator-approved listing only goes back to review if it got riskier.
        riskier = listing.reviewed_at is None or assessment.score > listing.risk_score
        if assessment.needs_review and riskier and new_status in OWNER_STATUSES and not is_admin:
            new_status = "review"
        conn.execute(
            "UPDATE listings SET category = ?, type = ?, title = ?, description = ?, price = ?, price_unit = ?, "
            "county = ?, location = ?, postal_code = ?, attributes = ?, status = ?, updated_at = ?, "
            "risk_score = ?, risk_flags = ?, text_hash = ?, search_meta = ? WHERE id = ?",
            (
                clean["category"],
                clean["type"],
                clean["title"],
                clean["description"],
                clean["price"],
                clean["price_unit"],
                clean["county"],
                clean["location"],
                clean["postal_code"],
                json.dumps(clean["attributes"], ensure_ascii=False),
                new_status,
                now_iso(),
                assessment.score,
                json.dumps(assessment.codes),
                fingerprint,
                search_meta(clean),
                listing_id,
            ),
        )
        if status == "active":
            _renew(conn, listing, active_days)
    forget_counts()
    return get_listing(conn, listing_id)


def _renew(conn: sqlite3.Connection, listing: Listing, active_days: int) -> None:
    """Setting a listing active again starts a new period (imported listings follow their source)."""
    if not listing.is_imported:
        conn.execute(
            "UPDATE listings SET expires_at = ? WHERE id = ?",
            (iso_in(days=active_days) if active_days else None, listing.id),
        )


def set_status(
    conn: sqlite3.Connection,
    user_id: int,
    listing_id: int,
    status: str,
    is_admin: bool = False,
    active_days: int = 60,
) -> None:
    """Change the status. Setting "active" on an active listing renews it for another period."""
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    _check_owner_status(listing, status, is_admin)
    if listing.status == "review" and not is_admin:
        return  # hiding a listing that is not public yet changes nothing
    with transaction(conn):
        conn.execute(
            "UPDATE listings SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), listing_id)
        )
        if status == "active":
            _renew(conn, listing, active_days)
    forget_counts()


def expire_listings(conn: sqlite3.Connection) -> list[Listing]:
    """Hide listings whose period is over. Returns them, so their owners can be told."""
    rows = conn.execute(
        # "+l.status": find them through the index of end times, not by reading every active listing.
        f"{_SELECT} WHERE l.source IS NULL AND +l.status = 'active' AND l.expires_at IS NOT NULL "
        "AND l.expires_at < ?",
        (now_iso(),),
    ).fetchall()
    expired = [_listing(row) for row in rows]
    if expired:
        with transaction(conn):
            for listing in expired:
                conn.execute(
                    "UPDATE listings SET status = 'inactive', updated_at = ? WHERE id = ?",
                    (now_iso(), listing.id),
                )
    return expired


# Old listings are deleted automatically (Settings.delete_after_days). A listing that is not active (hidden,
# sold, in review or removed) and has not changed for that long, less the notice period, is marked and its
# owner told; DELETION_NOTICE_DAYS later it is deleted with its photos. Any change before then, such as
# renewing it, cancels the deletion (see SCHEMA_V6). Imported and synced listings follow their source.
DELETION_NOTICE_DAYS = 14
DELETION_BATCH = 500  # per maintenance round, so a backlog never makes one round slow


def mark_for_deletion(conn: sqlite3.Connection, delete_after_days: int) -> list[Listing]:
    """Mark the listings whose time is nearly up. Returns them, so their owners can be told."""
    now = now_iso()
    with transaction(conn):  # finding and marking in one go: a listing renewed meanwhile is never marked
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM listings INDEXED BY idx_listings_idle WHERE status <> 'active' AND source IS NULL "
                "AND feed IS NULL AND updated_at < ? AND deletion_notice_at IS NULL ORDER BY updated_at LIMIT ?",
                (iso_ago(days=delete_after_days - DELETION_NOTICE_DAYS), DELETION_BATCH),
            )
        ]
        conn.executemany("UPDATE listings SET deletion_notice_at = ? WHERE id = ?", [(now, i) for i in ids])
    if not ids:
        return []
    return fetch(conn, f"WHERE l.id IN ({','.join('?' * len(ids))}) ORDER BY l.id", ids)


def delete_marked_listings(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """Delete the marked listings whose notice period is over.

    Returns how many, and the image files the caller should remove from disk. Conversations about them stay,
    as when the owner deletes one.
    """
    with transaction(conn):  # finding and deleting in one go: a listing renewed meanwhile is kept
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM listings WHERE deletion_notice_at < ? AND status <> 'active' "
                "ORDER BY deletion_notice_at LIMIT ?",
                (iso_ago(days=DELETION_NOTICE_DAYS), DELETION_BATCH),
            )
        ]
        marks = ",".join("?" * len(ids))
        filenames = [
            row["filename"]
            for row in conn.execute(f"SELECT filename FROM listing_images WHERE listing_id IN ({marks})", ids)
        ]
        conn.execute(f"DELETE FROM listings WHERE id IN ({marks})", ids)  # triggers update the search index
    return len(ids), filenames


def cancel_deletions(conn: sqlite3.Connection) -> int:
    """Unmark every listing, when automatic deletion has been turned off."""
    return conn.execute(
        "UPDATE listings SET deletion_notice_at = NULL WHERE deletion_notice_at IS NOT NULL"
    ).rowcount


def add_risk_flag(conn: sqlite3.Connection, listing_id: int, code: str) -> bool:
    """Add a signal found outside the text (e.g. a reused image). Returns True if the listing went to review."""
    listing = get_listing(conn, listing_id)
    if code in listing.risk_flags:
        return False
    codes = [*listing.risk_flags, code]
    assessment = fraud.Assessment(codes)
    to_review = assessment.needs_review and listing.status in OWNER_STATUSES
    conn.execute(
        "UPDATE listings SET risk_flags = ?, risk_score = ?, status = ? WHERE id = ?",
        (json.dumps(codes), assessment.score, "review" if to_review else listing.status, listing_id),
    )
    return to_review


def delete_listing(
    conn: sqlite3.Connection, user_id: int, listing_id: int, is_admin: bool = False
) -> list[str]:
    """Delete a listing. Returns the image filenames that the caller should remove from disk."""
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))  # a trigger removes it from the index
    forget_counts()
    return [image.filename for image in listing.images]


# Active listings per category, for the front page and the search page. Counting a million listings takes
# about a tenth of a second, so the numbers are kept for a minute. Meanwhile one request counts again while
# the others use the previous numbers. On a small site counting is quick, and the numbers are counted again
# after every change this process makes, so a new listing shows at once.
COUNTS_SECONDS = 60.0
QUICK_COUNT_SECONDS = 0.01
_counts: dict[str, tuple[float, float, dict[str, int]]] = {}  # file -> (counted at, seconds it took, counts)
_counting: set[str] = set()
_counts_lock = threading.Lock()


def _database_file(conn: sqlite3.Connection) -> str:
    return conn.execute("PRAGMA database_list").fetchone()["file"]


def forget_counts() -> None:
    with _counts_lock:
        for key in [key for key, (_, took, _) in _counts.items() if took < QUICK_COUNT_SECONDS]:
            del _counts[key]


def category_counts(conn: sqlite3.Connection) -> dict[str, int]:
    key = _database_file(conn)
    with _counts_lock:
        cached = _counts.get(key)
        if cached and (time.monotonic() - cached[0] < COUNTS_SECONDS or key in _counting):
            return dict(cached[2])
        _counting.add(key)
    try:
        started = time.monotonic()
        rows = conn.execute(
            f"SELECT category, COUNT(*) AS n FROM listings l WHERE l.status = 'active' AND {SELLER_OK} "
            "GROUP BY category"
        )
        counts = {r["category"]: r["n"] for r in rows}
        for group in taxonomy.GROUPS:
            counts[group] = sum(counts.get(c, 0) for c in taxonomy.CATEGORIES[group].children)
        with _counts_lock:
            _counts[key] = (started, time.monotonic() - started, counts)
    finally:
        with _counts_lock:
            _counting.discard(key)
    return dict(counts)


def create_report(
    conn: sqlite3.Connection,
    listing_id: int | None,
    reason: str,
    comment: str | None,
    reporter_id: int | None,
    via: str = "web",
    *,
    reported_user_id: int | None = None,
    conversation_id: int | None = None,
) -> int:
    """Report a listing (or a user in a conversation). Enough reports hide a listing until reviewed."""
    if listing_id is not None:
        listing = get_listing(conn, listing_id)
        reported_user_id = reported_user_id or listing.user_id
    if reason not in REPORT_REASONS:
        raise ValidationProblem.field(
            "reason", "Ugyldig grunn.", hint=f"Valid reasons: {', '.join(REPORT_REASONS)}"
        )
    comment = (comment or "").strip()[:2000] or None
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO reports (listing_id, reported_user_id, conversation_id, reporter_id, reason, comment, "
            "created_via, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (listing_id, reported_user_id, conversation_id, reporter_id, reason, comment, via, now_iso()),
        )
    if listing_id is not None and conversation_id is None:
        reporters = conn.execute(
            "SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE listing_id = ? AND resolved_at IS NULL "
            "AND reporter_id IS NOT NULL",
            (listing_id,),
        ).fetchone()[0]
        if reporters >= fraud.AUTO_REVIEW_REPORTS:
            add_risk_flag(conn, listing_id, "reported")
    return cursor.lastrowid  # type: ignore[return-value]


# --- Search -----------------------------------------------------------------------------------
#
# A search does a bounded amount of work however many listings there are, so a small server copes with
# millions of them:
#
# * The ids on a page come from a covering index (or, for words, from the full-text index newest first) and
#   the query stops as soon as the page is full. Only the listings on the page are read in full.
# * Matches are counted up to COUNT_LIMIT. Above that the total reads "over 1 000" (more than 40 pages).
# * To count a word search, at most the SCAN_LIMIT newest hits for the words are looked at; if there are
#   more, the total reads "minst 2 300". Filters the full-text index can apply itself (county, category,
#   place, id ranges) are part of the full-text query, so they never use up that budget; other filters
#   only matter when a very common word meets a very narrow filter. Pages always show every match.
# * "Mest relevant" puts listings with all the words in the title, category, place or properties first,
#   newest first, then the rest. Among very common words it does this for the RANKED_HITS newest hits.

SORTS = {
    "relevance": "Mest relevant",
    "newest": "Nyeste først",
    "oldest": "Eldste først",
    "price_asc": "Lavest pris",
    "price_desc": "Høyest pris",
}
SEARCH_STATUSES = ("active", "sold", "any")
MAX_LIMIT = 100
MAX_OFFSET = 1_000_000
MAX_ATTR_FILTERS = 20
MAX_SQL_INT = 2**63 - 1  # the largest number SQLite stores
COUNT_LIMIT = 1_000
SCAN_LIMIT = 20_000
RANKED_HITS = 2_000
# Listings of closed accounts are hidden. Few accounts are closed, and a partial index lists them.
SELLER_OK = "l.user_id NOT IN (SELECT id FROM users WHERE banned_at IS NOT NULL)"


@dataclass
class AttrFilter:
    key: str
    values: list[Any] | None = None
    min: Any = None
    max: Any = None

    def to_expression(self) -> str:
        """Back to the compact `attr=` syntax used by the API."""
        if self.values is not None:
            return f"{self.key}:{','.join(_format_filter_value(v) for v in self.values)}"
        low = "" if self.min is None else _format_filter_value(self.min)
        high = "" if self.max is None else _format_filter_value(self.max)
        return f"{self.key}:{low}..{high}"


def _format_filter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass
class SearchParams:
    q: str | None = None
    category: str | None = None
    type: str | None = None
    county: str | None = None
    location: str | None = None
    price_min: int | None = None
    price_max: int | None = None
    attrs: list[AttrFilter] = field(default_factory=list)
    user_id: int | None = None
    status: str = "active"
    updated_since: str | None = None
    has_images: bool = False
    sort: str | None = None
    limit: int = 20
    offset: int = 0
    include_hidden: bool = False  # allows status "inactive"/"all"; owner views only, never from public input
    include_imported: bool = True  # False leaves out listings imported from open sources
    after_id: int | None = None  # only listings with a higher id, i.e. added after that one (ids only grow)
    # Saved searches: only listings that became public after this point in the order of publishing
    # (public_seq), and not after up_to_seq. A draft or a listing that waited for review counts from
    # when it was published.
    after_seq: int | None = None
    up_to_seq: int | None = None
    exclude_user_id: int | None = None  # leave out this person's own listings

    @property
    def effective_sort(self) -> str:
        if self.sort and self.sort != "relevance":
            return self.sort
        return "relevance" if self.q and self.q.strip() else "newest"


@dataclass
class SearchResult:
    items: list[Listing]
    total: int  # 0 when the caller did not ask for a count
    params: SearchParams
    total_exact: bool = True  # False: there are at least `total` matches (see COUNT_LIMIT and SCAN_LIMIT)
    has_more: bool = False  # more matches after this page

    def total_label(self, sep: str = " ") -> str:
        """The total for people: "123", or "over 1 000" and "minst 230" when not every match was counted."""
        number = format_number(self.total, sep)
        if self.total_exact:
            return number
        return f"over {number}" if self.total >= COUNT_LIMIT else f"minst {number}"


def _attr_error(message: str) -> ValidationProblem:
    return ValidationProblem.field(
        "attr",
        message,
        hint="Use attr=key:value, attr=key:v1,v2 or attr=key:min..max. Keys: GET /api/v1/categories/{slug}",
    )


def _filter_attribute(key: str) -> Attribute:
    attr = ATTRIBUTES.get(key)
    if attr is None:
        raise _attr_error(f"Ukjent attributt {key!r}. {taxonomy.suggest(key, sorted(ATTRIBUTES))}")
    return attr


def _coerce_filter(attr: Attribute, raw: Any) -> Any:
    try:
        return coerce_attribute(attr, raw)
    except ValueError as exc:
        raise _attr_error(f"{attr.key}: {exc}") from None


def parse_attr_expression(expression: str) -> AttrFilter:
    """Parse `key:value`, `key:v1,v2`, `key:min..max`, `key:min..` or `key:..max`."""
    key, sep, rest = expression.partition(":")
    key = key.strip()
    if not sep or not key or not rest.strip():
        raise _attr_error(f"Ugyldig attributtfilter {expression!r}.")
    attr = _filter_attribute(key)
    rest = rest.strip()
    if ".." in rest and attr.type in ("integer", "date"):
        low, _, high = rest.partition("..")
        return AttrFilter(
            key,
            min=_coerce_filter(attr, low) if low.strip() else None,
            max=_coerce_filter(attr, high) if high.strip() else None,
        )
    return AttrFilter(key, values=[_coerce_filter(attr, part) for part in rest.split(",") if part.strip()])


def attr_filters_from_params(items: Iterable[tuple[str, str]]) -> list[AttrFilter]:
    """Collect filters from query parameters: `attr=...` plus form-style `a.key`, `a.key.min`, `a.key.max`."""
    filters: list[AttrFilter] = []
    ranges: dict[str, AttrFilter] = {}
    for name, value in items:
        if not value or not value.strip():
            continue
        if name == "attr":
            filters.append(parse_attr_expression(value))
        elif name.startswith("a."):
            parts = name[2:].split(".")
            attr = _filter_attribute(parts[0])
            if len(parts) == 2 and parts[1] in ("min", "max") and attr.type in ("integer", "date"):
                entry = ranges.setdefault(attr.key, AttrFilter(attr.key))
                setattr(entry, parts[1], _coerce_filter(attr, value))
            elif len(parts) == 1:
                filters.append(AttrFilter(attr.key, values=[_coerce_filter(attr, value)]))
    return filters + list(ranges.values())


def attr_filters_from_object(obj: dict[str, Any] | None) -> list[AttrFilter]:
    """MCP style: {"fuel": "electric", "make": ["Volvo", "Tesla"], "year": {"min": 2018}}."""
    filters = []
    for key, spec in (obj or {}).items():
        attr = _filter_attribute(key)
        if isinstance(spec, dict):
            unknown = set(spec) - {"min", "max"}
            if unknown or not spec:
                raise _attr_error(f'{key}: bruk {{"min": ..., "max": ...}} for intervaller.')
            filters.append(
                AttrFilter(
                    key,
                    min=_coerce_filter(attr, spec["min"]) if spec.get("min") is not None else None,
                    max=_coerce_filter(attr, spec["max"]) if spec.get("max") is not None else None,
                )
            )
        elif isinstance(spec, list):
            filters.append(AttrFilter(key, values=[_coerce_filter(attr, v) for v in spec]))
        elif spec is not None:
            filters.append(AttrFilter(key, values=[_coerce_filter(attr, spec)]))
    return filters


def validate_search(params: SearchParams) -> SearchParams:
    if params.category and params.category not in taxonomy.CATEGORIES:
        raise ValidationProblem.field(
            "category",
            f"Ukjent kategori {params.category!r}.",
            hint=taxonomy.suggest_category(params.category),
        )
    if params.type and params.type not in LISTING_TYPES:
        raise ValidationProblem.field(
            "type", f"Ukjent annonsetype {params.type!r}.", hint=f"Valid types: {', '.join(LISTING_TYPES)}"
        )
    if params.county:
        params.county = resolve_county(params.county)
    if params.sort and params.sort not in SORTS:
        raise ValidationProblem.field(
            "sort", f"Ukjent sortering {params.sort!r}.", hint=f"Valid: {', '.join(SORTS)}"
        )
    allowed = SEARCH_STATUSES + (("inactive", "review", "removed", "all") if params.include_hidden else ())
    if params.status not in allowed:
        raise ValidationProblem.field(
            "status", f"Ukjent status {params.status!r}.", hint=f"Valid: {', '.join(allowed)}"
        )
    if params.updated_since:
        try:
            params.updated_since = to_iso(parse_iso(params.updated_since))
        except ValueError:
            raise ValidationProblem.field(
                "updated_since", "Ugyldig tidspunkt.", hint="Use ISO 8601, e.g. 2026-10-01T12:00:00Z"
            ) from None
    for key in ("price_min", "price_max"):
        value = getattr(params, key)
        if value is not None and not 0 <= value <= MAX_PRICE:
            raise ValidationProblem.field(
                key,
                f"Prisen må være mellom 0 og {format_number(MAX_PRICE)} kr.",
                hint="Leave it out for no limit.",
            )
    if params.user_id is not None and not 0 <= params.user_id <= MAX_SQL_INT:
        raise ValidationProblem.field("seller_id", "Ukjent selger.")
    if len(params.attrs) > MAX_ATTR_FILTERS:
        raise _attr_error(f"Maks {MAX_ATTR_FILTERS} attributtfiltre per søk.")
    for flt in params.attrs:
        for value in [*(flt.values or []), flt.min, flt.max]:
            if isinstance(value, int) and not -MAX_SQL_INT <= value <= MAX_SQL_INT:
                raise _attr_error(f"{flt.key}: tallet er for stort.")
    params.limit = max(1, min(int(params.limit), MAX_LIMIT))
    params.offset = max(0, min(int(params.offset), MAX_OFFSET))
    for key in ("after_id", "after_seq", "up_to_seq"):
        value = getattr(params, key)
        if value is not None:
            setattr(params, key, max(0, min(int(value), MAX_SQL_INT)))
    return params


def _int_param(value: str | None, high: int = MAX_SQL_INT) -> int | None:
    """A whole number from a URL, or None if it is missing, not a number or out of range."""
    try:
        number = int(value) if value not in (None, "") else None
    except ValueError:
        return None
    return number if number is None or 0 <= number <= high else None


def params_from_query(pairs: Iterable[tuple[str, str]], *, limit: int = 20) -> SearchParams:
    """Search parameters from /sok-style query parameters. Lenient, for URLs people share and saved
    searches: invalid values are left out instead of failing."""
    items = list(pairs)
    values: dict[str, str] = {}
    attrs: list[AttrFilter] = []
    for name, value in items:
        if name == "attr" or name.startswith("a."):
            try:
                found = attr_filters_from_params([(name, value)])
                validate_search(SearchParams(attrs=found))  # e.g. numbers SQLite cannot hold
            except ValidationProblem:
                continue
            attrs.extend(found)
        else:
            values[name] = value  # the last one wins, as in Starlette's query_params
    qp = values.get
    return SearchParams(
        q=" ".join((qp("q") or "").split()) or None,
        category=qp("category") if qp("category") in taxonomy.CATEGORIES else None,
        type=qp("type") if qp("type") in LISTING_TYPES else None,
        county=qp("county") if qp("county") in COUNTIES else None,
        location=" ".join((qp("location") or "").split())[:80] or None,
        price_min=_int_param(qp("price_min"), MAX_PRICE),
        price_max=_int_param(qp("price_max"), MAX_PRICE),
        attrs=attrs[:MAX_ATTR_FILTERS],
        user_id=_int_param(qp("seller_id")),
        status=qp("status") if qp("status") in SEARCH_STATUSES else "active",
        has_images=qp("has_images") in ("1", "true", "on"),
        sort=qp("sort") if qp("sort") in SORTS else None,
        limit=limit,
    )


_TOKEN_RE = re.compile(r"[\w][\w\-./+]*", re.UNICODE)
# Short function words filter nothing useful ("vi søker", "sofa og bord"), so they are ignored.
_SHORT_STOPWORDS = {
    "og",
    "i",
    "på",
    "en",
    "et",
    "er",
    "av",
    "vi",
    "du",
    "de",
    "om",
    "så",
    "å",
    "at",
    "ei",
    "eg",
}


def search_terms(q: str) -> list[str]:
    """The words of a search, case-folded, without short function words and repeats."""
    terms: list[str] = []
    for token in _TOKEN_RE.findall(q.casefold()):
        token = token.strip("-./+")
        if token and token not in _SHORT_STOPWORDS and token not in terms:
            terms.append(token)
    return terms


def _phrase(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _word_query(term: str) -> str:
    """One word as an FTS5 trigram query. From three letters it matches anywhere, so "sofa" finds
    "hjørnesofa". A shorter word must start or end a word (every indexed text has a space on both sides)."""
    if len(term) >= 3:
        return _phrase(term)
    if len(term) == 2:
        return f"({_phrase(' ' + term)} OR {_phrase(term + ' ')})"
    return _phrase(f" {term} ")


def build_fts_query(q: str) -> str | None:
    """Free text as an FTS5 query that every word must match, or None if there is nothing to search for."""
    return " AND ".join(_word_query(term) for term in search_terms(q)) or None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _place_filter(location: str) -> tuple[str, str]:
    """The place filter as (full-text query on meta, LIKE pattern for ' ' || casefold(location)). From three
    letters it matches anywhere in the place; shorter text must start a word, so "ås" finds Ås, not Kvås."""
    text = location.strip().casefold()
    if len(text) >= 3:
        return _phrase(text), f"%{_escape_like(text)}%"
    return _phrase(" " + text), f"% {_escape_like(text)}%"


def _conditions(params: SearchParams) -> tuple[list[str], list[Any]]:
    """SQL conditions on listings `l` for everything except the words."""
    conditions: list[str] = []
    args: list[Any] = []
    if params.status == "any":
        conditions.append("l.status IN ('active', 'sold')")
    elif params.status != "all":  # "all" (incl. hidden) is only accepted for owners, see validate_search
        conditions.append("l.status = ?")
        args.append(params.status)
    if not params.include_hidden:
        conditions.append(SELLER_OK)
    if params.category:
        slugs = taxonomy.descendants(params.category)
        conditions.append(f"l.category IN ({','.join('?' * len(slugs))})")
        args.extend(slugs)
    if params.type:
        conditions.append("l.type = ?")
        args.append(params.type)
    if params.county:
        conditions.append("l.county = ?")
        args.append(params.county)
    if params.location and params.location.strip():
        conditions.append("(' ' || casefold(l.location)) LIKE ? ESCAPE '\\'")
        args.append(_place_filter(params.location)[1])
    if params.price_min is not None:
        conditions.append("l.price >= ?")
        args.append(params.price_min)
    if params.price_max is not None:
        conditions.append("l.price <= ?")
        args.append(params.price_max)
    if params.user_id is not None:
        conditions.append("l.user_id = ?")
        args.append(params.user_id)
    if params.updated_since:
        conditions.append("l.updated_at >= ?")
        args.append(params.updated_since)
    if params.has_images:
        conditions.append("EXISTS (SELECT 1 FROM listing_images i WHERE i.listing_id = l.id)")
    if not params.include_imported:
        conditions.append("l.source IS NULL")
    if params.after_id is not None:
        conditions.append("l.id > ?")
        args.append(params.after_id)
    if params.exclude_user_id is not None:
        conditions.append("l.user_id != ?")
        args.append(params.exclude_user_id)
    if params.after_seq is not None:
        conditions.append("l.public_seq > ?")
        args.append(params.after_seq)
    if params.up_to_seq is not None:
        conditions.append("l.public_seq <= ?")
        args.append(params.up_to_seq)
    for flt in params.attrs:
        attr = ATTRIBUTES[flt.key]  # keys were validated against the registry when parsed
        column = f"json_extract(l.attributes, '$.\"{flt.key}\"')"
        if flt.values:
            if attr.type == "string":
                column = f"casefold({column})"
                values = [str(v).casefold() for v in flt.values]
            else:
                values = [int(v) if isinstance(v, bool) else v for v in flt.values]
            conditions.append(f"{column} IN ({','.join('?' * len(values))})")
            args.extend(values)
        if flt.min is not None:
            conditions.append(f"{column} >= ?")
            args.append(flt.min)
        if flt.max is not None:
            conditions.append(f"{column} <= ?")
            args.append(flt.max)
    return conditions, args


def _full_text(params: SearchParams) -> tuple[str | None, str | None]:
    """(query for every hit, query for hits with all words in the title, category, place or properties).

    Both are None when neither words nor a place are searched for. Filters that the index can apply itself
    (county, category and place are in the meta column) are part of both queries: the SQL filters still
    decide, but the index no longer hands over hits that cannot pass them.
    """
    words = build_fts_query(params.q or "")
    place = params.location.strip() if params.location else ""
    if words is None and not place:
        return None, None
    narrowing = []
    if params.county:
        narrowing.append("{meta} : " + _phrase(filter_tag("f", params.county)))
    category = taxonomy.CATEGORIES.get(params.category or "")
    if category and category.is_leaf:  # a whole group (e.g. Torget) is too large to gain from it
        narrowing.append("{meta} : " + _phrase(filter_tag("k", category.slug)))
    if place:
        narrowing.append("{meta} : " + _place_filter(place)[0])
    every = " AND ".join(([f"({words})"] if words else []) + narrowing)
    best = " AND ".join([f"{{title meta}} : ({words})", *narrowing]) if words else None
    return every, best


Segment = tuple[str, list[Any]]


def _page(
    conn: sqlite3.Connection, segments: list[Segment], offset: int, limit: int
) -> tuple[list[int], bool]:
    """Ids [offset, offset + limit) of the segments' results one after the other, and whether more follow.
    Each segment is a query for listing ids in order; LIMIT and OFFSET are added here."""
    ids: list[int] = []
    wanted = limit + 1  # one more than fits on the page tells whether there is a next page
    for sql, args in segments:
        if wanted <= 0:
            break
        rows = conn.execute(f"{sql} LIMIT ? OFFSET ?", [*args, wanted, offset]).fetchall()
        if rows:
            ids += [row[0] for row in rows]
            wanted -= len(rows)
            offset = 0
        elif offset:  # the page starts after this segment: skip it
            offset -= conn.execute(f"SELECT COUNT(*) FROM ({sql} LIMIT ?)", [*args, offset]).fetchone()[0]
    return ids[:limit], len(ids) > limit


def _count(conn: sqlite3.Connection, sql: str, args: list[Any]) -> tuple[int, bool]:
    """How many rows `sql` gives, up to COUNT_LIMIT: (count, exact)."""
    found = conn.execute(f"SELECT COUNT(*) FROM ({sql} LIMIT {COUNT_LIMIT + 1})", args).fetchone()[0]
    return (COUNT_LIMIT, False) if found > COUNT_LIMIT else (found, True)


def _is_plain(params: SearchParams) -> bool:
    """A search for one category (or everything) and nothing else, which the cached counts answer."""
    numbers = (params.price_min, params.price_max, params.user_id, params.after_id, params.after_seq)
    return (
        params.status == "active"
        and not params.include_hidden
        and params.include_imported
        and not (params.q and build_fts_query(params.q))
        and not (params.type or params.county or params.location or params.updated_since or params.has_images)
        and not params.attrs
        and all(number is None for number in (*numbers, params.up_to_seq, params.exclude_user_id))
    )


def _browse(
    conn: sqlite3.Connection, params: SearchParams, where: str, args: list[Any], count: bool
) -> tuple[list[Segment], tuple[int, bool]]:
    """Searches without words: a covering index gives the ids in order."""
    total = (0, True)
    if count:
        if _is_plain(params):
            counts = category_counts(conn)
            groups = taxonomy.GROUPS
            plain = (
                counts.get(params.category, 0) if params.category else sum(counts.get(g, 0) for g in groups)
            )
            total = (plain, True)
        else:
            total = _count(conn, f"SELECT 1 FROM listings l WHERE {where}", args)
    sort = params.effective_sort
    if sort.startswith("price"):
        # Many matches with a price: walk the price index until the page is full. Few: find them through the
        # other filters and sort them ("+" keeps SQLite from walking the whole price index for a few).
        priced = _count(conn, f"SELECT 1 FROM listings l WHERE {where} AND +l.price IS NOT NULL", args)
        if not priced[1] and params.status == "active":
            select, price = (
                f"SELECT l.id FROM listings l INDEXED BY idx_listings_by_price WHERE {where}",
                "l.price",
            )
        else:
            select, price = f"SELECT l.id FROM listings l WHERE {where}", "+l.price"
        if sort == "price_asc":
            segments = [
                (f"{select} AND {price} IS NOT NULL ORDER BY {price}, l.id DESC", args),
                (
                    f"SELECT l.id FROM listings l WHERE {where} AND l.price IS NULL "
                    "ORDER BY l.created_at DESC, l.id DESC",
                    args,
                ),
            ]
        else:
            segments = [(f"{select} ORDER BY {price} DESC, l.id DESC", args)]
    else:
        order = "l.created_at, l.id" if sort == "oldest" else "l.created_at DESC, l.id DESC"
        segments = [(f"SELECT l.id FROM listings l WHERE {where} ORDER BY {order}", args)]
    return segments, total


def _hits(bounds: str, *, newest_first: bool, limit: int) -> str:
    """Full-text hits as a subquery that keeps its order (see _words)."""
    if newest_first and not bounds:
        return f"SELECT rowid AS id FROM listings_fts WHERE listings_fts MATCH ? ORDER BY rowid DESC LIMIT {limit}"
    # The index ignores a lower id bound when it reads newest first, so bounded ranges are read oldest first.
    return f"SELECT rowid AS id FROM listings_fts WHERE listings_fts MATCH ?{bounds} LIMIT {limit}"


def _many_hits(conn: sqlite3.Connection, bounds: str, hit_args: list[Any]) -> bool:
    """More hits than SCAN_LIMIT?"""
    more = f"SELECT 1 FROM listings_fts WHERE listings_fts MATCH ?{bounds} LIMIT 1 OFFSET {SCAN_LIMIT}"
    return conn.execute(more, hit_args).fetchone() is not None


def _words(
    conn: sqlite3.Connection,
    params: SearchParams,
    where: str,
    args: list[Any],
    every: str,
    best: str | None,
) -> tuple[list[Segment], tuple[int, bool], bool] | None:
    """Searches with words (or a place): the full-text index gives the hits, newest first.

    The matches among the SCAN_LIMIT newest hits go into a temporary table in memory, up to COUNT_LIMIT + 1
    of them: one statement that stops early when the words are common. That gives the count, and when
    there are few matches, the pages and the ranking read the table instead of the full-text index again.
    With many matches, pages read the hits from the index as they come: a subquery with ORDER BY and LIMIT,
    which SQLite runs as a co-routine that hands over the rows in order, so the page query stops as soon as
    the page is full. (An ORDER BY on the outer query would make SQLite sort every hit; without the LIMIT
    it would drop the inner ORDER BY.)
    """
    bounds, bound_args = "", []  # id ranges the index applies itself
    if params.after_id is not None:
        bounds += " AND rowid > ?"
        bound_args.append(params.after_id)
    if params.after_seq is not None:
        # Listings published after that point; a draft published late has an older id.
        oldest = conn.execute(
            "SELECT MIN(id) FROM listings WHERE public_seq > ?", (params.after_seq,)
        ).fetchone()[0]
        if oldest is None:
            return None
        bounds += " AND rowid >= ?"
        bound_args.append(oldest)
    sort = params.effective_sort
    by_price = sort in ("price_asc", "price_desc")
    hit_args = [every, *bound_args]
    for table in ("search_matches", "search_best"):
        conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY)")
        conn.execute(f"DELETE FROM temp.{table}")
    newest = _hits(bounds, newest_first=True, limit=SCAN_LIMIT)
    conn.execute(
        f"INSERT INTO temp.search_matches SELECT l.id FROM ({newest}) f CROSS JOIN listings l ON l.id = f.id "
        f"WHERE {where} LIMIT {COUNT_LIMIT + 1}",
        [*hit_args, *args],
    )
    found = conn.execute("SELECT COUNT(*) FROM temp.search_matches").fetchone()[0]
    few = found <= COUNT_LIMIT
    beyond = (few or by_price) and _many_hits(conn, bounds, hit_args)  # more hits than were looked at
    in_table = few and not beyond  # the table holds every match
    total = (min(found, COUNT_LIMIT), in_table)
    descending = " ORDER BY id DESC" if sort != "oldest" else " ORDER BY id"
    if in_table:
        matches = "SELECT id FROM temp.search_matches"
        if by_price:
            select = "SELECT l.id FROM listings l WHERE l.id IN temp.search_matches"
            if sort == "price_asc":
                segments = [
                    (f"{select} AND l.price IS NOT NULL ORDER BY l.price, l.id DESC", []),
                    (f"{select} AND l.price IS NULL ORDER BY l.id DESC", []),
                ]
            else:
                segments = [(f"{select} ORDER BY l.price DESC, l.id DESC", [])]
        elif sort == "relevance" and best:
            # Few matches: all of them are ranked, those with every word in the title, category, place or
            # properties first.
            conn.execute(
                f"INSERT INTO temp.search_best SELECT rowid FROM listings_fts WHERE listings_fts MATCH ?{bounds} "
                "AND rowid >= (SELECT MIN(id) FROM temp.search_matches)",
                [best, *bound_args],
            )
            segments = [
                (f"{matches} WHERE id IN temp.search_best{descending}", []),
                (f"{matches} WHERE id NOT IN temp.search_best{descending}", []),
            ]
        else:
            segments = [(matches + descending, [])]
        return segments, total, True
    ordered = _hits(bounds, newest_first=sort != "oldest", limit=-1)  # -1: no limit, but keeps the order
    resort = " ORDER BY f.id DESC" if bounds and sort != "oldest" else ""
    joined = f"SELECT l.id FROM ({ordered}) f CROSS JOIN listings l ON l.id = f.id WHERE {where}"
    if by_price:
        # Sorted by price among the SCAN_LIMIT newest hits (all of them, unless the words are very common).
        select = f"SELECT l.id FROM listings l WHERE {where} AND l.id IN ({newest})"
        if sort == "price_asc":
            segments = [
                (f"{select} AND l.price IS NOT NULL ORDER BY l.price, l.id DESC", [*args, *hit_args]),
                (f"{select} AND l.price IS NULL ORDER BY l.id DESC", [*args, *hit_args]),
            ]
        else:
            segments = [(f"{select} ORDER BY l.price DESC, l.id DESC", [*args, *hit_args])]
    elif sort == "relevance" and best:
        # Many matches: the newest RANKED_HITS hits are ranked, those with every word in the title,
        # category, place or properties first. Older hits follow by date. (The window is read oldest first:
        # the index ignores a lower id bound when it reads newest first.)
        floor = 0
        if not bounds:
            row = conn.execute(
                "SELECT rowid FROM listings_fts WHERE listings_fts MATCH ? ORDER BY rowid DESC "
                f"LIMIT 1 OFFSET {RANKED_HITS - 1}",
                hit_args,
            ).fetchone()
            floor = row[0] if row else 0
        conn.execute(
            f"INSERT INTO temp.search_best SELECT rowid FROM listings_fts WHERE listings_fts MATCH ?{bounds} "
            f"AND rowid >= ? LIMIT {RANKED_HITS}",
            [best, *bound_args, floor],
        )
        segments = [
            (
                f"SELECT l.id FROM temp.search_best f CROSS JOIN listings l ON l.id = f.id WHERE {where} "
                "ORDER BY f.id DESC",
                args,
            ),
            (f"{joined} AND f.id NOT IN temp.search_best{resort}", [*hit_args, *args]),
        ]
    else:
        segments = [(joined + resort, [*hit_args, *args])]
    return segments, total, not (beyond and by_price)


def _by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[Listing]:
    if not ids:
        return []
    found = {item.id: item for item in fetch(conn, f"WHERE l.id IN ({','.join('?' * len(ids))})", ids)}
    return [found[listing_id] for listing_id in ids if listing_id in found]


def search(conn: sqlite3.Connection, params: SearchParams, *, count: bool = True) -> SearchResult:
    """Find listings. With count=False the matches are not counted (total is 0), which saves time when
    only the first few listings are shown."""
    params = validate_search(params)
    conditions, args = _conditions(params)
    where = " AND ".join(conditions) or "1"
    every, best = _full_text(params)
    if every is None:
        plan = (*_browse(conn, params, where, args, count), True)
    else:
        plan = _words(conn, params, where, args, every, best)
    if plan is None:
        return SearchResult(items=[], total=0, params=params)
    segments, (total, exact), complete = plan
    ids, more = _page(conn, segments, params.offset, params.limit)
    if complete and not more and (ids or not params.offset):  # the page shows the last match
        total, exact = params.offset + len(ids), True
    if not count:
        total, exact = 0, True
    return SearchResult(
        items=_by_ids(conn, ids), total=total, params=params, total_exact=exact, has_more=more
    )


def iter_public_listings(
    conn: sqlite3.Connection, batch: int = 500, *, include_imported: bool = True
) -> Iterable[Listing]:
    """All active and sold listings, oldest first, in batches (for exports and sitemaps)."""
    last_id = 0
    only_own = "" if include_imported else "AND l.source IS NULL "
    while True:
        rows = conn.execute(
            # "+l.status": walk the listings in id order instead of sorting all of them for each batch.
            f"{_SELECT} WHERE +l.status IN ('active', 'sold') AND u.banned_at IS NULL AND l.id > ? {only_own}"
            "ORDER BY l.id LIMIT ?",
            (last_id, batch),
        ).fetchall()
        if not rows:
            return
        items = [_listing(row) for row in rows]
        _attach_images(conn, items)
        yield from items
        last_id = items[-1].id
