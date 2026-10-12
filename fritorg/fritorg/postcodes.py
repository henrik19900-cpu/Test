"""Norwegian postal codes: the place and county for a postal code.

From Bring's postal code register (data/postnummer.tsv, Norsk lisens for offentlige data, NLOD 2.0;
"Inneholder data fra Posten Bring AS"). Update it once a year with a new download from
https://data.norge.no/datasets/f7508db5-2167-3356-ab5e-aacffce2a9b6.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "postnummer.tsv"

# County number (the first two digits of the municipality number, since 2024) -> county slug.
COUNTY_BY_NUMBER = {
    "03": "oslo",
    "11": "rogaland",
    "15": "more-og-romsdal",
    "18": "nordland",
    "21": "svalbard",
    "31": "ostfold",
    "32": "akershus",
    "33": "buskerud",
    "34": "innlandet",
    "39": "vestfold",
    "40": "telemark",
    "42": "agder",
    "46": "vestland",
    "50": "trondelag",
    "55": "troms",
    "56": "finnmark",
}


@dataclass(frozen=True)
class Place:
    postal_code: str
    place: str  # poststed, e.g. "Mo i Rana"
    municipality: str
    county: str | None  # county slug


@cache
def _register() -> dict[str, Place]:
    places = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        code, place, number, municipality, _category = line.split("\t")
        places[code] = Place(code, place, municipality, COUNTY_BY_NUMBER.get(number[:2]))
    return places


def lookup(postal_code: str | None) -> Place | None:
    return _register().get((postal_code or "").strip())


@cache
def _counties_by_name() -> dict[str, frozenset[str]]:
    """Postal place and municipality names (casefolded) -> the counties they are in."""
    names: dict[str, set[str]] = {}
    for place in _register().values():
        if place.county:
            for name in (place.place, place.municipality):
                names.setdefault(name.casefold(), set()).add(place.county)
    return {name: frozenset(counties) for name, counties in names.items()}


def county_for_place(text: str | None) -> str | None:
    """The county of a place name such as "Bergen", "Majorstuen, Oslo" or "Mo i Rana", when the postal code
    register has that name in one county only."""
    text = " ".join((text or "").split())
    if not text:
        return None
    candidates = [text, *(part.strip() for part in reversed(text.split(",")))]
    words = text.split()
    if len(words) <= 3:  # "Bergen sentrum"
        candidates.append(words[0])
    names = _counties_by_name()
    for candidate in candidates:
        counties = names.get(candidate.casefold())
        if counties and len(counties) == 1:
            return next(iter(counties))
    return None
