from __future__ import annotations

from conftest import csrf, make_listing, register, web_login

from fritorg import listings, maintenance
from fritorg.mailer import MemoryMailer
from fritorg.util import iso_in


def test_listings_expire_and_can_be_renewed(app, client, auth, settings):
    listing = make_listing(client, auth)
    assert listing["expires_at"][:10] == iso_in(days=settings.listing_days)[:10]

    memory = MemoryMailer(settings)
    app.state.mailer = memory
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
        conn.execute("UPDATE listings SET expires_at = '2001-01-01T00:00:00Z'")
    report = maintenance.run(app.state.db, settings, memory)
    assert report.expired == 1
    assert client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()["status"] == "inactive"
    assert client.get("/api/v1/listings").json()["total"] == 0
    assert "utløpt" in memory.outbox[0].subject and f"/annonse/{listing['id']}" in memory.outbox[0].body

    renewed = client.patch(
        f"/api/v1/listings/{listing['id']}", json={"status": "active"}, headers=auth
    ).json()
    assert (
        renewed["status"] == "active"
        and renewed["expires_at"][:10] == iso_in(days=settings.listing_days)[:10]
    )
    assert maintenance.run(app.state.db, settings, memory).expired == 0


def test_owners_are_offered_to_renew_in_the_last_week(app, client):
    user_id = register(client)["account"]["id"]
    web_login(client)
    with app.state.db.session() as conn:
        listing_id = listings.create_listing(
            conn,
            user_id,
            {"category": "mobler", "title": "Spisebord", "description": "Pent brukt spisebord i eik."},
            active_days=3,
        )
    page = client.get(f"/annonse/{listing_id}").text
    assert "Forny annonsen" in page and "Aktiv til" in page
    client.post(f"/annonse/{listing_id}/status", data={"csrf_token": csrf(client), "status": "active"})
    with app.state.db.session() as conn:
        expires = conn.execute("SELECT expires_at FROM listings WHERE id = ?", (listing_id,)).fetchone()[0]
    assert expires[:10] == iso_in(days=60)[:10]
    assert "Forny annonsen" not in client.get(f"/annonse/{listing_id}").text


def test_no_expiry_when_turned_off(app, client, auth, settings):
    settings.listing_days = 0
    listing = make_listing(client, auth)
    assert listing["expires_at"] is None


def test_purge_removes_what_is_no_longer_needed(app, client):
    register(client)
    with app.state.db.session() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES ('old', 1, '2000-01-01T00:00:00Z', '2000-02-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO phone_codes (user_id, phone_hash, phone_hint, code_hash, created_at, expires_at) "
            "VALUES (1, 'h', '+47 •••••567', 'c', '2000-01-01T00:00:00Z', '2000-01-01T00:10:00Z')"
        )
        assert maintenance.purge(conn) == 2
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = 'old'").fetchone()[0] == 0
