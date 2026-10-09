from __future__ import annotations

from conftest import PHOTO, csrf, make_listing, register, web_login

from fritorg import listings, maintenance
from fritorg.mailer import MemoryMailer
from fritorg.util import format_days_no, iso_ago, iso_in


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


def _hide(client, auth, listing_id, status="inactive"):
    response = client.patch(f"/api/v1/listings/{listing_id}", json={"status": status}, headers=auth)
    assert response.status_code == 200, response.text


def _last_changed(app, listing_id, days_ago):
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET updated_at = ? WHERE id = ?", (iso_ago(days=days_ago), listing_id))


def _told(app, listing_id, days_ago):
    """Pretend the owner was told `days_ago` days ago that the listing will be deleted."""
    with app.state.db.session() as conn:
        conn.execute(
            "UPDATE listings SET deletion_notice_at = ? WHERE id = ?", (iso_ago(days=days_ago), listing_id)
        )


def _marked(app):
    with app.state.db.session() as conn:
        return [
            row[0] for row in conn.execute("SELECT id FROM listings WHERE deletion_notice_at IS NOT NULL")
        ]


def test_old_listings_are_deleted_two_weeks_after_a_notice(app, client, auth, other_auth, settings):
    listing = make_listing(client, auth)
    upload = client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("p.png", PHOTO, "image/png")},
        headers=auth,
    )
    assert upload.status_code == 201, upload.text
    client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Er den ledig?"},
        headers=other_auth,
    )
    _hide(client, auth, listing["id"], "sold")
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    _last_changed(app, listing["id"], days_ago=400)
    memory = MemoryMailer(settings)

    report = maintenance.run(app.state.db, settings, memory)
    assert (report.marked, report.deleted) == (1, 0)
    mail = memory.outbox[0]
    assert mail.subject.startswith("Annonsen din slettes") and "Terrengsykkel" in mail.subject
    assert f"/annonse/{listing['id']}" in mail.body and "/min-side" in mail.body
    shown = client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()
    assert shown["deletes_at"][:10] == iso_in(days=listings.DELETION_NOTICE_DAYS)[:10]
    assert maintenance.run(app.state.db, settings, memory).marked == 0  # the owner is told once
    assert len(memory.outbox) == 1

    _told(app, listing["id"], days_ago=listings.DELETION_NOTICE_DAYS + 1)
    photos = list(settings.uploads_dir.rglob("*.webp"))
    assert len(photos) == 2  # the photo and its thumbnail
    assert maintenance.run(app.state.db, settings, memory).deleted == 1
    assert client.get(f"/api/v1/listings/{listing['id']}", headers=auth).status_code == 404
    assert not any(path.exists() for path in photos)
    conversation = client.get("/api/v1/conversations", headers=other_auth).json()[0]
    assert conversation["listing_id"] is None and conversation["listing_title"]


def test_renewing_or_editing_keeps_an_old_listing(app, client, auth, settings):
    renewed = make_listing(client, auth, title="Spisebord i eik", description="Spisebord til seks personer.")
    edited = make_listing(
        client, auth, title="Seks stoler", description="Stoler i eik som passer til bordet."
    )
    for listing in (renewed, edited):
        _hide(client, auth, listing["id"])
        _last_changed(app, listing["id"], days_ago=400)
    assert maintenance.run(app.state.db, settings).marked == 2

    _hide(client, auth, renewed["id"], "active")
    client.patch(f"/api/v1/listings/{edited['id']}", json={"price": 900}, headers=auth)
    assert _marked(app) == []
    for listing in (renewed, edited):
        assert client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()["deletes_at"] is None
    report = maintenance.run(app.state.db, settings)
    assert (report.marked, report.deleted) == (0, 0)


def test_only_old_listings_that_nobody_follows_are_deleted(app, client, auth, settings):
    active = make_listing(client, auth, title="Aktiv sykkel")
    recent = make_listing(client, auth, title="Nylig skjult sykkel")
    imported = make_listing(client, auth, title="Stilling fra Nav")
    old = make_listing(client, auth, title="Gammel skjult sykkel")
    feed = client.put(
        "/api/v1/me/feeds/lager",
        json={
            "listings": [
                {
                    "external_id": "1",
                    "status": "inactive",
                    "category": "sykler",
                    "title": "Bysykkel",
                    "description": "Bysykkel fra lageret vårt.",
                }
            ]
        },
        headers=auth,
    ).json()
    synced = feed["listings"][0]["id"]
    for listing in (recent, imported, old):
        _hide(client, auth, listing["id"])
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET source = 'nav', source_id = '1' WHERE id = ?", (imported["id"],))
    for listing_id in (active["id"], imported["id"], old["id"], synced):
        _last_changed(app, listing_id, days_ago=400)

    assert maintenance.run(app.state.db, settings).marked == 1
    assert _marked(app) == [old["id"]]


def test_owners_get_one_email_about_all_their_old_listings(app, client, auth, settings):
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    for title, description in (
        ("Spisebord i eik", "Til seks personer."),
        ("Seks stoler", "Passer til bordet."),
    ):
        listing = make_listing(client, auth, title=title, description=description)
        _hide(client, auth, listing["id"])
        _last_changed(app, listing["id"], days_ago=400)
    memory = MemoryMailer(settings)
    maintenance.run(app.state.db, settings, memory)
    assert len(memory.outbox) == 1
    mail = memory.outbox[0]
    assert mail.subject.startswith("2 av annonsene dine slettes")
    assert "Spisebord i eik" in mail.body and "Seks stoler" in mail.body and "ett år" in mail.body


def test_automatic_deletion_can_be_turned_off(app, client, auth, settings):
    listing = make_listing(client, auth)
    _hide(client, auth, listing["id"])
    _last_changed(app, listing["id"], days_ago=400)
    assert maintenance.run(app.state.db, settings).marked == 1

    settings.delete_after_days = 0
    _told(app, listing["id"], days_ago=30)
    report = maintenance.run(app.state.db, settings)
    assert (report.marked, report.deleted) == (0, 0)
    assert client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()["deletes_at"] is None
    assert "slettes automatisk" not in client.get("/vilkar").text


def test_pages_explain_automatic_deletion(app, client, auth, settings):
    assert (
        "slettes automatisk sammen med bildene når de ikke har vært endret på ett år"
        in client.get("/vilkar").text
    )
    assert "deletes_at" in client.get("/llms.txt").text
    assert "Hva skjer med gamle annonser?" in client.get("/hjelp").text
    assert [format_days_no(days) for days in (1, 14, 365, 730)] == ["én dag", "14 dager", "ett år", "2 år"]

    listing = make_listing(client, auth)
    _hide(client, auth, listing["id"], "sold")
    _last_changed(app, listing["id"], days_ago=400)
    maintenance.run(app.state.db, settings)
    web_login(client)
    my_page = client.get("/min-side").text
    assert "Slettes " in my_page and "slettes automatisk med bildene" in my_page
    assert "Slettes automatisk" in client.get(f"/annonse/{listing['id']}").text
