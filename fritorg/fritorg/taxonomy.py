"""Categories, listing types, counties and per-category attribute schemas.

This is the single source of truth for structured data on Fritorg. The same definitions
drive form fields, validation, search filters, the OpenAPI/MCP schemas and llms.txt, so
humans and agents always see the same rules.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .util import MONTHS_NO

THIS_YEAR = date.today().year


@dataclass(frozen=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True)
class Attribute:
    key: str
    label: str
    type: str  # "string" | "integer" | "enum" | "boolean" | "date"
    description: str = ""
    options: tuple[Option, ...] = ()
    unit: str | None = None
    min: int | None = None
    max: int | None = None
    max_length: int = 80

    def option_label(self, value: Any) -> str:
        for option in self.options:
            if option.value == value:
                return option.label
        return str(value)

    def display(self, value: Any) -> str:
        """Human-readable Norwegian value, e.g. '120 000 km' or 'Ja'."""
        if self.type == "boolean":
            return "Ja" if value else "Nei"
        if self.type == "enum":
            return self.option_label(value)
        if self.type == "integer" and isinstance(value, int):
            text = f"{value:,}".replace(",", " ") if self.key not in NO_GROUPING else str(value)
            return f"{text} {self.unit}" if self.unit else text
        if self.type == "date":
            try:
                day = date.fromisoformat(str(value))
            except ValueError:
                return str(value)
            return f"{day.day}. {MONTHS_NO[day.month - 1]} {day.year}"
        return str(value)

    def json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"title": self.label}
        if self.description:
            schema["description"] = self.description
        if self.type == "enum":
            schema["type"] = "string"
            schema["enum"] = [o.value for o in self.options]
            schema["x-labels"] = {o.value: o.label for o in self.options}
        elif self.type == "integer":
            schema["type"] = "integer"
            if self.min is not None:
                schema["minimum"] = self.min
            if self.max is not None:
                schema["maximum"] = self.max
            if self.unit:
                schema["x-unit"] = self.unit
        elif self.type == "boolean":
            schema["type"] = "boolean"
        elif self.type == "date":
            schema["type"] = "string"
            schema["format"] = "date"
        else:
            schema["type"] = "string"
            schema["maxLength"] = self.max_length
        return schema


# Years and similar numbers read wrong with thousand separators ("2 019").
NO_GROUPING = {"year", "year_built", "floor"}


@dataclass(frozen=True)
class Category:
    slug: str
    name: str
    name_en: str
    parent: str | None = None
    attributes: tuple[Attribute, ...] = ()
    types: tuple[str, ...] = ()
    description: str = ""
    children: tuple[str, ...] = field(default=())

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def group(self) -> str:
        return self.parent or self.slug

    def attribute(self, key: str) -> Attribute | None:
        for attr in self.attributes:
            if attr.key == key:
                return attr
        return None

    def attributes_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {a.key: a.json_schema() for a in self.attributes},
        }


@dataclass(frozen=True)
class ListingType:
    slug: str
    label: str
    label_en: str


LISTING_TYPES: dict[str, ListingType] = {
    t.slug: t
    for t in (
        ListingType("sell", "Til salgs", "For sale"),
        ListingType("give", "Gis bort", "Free, giving away"),
        ListingType("wanted", "Ønskes", "Wanted"),
        ListingType("rent", "Til leie", "For rent"),
        ListingType("job", "Ledig stilling", "Job opening"),
        ListingType("service", "Tjeneste tilbys", "Service offered"),
    )
}

PRICE_UNITS: dict[str, str] = {"total": "", "month": "/mnd", "week": "/uke", "day": "/dag", "hour": "/time"}
PRICE_UNIT_LABELS: dict[str, str] = {
    "total": "Totalpris",
    "month": "Per måned",
    "week": "Per uke",
    "day": "Per dag",
    "hour": "Per time",
}

STATUSES: dict[str, str] = {
    "active": "Aktiv",
    "sold": "Solgt",
    "inactive": "Skjult",
    "review": "Til kontroll",
    "removed": "Fjernet",
}
# Statuses an owner may choose; "review" and "removed" are set by fraud checks and moderators.
OWNER_STATUSES = ("active", "sold", "inactive")


@dataclass(frozen=True)
class County:
    slug: str
    name: str


# Norwegian counties (fylker) from 2024, plus Svalbard. Sorted the way a Norwegian reader expects.
COUNTIES: dict[str, County] = {
    c.slug: c
    for c in (
        County("agder", "Agder"),
        County("akershus", "Akershus"),
        County("buskerud", "Buskerud"),
        County("finnmark", "Finnmark"),
        County("innlandet", "Innlandet"),
        County("more-og-romsdal", "Møre og Romsdal"),
        County("nordland", "Nordland"),
        County("oslo", "Oslo"),
        County("rogaland", "Rogaland"),
        County("svalbard", "Svalbard"),
        County("telemark", "Telemark"),
        County("troms", "Troms"),
        County("trondelag", "Trøndelag"),
        County("vestfold", "Vestfold"),
        County("vestland", "Vestland"),
        County("ostfold", "Østfold"),
    )
}

# --- Attribute definitions -------------------------------------------------------------

CONDITION = Attribute(
    "condition",
    "Tilstand",
    "enum",
    "Condition of the item",
    options=(
        Option("new", "Ny/ubrukt"),
        Option("like_new", "Som ny"),
        Option("good", "Pent brukt"),
        Option("used", "Godt brukt"),
        Option("for_parts", "Defekt / til deler"),
    ),
)
BRAND = Attribute("brand", "Merke", "string", "Brand or manufacturer", max_length=60)
CAN_SHIP = Attribute("can_ship", "Kan sendes", "boolean", "The seller is willing to ship the item")
TORGET_COMMON = (CONDITION, BRAND, CAN_SHIP)

MAKE = Attribute("make", "Merke", "string", "Make, e.g. Volvo, Tesla, Yamaha", max_length=40)
MODEL = Attribute("model", "Modell", "string", "Model name", max_length=60)
YEAR = Attribute("year", "Årsmodell", "integer", "Model year", min=1900, max=THIS_YEAR + 1)
MILEAGE = Attribute(
    "mileage_km",
    "Kilometerstand",
    "integer",
    "Odometer reading in kilometres",
    unit="km",
    min=0,
    max=3_000_000,
)
FUEL = Attribute(
    "fuel",
    "Drivstoff",
    "enum",
    "Fuel or power source",
    options=(
        Option("petrol", "Bensin"),
        Option("diesel", "Diesel"),
        Option("electric", "Elektrisk"),
        Option("hybrid", "Hybrid"),
        Option("plugin_hybrid", "Ladbar hybrid"),
        Option("hydrogen", "Hydrogen"),
        Option("other", "Annet"),
    ),
)
GEARBOX = Attribute(
    "gearbox",
    "Girkasse",
    "enum",
    "Transmission",
    options=(Option("manual", "Manuell"), Option("automatic", "Automat")),
)

BEDROOMS = Attribute("bedrooms", "Soverom", "integer", "Number of bedrooms", min=0, max=50)
AREA = Attribute(
    "area_m2",
    "Bruksareal",
    "integer",
    "Usable floor area (BRA) in square metres",
    unit="m²",
    min=1,
    max=100_000,
)
PLOT_AREA = Attribute(
    "plot_area_m2", "Tomteareal", "integer", "Plot area in square metres", unit="m²", min=1, max=10_000_000
)
YEAR_BUILT = Attribute(
    "year_built", "Byggeår", "integer", "Year the building was built", min=1500, max=THIS_YEAR + 3
)
OWNERSHIP = Attribute(
    "ownership",
    "Eierform",
    "enum",
    "Form of ownership (selveier = freehold, andel = housing cooperative share)",
    options=(
        Option("freehold", "Selveier"),
        Option("cooperative", "Andel (borettslag)"),
        Option("share", "Aksje"),
        Option("other", "Annet"),
    ),
)

JOB_ATTRIBUTES = (
    Attribute("employer", "Arbeidsgiver", "string", "Name of the employer", max_length=100),
    Attribute(
        "employment_type",
        "Ansettelsesform",
        "enum",
        "Type of employment",
        options=(
            Option("full_time", "Fast, heltid"),
            Option("part_time", "Deltid"),
            Option("temporary", "Vikariat/midlertidig"),
            Option("seasonal", "Sesong"),
            Option("freelance", "Frilans/oppdrag"),
            Option("apprentice", "Lærling/trainee"),
        ),
    ),
    Attribute(
        "remote",
        "Arbeidssted",
        "enum",
        "Where the work is done",
        options=(
            Option("onsite", "På arbeidsplassen"),
            Option("hybrid", "Hybrid"),
            Option("remote", "Fjernarbeid"),
        ),
    ),
    Attribute("deadline", "Søknadsfrist", "date", "Application deadline (YYYY-MM-DD)"),
    Attribute("salary", "Lønn", "string", "Salary as free text, e.g. '600 000–700 000 kr/år'", max_length=80),
)

SERVICE_ATTRIBUTES = (
    Attribute(
        "provider_type",
        "Tilbyder",
        "enum",
        "Whether the provider is a private person or a business",
        options=(Option("private", "Privatperson"), Option("business", "Bedrift")),
    ),
)

# --- Category tree ---------------------------------------------------------------------

_TORGET = ("sell", "give", "wanted")
_VEHICLES = ("sell", "wanted", "rent")
_PROPERTY = ("sell", "rent", "wanted")

_TREE: list[tuple[Category, list[Category]]] = [
    (
        Category(
            "torget", "Torget", "Marketplace", types=_TORGET, description="Kjøp, salg og gaver av alt mulig"
        ),
        [
            Category(
                "elektronikk",
                "Elektronikk og hvitevarer",
                "Electronics and appliances",
                attributes=TORGET_COMMON,
            ),
            Category("mobler", "Møbler og interiør", "Furniture and interior", attributes=TORGET_COMMON),
            Category(
                "klaer",
                "Klær, sko og tilbehør",
                "Clothing, shoes and accessories",
                attributes=(
                    *TORGET_COMMON,
                    Attribute("size", "Størrelse", "string", "Size, e.g. M, 42, 110 cm", max_length=20),
                ),
            ),
            Category("sport", "Sport og friluftsliv", "Sports and outdoors", attributes=TORGET_COMMON),
            Category(
                "sykler",
                "Sykler",
                "Bicycles",
                attributes=(
                    Attribute(
                        "bike_type",
                        "Sykkeltype",
                        "enum",
                        "Kind of bicycle",
                        options=(
                            Option("city", "By/hybrid"),
                            Option("terrain", "Terreng"),
                            Option("road", "Landevei/gravel"),
                            Option("electric", "Elsykkel"),
                            Option("kids", "Barnesykkel"),
                            Option("cargo", "Lastesykkel"),
                            Option("other", "Annet"),
                        ),
                    ),
                    Attribute(
                        "frame_size",
                        "Rammestørrelse",
                        "string",
                        'Frame size, e.g. M, 54 cm, 19"',
                        max_length=20,
                    ),
                    *TORGET_COMMON,
                ),
            ),
            Category("barn", "Barn og baby", "Kids and baby", attributes=TORGET_COMMON),
            Category(
                "hjem-og-hage",
                "Hus, hage og oppussing",
                "Home improvement and garden",
                attributes=TORGET_COMMON,
            ),
            Category("hobby", "Hobby, bøker og musikk", "Hobbies, books and music", attributes=TORGET_COMMON),
            Category("dyr", "Dyr og utstyr", "Pets and pet supplies", attributes=TORGET_COMMON),
            Category("antikk-og-kunst", "Antikk og kunst", "Antiques and art", attributes=TORGET_COMMON),
            Category("annet", "Annet", "Everything else", attributes=TORGET_COMMON),
        ],
    ),
    (
        Category(
            "kjoretoy",
            "Kjøretøy og båt",
            "Vehicles and boats",
            types=_VEHICLES,
            description="Bil, MC, båt og bobil",
        ),
        [
            Category("bil", "Bil", "Cars", attributes=(MAKE, MODEL, YEAR, MILEAGE, FUEL, GEARBOX)),
            Category(
                "mc",
                "MC og moped",
                "Motorcycles and mopeds",
                attributes=(
                    MAKE,
                    MODEL,
                    YEAR,
                    MILEAGE,
                    Attribute(
                        "engine_cc",
                        "Slagvolum",
                        "integer",
                        "Engine displacement in cc",
                        unit="ccm",
                        min=0,
                        max=5000,
                    ),
                ),
            ),
            Category(
                "bat",
                "Båt",
                "Boats",
                attributes=(
                    Attribute(
                        "boat_type",
                        "Båttype",
                        "enum",
                        "Kind of boat",
                        options=(
                            Option("motorboat", "Motorbåt"),
                            Option("sailboat", "Seilbåt"),
                            Option("rib", "RIB"),
                            Option("small_boat", "Jolle/robåt"),
                            Option("kayak", "Kajakk/kano"),
                            Option("other", "Annet"),
                        ),
                    ),
                    MAKE,
                    MODEL,
                    YEAR,
                    Attribute("length_ft", "Lengde", "integer", "Length in feet", unit="fot", min=1, max=300),
                    Attribute(
                        "engine_hp",
                        "Motor",
                        "integer",
                        "Engine power in horsepower",
                        unit="hk",
                        min=0,
                        max=5000,
                    ),
                ),
            ),
            Category(
                "bobil",
                "Bobil og campingvogn",
                "Motorhomes and caravans",
                attributes=(
                    Attribute(
                        "vehicle_type",
                        "Type",
                        "enum",
                        "Motorhome or caravan",
                        options=(Option("motorhome", "Bobil"), Option("caravan", "Campingvogn")),
                    ),
                    MAKE,
                    MODEL,
                    YEAR,
                    MILEAGE,
                    Attribute("berths", "Soveplasser", "integer", "Number of sleeping places", min=0, max=20),
                ),
            ),
            Category("deler", "Deler og utstyr", "Parts and accessories", attributes=TORGET_COMMON),
        ],
    ),
    (
        Category(
            "eiendom", "Eiendom", "Real estate", types=_PROPERTY, description="Bolig, hytte, tomt og næring"
        ),
        [
            Category(
                "bolig",
                "Bolig",
                "Homes",
                attributes=(
                    Attribute(
                        "property_type",
                        "Boligtype",
                        "enum",
                        "Kind of home",
                        options=(
                            Option("apartment", "Leilighet"),
                            Option("detached", "Enebolig"),
                            Option("semi_detached", "Tomannsbolig"),
                            Option("terraced", "Rekkehus"),
                            Option("room", "Hybel/rom"),
                            Option("other", "Annet"),
                        ),
                    ),
                    BEDROOMS,
                    AREA,
                    OWNERSHIP,
                    YEAR_BUILT,
                    Attribute("floor", "Etasje", "integer", "Floor the home is on", min=-5, max=100),
                ),
            ),
            Category(
                "fritidsbolig",
                "Fritidsbolig",
                "Holiday homes and cabins",
                attributes=(BEDROOMS, AREA, PLOT_AREA, OWNERSHIP, YEAR_BUILT),
            ),
            Category("tomt", "Tomter", "Plots of land", attributes=(PLOT_AREA,)),
            Category(
                "naering",
                "Næringseiendom",
                "Commercial property",
                attributes=(
                    Attribute(
                        "usage",
                        "Type lokale",
                        "enum",
                        "Kind of commercial premises",
                        options=(
                            Option("office", "Kontor"),
                            Option("retail", "Butikk/handel"),
                            Option("warehouse", "Lager"),
                            Option("industrial", "Industri/verksted"),
                            Option("other", "Annet"),
                        ),
                    ),
                    AREA,
                ),
            ),
        ],
    ),
    (
        Category("jobb", "Jobb", "Jobs", types=("job",), description="Ledige stillinger og oppdrag"),
        [
            Category("jobb-it", "IT og teknologi", "IT and technology", attributes=JOB_ATTRIBUTES),
            Category("jobb-helse", "Helse og omsorg", "Health and care", attributes=JOB_ATTRIBUTES),
            Category("jobb-bygg", "Bygg og anlegg", "Construction", attributes=JOB_ATTRIBUTES),
            Category(
                "jobb-handel",
                "Butikk, salg og service",
                "Retail, sales and service",
                attributes=JOB_ATTRIBUTES,
            ),
            Category(
                "jobb-transport",
                "Transport og logistikk",
                "Transport and logistics",
                attributes=JOB_ATTRIBUTES,
            ),
            Category("jobb-utdanning", "Undervisning", "Education", attributes=JOB_ATTRIBUTES),
            Category(
                "jobb-industri",
                "Industri og produksjon",
                "Industry and production",
                attributes=JOB_ATTRIBUTES,
            ),
            Category(
                "jobb-kontor",
                "Kontor, økonomi og ledelse",
                "Office, finance and management",
                attributes=JOB_ATTRIBUTES,
            ),
            Category("jobb-annet", "Andre stillinger", "Other jobs", attributes=JOB_ATTRIBUTES),
        ],
    ),
    (
        Category(
            "tjenester",
            "Tjenester",
            "Services",
            types=("service", "wanted"),
            description="Håndverk, flyttehjelp og mer",
        ),
        [
            Category("handverk", "Håndverkere", "Tradespeople", attributes=SERVICE_ATTRIBUTES),
            Category(
                "flytting", "Flytting og transport", "Moving and transport", attributes=SERVICE_ATTRIBUTES
            ),
            Category("rengjoring", "Rengjøring", "Cleaning", attributes=SERVICE_ATTRIBUTES),
            Category(
                "hagearbeid",
                "Hage og snømåking",
                "Gardening and snow clearing",
                attributes=SERVICE_ATTRIBUTES,
            ),
            Category(
                "undervisning", "Kurs og leksehjelp", "Courses and tutoring", attributes=SERVICE_ATTRIBUTES
            ),
            Category(
                "pass-og-omsorg",
                "Barnepass og dyrepass",
                "Childcare and pet sitting",
                attributes=SERVICE_ATTRIBUTES,
            ),
            Category("it-hjelp", "Data- og IT-hjelp", "Computer and IT help", attributes=SERVICE_ATTRIBUTES),
            Category("andre-tjenester", "Andre tjenester", "Other services", attributes=SERVICE_ATTRIBUTES),
        ],
    ),
]


def _build() -> tuple[dict[str, Category], list[str], dict[str, Attribute]]:
    categories: dict[str, Category] = {}
    groups: list[str] = []
    for group, children in _TREE:
        groups.append(group.slug)
        categories[group.slug] = Category(
            group.slug,
            group.name,
            group.name_en,
            types=group.types,
            description=group.description,
            children=tuple(c.slug for c in children),
        )
        for child in children:
            categories[child.slug] = Category(
                child.slug,
                child.name,
                child.name_en,
                parent=group.slug,
                attributes=child.attributes,
                types=group.types,
            )
    # Attribute keys are global: a key means the same thing (and has the same type and
    # options) in every category. That keeps filters like attr=year:2018.. unambiguous.
    attributes: dict[str, Attribute] = {}
    for category in categories.values():
        for attr in category.attributes:
            known = attributes.setdefault(attr.key, attr)
            if (known.type, known.options) != (attr.type, attr.options):
                raise ValueError(f"Attribute {attr.key!r} is defined inconsistently")
    return categories, groups, attributes


CATEGORIES, GROUPS, ATTRIBUTES = _build()
LEAF_SLUGS: list[str] = [c.slug for c in CATEGORIES.values() if c.is_leaf]
ALL_SLUGS: list[str] = list(CATEGORIES)


def get_category(slug: str | None) -> Category | None:
    return CATEGORIES.get(slug) if slug else None


def descendants(slug: str) -> list[str]:
    """The slug itself (if leaf) or all leaf slugs below a group."""
    category = CATEGORIES[slug]
    return [slug] if category.is_leaf else list(category.children)


def path(slug: str) -> list[Category]:
    category = CATEGORIES[slug]
    return [CATEGORIES[category.parent], category] if category.parent else [category]


def suggest(value: str, choices: list[str]) -> str:
    """Agent-friendly hint for an unknown value: close matches, else the full list."""
    close = difflib.get_close_matches(value.lower(), choices, n=3, cutoff=0.5)
    if close:
        return "Did you mean " + " or ".join(repr(c) for c in close) + "?"
    return "Valid values: " + ", ".join(choices)


def find_category(text: str) -> str | None:
    """Map a slug, Norwegian name or English name to a slug (case-insensitive)."""
    needle = text.strip().lower()
    for category in CATEGORIES.values():
        if needle in (category.slug, category.name.lower(), category.name_en.lower()):
            return category.slug
    return None


def suggest_category(value: str, *, leaf_only: bool = False) -> str:
    """Hint for an unknown category, matching slugs as well as Norwegian and English names."""
    needle = value.strip().lower()
    hint = "See GET /api/v1/categories for the full list."
    group = CATEGORIES.get(needle)
    if leaf_only and group and not group.is_leaf:
        return f"{needle!r} is a category group; use one of its subcategories: {', '.join(group.children)}."
    names: dict[str, str] = {}
    for category in CATEGORIES.values():
        if leaf_only and not category.is_leaf:
            continue
        for name in (category.slug, category.name.lower(), category.name_en.lower()):
            names.setdefault(name, category.slug)
        for word in f"{category.name} {category.name_en}".lower().replace(",", " ").split():
            if len(word) > 3:
                names.setdefault(word, category.slug)
    exact = names.get(needle)
    matches = [exact] if exact else []
    for name in difflib.get_close_matches(needle, list(names), n=5, cutoff=0.6):
        if names[name] not in matches:
            matches.append(names[name])
    if matches:
        return "Did you mean " + " or ".join(repr(m) for m in matches[:3]) + "? " + hint
    return hint
