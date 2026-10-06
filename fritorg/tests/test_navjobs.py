from __future__ import annotations

import json
from datetime import timedelta
from email.utils import parsedate_to_datetime

import pytest
from fastapi.testclient import TestClient
from test_mcp import call

from fritorg import navjobs, ops
from fritorg.app import create_app
from fritorg.config import Settings
from fritorg.navjobs import HttpResponse
from fritorg.util import utcnow

BASE = "https://feed.test"
FUTURE = "2099-01-01T00:00:00+01:00"


def line(uuid: str, status: str = "ACTIVE", ts: str = "2026-10-05T12:00:00.000001+02:00") -> dict:
    return {
        "id": uuid,
        "url": f"/api/v1/feedentry/{uuid}",
        "title": "Stilling",
        "_feed_entry": {"uuid": uuid, "status": status, "title": "Stilling", "sistEndret": ts},
    }


def ad(uuid: str, **overrides) -> dict:
    content = {
        "uuid": uuid,
        "published": "2026-10-05T00:00:00+02:00",
        "expires": FUTURE,
        "updated": "2026-10-05T12:00:00+02:00",
        "workLocations": [
            {"country": "NORGE", "address": "Prinsens gate 1", "city": "TRONDHEIM", "postalCode": "7030",
             "county": "TRØNDELAG", "municipal": "TRONDHEIM"}
        ],
        "contactList": [{"name": "Kari Kontakt", "phone": "99999999", "email": "kari@sykehus.example"}],
        "title": "Sykepleier i turnus",
        "description": "<p>Vi søker en <strong>sykepleier</strong>.</p><ul><li>Turnus</li><li>God opplæring</li></ul>",
        "applicationUrl": f"https://jobb.example/apply/{uuid}",
        "applicationDue": "2099-01-01T00:00:00",
        "occupationCategories": [{"level1": "Helse og sosial", "level2": "Sykepleier"}],
        "jobtitle": "Sykepleier",
        "link": f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}",
        "employer": {"name": "St. Olavs hospital", "orgnr": "883974832", "description": "<p>Et stort sykehus.</p>"},
        "engagementtype": "Fast",
        "extent": "Heltid",
        "starttime": "Etter avtale",
        "positioncount": "2",
        "sector": "Offentlig",
    }  # fmt: skip
    content.update(overrides)
    return {
        "uuid": uuid,
        "status": "ACTIVE",
        "sistEndret": "2026-10-05T12:00:00.000001+02:00",
        "ad_content": content,
    }


class FakeNav:
    """Nav's feed in memory: pages of lines, full entries, and the public token."""

    def __init__(self):
        self.pages: dict[str, dict] = {}
        self.first = "p1"
        self.entries: dict[str, dict] = {}
        self.token = "token-1"
        self.requests: list[tuple[str, dict]] = []
        self.fail_pages = False

    def page(self, page_id: str, items: list[dict], next_id: str | None = None) -> None:
        self.pages[page_id] = {"id": page_id, "items": items, "next_id": next_id}

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        path = url.removeprefix(BASE)
        self.requests.append((path, headers))
        if path == "/api/publicToken":
            return HttpResponse(
                200, {}, f"Current public token for Nav Job Vacancy Feed:\n{self.token}\n".encode()
            )
        if headers.get("Authorization") != f"Bearer {self.token}":
            return HttpResponse(401, {}, b"")
        if path.startswith("/api/v1/feedentry/"):
            entry = self.entries.get(path.rsplit("/", 1)[1])
            return HttpResponse(200, {}, json.dumps(entry).encode()) if entry else HttpResponse(404, {}, b"")
        if self.fail_pages:
            return HttpResponse(500, {}, b"")
        page_id = self.first if path == "/api/v1/feed" else path.rsplit("/", 1)[1]
        page = self.pages[page_id]
        etag = f'"{page_id}-{len(page["items"])}"'
        if headers.get("If-None-Match") == etag and headers.get("If-Modified-Since"):
            return HttpResponse(304, {}, b"")
        meta = {"etag": etag, "last-modified": "Mon, 05 Oct 2026 10:00:00 GMT"}
        return HttpResponse(200, meta, json.dumps(page).encode())

    def fetched(self) -> list[str]:
        return [path for path, _ in self.requests if path.startswith("/api/v1/feedentry/")]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", bankid_mode="off", verification="none", nav_feed_url=BASE)


@pytest.fixture
def nav() -> FakeNav:
    fake = FakeNav()
    fake.page("p1", [line("a"), line("b"), line("c"), line("c", "INACTIVE")], next_id="p2")
    fake.page("p2", [line("a", ts="2026-10-05T13:00:00.000001+02:00")])
    fake.entries = {"a": ad("a"), "b": ad("b", title="Helsefagarbeider")}
    return fake


def run(app, nav, **kwargs) -> navjobs.SyncReport:
    return navjobs.sync(app.state.db, app.state.settings, http=nav, **kwargs)


def imported(app) -> dict[str, dict]:
    with app.state.db.session() as conn:
        rows = conn.execute("SELECT * FROM listings WHERE source = 'nav'").fetchall()
    return {row["source_id"]: dict(row) for row in rows}


def test_html_to_text():
    html = "<p>Vi søker <strong>deg</strong>!</p><ul>\n <li>Én</li>\n <li>To</li></ul><p>Søk&nbsp;nå<br>i dag</p><script>x()</script>"
    assert navjobs.html_to_text(html) == "Vi søker deg!\n\n- Én\n- To\n\nSøk nå\ni dag"
    assert navjobs.html_to_text(None) == ""
    nested = "<p>Vi ser etter:</p><ul><li><p>Serviceinnstilt</p></li><li><p>Positiv</p><p>og blid</p></li></ul><p>Slutt</p>"
    assert navjobs.html_to_text(nested) == "Vi ser etter:\n\n- Serviceinnstilt\n- Positiv og blid\n\nSlutt"
    unclosed = "<ul><li>Én<li>To</ul><p>Etter</p><p>listen</p>"
    assert navjobs.html_to_text(unclosed) == "- Én\n- To\n\nEtter\n\nlisten"


def test_places_categories_and_employment_types():
    assert navjobs.place_name("MO I RANA") == "Mo i Rana"
    assert navjobs.place_name("AURSKOG-HØLAND") == "Aurskog-Høland"
    assert navjobs.place_name("NORE OG UVDAL") == "Nore og Uvdal"
    category = navjobs.category_for
    assert category({"occupationCategories": [{"level1": "IT", "level2": "Utvikling"}]}) == "jobb-it"
    assert category({"occupationCategories": [{"level1": "Kontor og økonomi"}]}) == "jobb-kontor"
    assert category({"occupationCategories": [{"level1": "Transport og lager"}]}) == "jobb-transport"
    assert category({"occupationCategories": [{"level1": "Industri og produksjon"}]}) == "jobb-industri"
    assert category({"occupationCategories": [{"level1": "Sikkerhet og beredskap"}]}) == "jobb-annet"
    assert category({}) == "jobb-annet"
    assert navjobs.employment_type("Vikariat", "Heltid") == "temporary"
    assert navjobs.employment_type("Fast", "Deltid") == "part_time"
    assert navjobs.employment_type("Fast", "Heltid") == "full_time"
    assert navjobs.employment_type("Sesong", None) == "seasonal"
    assert navjobs.employment_type(None, None) is None


def test_map_ad():
    values = navjobs.map_ad(ad("a")["ad_content"])
    assert values["category"] == "jobb-helse" and values["type"] == "job" and values["price"] is None
    assert (
        values["county"] == "trondelag"
        and values["location"] == "Trondheim"
        and values["postal_code"] == "7030"
    )
    assert values["attributes"] == {
        "employer": "St. Olavs hospital",
        "employment_type": "full_time",
        "deadline": "2099-01-01",
    }
    text = values["description"]
    assert text.startswith("Vi søker en sykepleier.\n\n- Turnus\n- God opplæring")
    assert "Om arbeidsgiveren\n\nEt stort sykehus." in text and "Antall stillinger: 2" in text
    assert "Kari Kontakt" not in text and "99999999" not in text  # contact persons are not imported

    abroad = navjobs.map_ad(
        ad("x", workLocations=[{"country": "SVERIGE", "city": "STOCKHOLM"}], applicationDue="Snarest")[
            "ad_content"
        ]
    )
    assert abroad["county"] is None and abroad["location"] == "Stockholm, Sverige"
    assert "deadline" not in abroad["attributes"] and "Søknadsfrist: Snarest" in abroad["description"]


def test_sync_imports_updates_and_removes(app, client, nav, auth):
    report = run(app, nav)
    assert (report.created, report.removed, report.caught_up, report.waiting) == (2, 0, True, 0)
    assert set(imported(app)) == {"a", "b"}  # "c" became inactive before it was ever imported
    assert sorted(nav.fetched()) == ["/api/v1/feedentry/a", "/api/v1/feedentry/b"]

    # Nothing new: the newest page answers 304 and no ad is fetched.
    nav.requests.clear()
    report = run(app, nav)
    assert report.caught_up and report.fetched == 0 and report.pages == 0

    # An ad ends and another changes: removed at once, updated after one fetch.
    nav.pages["p2"]["items"] += [line("b", "INACTIVE"), line("a", ts="2026-10-05T14:00:00.000001+02:00")]
    nav.entries["a"] = ad("a", title="Sykepleier, natt")
    nav.entries["a"]["sistEndret"] = "2026-10-05T14:00:00.000001+02:00"
    nav.requests.clear()
    report = run(app, nav)
    assert (report.removed, report.updated) == (1, 1)
    assert set(imported(app)) == {"a"} and imported(app)["a"]["title"] == "Sykepleier, natt"
    # The changed page was read again without conditions, so no line could be filtered away.
    page_reads = [headers for path, headers in nav.requests if path == "/api/v1/feed/p2"]
    assert len(page_reads) == 2 and "If-None-Match" not in page_reads[1]

    listing_id = imported(app)["a"]["id"]
    data = client.get(f"/api/v1/listings/{listing_id}").json()
    assert data["source"]["id"] == "nav" and data["source"]["apply_url"] == "https://jobb.example/apply/a"
    assert data["links"]["apply"] == "https://jobb.example/apply/a" and "contact_seller" not in data["links"]
    assert data["seller"]["new_account"] is False and data["created_via"] == "import"
    contact = client.post(
        "/api/v1/conversations", json={"listing_id": listing_id, "message": "Hei!"}, headers=auth
    )
    assert contact.status_code == 422 and "arbeidsplassen.no" in contact.json()["detail"]


def test_listing_page_and_search(app, client, nav):
    run(app, nav)
    listing_id = imported(app)["a"]["id"]
    page = client.get(f"/annonse/{listing_id}").text
    assert 'href="https://jobb.example/apply/a"' in page and "Søk på stillingen" in page
    assert "Fra arbeidsplassen.no (Nav)" in page and "Trygg jobbsøking" in page
    assert "/melding" not in page and "Rediger annonsen" not in page
    found = client.get("/api/v1/listings", params={"q": "helsefagarbeider", "category": "jobb"}).json()
    assert found["total"] == 1 and found["items"][0]["source"] == "nav"
    assert "Sykepleier i turnus" in client.get("/sok?category=jobb-helse").text
    markdown = client.get(f"/annonse/{listing_id}.md").text
    assert "**Søk på stillingen:** https://jobb.example/apply/a" in markdown
    hits = call(client, "search_listings", {"query": "sykepleier"})["structuredContent"]["items"]
    assert hits[0]["apply_url"] == "https://jobb.example/apply/a"


def test_imported_ads_stay_out_of_bulk_export_and_home(app, client, nav):
    run(app, nav)
    export = client.get("/api/v1/export/listings.ndjson").text
    assert "Sykepleier" not in export
    assert "Sykepleier i turnus" not in client.get("/").text
    assert "Sykepleier i turnus" in client.get("/sok").text


def test_unsafe_links_and_expired_ads(app, nav):
    nav.entries["a"] = ad("a", applicationUrl="javascript:alert(1)")
    nav.entries["b"] = ad("b", expires="2001-01-01T00:00:00+01:00")
    run(app, nav)
    rows = imported(app)
    assert set(rows) == {"a"}  # an ad that has already expired is not imported
    assert rows["a"]["apply_url"] == "https://arbeidsplassen.nav.no/stillinger/stilling/a"

    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET expires_at = '2001-01-01T00:00:00Z' WHERE source = 'nav'")
    assert run(app, nav).removed == 1 and imported(app) == {}


def test_moderator_removal_survives_updates(app, nav):
    run(app, nav)
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET status = 'removed' WHERE source_id = 'a'")
        conn.execute("UPDATE listings SET status = 'review' WHERE source_id = 'b'")  # reported by users
    nav.pages["p2"]["items"] += [
        line("a", ts="2026-10-06T09:00:00.000001+02:00"),
        line("b", ts="2026-10-06T09:00:00.000001+02:00"),
    ]
    nav.entries["a"]["sistEndret"] = nav.entries["b"]["sistEndret"] = "2026-10-06T09:00:00.000001+02:00"
    assert run(app, nav).updated == 2
    assert imported(app)["a"]["status"] == "removed" and imported(app)["b"]["status"] == "review"


def test_backfill_starts_six_months_back_and_continues_in_runs(app, nav):
    report = run(app, nav, max_pages=1, max_fetches=1)
    assert not report.caught_up and report.fetched == 1 and report.waiting == 1
    since = parsedate_to_datetime(nav.requests[1][1]["If-Modified-Since"])  # after the token request
    assert abs((utcnow() - since) - timedelta(days=navjobs.BACKFILL_DAYS)) < timedelta(minutes=5)
    report = run(app, nav)
    assert report.done and set(imported(app)) == {"a", "b"}


def test_public_token_is_cached_and_renewed(app, nav):
    run(app, nav)
    assert [path for path, _ in nav.requests].count("/api/publicToken") == 1
    nav.token = "token-2"  # Nav rotates the public token
    nav.requests.clear()
    run(app, nav)
    assert [path for path, _ in nav.requests].count("/api/publicToken") == 1

    nav.requests.clear()
    app.state.settings.nav_token = "token-2"  # a production token is used as it is
    run(app, nav)
    assert all(path != "/api/publicToken" for path, _ in nav.requests)


def test_one_import_at_a_time_and_errors_are_recorded(app, nav):
    with app.state.db.session() as conn:
        conn.execute("INSERT INTO import_state (source, lease_until) VALUES ('nav', '2999-01-01T00:00:00Z')")
    assert run(app, nav).skipped
    with app.state.db.session() as conn:
        conn.execute("UPDATE import_state SET lease_until = NULL")

    nav.fail_pages = True
    with pytest.raises(navjobs.FeedError):
        run(app, nav)
    app.state.settings.nav_import = True
    checks = ops.doctor(app.state.settings)
    assert any(c.ok is False and "HTTP 500" in c.text for c in checks)
    assert any(c.ok is None and "nav.team.arbeidsplassen@nav.no" in c.text for c in checks)
    nav.fail_pages = False
    run(app, nav)
    assert any(c.ok and "2 stillinger fra Nav" in c.text for c in ops.doctor(app.state.settings))


def test_background_importer_runs_with_the_app(tmp_path, nav, monkeypatch):
    monkeypatch.setattr(navjobs, "http_get", nav)
    settings = Settings(data_dir=tmp_path, verification="none", nav_feed_url=BASE, nav_import=True)
    app = create_app(settings)
    with TestClient(app):
        scheduler = app.state.importer
        assert scheduler is not None and [job.name for job in scheduler.jobs] == ["nav"]
        for _ in range(50):
            if len(imported(app)) == 2:
                break
            scheduler._stop.wait(0.1)
    assert set(imported(app)) == {"a", "b"}
    assert not scheduler._thread.is_alive()
