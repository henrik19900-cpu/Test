"""`fritorg benchmark`: fill a throwaway database with made-up listings and time the searches pages run.

Run it on the server you consider renting to see how it copes with as many listings as you expect. The
listings look like a Norwegian marketplace (categories, counties, prices, short ads and long job ads), so
the full-text index has a realistic size. Nothing is sent anywhere and the real database is not touched.
"""

from __future__ import annotations

import json
import random
import statistics
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import listings, taxonomy
from .db import SCHEMA_V5, Database, analyze
from .listings import AttrFilter, SearchParams

WORDS = {
    "elektronikk": ["iPhone", "Samsung", "TV", "høyttaler", "PlayStation", "MacBook", "kamera", "skjerm"],
    "mobler": ["sofa", "hjørnesofa", "spisebord", "stol", "kommode", "bokhylle", "seng", "lenestol"],
    "klaer": ["jakke", "dunjakke", "kjole", "jeans", "sko", "genser", "bunad", "støvler"],
    "sport": ["ski", "langrennski", "telt", "sovepose", "golfsett", "tursekk", "skøyter"],
    "sykler": ["elsykkel", "terrengsykkel", "barnesykkel", "racersykkel", "sykkelvogn"],
    "barn": ["barnevogn", "bilstol", "LEGO", "sprinkelseng", "tripp trapp"],
    "hjem-og-hage": ["gressklipper", "grill", "vaskemaskin", "kjøleskap", "drill", "snøfreser"],
    "bil": ["Volvo XC60", "Tesla Model 3", "Toyota RAV4", "VW Golf", "Skoda Octavia", "BMW X3"],
    "bolig": ["leilighet", "enebolig", "rekkehus", "hybel", "tomannsbolig"],
}
COMMON = (
    "og i på med til for som er det en av at har kan ikke var fra ved om men så også bare veldig godt litt "
    "pent brukt lite selges grunnet flytting må hentes kan sendes fungerer fint ingen riper røykfritt hjem"
).split()
JOB_WORDS = (
    "vi søker en engasjert medarbeider arbeidsoppgaver kvalifikasjoner erfaring utdanning tilbyr gode "
    "betingelser pensjon fleksibel arbeidstid kolleger søknad stillingen tiltredelse etter avtale"
).split()
JOB_TITLES = [
    "Sykepleier",
    "Utvikler",
    "Lærer",
    "Elektriker",
    "Sjåfør",
    "Butikkmedarbeider",
    "Kokk",
    "Rådgiver",
]
CATEGORY_SHARE = {
    "elektronikk": 12,
    "mobler": 10,
    "klaer": 10,
    "sport": 7,
    "sykler": 4,
    "barn": 7,
    "hjem-og-hage": 7,
    "bil": 8,
    "bolig": 4,
    "jobb-helse": 4,
    "jobb-it": 3,
}
COUNTY_SHARE = {
    "oslo": 13,
    "akershus": 13,
    "vestland": 12,
    "rogaland": 9,
    "trondelag": 9,
    "innlandet": 7,
    "agder": 6,
    "ostfold": 6,
    "buskerud": 5,
    "vestfold": 5,
    "more-og-romsdal": 5,
    "nordland": 4,
    "telemark": 3,
    "troms": 3,
    "finnmark": 1,
}


def _text(rng: random.Random, vocabulary: list[str], length: int) -> str:
    """Made-up text: mostly common words, some from the category, and some rare ones (names, models)."""
    words: list[str] = []
    size = 0
    while size < length:
        roll = rng.random()
        if roll < 0.6:
            word = rng.choice(COMMON)
        elif roll < 0.9:
            word = rng.choice(vocabulary)
        else:
            word = f"x{rng.getrandbits(20):x}"
        words.append(word)
        size += len(word) + 1
    return " ".join(words).capitalize() + "."


def fill(db: Database, count: int, *, seed: int = 1, progress: Callable[[int], None] | None = None) -> None:
    """Add `count` made-up listings (and a user per five listings)."""
    rng = random.Random(seed)
    now = datetime.now(UTC)
    conn = db.connect()
    conn.execute("PRAGMA synchronous = OFF")  # a throwaway database: no need to wait for the disk
    # Indexing row by row through the trigger writes the index to disk for every row; for a bulk load it is
    # much quicker to build the index once at the end.
    conn.execute("DROP TRIGGER listings_fts_insert")
    try:
        users = max(10, count // 5)
        start = conn.execute("SELECT COALESCE(MAX(id), 0) FROM users").fetchone()[0]
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO users (id, email, name, password_hash, created_at) VALUES (?, ?, ?, '!', ?)",
            (
                (start + i, f"test{start + i}@example.invalid", f"Testbruker {i}", now.isoformat())
                for i in range(1, users + 1)
            ),
        )
        conn.execute("COMMIT")
        categories, category_weights = list(CATEGORY_SHARE), list(CATEGORY_SHARE.values())
        counties, county_weights = list(COUNTY_SHARE), list(COUNTY_SHARE.values())
        batch: list[tuple] = []
        for n in range(count):
            category = rng.choices(categories, category_weights)[0]
            county = rng.choices(counties, county_weights)[0]
            attributes: dict = {}
            if category.startswith("jobb"):
                kind, price = "job", None
                title = f"{rng.choice(JOB_TITLES)} – {taxonomy.COUNTIES[county].name}"
                description = _text(rng, JOB_WORDS, int(rng.lognormvariate(7.6, 0.4)))
            else:
                kind = "sell"
                noun = rng.choice(WORDS[category])
                title = f"{noun} {rng.choice(['pent brukt', 'som ny', 'selges', 'til salgs', 'billig'])}".capitalize()
                long = category in ("bil", "bolig")
                description = _text(
                    rng, WORDS[category], rng.randint(300, 1500) if long else rng.randint(60, 500)
                )
                price = int(rng.lognormvariate(12 if long else 6.5, 0.9))
                if category == "bil":
                    attributes = {
                        "fuel": rng.choice(["petrol", "diesel", "electric", "hybrid"]),
                        "year": rng.randint(2005, 2025),
                    }
            created = (now - timedelta(seconds=rng.randint(0, 60 * 86400))).strftime("%Y-%m-%dT%H:%M:%SZ")
            values = {
                "category": category,
                "type": kind,
                "county": county,
                "location": None,
                "postal_code": None,
                "attributes": attributes,
            }
            batch.append(
                (
                    start + rng.randint(1, users),
                    category,
                    kind,
                    title,
                    description,
                    price,
                    county,
                    json.dumps(attributes),
                    created,
                    created,
                    listings.search_meta(values),
                )
            )
            if len(batch) == 5000 or n == count - 1:
                conn.execute("BEGIN")
                conn.executemany(
                    "INSERT INTO listings (user_id, category, type, title, description, price, county, attributes, "
                    "status, created_at, updated_at, search_meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                    batch,
                )
                conn.execute("COMMIT")
                batch = []
                if progress:
                    progress(n + 1)
    finally:
        conn.execute(next(sql for sql in SCHEMA_V5 if "TRIGGER listings_fts_insert" in sql))
        conn.execute("INSERT INTO listings_fts (listings_fts) VALUES ('rebuild')")
        analyze(conn)
        conn.close()


SEARCHES: list[tuple[str, SearchParams]] = [
    ("Forsiden: nyeste annonser", SearchParams(sort="newest", limit=12, include_imported=False)),
    ("Alle annonser", SearchParams(limit=24)),
    ("Kategori: Møbler", SearchParams(category="mobler", limit=24)),
    ("Møbler i Oslo", SearchParams(category="mobler", county="oslo", limit=24)),
    ("Bil, lavest pris", SearchParams(category="bil", sort="price_asc", limit=24)),
    (
        "Elbil fra 2018",
        SearchParams(
            category="bil",
            attrs=[AttrFilter("fuel", values=["electric"]), AttrFilter("year", min=2018)],
            limit=24,
        ),
    ),
    ("Søk «sofa»", SearchParams(q="sofa", limit=24)),
    ("Søk «sofa» i Finnmark", SearchParams(q="sofa", county="finnmark", limit=24)),
    ("Søk «selges» (vanlig ord)", SearchParams(q="selges", limit=24)),
    ("Søk «sykepleier» i Oslo", SearchParams(q="sykepleier", county="oslo", limit=24)),
    ("Søk «tv» (to bokstaver)", SearchParams(q="tv", limit=24)),
    ("Søk «sofa», side 10", SearchParams(q="sofa", offset=216, limit=24)),
    ("Søk «sofa», lavest pris", SearchParams(q="sofa", sort="price_asc", limit=24)),
]


def run(
    count: int, keep: Path | None = None, echo: Callable[[str], None] = print
) -> list[tuple[str, float, str]]:
    """Make the database, time every search (median of five) and return (name, milliseconds, total)."""
    folder = None if keep else tempfile.TemporaryDirectory(prefix="fritorg-benchmark-")
    path = keep or Path(folder.name) / "benchmark.sqlite3"  # type: ignore[union-attr]
    try:
        db = Database(path)
        db.init()
        started = time.perf_counter()
        fill(db, count, progress=lambda n: echo(f"  {n} annonser laget …") if n % 50_000 == 0 else None)
        echo(f"Laget {count} annonser på {time.perf_counter() - started:.0f} s.")
        conn = db.connect()
        try:
            size = (
                conn.execute("PRAGMA page_count").fetchone()[0]
                * conn.execute("PRAGMA page_size").fetchone()[0]
            )
            echo(f"Databasen er {size / 1e6:.0f} MB ({size / max(count, 1) / 1000:.1f} kB per annonse).")
            results = []
            for name, params in SEARCHES:
                times, result = [], None
                for _ in range(5):
                    begin = time.perf_counter()
                    result = listings.search(conn, SearchParams(**vars(params)))
                    times.append((time.perf_counter() - begin) * 1000)
                assert result is not None
                results.append((name, statistics.median(times), result.total_label()))
                echo(f"  {name:32s} {statistics.median(times):7.1f} ms   {result.total_label()} treff")
            return results
        finally:
            conn.close()
    finally:
        if folder is not None:
            folder.cleanup()
