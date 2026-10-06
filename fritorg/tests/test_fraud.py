from __future__ import annotations

import pytest
from conftest import PHOTO, csrf, make_image, make_listing, register, web_login

from fritorg import fraud, users

SCAM_RENTAL = {
    "category": "bolig",
    "type": "rent",
    "title": "Lys 3-roms på Majorstuen",
    "description": "Jeg jobber på oljeplattform og sender nøklene i posten når depositum er betalt.",
    "price": 9000,
    "price_unit": "month",
    "county": "oslo",
    "attributes": {"property_type": "apartment"},
}


@pytest.mark.parametrize(
    "text",
    [
        "Betaling via Western Union.",
        "Betal med gavekort fra iTunes, så sender jeg telefonen.",
        "Send meg BankID-koden din så overfører jeg pengene.",
        "Første som betaler får den!",
        "Vi søker finansagent som kan motta betalinger på din egen konto.",
        "Du må betale depositum før visning.",
    ],
)
def test_strong_scam_patterns_need_review(text):
    assert fraud.Assessment(fraud.text_codes(text)).needs_review


@pytest.mark.parametrize(
    "text",
    [
        "Pent brukt sofa, hentes på Grünerløkka. Ring 912 34 567.",
        "Selger gavekort til Elkjøp, verdi 500 kr.",
        "Kan sendes mot at kjøper betaler frakt og varen på forhånd via Vipps.",
        "Depositum tilsvarende tre måneders leie betales ved kontraktsignering.",
        "Ta kontakt på +47 912 34 567.",
        "Bitcoin mining rig, fungerer fint.",
    ],
)
def test_honest_texts_are_not_flagged(text):
    assert fraud.text_codes(text) == []


def test_payment_links_in_messages_are_flagged():
    assessment = fraud.assess_message(
        "Jeg har betalt! Motta pengene her: https://posten-betaling.example/abc"
    )
    assert "payment_link" in assessment.codes
    assert any("betalingslenke" in w for w in fraud.message_warnings(assessment.codes))
    assert fraud.assess_message("Se bilder her: https://example.no/album").codes == ["external_link"]


def test_scam_listing_is_held_for_review(client, auth, other_auth):
    listing = make_listing(client, auth, **SCAM_RENTAL)
    assert listing["status"] == "review"
    reasons = {r["code"] for r in listing["moderation"]["reasons"]}
    assert {"keys_by_mail", "abroad_story"} <= reasons

    assert client.get(f"/api/v1/listings/{listing['id']}").status_code == 404
    assert client.get("/api/v1/listings", params={"q": "Majorstuen"}).json()["total"] == 0
    owner_view = client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()
    assert owner_view["moderation"]["status"] == "review"

    activate = client.patch(f"/api/v1/listings/{listing['id']}", json={"status": "active"}, headers=auth)
    assert activate.status_code == 403
    message = client.post(
        "/api/v1/conversations", json={"listing_id": listing["id"], "message": "Hei"}, headers=other_auth
    )
    assert message.status_code == 422


def test_honest_listing_is_published_with_neutral_warnings(client, auth):
    listing = make_listing(
        client, auth, description="Pent brukt sykkel. Spørsmål? Send en melding på WhatsApp."
    )
    assert listing["status"] == "active"
    public = client.get(f"/api/v1/listings/{listing['id']}").json()
    assert public["moderation"] is None
    assert any("utenfor Fritorg" in w for w in public["safety_warnings"])


def test_copied_text_from_another_seller(client, auth, other_auth):
    description = (
        "Selger min flotte terrengsykkel. Nylig service, nye dekk og bremser. Hentes i Oslo sentrum."
    )
    original = make_listing(client, auth, description=description)
    copy = make_listing(client, other_auth, description=description.upper())
    assert original["status"] == "active"
    assert copy["status"] == "review"
    assert "copied_text" in {r["code"] for r in copy["moderation"]["reasons"]}


def test_reused_image_from_another_seller(client, auth, other_auth):
    original = make_listing(client, auth)
    upload = client.post(
        f"/api/v1/listings/{original['id']}/images",
        files={"file": ("a.png", PHOTO, "image/png")},
        headers=auth,
    )
    assert upload.json()["listing_status"] == "active"

    # The thief downloads the photo, shrinks it and saves it as JPEG: still recognised.
    from io import BytesIO

    from PIL import Image as PILImage

    copy = BytesIO()
    PILImage.open(BytesIO(PHOTO)).resize((400, 300)).save(copy, format="JPEG", quality=70)
    thief = make_listing(
        client, other_auth, title="Sykkel til salgs", description="En fin sykkel med lite bruk."
    )
    stolen = client.post(
        f"/api/v1/listings/{thief['id']}/images",
        files={"file": ("b.jpg", copy.getvalue(), "image/jpeg")},
        headers=other_auth,
    )
    assert stolen.json()["listing_status"] == "review"

    # The original owner is never flagged, and different photos are fine.
    again = client.post(
        f"/api/v1/listings/{original['id']}/images",
        files={"file": ("c.png", PHOTO, "image/png")},
        headers=auth,
    )
    assert again.json()["listing_status"] == "active"
    honest = make_listing(
        client, other_auth, title="Annen sykkel", description="Helt annen sykkel, pent brukt."
    )
    other_photo = client.post(
        f"/api/v1/listings/{honest['id']}/images",
        files={"file": ("d.png", make_image(7), "image/png")},
        headers=other_auth,
    )
    assert other_photo.json()["listing_status"] == "active"


def test_price_far_below_similar_listings(client, auth, other_auth):
    for index, price in enumerate([150000, 180000, 210000, 240000, 260000]):
        make_listing(
            client,
            auth,
            category="bil",
            title=f"Bil {index}",
            description=f"Fin bil nummer {index}.",
            price=price,
            attributes={},
        )
    cheap = make_listing(
        client,
        other_auth,
        category="bil",
        title="Tesla Model 3 2022",
        description="Må selges, fin bil.",
        price=9000,
        attributes={},
    )
    assert cheap["status"] == "review"
    assert "price_far_below" in {r["code"] for r in cheap["moderation"]["reasons"]}


def test_message_warnings_reach_the_recipient_and_agents(client, auth, other_auth):
    listing = make_listing(client, auth)
    sent = client.post(
        "/api/v1/conversations",
        json={
            "listing_id": listing["id"],
            "message": "Har betalt. Motta pengene her: https://bring-betaling.example/x",
        },
        headers=other_auth,
    ).json()
    assert sent["messages"][0]["warnings"] == []  # the sender is not warned about their own message

    received = client.get(f"/api/v1/conversations/{sent['id']}", headers=auth).json()
    assert any("betalingslenke" in w for w in received["messages"][0]["warnings"])

    mcp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_conversation", "arguments": {"conversation_id": sent["id"]}},
        },
        headers=auth,
    ).json()["result"]["structuredContent"]
    assert mcp["messages"][0]["warnings"]

    report = client.post(
        f"/api/v1/conversations/{sent['id']}/reports",
        json={"reason": "fraud", "comment": "Falsk lenke"},
        headers=auth,
    )
    assert report.status_code == 202


def test_reports_from_three_users_hide_a_listing(client, auth):
    listing = make_listing(client, auth)
    for number in range(3):
        reporter = register(client, email=f"r{number}@example.no", name=f"Rapportør {number}")
        headers = {"Authorization": f"Bearer {reporter['token']['token']}"}
        client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "fraud"}, headers=headers)
    assert client.get(f"/api/v1/listings/{listing['id']}").status_code == 404
    owner_view = client.get(f"/api/v1/listings/{listing['id']}", headers=auth).json()
    assert owner_view["status"] == "review"


def test_anonymous_reports_do_not_hide_listings(client, auth):
    listing = make_listing(client, auth)
    for _ in range(5):
        client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "spam"})
    assert client.get(f"/api/v1/listings/{listing['id']}").status_code == 200


def test_new_accounts_get_a_lower_quota(app, client, auth):
    app.state.settings.new_account_max_listings_per_day = 2
    make_listing(client, auth, title="Første")
    make_listing(client, auth, title="Andre")
    response = client.post(
        "/api/v1/listings",
        json={"category": "sykler", "title": "Tredje", "description": "Nok en sykkel til salgs."},
        headers=auth,
    )
    assert response.status_code == 429
    assert "new accounts" in response.json()["hint"]


def _moderator(app, client):
    data = register(client, email="mod@example.no", name="Moderator")
    with app.state.db.session() as conn:
        users.set_admin(conn, data["account"]["id"])
    web_login(client, "mod@example.no")


def test_moderators_approve_remove_and_ban(app, client, auth, other_auth):
    held = make_listing(client, auth, **SCAM_RENTAL)
    scam = make_listing(client, other_auth, **{**SCAM_RENTAL, "title": "Hybel på Frogner"})
    honest = make_listing(client, other_auth, title="Ærlig sykkel", description="En helt vanlig sykkel.")

    assert client.get("/moderering", follow_redirects=False).status_code == 303  # not logged in
    _moderator(app, client)
    page = client.get("/moderering")
    assert page.status_code == 200 and "Lys 3-roms" in page.text and "nøkler i posten" in page.text

    token = csrf(client)
    approved = client.post(
        f"/moderering/annonse/{held['id']}/godkjenn", data={"csrf_token": token}, follow_redirects=False
    )
    assert approved.status_code == 303
    assert client.get(f"/api/v1/listings/{held['id']}").json()["status"] == "active"

    # An approved listing stays public when edited without adding new risk.
    edited = client.patch(f"/api/v1/listings/{held['id']}", json={"price": 8500}, headers=auth).json()
    assert edited["status"] == "active"

    missing_note = client.post(f"/moderering/annonse/{scam['id']}/fjern", data={"csrf_token": token})
    assert "begrunnelse" in missing_note.text.lower()
    client.post(f"/moderering/annonse/{scam['id']}/fjern", data={"csrf_token": token, "note": "Falsk utleie"})
    owner_view = client.get(f"/api/v1/listings/{scam['id']}", headers=other_auth).json()
    assert owner_view["status"] == "removed" and owner_view["moderation"]["note"] == "Falsk utleie"
    assert (
        client.patch(f"/api/v1/listings/{scam['id']}", json={"price": 1}, headers=other_auth).status_code
        == 403
    )

    client.post(
        f"/moderering/bruker/{honest['seller_id']}/steng", data={"csrf_token": token, "reason": "Svindel"}
    )
    assert client.get(f"/api/v1/listings/{honest['id']}").status_code == 404
    assert client.get("/api/v1/me", headers=other_auth).status_code == 401
    login = client.post("/api/v1/auth/token", json={"email": "ola@example.no", "password": "hemmelig123"})
    assert login.status_code == 403


def test_regular_users_cannot_see_moderation(client, auth):
    web_login(client)
    assert client.get("/moderering").status_code == 404
