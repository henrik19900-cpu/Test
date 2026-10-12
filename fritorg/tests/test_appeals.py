"""Appeals against moderation decisions: once per removal, decided by a moderator, answered by e-mail."""

from __future__ import annotations

from conftest import csrf, make_listing, register, web_login
from test_mcp import call

from fritorg.mailer import MemoryMailer


def _removed(app, client, auth):
    """A listing that a moderator (another account) removed."""
    listing = make_listing(client, auth)
    register(client, email="mod@example.no", name="Mona Berg")
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = 'mod@example.no'")
    web_login(client, email="mod@example.no")
    client.post(
        f"/moderering/annonse/{listing['id']}/fjern",
        data={"csrf_token": csrf(client), "note": "Ser ut som svindel"},
    )
    return listing


def test_owners_appeal_once_and_a_moderator_publishes_it_again(app, client, auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    listing = _removed(app, client, auth)
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    shown = client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()["moderation"]
    assert shown["status"] == "removed" and shown["can_appeal"] is True and shown["appeal"] is None

    too_short = client.post(f"/api/v1/listings/{listing['id']}/appeal", json={"text": "Feil"}, headers=auth)
    assert too_short.status_code == 422
    appeal = client.post(
        f"/api/v1/listings/{listing['id']}/appeal",
        json={"text": "Dette er min egen sykkel, og jeg har kvittering."},
        headers=auth,
    ).json()
    assert appeal["status"] == "open"
    again = client.post(
        f"/api/v1/listings/{listing['id']}/appeal",
        json={"text": "Vær så snill, se på den igjen."},
        headers=auth,
    )
    assert again.status_code == 422
    other = {
        "Authorization": f"Bearer {register(client, email='per@example.no', name='Per')['token']['token']}"
    }
    assert (
        client.post(
            f"/api/v1/listings/{listing['id']}/appeal",
            json={"text": "Ikke min annonse, men likevel."},
            headers=other,
        ).status_code
        == 403
    )

    page = client.get("/moderering").text  # the moderator is logged in on this client
    assert "Klager på avgjørelser (1)" in page and "jeg har kvittering" in page
    client.post(f"/moderering/klage/{appeal['id']}", data={"csrf_token": csrf(client), "decision": "reverse"})
    assert client.get(f"/api/v1/listings/{listing['id']}").json()["status"] == "active"
    assert "Klager på avgjørelser (0)" in client.get("/moderering").text
    assert memory.outbox[-1].to == "kari@example.no" and "publisert" in memory.outbox[-1].subject


def test_an_upheld_removal_is_answered_and_can_be_appealed_after_a_new_removal(app, client, auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    listing = _removed(app, client, auth)
    appeal = client.post(
        f"/api/v1/listings/{listing['id']}/appeal", json={"text": "Annonsen følger vilkårene."}, headers=auth
    ).json()
    missing_answer = client.post(
        f"/moderering/klage/{appeal['id']}", data={"csrf_token": csrf(client), "decision": "uphold"}
    )
    assert "Skriv et kort svar" in missing_answer.text
    client.post(
        f"/moderering/klage/{appeal['id']}",
        data={
            "csrf_token": csrf(client),
            "decision": "uphold",
            "note": "Bildene er hentet fra en annen annonse.",
        },
    )
    assert memory.outbox[-1].to == "kari@example.no" and "Svar på klagen" in memory.outbox[-1].subject
    assert "hentet fra en annen annonse" in memory.outbox[-1].body
    moderation = client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()["moderation"]
    assert moderation["appeal"]["status"] == "upheld" and moderation["can_appeal"] is False
    assert moderation["appeal"]["answer"] == "Bildene er hentet fra en annen annonse."

    # Published again later and then removed again: a new decision, so a new appeal is allowed.
    with app.state.db.session() as conn:
        conn.execute("UPDATE appeals SET created_at = '2001-01-01T00:00:00Z'")
    client.post(f"/moderering/annonse/{listing['id']}/godkjenn", data={"csrf_token": csrf(client)})
    client.post(
        f"/moderering/annonse/{listing['id']}/fjern", data={"csrf_token": csrf(client), "note": "Igjen"}
    )
    assert (
        client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()["moderation"]["can_appeal"]
        is True
    )


def test_appeals_on_the_listing_page_and_through_mcp(app, client, auth):
    listing = _removed(app, client, auth)
    web_login(client)  # the owner
    page = client.get(f"/annonse/{listing['id']}").text
    assert "Klag på avgjørelsen" in page and "Ser ut som svindel" in page
    # Only appealing and deleting are possible, so nothing else is offered.
    assert "Gjør aktiv igjen" not in page and "Rediger annonsen" not in page
    edit = client.get(f"/annonse/{listing['id']}/rediger", follow_redirects=False)
    assert edit.status_code == 303 and edit.headers["location"] == f"/annonse/{listing['id']}#klage"
    client.post(
        f"/annonse/{listing['id']}/klage",
        data={"csrf_token": csrf(client), "text": "Jeg eier sykkelen og har kvittering."},
    )
    page = client.get(f"/annonse/{listing['id']}").text
    assert "Du klaget" in page and "Klag på avgjørelsen" not in page
    result = call(
        client, "appeal_removal", {"listing_id": listing["id"], "text": "En gang til, takk."}, headers=auth
    )
    assert result["isError"] is True  # once per removal


def test_closed_accounts_are_told_where_to_complain(app, client, settings):
    register(client)
    settings.contact_email = "hjelp@fritorg.no"
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET banned_at = '2026-01-01T00:00:00Z'")
    response = client.post(
        "/logg-inn",
        data={
            "email": "kari@example.no",
            "password": "hemmelig123",
            "csrf_token": csrf(client),
            "neste": "/",
        },
    )
    assert "stengt" in response.text and "hjelp@fritorg.no" in response.text


def test_the_export_keeps_appeals_after_they_are_decided(app, client, auth):
    listing = _removed(app, client, auth)
    appeal = client.post(
        f"/api/v1/listings/{listing['id']}/appeal",
        json={"text": "Min egen sykkel, med kvittering."},
        headers=auth,
    ).json()
    client.post(f"/moderering/klage/{appeal['id']}", data={"csrf_token": csrf(client), "decision": "reverse"})
    appeals = client.get("/api/v1/me/export", headers=auth).json()["appeals"]
    assert appeals[0]["text"] == "Min egen sykkel, med kvittering." and appeals[0]["decision"] == "reversed"
