"""Favourites and saved searches: API, MCP tools, web pages and e-mail alerts."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from conftest import csrf, make_listing, register, web_login
from test_mcp import call, rpc

from fritorg import maintenance, saved_searches
from fritorg.mailer import MemoryMailer


def test_favourites_api(client, auth, other_auth):
    listing = make_listing(client, auth)
    other = make_listing(client, auth, title="Racersykkel Bianchi", price=9000)
    lid = listing["id"]

    assert client.put(f"/api/v1/me/favorites/{lid}", headers=other_auth).status_code == 204
    assert client.put(f"/api/v1/me/favorites/{lid}", headers=other_auth).status_code == 204  # idempotent
    assert client.put(f"/api/v1/me/favorites/{other['id']}", headers=other_auth).status_code == 204
    saved = client.get("/api/v1/me/favorites", headers=other_auth).json()
    assert saved["total"] == 2 and [i["id"] for i in saved["items"]] == [other["id"], lid]

    # Sold listings stay; hidden ones are no longer shown, and unknown ones cannot be saved.
    client.patch(f"/api/v1/listings/{lid}", json={"status": "sold"}, headers=auth)
    client.patch(f"/api/v1/listings/{other['id']}", json={"status": "inactive"}, headers=auth)
    saved = client.get("/api/v1/me/favorites", headers=other_auth).json()
    assert [(i["id"], i["status"]) for i in saved["items"]] == [(lid, "sold")]
    assert client.put(f"/api/v1/me/favorites/{other['id']}", headers=other_auth).status_code == 404
    assert client.put("/api/v1/me/favorites/999999", headers=other_auth).status_code == 404

    assert client.delete(f"/api/v1/me/favorites/{lid}", headers=other_auth).status_code == 204
    assert client.get("/api/v1/me/favorites", headers=other_auth).json()["total"] == 0
    assert client.get("/api/v1/me/favorites").status_code == 401

    # Deleting a listing removes it from favourites too.
    client.put(f"/api/v1/me/favorites/{lid}", headers=other_auth)
    client.delete(f"/api/v1/listings/{lid}", headers=auth)
    assert client.get("/api/v1/me/favorites", headers=other_auth).json()["total"] == 0


def test_saved_search_counts_new_matches(client, auth, other_auth):
    make_listing(client, auth)  # exists before the search is saved: not new
    response = client.post(
        "/api/v1/me/saved-searches",
        json={"q": "sykkel", "county": "oslo", "price_max": 10000, "attr": ["condition:good"]},
        headers=other_auth,
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["name"] == "«sykkel», Oslo, under 10\u00a0000\u00a0kr, Tilstand: Pent brukt"
    assert saved["new_count"] == 0 and saved["notify"] is True
    assert saved["query"] == {"q": "sykkel", "county": "oslo", "price_max": 10000, "attr": ["condition:good"]}

    again = client.post(
        "/api/v1/me/saved-searches",
        json={
            "county": "oslo",
            "q": "sykkel",
            "price_max": 10000,
            "attr": ["condition:good"],
            "notify": False,
        },
        headers=other_auth,
    )
    assert again.status_code == 200 and again.json()["id"] == saved["id"] and again.json()["notify"] is False

    new = make_listing(client, auth, title="Barnesykkel 20 tommer", price=900)
    make_listing(client, auth, title="Barnesykkel i Bergen", county="vestland", price=900)  # no match
    [listed] = client.get("/api/v1/me/saved-searches", headers=other_auth).json()
    assert listed["new_count"] == 1
    new_items = client.get(listed["new_listings_url"]).json()["items"]
    assert [i["id"] for i in new_items] == [new["id"]]
    assert client.get(listed["listings_url"]).json()["total"] == 2

    seen = client.patch(f"/api/v1/me/saved-searches/{saved['id']}", json={"seen": True}, headers=other_auth)
    assert seen.json()["new_count"] == 0
    assert client.get(seen.json()["new_listings_url"]).json()["total"] == 0

    bad = client.post("/api/v1/me/saved-searches", json={}, headers=other_auth)
    assert bad.status_code == 422
    unknown = client.post("/api/v1/me/saved-searches", json={"category": "finnes-ikke"}, headers=other_auth)
    assert unknown.status_code == 422
    assert client.delete(f"/api/v1/me/saved-searches/{saved['id']}", headers=auth).status_code == 404
    assert client.delete(f"/api/v1/me/saved-searches/{saved['id']}", headers=other_auth).status_code == 204
    assert client.get("/api/v1/me/saved-searches", headers=other_auth).json() == []


def test_after_id_filter(client, auth):
    first = make_listing(client, auth)
    second = make_listing(client, auth, title="Sykkelhjelm", price=300)
    result = client.get("/api/v1/listings", params={"after_id": first["id"]}).json()
    assert [i["id"] for i in result["items"]] == [second["id"]]


def test_mcp_favourites_and_saved_searches(client, auth, other_auth):
    listing = make_listing(client, auth)
    names = {t["name"] for t in rpc(client, "tools/list", headers=other_auth).json()["result"]["tools"]}
    assert {"save_favorite", "list_favorites", "save_search", "check_saved_searches"} <= names

    saved = call(client, "save_favorite", {"listing_id": listing["id"]}, headers=other_auth)[
        "structuredContent"
    ]
    assert saved["saved"] is True and saved["changed"] is True
    favourites = call(client, "list_favorites", headers=other_auth)["structuredContent"]
    assert [i["id"] for i in favourites["items"]] == [listing["id"]]
    removed = call(client, "save_favorite", {"listing_id": listing["id"], "remove": True}, headers=other_auth)
    assert removed["structuredContent"]["saved"] is False

    created = call(
        client, "save_search", {"query": "sykkel", "attributes": {"condition": "good"}}, headers=other_auth
    )["structuredContent"]
    assert created["created"] is True and "check_saved_searches" in created["next_steps"]
    new = make_listing(client, auth, title="Sykkel til salgs", price=500)
    checked = call(client, "check_saved_searches", headers=other_auth)["structuredContent"]
    [entry] = checked["saved_searches"]
    assert entry["new_count"] == 1 and [i["id"] for i in entry["new_listings"]] == [new["id"]]
    again = call(client, "check_saved_searches", headers=other_auth)["structuredContent"]
    assert again["saved_searches"][0]["new_count"] == 0  # marked as seen

    deleted = call(client, "delete_saved_search", {"saved_search_id": created["id"]}, headers=other_auth)
    assert deleted["structuredContent"]["deleted"] is True
    assert (
        call(client, "check_saved_searches", headers=other_auth)["structuredContent"]["saved_searches"] == []
    )


def test_web_favourites_and_saved_searches(app, client, auth):
    listing = make_listing(client, auth)
    register(client, email="ola@example.no", name="Ola Hansen")

    # Logged out: saving asks for a login and comes back.
    response = client.post(
        f"/annonse/{listing['id']}/favoritt", data={"csrf_token": csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"].startswith("/logg-inn?neste=")

    web_login(client, email="ola@example.no")
    page = client.get(f"/annonse/{listing['id']}").text
    assert "Lagre som favoritt" in page
    response = client.post(
        f"/annonse/{listing['id']}/favoritt",
        data={"csrf_token": csrf(client), "action": "add", "neste": "/sok?q=sykkel#a1"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/sok?q=sykkel#a1"
    assert "Fjern fra favoritter" in client.get(f"/annonse/{listing['id']}").text
    assert listing["title"] in client.get("/favoritter").text
    assert "Fjern fra favoritter" in client.get("/sok?q=sykkel").text  # the card's heart is filled

    # Save the search from the search page.
    search = client.get("/sok?q=sykkel&county=oslo&sort=price_asc").text
    assert "Lagre søket" in search
    response = client.post(
        "/lagrede-sok",
        data={"csrf_token": csrf(client), "query": "q=sykkel&county=oslo"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/sok?q=sykkel&county=oslo"
    assert "Søket er lagret" in client.get("/sok?q=sykkel&county=oslo").text

    new = make_listing(client, auth, title="Sykkel for barn", price=700)
    overview = client.get("/lagrede-sok").text
    assert "«sykkel», Oslo" in overview and "1 ny" in overview
    with app.state.db.session() as conn:
        [saved] = saved_searches.list_for(conn, 2)
    opened = client.get(f"/lagrede-sok/{saved.id}", follow_redirects=False)
    target = urlparse(opened.headers["location"])
    assert target.path == "/sok" and parse_qs(target.query)["sort"] == ["newest"]
    results = client.get(opened.headers["location"]).text
    assert results.count("card-new") == 1 and f'id="a{new["id"]}"' in results
    assert "1 ny" not in client.get("/lagrede-sok").text

    client.post(f"/lagrede-sok/{saved.id}/varsel", data={"csrf_token": csrf(client), "notify": "0"})
    with app.state.db.session() as conn:
        assert saved_searches.get(conn, 2, saved.id).notify is False
    client.post(f"/lagrede-sok/{saved.id}/slett", data={"csrf_token": csrf(client)})
    assert "Du har ingen lagrede søk" in client.get("/lagrede-sok").text


def test_owner_sees_how_many_saved_the_listing(client, auth, other_auth):
    listing = make_listing(client, auth)
    client.put(f"/api/v1/me/favorites/{listing['id']}", headers=other_auth)
    web_login(client)
    assert "1 har lagret annonsen" in client.get(f"/annonse/{listing['id']}").text


def test_alert_emails(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    secret = app.state.secret_key
    client.post("/api/v1/me/saved-searches", json={"q": "sykkel"}, headers=other_auth)
    client.post("/api/v1/me/saved-searches", json={"category": "sykler"}, headers=other_auth)
    with app.state.db.session() as conn:
        conn.execute(
            "UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z' WHERE email = 'ola@example.no'"
        )

    assert maintenance.run(app.state.db, settings, memory, secret).alerts == 0  # nothing new yet
    first = make_listing(client, auth, title="Sykkel nummer én", price=1000)
    assert maintenance.run(app.state.db, settings, memory, secret).alerts == 1
    [mail] = memory.outbox
    assert mail.to == "ola@example.no" and mail.subject == "Nye treff i 2 lagrede søk"
    assert (
        f"/annonse/{first['id']}" in mail.body
        and "Sykkel nummer én (1 000 kr, Majorstuen, Oslo)" in mail.body
    )
    assert mail.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    # At most one e-mail per search per hour: new matches wait, and are not announced twice.
    make_listing(client, auth, title="Sykkel nummer to", price=2000)
    assert maintenance.run(app.state.db, settings, memory, secret).alerts == 0
    with app.state.db.session() as conn:
        conn.execute("UPDATE saved_searches SET alerted_at = '2001-01-01T00:00:00Z'")
    assert maintenance.run(app.state.db, settings, memory, secret).alerts == 1
    body = memory.outbox[-1].body
    assert "Sykkel nummer to" in body and "Sykkel nummer én" not in body

    # The one-click unsubscribe link in the header turns all alerts off, without logging in.
    link = mail.headers["List-Unsubscribe"].strip("<>")
    path = link[link.index("/varsler/av") :]
    confirm = client.get(path)
    assert confirm.status_code == 200 and "alle de lagrede søkene dine" in confirm.text
    response = client.post(path, data={"List-Unsubscribe": "One-Click"})
    assert response.status_code == 200 and response.text == "ok"
    with app.state.db.session() as conn:
        assert {s.notify for s in saved_searches.list_for(conn, 2)} == {False}
    assert client.get("/varsler/av?token=s1.feil").status_code == 404

    # Unverified addresses get nothing.
    with app.state.db.session() as conn:
        conn.execute("UPDATE saved_searches SET notify = 1, alerted_at = NULL")
        conn.execute("UPDATE users SET email_verified_at = NULL")
    make_listing(client, auth, title="Sykkel nummer tre", price=3000)
    assert maintenance.run(app.state.db, settings, memory, secret).alerts == 0


def test_canonical_query_and_names():
    from fritorg.listings import params_from_query

    params = params_from_query(
        [
            ("q", "  Sofa  "),
            ("category", "mobler"),
            ("side", "3"),
            ("sort", "newest"),
            ("price_min", "100"),
            ("price_max", "2000"),
            ("finnes", "ikke"),
        ]
    )
    assert saved_searches.canonical_query(params) == "q=Sofa&category=mobler&price_min=100&price_max=2000"
    assert saved_searches.describe(params) == "«Sofa», Møbler og interiør, 100–2\u00a0000\u00a0kr"
    assert saved_searches.canonical_query(params_from_query([("sort", "newest")])) == ""


def test_price_drop_alerts(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    secret = app.state.secret_key
    listing = make_listing(client, auth)  # 6 500 kr
    lid = listing["id"]
    client.put(f"/api/v1/me/favorites/{lid}", headers=other_auth)
    with app.state.db.session() as conn:
        conn.execute(
            "UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z' WHERE email = 'ola@example.no'"
        )

    def run():
        return maintenance.run(app.state.db, settings, memory, secret).price_drops

    client.patch(f"/api/v1/listings/{lid}", json={"price": 6400}, headers=auth)
    assert run() == 0  # a small change is not worth an e-mail
    client.patch(f"/api/v1/listings/{lid}", json={"price": 5000}, headers=auth)
    assert run() == 1
    mail = memory.outbox[-1]
    assert mail.subject == "Prisen er satt ned: «Terrengsykkel Trek Marlin 7»"
    assert "5 000 kr (før 6 500 kr)" in mail.body and f"/annonse/{lid}" in mail.body
    assert run() == 0  # each drop once

    client.patch(f"/api/v1/listings/{lid}", json={"price": 4000}, headers=auth)
    assert run() == 0  # at most one e-mail every 12 hours
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET price_alerted_at = '2001-01-01T00:00:00Z'")
    assert run() == 1 and "4 000 kr (før 5 000 kr)" in memory.outbox[-1].body

    # The favourites page shows the price when it was saved.
    web_login(client, email="ola@example.no")
    page = client.get("/favoritter").text
    assert "<s>6 500 kr</s>" in page and "Du får e-post når prisen settes ned" in page

    # The link in the e-mail turns price alerts off.
    link = mail.headers["List-Unsubscribe"].strip("<>")
    assert client.post(link[link.index("/varsler/av") :], data={"List-Unsubscribe": "One-Click"}).text == "ok"
    assert "E-post når prisen settes ned er slått av" in client.get("/favoritter").text
    client.patch(f"/api/v1/listings/{lid}", json={"price": 2000}, headers=auth)
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET price_alerted_at = NULL")
    assert run() == 0
    client.post("/favoritter/varsel", data={"csrf_token": csrf(client), "price_alerts": "1"})
    assert run() == 1


def test_databases_from_earlier_versions_are_upgraded(tmp_path):
    import sqlite3

    from fritorg.db import MIGRATIONS, SCHEMA_V1, Database

    # The first schema, and the first schema as it was for a while: with favourites and saved
    # searches, but without the price columns.
    briefly = """
    CREATE TABLE favorites (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, listing_id)
    ) WITHOUT ROWID;
    CREATE INDEX idx_favorites_listing ON favorites(listing_id);
    CREATE TABLE saved_searches (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, query TEXT NOT NULL, notify INTEGER NOT NULL DEFAULT 1,
        seen_id INTEGER NOT NULL DEFAULT 0, alerted_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, alerted_at TEXT
    );
    CREATE UNIQUE INDEX idx_saved_searches_user_query ON saved_searches(user_id, query);
    """
    for name, extra in (("first", ""), ("briefly", briefly)):
        path = tmp_path / f"{name}.sqlite3"
        conn = sqlite3.connect(path)
        conn.executescript(f"BEGIN;\n{SCHEMA_V1}\n{extra}\nPRAGMA user_version = 1;\nCOMMIT;")
        conn.close()
        db = Database(path)
        db.init()
        with db.session() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
            assert {"price", "notified_price"} <= {r[1] for r in conn.execute("PRAGMA table_info(favorites)")}
            assert "price_alerts" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            assert conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0] == 0
