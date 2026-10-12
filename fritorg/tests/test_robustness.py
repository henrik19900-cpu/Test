"""Regression tests for problems found in review: bad input, alerts that must not get lost, unsubscribe
links for reused ids, listings published after they were written, and changed postal codes."""

from __future__ import annotations

from conftest import csrf, make_listing, register, web_login
from test_mcp import call

from fritorg import alerts, listings, maintenance, saved_searches
from fritorg.mailer import MemoryMailer
from fritorg.util import format_date_no


def _verify_all(app):
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")


def test_huge_numbers_are_refused_or_ignored(client, auth, other_auth):
    too_big = 10**20
    response = client.post("/api/v1/me/saved-searches", json={"q": "bil", "price_min": too_big}, headers=auth)
    assert response.status_code == 422
    response = client.post(
        "/api/v1/me/saved-searches", json={"q": "bil", "attr": ["condition:good"] * 21}, headers=auth
    )
    assert response.status_code == 422
    assert (
        call(client, "save_search", {"query": "bil", "price_max": too_big}, headers=auth)["isError"] is True
    )
    assert client.get("/api/v1/listings", params={"after_id": too_big}).status_code == 422
    assert client.get("/api/v1/listings", params={"price_max": too_big}).status_code == 422

    # The web is lenient: the impossible filter is left out.
    web_login(client)
    client.post("/lagrede-sok", data={"csrf_token": csrf(client), "query": f"q=sykkel&seller_id={too_big}"})
    [saved] = client.get("/api/v1/me/saved-searches", headers=auth).json()
    assert saved["query"] == {"q": "sykkel"}
    assert client.get(f"/sok?side={too_big}").status_code == 200
    assert client.get(f"/favoritter?side={too_big}").status_code == 200


def test_one_broken_search_does_not_stop_the_others(app, client, auth, other_auth, settings, monkeypatch):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    client.post("/api/v1/me/saved-searches", json={"q": "kaboom"}, headers=auth)  # Kari, the lower user id
    client.post("/api/v1/me/saved-searches", json={"q": "sykkel"}, headers=other_auth)
    _verify_all(app)
    per = {
        "Authorization": f"Bearer {register(client, email='per@example.no', name='Per Olsen')['token']['token']}"
    }
    make_listing(client, per, title="Sykkel kaboom", price=100)

    real_search = listings.search

    def failing(conn, params):
        if params.q == "kaboom":
            raise RuntimeError("broken search")
        return real_search(conn, params)

    monkeypatch.setattr(saved_searches.listings, "search", failing)
    report = maintenance.run(app.state.db, settings, memory, app.state.secret_key)
    alert_mail = [m.to for m in memory.outbox if "treff" in m.subject]
    assert report.alerts == 1 and alert_mail == ["ola@example.no"]
    with app.state.db.session() as conn:
        kari = conn.execute("SELECT alerted_at FROM saved_searches WHERE query = 'q=kaboom'").fetchone()
        assert kari["alerted_at"] is None  # left for the next round, not marked as sent
    monkeypatch.setattr(saved_searches.listings, "search", real_search)
    assert maintenance.run(app.state.db, settings, memory, app.state.secret_key).alerts == 1
    assert memory.outbox[-1].to == "kari@example.no"


def test_unsubscribe_links_do_not_work_for_a_reused_id(app, client, auth, other_auth):
    secret = app.state.secret_key
    created = client.post("/api/v1/me/saved-searches", json={"q": "privat"}, headers=auth).json()
    with app.state.db.session() as conn:
        stamp = conn.execute(
            "SELECT created_at FROM saved_searches WHERE id = ?", (created["id"],)
        ).fetchone()[0]
    token = alerts.unsubscribe_token(secret, "search", created["id"], stamp)
    assert client.get(f"/varsler/av?token={token}").status_code == 200
    client.delete(f"/api/v1/me/saved-searches/{created['id']}", headers=auth)
    with app.state.db.session() as conn:  # someone else's search gets the same id, a second later
        conn.execute(
            "INSERT INTO saved_searches (id, user_id, name, query, created_at) VALUES (?, 2, 'Ola', 'q=x', ?)",
            (created["id"], "2030-01-01T00:00:00Z"),
        )
    assert client.get(f"/varsler/av?token={token}").status_code == 404
    assert (
        client.post(f"/varsler/av?token={token}", data={"List-Unsubscribe": "One-Click"}).status_code == 404
    )
    with app.state.db.session() as conn:
        assert (
            conn.execute("SELECT notify FROM saved_searches WHERE id = ?", (created["id"],)).fetchone()[0]
            == 1
        )
    # Odd characters in a token are simply invalid.
    assert client.get("/varsler/av?token=s1.æøå").status_code == 404
    assert client.post("/varsler/av?token=p1.æøå", data={}).status_code == 404


def test_drafts_count_as_new_when_published(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    draft = make_listing(client, auth, title="Sykkel kladd", status="inactive")
    approved_later = make_listing(client, auth, title="Sykkel til kontroll", price=200)
    with app.state.db.session() as conn:  # as if it had been held for review from the start
        conn.execute(
            "UPDATE listings SET status = 'review', public_seq = NULL WHERE id = ?", (approved_later["id"],)
        )
    client.post("/api/v1/me/saved-searches", json={"q": "sykkel"}, headers=other_auth)
    _verify_all(app)
    [saved] = client.get("/api/v1/me/saved-searches", headers=other_auth).json()
    assert saved["new_count"] == 0

    client.patch(f"/api/v1/listings/{draft['id']}", json={"status": "active"}, headers=auth)
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET status = 'active' WHERE id = ?", (approved_later["id"],))
    [saved] = client.get("/api/v1/me/saved-searches", headers=other_auth).json()
    assert saved["new_count"] == 2
    new = client.get(saved["new_listings_url"], headers=other_auth).json()
    assert {item["id"] for item in new["items"]} == {draft["id"], approved_later["id"]}
    assert maintenance.run(app.state.db, settings, memory, app.state.secret_key).alerts == 1
    assert "Sykkel kladd" in memory.outbox[-1].body

    # Hiding and showing a listing again does not make it new once more.
    client.patch(f"/api/v1/listings/{draft['id']}", json={"status": "inactive"}, headers=auth)
    client.patch(f"/api/v1/me/saved-searches/{saved['id']}", json={"seen": True}, headers=other_auth)
    client.patch(f"/api/v1/listings/{draft['id']}", json={"status": "active"}, headers=auth)
    [saved] = client.get("/api/v1/me/saved-searches", headers=other_auth).json()
    assert saved["new_count"] == 0


def test_changing_the_postal_code_moves_the_listing(client, auth):
    listing = make_listing(client, auth, county=None, location=None, postal_code="0150")
    assert (listing["location"], listing["county"]) == ("Oslo", "oslo")
    moved = client.patch(
        f"/api/v1/listings/{listing['id']}", json={"postal_code": "5003"}, headers=auth
    ).json()
    assert (moved["location"], moved["county"]) == ("Bergen", "vestland")
    # A place the seller wrote stays.
    own = make_listing(client, auth, title="Sykkel nummer to", location="Grünerløkka", postal_code="0150")
    moved = client.patch(f"/api/v1/listings/{own['id']}", json={"postal_code": "5003"}, headers=auth).json()
    assert moved["location"] == "Grünerløkka" and moved["county"] == "vestland"


def test_line_breaks_never_reach_names_or_subjects(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    saved = client.post(
        "/api/v1/me/saved-searches",
        json={"q": "sykkel", "location": "Oslo\r\nBcc: x@example.no"},
        headers=other_auth,
    ).json()
    assert "\n" not in saved["name"] and "\r" not in saved["name"]
    _verify_all(app)
    make_listing(client, auth, title="Sykkel i Oslo", location="Oslo Bcc: x@example.no", price=100)
    maintenance.run(app.state.db, settings, memory, app.state.secret_key)
    assert all("\n" not in mail.subject for mail in memory.outbox)


def test_impossible_dates_do_not_break_pages():
    assert format_date_no("2026-02-30") == "2026-02-30"
    assert format_date_no("2026-02-28").startswith("28.")


def test_price_alerts_for_favourites_saved_without_a_price(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    listing = make_listing(client, auth, price=None)
    client.put(f"/api/v1/me/favorites/{listing['id']}", headers=other_auth)
    _verify_all(app)
    client.patch(f"/api/v1/listings/{listing['id']}", json={"price": 5000}, headers=auth)
    assert (
        maintenance.run(app.state.db, settings, memory, app.state.secret_key).price_drops == 0
    )  # first price
    client.patch(f"/api/v1/listings/{listing['id']}", json={"price": 4000}, headers=auth)
    assert maintenance.run(app.state.db, settings, memory, app.state.secret_key).price_drops == 1


def test_own_listings_are_not_announced(app, client, auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    client.post("/api/v1/me/saved-searches", json={"q": "sykkel"}, headers=auth)
    _verify_all(app)
    make_listing(client, auth, title="Min egen sykkel", price=100)
    [saved] = client.get("/api/v1/me/saved-searches", headers=auth).json()
    assert saved["new_count"] == 0
    assert maintenance.run(app.state.db, settings, memory, app.state.secret_key).alerts == 0
