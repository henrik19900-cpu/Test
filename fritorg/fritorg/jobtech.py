"""Swedish job ads that are relevant in Norway, from Arbetsförmedlingen's open JobSearch API
(Platsbanken, run by JobTech). The ads are published under CC0, so they may be republished freely.

Only ads located in Norway, or asking for Norwegian, are taken: the full Swedish job market would
drown the Norwegian listings. Contact persons are left out. Every run replaces the set with the
current one, so ads that are removed or no longer match disappear.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
from collections.abc import Callable
from datetime import date
from typing import Any

from . import imports, listings
from .config import Settings
from .db import Database
from .errors import ValidationProblem
from .navjobs import HttpFn, http_get

logger = logging.getLogger(__name__)

SOURCE = "jobtech"
API = "https://jobsearch.api.jobtechdev.se/search"
NORWAY = "QJgN_Zge_BzJ"  # JobTech taxonomy concept id for the country Norway
# Ads in Norway, and ads asking for Norwegian. (A query for "Norge" also finds ads that merely mention it.)
QUERIES = ({"country": NORWAY}, {"q": "norska"}, {"q": "norsk"})
PAGE = 100
MAX_PER_QUERY = 1000
INTERVAL_SECONDS = 3 * 3600

# Swedish occupation fields -> Fritorg job categories, first match wins.
_CATEGORY_KEYWORDS = (
    ("jobb-it", ("data/it", "data", "it")),
    ("jobb-helse", ("hälso", "sjukvård", "social", "omsorg")),
    ("jobb-utdanning", ("pedagogik", "pedagogisk", "utbildning")),
    ("jobb-bygg", ("bygg", "anläggning")),
    ("jobb-transport", ("transport", "distribution", "lager")),
    ("jobb-industri", ("industriell", "tillverkning", "installation", "drift", "underhåll", "naturbruk")),
    ("jobb-kontor", ("administration", "ekonomi", "juridik", "chefer", "verksamhetsledare")),
    (
        "jobb-handel",
        ("försäljning", "inköp", "marknadsföring", "hotell", "restaurang", "storhushåll", "service"),
    ),
)


def category_for(ad: dict[str, Any]) -> str:
    label = str((ad.get("occupation_field") or {}).get("label") or "").casefold()
    words = set(re.findall(r"[\w/]+", label))
    for slug, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in words or (len(keyword) > 4 and keyword in label) for keyword in keywords):
            return slug
    return "jobb-annet"


def employment_type(ad: dict[str, Any]) -> str | None:
    kind = str((ad.get("employment_type") or {}).get("label") or "").casefold()
    hours = str((ad.get("working_hours_type") or {}).get("label") or "").casefold()
    if "säsong" in kind or "sommar" in kind or "ferie" in kind:
        return "seasonal"
    if any(word in kind for word in ("vikariat", "tidsbegränsad", "behovs", "projekt")):
        return "temporary"
    if "deltid" in hours:
        return "part_time"
    if "heltid" in hours:
        return "full_time"
    return None


def _real_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _place(ad: dict[str, Any]) -> tuple[str | None, str | None]:
    """(county slug, place). Ads in Norway get a Norwegian county when the region names one."""
    address = ad.get("workplace_address") or {}
    country = str(address.get("country") or "").strip()
    place = str(address.get("municipality") or address.get("city") or "").strip()
    if country.casefold() == "norge":
        county = None
        try:
            county = listings.resolve_county(str(address.get("region") or "").strip() or None)
        except ValidationProblem:
            county = None
        return county, place or "Norge"
    abroad = country or "Sverige"
    return None, f"{place}, {abroad}" if place else abroad


def _fingerprint(ad: dict[str, Any]) -> str:
    stable = {key: value for key, value in ad.items() if key != "relevance"}  # relevance varies per query
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:24]


def to_item(ad: dict[str, Any]) -> imports.Item | None:
    ad_id = str(ad.get("id") or "")
    title = " ".join(str(ad.get("headline") or "").split())
    if not ad_id or len(title) < 3:
        return None
    text = str((ad.get("description") or {}).get("text") or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) < 10:
        text = f"{title}. Les hele annonsen hos Platsbanken."
    employer = " ".join(str((ad.get("employer") or {}).get("name") or "").split())
    attributes: dict[str, Any] = {}
    if employer:
        attributes["employer"] = employer[:100]
    kind = employment_type(ad)
    if kind:
        attributes["employment_type"] = kind
    deadline = str(ad.get("application_deadline") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) and _real_date(deadline):
        attributes["deadline"] = deadline
    salary = " ".join(str(ad.get("salary_description") or "").split())
    if salary:
        attributes["salary"] = salary[:80]
    county, place = _place(ad)
    page = (
        imports.web_url(ad.get("webpage_url"))
        or f"https://arbetsformedlingen.se/platsbanken/annonser/{ad_id}"
    )
    apply = imports.web_url((ad.get("application_details") or {}).get("url")) or page
    return imports.Item(
        source_id=ad_id,
        values={
            "category": category_for(ad),
            "type": "job",
            "title": title[:120],
            "description": text[:10000],
            "price": None,
            "county": county,
            "location": (place or "")[:80] or None,
            "attributes": attributes,
        },
        source_url=page,
        apply_url=apply,
        # A fingerprint of the content tells whether an ad changed since the last run.
        changed="ad:" + _fingerprint(ad),
        published=imports.iso(ad.get("publication_date")),
        expires=imports.iso(ad.get("application_deadline") or ad.get("last_publication_date")),
    )


def fetch(http: HttpFn, agent: str) -> list[dict[str, Any]]:
    """Every ad that matches one of QUERIES, once."""
    ads: dict[str, dict[str, Any]] = {}
    for query in QUERIES:
        offset = 0
        while offset < MAX_PER_QUERY:
            params = urllib.parse.urlencode({**query, "limit": PAGE, "offset": offset})
            response = http(f"{API}?{params}", {"User-Agent": agent, "Accept": "application/json"})
            if response.status != 200:
                raise RuntimeError(f"JobSearch answered HTTP {response.status} for {query}")
            hits = json.loads(response.body).get("hits") or []
            for ad in hits:
                if ad.get("id") and not ad.get("removed"):
                    ads[str(ad["id"])] = ad
            if len(hits) < PAGE:
                break
            offset += PAGE
    return list(ads.values())


def sync(db: Database, settings: Settings, http: HttpFn | None = None) -> imports.SnapshotReport:
    with db.session() as conn:
        try:
            agent = f"Fritorg job import ({settings.contact_email or settings.base_url or 'no contact'})"
            items = [item for ad in fetch(http or http_get, agent) if (item := to_item(ad))]
            report = imports.apply_snapshot(conn, SOURCE, items)
        except Exception as exc:
            imports.record_run(conn, SOURCE, f"{type(exc).__name__}: {exc}")
            raise
        imports.record_run(conn, SOURCE)
    return report


def job(db: Database, settings: Settings) -> imports.Job:
    def run(should_stop: Callable[[], bool]) -> bool:
        logger.info("Swedish job ads: %s", sync(db, settings))
        return False

    return imports.Job(SOURCE, INTERVAL_SECONDS, run)
