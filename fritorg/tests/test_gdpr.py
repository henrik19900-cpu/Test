"""How long personal data is kept, what deleting an account removes, and the rights people can use."""

from __future__ import annotations

import json

from conftest import PHOTO, csrf, make_listing, register, web_login

from fritorg import maintenance, messages, users
from fritorg.__main__ import main
from fritorg.util import iso_ago


def _moderator(app, client):
    register(client, email="mod@example.no", name="Mona Berg")
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = 'mod@example.no'")
    web_login(client, email="mod@example.no")


def test_records_about_people_are_kept_a_year(app, client, auth, other_auth):
    listing = make_listing(client, auth)
    client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "spam"}, headers=other_auth)
    old = iso_ago(days=maintenance.RECORDS_DAYS + 1)
    with app.state.db.session() as conn:
        conn.execute(
            "INSERT INTO moderation_log (moderator_id, user_id, action, note, created_at) VALUES (NULL, 1, 'x', 'n', ?)",
            (old,),
        )
        conn.execute(
            "INSERT INTO moderation_log (moderator_id, user_id, action, note, created_at) VALUES (NULL, 1, 'y', 'n', ?)",
            (iso_ago(days=5),),
        )
        conn.execute("UPDATE reports SET resolved_at = ?, resolution = 'dismissed'", (old,))
        maintenance.purge(conn)
        assert [r["action"] for r in conn.execute("SELECT action FROM moderation_log")] == ["y"]
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_an_assistants_key_expires_when_it_is_not_used(app, client, auth):
    with app.state.db.session() as conn:
        token, record = users.create_api_token(conn, 1, "Claude")
        conn.execute(
            "UPDATE api_tokens SET oauth_client_id = 'fc_x', created_at = ?, last_used_at = ? WHERE id = ?",
            (iso_ago(days=200), iso_ago(days=maintenance.ASSISTANT_KEY_DAYS + 1), record.id),
        )
        maintenance.purge(conn)
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/v1/me", headers=auth).status_code == 200  # the account's own key stays


def test_deleting_an_account_leaves_no_notes_about_the_person(app, client, auth):
    listing = make_listing(client, auth)
    _moderator(app, client)
    client.post(
        f"/moderering/annonse/{listing['id']}/fjern",
        data={"csrf_token": csrf(client), "note": "Kari Nordmann selger tyvgods"},
    )
    with app.state.db.session() as conn:
        users.delete_user(conn, 1)
        rows = [dict(r) for r in conn.execute("SELECT user_id, note FROM moderation_log")]
    assert rows and all(r["note"] is None and r["user_id"] is None for r in rows)


def test_an_account_under_review_is_not_deleted_on_request(app, client, auth, other_auth):
    listing = make_listing(client, auth)
    client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "fraud"}, headers=other_auth)
    web_login(client)
    refused = client.post(
        "/min-side/slett-konto", data={"csrf_token": csrf(client), "password": "hemmelig123"}
    )
    assert "behandler en rapport" in refused.text
    assert client.get("/api/v1/me", headers=auth).status_code == 200
    with app.state.db.session() as conn:
        conn.execute("UPDATE reports SET resolved_at = '2026-01-01T00:00:00Z'")
    client.post("/min-side/slett-konto", data={"csrf_token": csrf(client), "password": "hemmelig123"})
    assert client.get("/api/v1/me", headers=auth).status_code == 401


def test_photos_of_a_removed_listing_stop_working(app, client, auth):
    listing = make_listing(client, auth)
    image = client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("p.png", PHOTO, "image/png")},
        headers=auth,
    ).json()
    old = image["url"].removeprefix("http://testserver")
    assert client.get(old).status_code == 200
    _moderator(app, client)
    client.post(
        f"/moderering/annonse/{listing['id']}/fjern", data={"csrf_token": csrf(client), "note": "Feil"}
    )
    assert client.get(old).status_code == 404
    owner_view = client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()
    assert client.get(owner_view["images"][0]["url"].removeprefix("http://testserver")).status_code == 200


def test_flagged_messages_keep_a_deleted_conversation_for_a_while(app, client, auth, other_auth):
    listing = make_listing(client, auth)
    conversation = client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Send meg BankID-koden din, så betaler jeg."},
        headers=other_auth,
    ).json()["id"]
    client.delete(f"/api/v1/conversations/{conversation}", headers=auth)
    client.delete(f"/api/v1/conversations/{conversation}", headers=other_auth)
    with app.state.db.session() as conn:
        assert messages.purge_deleted(conn) == 0
        conn.execute("UPDATE messages SET created_at = ?", (iso_ago(days=91),))
        assert messages.purge_deleted(conn) == 1


def test_people_can_correct_their_name_and_report_their_own_data(client, auth, other_auth):
    web_login(client)
    client.post("/min-side/navn", data={"csrf_token": csrf(client), "name": "Kari N. Hansen"})
    assert client.get("/api/v1/me", headers=auth).json()["name"] == "Kari N. Hansen"
    refused = client.post("/min-side/navn", data={"csrf_token": csrf(client), "name": "Fritorg kundeservice"})
    assert "Velg et annet visningsnavn" in refused.text
    listing = make_listing(client, auth)
    report = {"reason": "privacy", "comment": "Bildet viser huset mitt."}
    assert (
        client.post(f"/api/v1/listings/{listing['id']}/reports", json=report, headers=other_auth).status_code
        == 202
    )


def test_closed_accounts_have_no_public_profile(app, client, auth):
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET banned_at = '2026-01-01T00:00:00Z'")
    assert client.get("/bruker/1").status_code == 404
    assert client.get("/api/v1/users/1").status_code == 404


def test_apps_cannot_pose_as_the_site(client):
    registered = client.post(
        "/oauth/register",
        json={"client_name": "Fritorg kundeservice", "redirect_uris": ["https://x.example/cb"]},
    ).json()
    assert registered["client_name"] == "Ukjent app"


def test_the_operator_can_export_and_delete_an_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FRITORG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRITORG_VERIFICATION", "none")
    from fritorg.config import Settings
    from fritorg.db import Database

    settings = Settings.from_env()
    db = Database(settings.db_path)
    db.init()
    with db.session() as conn:
        users.create_user(conn, "kari@example.no", "Kari Nordmann", "hemmelig123")
    assert main(["export-user", "kari@example.no"]) == 0
    assert json.loads(capsys.readouterr().out)["account"]["email"] == "kari@example.no"
    assert main(["delete-user", "kari@example.no"]) == 1  # not without --yes
    assert main(["delete-user", "kari@example.no", "--yes"]) == 0
    with db.session() as conn:
        assert users.get_user_by_email(conn, "kari@example.no") is None


def test_the_privacy_policy_names_the_controller_processors_and_rights(client, settings):
    settings.operator = "Fritorg AS"
    settings.contact_email = "post@fritorg.no"
    settings.processors = "Oracle Cloud (servere, Sverige)"
    page = client.get("/vilkar").text
    for text in (
        "Fritorg AS, som er behandlingsansvarlig",
        "Oracle Cloud (servere, Sverige)",
        "artikkel 6 nr. 1 b",
        "Datatilsynet",
        "minst 18 år",
        "Tilgangsloggen slettes etter 14 dager",
        "Personopplysninger om meg",
    ):
        assert text in page, text
