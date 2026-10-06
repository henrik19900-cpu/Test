"""Listings: validation, storage, full-text search and quotas.

Validation messages ("detail") are Norwegian because people see them in forms; "hint"
texts are English because they tell API/MCP clients how to fix the request.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import fraud, taxonomy
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
from .util import format_number, iso_ago, now_iso, parse_iso, to_iso

CHANNELS = ("web", "api", "mcp")
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
    images: list[Image] = field(default_factory=list)
    rank: float | None = None
    # Seller statistics, only loaded for single-listing views (get_listing).
    seller_active: int | None = None
    seller_sold: int | None = None

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
        return self.seller_since > iso_ago(days=fraud.NEW_ACCOUNT_DAYS)

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
        error("title", "Tittelen må være mellom 3 og 120 tegn.")

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
    "u.verified_at AS seller_verified_at"
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
        rank=row["rank"] if "rank" in keys else None,
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


def _search_text(values: dict[str, Any]) -> str:
    """Extra indexed text: category names (Norwegian and English), place and attribute values."""
    category = taxonomy.CATEGORIES[values["category"]]
    group = taxonomy.CATEGORIES[category.group]
    parts = [
        category.name,
        category.name_en,
        group.name,
        group.name_en,
        LISTING_TYPES[values["type"]].label,
        COUNTIES[values["county"]].name if values.get("county") else None,
        values.get("location"),
        values.get("postal_code"),
    ]
    for key, value in values["attributes"].items():
        attr = ATTRIBUTES[key]
        parts.append(attr.display(value))
        if attr.type == "enum":
            parts.append(str(value).replace("_", " "))
    return " ".join(str(p) for p in parts if p)


def _index(conn: sqlite3.Connection, listing_id: int, values: dict[str, Any]) -> None:
    conn.execute("DELETE FROM listings_fts WHERE rowid = ?", (listing_id,))
    conn.execute(
        "INSERT INTO listings_fts (rowid, title, body, meta) VALUES (?, ?, ?, ?)",
        (listing_id, values["title"], values["description"], _search_text(values)),
    )


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
) -> int:
    """Create a listing. Listings with strong fraud signals start in status "review"."""
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
            "risk_flags, text_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ),
        )
        listing_id = cursor.lastrowid
        assert listing_id is not None
        _index(conn, listing_id, values)
    return listing_id


def update_listing(
    conn: sqlite3.Connection,
    user_id: int,
    listing_id: int,
    changes: dict[str, Any],
    *,
    merge_attributes: bool = True,
    is_admin: bool = False,
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
    values.update(changes)
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
            "risk_score = ?, risk_flags = ?, text_hash = ? WHERE id = ?",
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
                listing_id,
            ),
        )
        _index(conn, listing_id, clean)
    return get_listing(conn, listing_id)


def set_status(
    conn: sqlite3.Connection, user_id: int, listing_id: int, status: str, is_admin: bool = False
) -> None:
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    _check_owner_status(listing, status, is_admin)
    if listing.status == "review" and not is_admin:
        return  # hiding a listing that is not public yet changes nothing
    conn.execute(
        "UPDATE listings SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), listing_id)
    )


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
    with transaction(conn):
        conn.execute("DELETE FROM listings_fts WHERE rowid = ?", (listing_id,))
        conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    return [image.filename for image in listing.images]


def category_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT l.category, COUNT(*) AS n FROM listings l JOIN users u ON u.id = l.user_id "
        "WHERE l.status = 'active' AND u.banned_at IS NULL GROUP BY l.category"
    )
    counts = {r["category"]: r["n"] for r in rows}
    for group in taxonomy.GROUPS:
        counts[group] = sum(counts.get(c, 0) for c in taxonomy.CATEGORIES[group].children)
    return counts


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

SORTS = {
    "relevance": "Mest relevant",
    "newest": "Nyeste først",
    "oldest": "Eldste først",
    "price_asc": "Lavest pris",
    "price_desc": "Høyest pris",
}
SEARCH_STATUSES = ("active", "sold", "any")
MAX_LIMIT = 100


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

    @property
    def effective_sort(self) -> str:
        if self.sort and self.sort != "relevance":
            return self.sort
        return "relevance" if self.q and self.q.strip() else "newest"


@dataclass
class SearchResult:
    items: list[Listing]
    total: int
    params: SearchParams

    @property
    def has_more(self) -> bool:
        return self.params.offset + len(self.items) < self.total


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
    params.limit = max(1, min(int(params.limit), MAX_LIMIT))
    params.offset = max(0, int(params.offset))
    return params


_TOKEN_RE = re.compile(r"[\w][\w\-./+]*", re.UNICODE)


def build_fts_query(q: str) -> tuple[str | None, list[str]]:
    """Turn free text into an FTS5 trigram query (all terms must match).

    Terms shorter than three characters cannot use the trigram index; they are returned
    separately and matched with LIKE instead.
    """
    phrases, short = [], []
    for token in _TOKEN_RE.findall(q.casefold()):
        token = token.strip("-./+")
        if not token:
            continue
        if len(token) >= 3:
            phrases.append('"' + token.replace('"', '""') + '"')
        else:
            short.append(token)
    return (" AND ".join(phrases) or None), short


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(conn: sqlite3.Connection, params: SearchParams) -> SearchResult:
    params = validate_search(params)
    conditions: list[str] = []
    args: list[Any] = []

    if params.status == "any":
        conditions.append("l.status IN ('active', 'sold')")
    elif params.status != "all":  # "all" (incl. hidden) is only accepted for owners, see validate_search
        conditions.append("l.status = ?")
        args.append(params.status)
    if not params.include_hidden:
        conditions.append("u.banned_at IS NULL")

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
        conditions.append("casefold(l.location) LIKE ? ESCAPE '\\'")
        args.append(f"%{_escape_like(params.location.strip().casefold())}%")
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

    fts_query, short_terms = build_fts_query(params.q or "")
    for term in short_terms:
        conditions.append(
            "(casefold(l.title) LIKE ? ESCAPE '\\' OR casefold(l.description) LIKE ? ESCAPE '\\')"
        )
        pattern = f"%{_escape_like(term)}%"
        args.extend([pattern, pattern])

    if fts_query:
        source = "listings_fts JOIN listings l ON l.id = listings_fts.rowid JOIN users u ON u.id = l.user_id"
        columns = f"l.*, {_SELLER_COLUMNS}, bm25(listings_fts, 10.0, 1.0, 3.0) AS rank"
        conditions.insert(0, "listings_fts MATCH ?")
        args.insert(0, fts_query)
    else:
        source = "listings l JOIN users u ON u.id = l.user_id"
        columns = f"l.*, {_SELLER_COLUMNS}"

    where = " AND ".join(conditions) if conditions else "1"
    order = {
        "newest": "l.created_at DESC, l.id DESC",
        "oldest": "l.created_at ASC, l.id ASC",
        "price_asc": "l.price IS NULL, l.price ASC, l.id DESC",
        "price_desc": "l.price IS NULL, l.price DESC, l.id DESC",
        "relevance": "rank, l.created_at DESC, l.id DESC" if fts_query else "l.created_at DESC, l.id DESC",
    }[params.effective_sort]

    total = conn.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT {columns} FROM {source} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*args, params.limit, params.offset],
    ).fetchall()
    items = [_listing(row) for row in rows]
    _attach_images(conn, items)
    return SearchResult(items=items, total=total, params=params)


def iter_public_listings(conn: sqlite3.Connection, batch: int = 500) -> Iterable[Listing]:
    """All active and sold listings, oldest first, in batches (for exports and sitemaps)."""
    last_id = 0
    while True:
        rows = conn.execute(
            f"{_SELECT} WHERE l.status IN ('active', 'sold') AND u.banned_at IS NULL AND l.id > ? "
            "ORDER BY l.id LIMIT ?",
            (last_id, batch),
        ).fetchall()
        if not rows:
            return
        items = [_listing(row) for row in rows]
        _attach_images(conn, items)
        yield from items
        last_id = items[-1].id
