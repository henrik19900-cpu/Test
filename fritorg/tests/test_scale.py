"""Search and storage that stay fast with very many listings: totals counted up to a limit, ranking of the
newest hits, filters inside the full-text query, the sitemap index, photo folders and the reused-photo
lookup, and the upgrade that builds it all for an existing database."""

from __future__ import annotations

import random
import sqlite3
import xml.etree.ElementTree as ET

import pytest
from conftest import PHOTO, make_listing

from fritorg import db as database
from fritorg import images, listings, users
from fritorg.db import MIGRATIONS, Database
from fritorg.listings import SearchParams


@pytest.fixture
def conn(tmp_path):
    db = Database(tmp_path / "scale.sqlite3")
    db.init()
    with db.session() as connection:
        yield connection


@pytest.fixture
def seller(conn):
    return users.create_user(conn, "selger@example.no", "Selger", "hemmelig123")


def add(conn, seller, **data):
    base = {"category": "mobler", "title": "Ting", "description": "En helt vanlig ting til salgs."}
    base.update(data)
    return listings.create_listing(conn, seller.id, base, max_per_day=1000)


def ids(conn, **params):
    return [item.id for item in listings.search(conn, SearchParams(**params)).items]


def all_pages(conn, size, **params):
    found, offset = [], 0
    while True:
        page = listings.search(conn, SearchParams(limit=size, offset=offset, **params))
        found += [item.id for item in page.items]
        if not page.has_more:
            return found
        offset += size


def test_totals_are_counted_up_to_a_limit(conn, seller, monkeypatch):
    monkeypatch.setattr(listings, "COUNT_LIMIT", 3)
    made = [add(conn, seller, title=f"Sofa nummer {n}", price=100 + n) for n in range(5)]
    result = listings.search(conn, SearchParams(q="sofa", limit=2))
    assert (result.total, result.total_exact, result.has_more) == (3, False, True)
    assert result.total_label() == "over 3"
    assert listings.search(conn, SearchParams(price_min=100, limit=2)).total_label() == "over 3"
    # A category on its own is answered from the counts per category, which are exact.
    assert listings.search(conn, SearchParams(category="mobler", limit=2)).total == 5
    # Every match can still be reached, and the last page knows the total.
    assert sorted(all_pages(conn, 2, q="sofa")) == made
    last = listings.search(conn, SearchParams(q="sofa", limit=2, offset=4))
    assert (last.total, last.total_exact, last.has_more) == (5, True, False)


def test_counts_look_at_the_newest_hits_but_pages_show_every_match(conn, seller, monkeypatch):
    monkeypatch.setattr(listings, "SCAN_LIMIT", 3)
    cheap = add(conn, seller, title="Sofa", price=100)  # the oldest hit
    for n in range(4):
        add(conn, seller, title=f"Sofa {n}", price=5000)
    result = listings.search(conn, SearchParams(q="sofa", price_max=500))
    assert [item.id for item in result.items] == [cheap]
    assert (result.total, result.total_exact) == (1, True)  # the page reached the end
    many = listings.search(conn, SearchParams(q="sofa", price_min=1000, limit=2))
    assert (many.total, many.total_exact, many.total_label()) == (3, False, "minst 3")


def test_ranking_covers_the_newest_hits(conn, seller, monkeypatch):
    old_title = add(conn, seller, title="Sofa")
    middle = add(conn, seller, title="Stol", description="Står ved en sofa.")
    new_title = add(conn, seller, title="Sofa i skinn")
    newest = add(conn, seller, title="Bord", description="Passer til sofaen.")
    # A few matches are all ranked: title matches first.
    assert ids(conn, q="sofa") == [new_title, old_title, newest, middle]
    # Many matches: the two newest hits are ranked (a title match first); older hits follow by date.
    monkeypatch.setattr(listings, "COUNT_LIMIT", 2)
    monkeypatch.setattr(listings, "RANKED_HITS", 2)
    assert ids(conn, q="sofa") == [new_title, newest, middle, old_title]
    assert all_pages(conn, 1, q="sofa") == [new_title, newest, middle, old_title]


@pytest.mark.parametrize("count_limit", [1000, 2])
def test_pages_add_up_to_the_whole_result(conn, seller, monkeypatch, count_limit):
    monkeypatch.setattr(listings, "COUNT_LIMIT", count_limit)  # few matches, and many
    for n in range(9):
        add(
            conn,
            seller,
            title=f"Sofa {n}" if n % 2 else f"Stol {n}",
            description="Står ved sofaen." if n % 2 == 0 else "Fin og ren.",
            price=None if n % 3 == 0 else 100 * (n % 4),
        )
    for params in (
        {"q": "sofa"},
        {"q": "sofa", "sort": "newest"},
        {"q": "sofa", "sort": "oldest"},
        {"q": "sofa", "sort": "price_asc"},
        {"q": "sofa", "sort": "price_desc"},
        {"sort": "price_asc"},
        {"sort": "price_desc"},
        {"sort": "oldest"},
    ):
        everything = ids(conn, limit=100, **params)
        assert len(everything) == len(set(everything)) == (9 if "q" not in params else 9)
        for size in (1, 2, 4):
            assert all_pages(conn, size, **params) == everything, (params, size)
    prices = [listings.get_listing(conn, i).price for i in ids(conn, sort="price_asc", limit=100)]
    assert prices == sorted(p for p in prices if p is not None) + [None] * prices.count(None)


def test_filters_inside_the_full_text_query(conn, seller):
    oslo = add(conn, seller, title="Sofa", county="oslo", location="Grünerløkka")
    bergen = add(conn, seller, title="Sofa", county="vestland", location="Bergen")
    tv = add(conn, seller, category="elektronikk", title="TV ved sofaen", county="oslo", attributes={})
    nowhere = add(conn, seller, title="Sofa uten sted")
    assert ids(conn, q="sofa", county="oslo") == [tv, oslo]
    assert ids(conn, q="sofa", category="mobler") == [nowhere, bergen, oslo]
    assert ids(conn, q="sofa", category="mobler", county="oslo") == [oslo]
    assert ids(conn, q="sofa", category="torget", county="vestland") == [bergen]
    assert ids(conn, location="GRÜNER") == [oslo]
    assert ids(conn, location="berg", q="sofa") == [bergen]
    # The county's name is ordinary text: the filter does not match a listing that only mentions it.
    mention = add(conn, seller, title="Sofa", description="Kan leveres i Oslo.", county="agder")
    assert mention not in ids(conn, q="sofa", county="oslo")
    assert ids(conn, q="oslo", county="agder") == [mention]


def test_short_place_names_match_whole_words(conn, seller):
    aas = add(conn, seller, location="Ås")
    add(conn, seller, location="Kvås")
    mo = add(conn, seller, location="Mo i Rana")
    assert ids(conn, location="ås") == [aas]
    assert ids(conn, location="MO") == [mo]
    assert ids(conn, location="mo i") == [mo]


def test_ranges_by_id_and_publishing_order(conn, seller):
    first = add(conn, seller, title="Sofa en")
    second = add(conn, seller, title="Sofa to")
    third = add(conn, seller, title="Sofa tre", status="inactive")
    assert ids(conn, q="sofa", after_id=first) == [second]
    seq = conn.execute("SELECT public_seq FROM listings WHERE id = ?", (second,)).fetchone()[0]
    assert ids(conn, q="sofa", after_seq=seq) == []
    listings.set_status(conn, seller.id, third, "active")
    assert ids(conn, q="sofa", after_seq=seq) == [third]
    assert ids(conn, q="sofa", after_seq=seq, sort="oldest") == [third]


def test_counts_per_category_are_kept_for_a_minute(conn, seller, monkeypatch):
    add(conn, seller)
    assert listings.category_counts(conn)["mobler"] == 1
    conn.execute("UPDATE listings SET status = 'inactive'")  # behind the app's back
    assert listings.category_counts(conn)["mobler"] == 1
    monkeypatch.setattr(listings, "COUNTS_SECONDS", 0)
    assert listings.category_counts(conn).get("mobler", 0) == 0
    monkeypatch.setattr(listings, "COUNTS_SECONDS", 60)
    add(conn, seller)  # on a small site the app's own changes are counted at once
    assert listings.category_counts(conn)["mobler"] == 1
    monkeypatch.setattr(listings, "QUICK_COUNT_SECONDS", 0)  # as if counting were slow (a large site)
    add(conn, seller)
    assert listings.category_counts(conn)["mobler"] == 1


def test_the_index_follows_every_way_a_listing_disappears(conn, seller):
    other = users.create_user(conn, "annen@example.no", "Annen", "hemmelig123")
    add(conn, seller, title="Sofa")
    gone = add(conn, other, title="Sofa")
    users.delete_user(conn, other.id)
    assert ids(conn, q="sofa") != [] and gone not in ids(conn, q="sofa")
    conn.execute("INSERT INTO listings_fts (listings_fts, rank) VALUES ('integrity-check', 1)")


def test_search_text_has_filter_tags_but_no_private_characters(conn, seller):
    listing_id = add(conn, seller, location="Oslo", county="oslo")
    meta = conn.execute("SELECT search_meta FROM listings WHERE id = ?", (listing_id,)).fetchone()[0]
    assert meta.startswith("Møbler og interiør")
    assert listings.filter_tag("f", "oslo") in meta and listings.filter_tag("k", "mobler") in meta
    assert "" not in meta and "" not in meta
    assert listings.filter_tag("f", "oslo") != listings.filter_tag("k", "oslo")


def test_upgrading_builds_the_new_index(tmp_path):
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    for number, sql in enumerate(MIGRATIONS[:4], start=1):
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    old.execute(
        "INSERT INTO users (id, email, name, password_hash, created_at) VALUES (1, 'a@b.no', 'Anne', 'x', '2026')"
    )
    old.execute(
        "INSERT INTO listings (id, user_id, category, type, title, description, county, location, status, "
        "created_at, updated_at, attributes) VALUES (100001, 1, 'mobler', 'sell', 'Hjørnesofa', 'Pen og ren', "
        "'oslo', 'Frogner', 'active', '2026', '2026', '{}')"
    )
    old.execute(  # the old index kept its own copy of the text
        "INSERT INTO listings_fts (rowid, title, body, meta) VALUES (100001, 'Hjørnesofa', 'Pen og ren', 'Oslo')"
    )
    old.execute(
        "INSERT INTO listing_images (listing_id, filename, content_type, size_bytes, dhash, sha256, created_at) "
        "VALUES (100001, 'aa.webp', 'image/webp', 1, 'f0f0f0f00f0f0f0f', 'abc', '2026')"
    )
    old.commit()
    old.close()
    db = Database(path)
    db.init()
    with db.session() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert ids(conn, q="sofa", county="oslo") == [100001]
        assert ids(conn, q="frogner") == [100001]
        conn.execute("INSERT INTO listings_fts (listings_fts, rank) VALUES ('integrity-check', 1)")
        row = conn.execute("SELECT hash_a, hash_d FROM listing_images").fetchone()
        assert (row[0], row[1]) == (0xF0F0, 0x0F0F)
        assert conn.execute("SELECT deletion_notice_at FROM listings").fetchone()[0] is None


def test_old_listings_are_found_through_small_indexes(conn, seller):
    for n in range(3):
        listing_id = add(conn, seller, title=f"Gammel ting {n}")
        conn.execute(
            "UPDATE listings SET status = 'inactive', updated_at = '2000-01-01T00:00:00Z' WHERE id = ?",
            (listing_id,),
        )
    add(conn, seller, title="Aktiv ting")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    assert len(listings.mark_for_deletion(conn, 365)) == 3
    conn.execute("UPDATE listings SET deletion_notice_at = '2000-01-01T00:00:00Z' WHERE status = 'inactive'")
    assert listings.delete_marked_listings(conn)[0] == 3
    conn.set_trace_callback(None)
    finds = [sql for sql in statements if sql.startswith("SELECT id FROM listings")]
    plans = [" ".join(row["detail"] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")) for sql in finds]
    assert "idx_listings_idle" in plans[0] and "idx_listings_deletion" in plans[1]
    assert [row["title"] for row in conn.execute("SELECT title FROM listings")] == ["Aktiv ting"]


def test_sitemap_index_splits_listings(client, auth, monkeypatch):
    from fritorg import discovery

    monkeypatch.setattr(discovery, "SITEMAP_LISTINGS", 2)
    made = [make_listing(client, auth, title=f"Sykkel nummer {n}")["id"] for n in range(3)]
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    index = ET.fromstring(client.get("/sitemap.xml").content)
    files = [loc.text.rsplit("/", 1)[-1] for loc in index.findall("s:sitemap/s:loc", ns)]
    assert files[0] == "sitemap-sider.xml" and len(files) == 3
    urls = []
    for name in files[1:]:
        urls += [loc.text for loc in ET.fromstring(client.get(f"/{name}").content).findall("s:url/s:loc", ns)]
    assert [int(url.rsplit("/", 1)[-1]) for url in urls] == made
    pages = ET.fromstring(client.get("/sitemap-sider.xml").content)
    assert any(loc.text.endswith("/sok?category=bil") for loc in pages.findall("s:url/s:loc", ns))
    assert client.get("/sitemap-annonser-999.xml").status_code == 404


def test_photos_are_spread_over_folders(client, auth, settings):
    listing = make_listing(client, auth)
    image = client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("a.png", PHOTO, "image/png")},
        headers=auth,
    ).json()
    folder, name = image["url"].split("/uploads/", 1)[1].split("/")
    assert len(folder) == 2 and name.startswith(folder)
    assert (settings.uploads_dir / folder / name).exists()
    assert client.get(image["url"]).status_code == 200
    client.delete(f"/api/v1/listings/{listing['id']}/images/{image['id']}", headers=auth)
    assert not list(settings.uploads_dir.rglob("*.webp"))


def test_only_photo_names_are_ever_deleted(tmp_path):
    (tmp_path / "secret_key").write_text("x")
    (tmp_path / "ab").mkdir()
    (tmp_path / "ab" / "notes.txt").write_text("x")
    images.remove_files(tmp_path, ["../secret_key", "secret_key", "ab/notes.txt", "ab/../secret_key.webp"])
    assert (tmp_path / "secret_key").exists() and (tmp_path / "ab" / "notes.txt").exists()


def test_reused_photos_are_found_among_many(conn, seller):
    other = users.create_user(conn, "annen@example.no", "Annen", "hemmelig123")
    theirs = add(conn, other, title="Sykkel")
    mine = add(conn, seller, title="Sykkel")
    rng = random.Random(7)
    original = "a5c3f00f5aa53cc3"
    rows = [(f"{rng.getrandbits(64):016x}", f"{n:064x}") for n in range(3000)]
    rows.insert(1500, (original, "0" * 63 + "f"))
    for dhash, digest in rows:
        conn.execute(
            "INSERT INTO listing_images (listing_id, filename, content_type, size_bytes, sha256, dhash, hash_a, "
            "hash_b, hash_c, hash_d, created_at) VALUES (?, 'x.webp', 'image/webp', 1, ?, ?, ?, ?, ?, ?, '2026')",
            (theirs, digest, dhash, *images.hash_quarters(dhash)),
        )
    near = f"{int(original, 16) ^ 0b1000000100000000100000000000000000000000000000000000000000000001:016x}"
    assert images.reused_by_other_seller(conn, seller.id, "f" * 64, near)  # four bits apart
    assert images.reused_by_other_seller(conn, seller.id, "0" * 63 + "f", "0" * 16)  # the same file
    assert not images.reused_by_other_seller(conn, other.id, "f" * 64, near)  # the original seller
    assert not images.reused_by_other_seller(conn, seller.id, "e" * 64, "5a3c0ff0a55ac33c")
    assert mine


def test_uploads_can_live_in_their_own_folder(monkeypatch, tmp_path):
    from fritorg.config import Settings

    monkeypatch.setenv("FRITORG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRITORG_UPLOADS_DIR", str(tmp_path / "photos"))
    assert Settings.from_env().uploads_dir == tmp_path / "photos"
    monkeypatch.delenv("FRITORG_UPLOADS_DIR")
    assert Settings.from_env().uploads_dir == tmp_path / "data" / "uploads"


def test_statistics_are_refreshed_once_a_day(app, settings, monkeypatch):
    from fritorg import maintenance

    calls = []
    monkeypatch.setattr(maintenance, "analyze", lambda conn: calls.append(1))
    maintenance._analyzed.clear()
    maintenance.run(app.state.db, settings)
    maintenance.run(app.state.db, settings)
    assert calls == [1]
    assert database.analyze  # the real one is what the migration and maintenance use


def test_benchmark_uses_a_database_of_its_own(tmp_path):
    from fritorg import benchmark

    lines: list[str] = []
    results = benchmark.run(300, echo=lines.append)
    assert [name for name, _, _ in results] == [name for name, _ in benchmark.SEARCHES]
    assert any("kB per annonse" in line for line in lines)
    kept = tmp_path / "test.sqlite3"
    benchmark.run(100, keep=kept, echo=lambda line: None)
    with Database(kept).session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 100
        conn.execute("INSERT INTO listings_fts (listings_fts, rank) VALUES ('integrity-check', 1)")
