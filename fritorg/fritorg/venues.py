"""Venues and facilities that Stavanger kommune rents out (sports halls, pools, pitches, meeting
rooms and more), from the municipality's open dataset "Aktiv kommune – Ressursoversikt".

The data is published under the Norwegian Licence for Open Government Data (NLOD 2.0), which allows
republishing with credit; the listing pages carry the attribution text the licence asks for. The
contact e-mail column is left out, since some addresses are private. The list is replaced by the
current one on every run, so venues the municipality no longer rents out disappear.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from collections.abc import Callable

from . import imports
from .config import Settings
from .db import Database
from .navjobs import HttpFn, http_get

logger = logging.getLogger(__name__)

SOURCE = "stavanger"
CSV_URL = (
    "https://opencom.no/dataset/6400faa2-7203-4b6b-b63a-92d76c32b05f/resource/"
    "a475b7bd-7615-4844-bbcf-d9264a2161ec/download/resources.csv"
)
DATASET_URL = "https://opencom.no/dataset/aktiv-kommune-ressursoversikt-1103"
BOOKING_URL = "https://site1.aktiv-kommune.no/1103/bookingfrontend/"
INTERVAL_SECONDS = 24 * 3600  # the dataset is updated daily

_VENUE_TYPES = (  # the resource's own name is checked before the place's
    ("market", ("marked", "salgsplass", "stand", "bod")),
    ("pool", ("basseng", "svømme", "badeland")),
    ("field", ("bane", "stadion", "løkke", "slette", "stripe", "friidrett", "kunstgress", "tennis", "padel",
               "idrettspark")),
    ("sports_hall", ("hall", "gymsal", "styrkerom", "klatrevegg", "dansesal", "turnsal", "squash")),
    ("party", ("selskap", "festsal", "kafe", "peisestue", "disko", "kjøkken")),
    ("room", ("rom", "sal", "aula", "amfi", "scene", "atelier", "verksted", "verkstad", "kontor", "klubb",
              "senter", "lokale", "stova", "stue", "hus", "bibliotek", "kantine", "møteplass", "studio",
              "arbeidsplass", "arbeidsstad")),
)  # fmt: skip


def _matches(word: str, keyword: str) -> bool:
    # Norwegian compounds put the main word last ("grusbane", "storsalen", "grupperom").
    if len(keyword) >= 4:
        return keyword in word
    return any(word.endswith(keyword + ending) for ending in ("", "en", "et", "a", "ene", "met", "mene"))


def _kind(name: str, skip: tuple[str, ...] = ()) -> str:
    words = re.findall(r"[^\W\d_]+", name.casefold().replace("è", "e").replace("é", "e"))
    for kind, keywords in _VENUE_TYPES:
        if any(_matches(word, keyword) for word in words for keyword in keywords if keyword not in skip):
            return kind
    return "other"


def venue_type(resource: str, place: str) -> str:
    """The resource's own name decides, unless it is just a "sal" in a hall, pool or field."""
    own, where = _kind(resource), _kind(place)
    if (
        own == "room"
        and _kind(resource, skip=("sal",)) == "other"
        and where in ("sports_hall", "pool", "field")
    ):
        return where
    return own if own != "other" else where


def _clean(value: str | None) -> str:
    # The file has HTML character references with the "&#" lost: "amp 40" for "(".
    text = " ".join((value or "").split())
    text = re.sub(r"\bamp (\d{2,3})\b ?", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", text))
    return "" if text in ("0", "-") else text


def _skip(place: str, resource: str) -> bool:
    """Test entries and resources marked as not available."""
    both = f"{place} {resource}".casefold()
    return bool(
        re.match(r"test", place.casefold())
        or re.match(r"test", resource.casefold())
        or resource.casefold() == "x"
    ) or ("ikke tilgjengelig" in both)


def parse(text: str) -> list[imports.Item]:
    items = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        resource_id = _clean(row.get("Ressursid"))
        place = _clean(row.get("Sted"))
        resource = _clean(row.get("Ressurs"))
        if not resource_id or not (place or resource) or _skip(place, resource):
            continue
        title = place if not resource or resource.casefold() == place.casefold() else f"{resource} – {place}"
        street = _clean(row.get("Gateadresse"))
        postal = _clean(row.get("Postnr"))
        town = _clean(row.get("Poststed")) or "Stavanger"
        district = _clean(row.get("Bydel"))
        if not re.search(r"[A-Za-zÆØÅæøå]", district) or district.casefold() == town.casefold():
            district = ""
        address = ", ".join(part for part in (street, f"{postal} {town}".strip()) if part)
        description = (
            f"{resource or place} på {place}{f', {address}' if address else ''}{f' (bydel {district})' if district else ''}. "
            "Idrettsavdelingen i Stavanger kommune leier ut lokalet eller anlegget til lag, foreninger og andre. "
            "Ledige tider, priser og vilkår finner du i kommunens bookingsystem, der du også bestiller."
        )
        items.append(
            imports.Item(
                source_id=resource_id,
                values={
                    "category": "lokaler",
                    "type": "rent",
                    "title": title[:120],
                    "description": description,
                    "price": None,
                    "county": "rogaland",
                    "location": f"{district}, {town}" if district else town,
                    "postal_code": postal if re.fullmatch(r"\d{4}", postal) else None,
                    "attributes": {"venue_type": venue_type(resource, place)},
                },
                source_url=DATASET_URL,
                apply_url=BOOKING_URL,
                # The CSV has no change times, so a fingerprint of the row stands in for one.
                changed="row:" + hashlib.sha256("|".join(row.values()).encode()).hexdigest()[:24],
            )
        )
    return items


def sync(db: Database, settings: Settings, http: HttpFn | None = None) -> imports.SnapshotReport:
    with db.session() as conn:
        try:
            agent = f"Fritorg venue import ({settings.contact_email or settings.base_url or 'no contact'})"
            response = (http or http_get)(CSV_URL, {"User-Agent": agent})
            if response.status != 200:
                raise RuntimeError(f"Stavanger venue list answered HTTP {response.status}")
            items = parse(response.body.decode("utf-8", "replace"))
            if len(items) < 10:  # a broken or empty file must not wipe the venues
                raise RuntimeError(
                    f"Stavanger venue list has only {len(items)} rows; keeping the current ones"
                )
            report = imports.apply_snapshot(conn, SOURCE, items)
        except Exception as exc:
            imports.record_run(conn, SOURCE, f"{type(exc).__name__}: {exc}")
            raise
        imports.record_run(conn, SOURCE)
    return report


def job(db: Database, settings: Settings) -> imports.Job:
    def run(should_stop: Callable[[], bool]) -> bool:
        report = sync(db, settings)
        logger.info("Stavanger venues: %s", report)
        return False

    return imports.Job(SOURCE, INTERVAL_SECONDS, run)
