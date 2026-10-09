"""What makes Fritorg easy and safe for AI agents beyond the basic tools (see test_mcp.py for those)."""

from __future__ import annotations

import base64

from conftest import PHOTO, make_listing
from test_inventory import item, sync
from test_mcp import HEADERS, call

from fritorg.mailer import MemoryMailer

SOFA = {
    "category": "mobler",
    "title": "IKEA Ektorp sofa",
    "description": "Pen tresetersofa med avtakbart trekk. Røykfritt hjem.",
    "price": 1500,
    "county": "vestland",
    "location": "Bergen",
}


def test_a_repeated_create_returns_the_listing_already_made(client, auth):
    """Agents retry calls that timed out; that must not post the same listing twice."""
    first = call(client, "create_listing", SOFA, headers=auth)["structuredContent"]
    again = call(client, "create_listing", SOFA, headers=auth)["structuredContent"]
    assert again["id"] == first["id"]
    rest = client.post("/api/v1/listings", json=SOFA, headers=auth).json()
    assert rest["id"] == first["id"]
    cheaper = client.post("/api/v1/listings", json={**SOFA, "price": 1200}, headers=auth).json()
    assert cheaper["id"] != first["id"]  # a different listing is a new one
    mine = client.get("/api/v1/me/listings", headers=auth).json()
    assert mine["total"] == 2


def test_the_same_photo_twice_is_one_photo(client, auth):
    listing = make_listing(client, auth)
    photo = {"listing_id": listing["id"], "image_base64": base64.b64encode(PHOTO).decode()}
    first = call(client, "add_listing_image", photo, headers=auth)["structuredContent"]
    again = call(client, "add_listing_image", photo, headers=auth)["structuredContent"]
    assert again["id"] == first["id"]
    assert len(client.get(f"/api/v1/listings/{listing['id']}").json()["images"]) == 1


def test_a_repeated_message_is_sent_once(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    listing = make_listing(client, auth)
    ask = {"listing_id": listing["id"], "message": "Er den ledig? Kan hente lørdag."}
    first = call(client, "send_message", ask, headers=other_auth)["structuredContent"]
    again = call(client, "send_message", ask, headers=other_auth)["structuredContent"]
    assert again["id"] == first["id"] and len(again["messages"]) == 1
    assert len(memory.outbox) == 1  # the seller is told once

    conversation = f"/api/v1/conversations/{first['id']}/messages"
    client.post(conversation, json={"message": "Ja, den er ledig."}, headers=auth)
    client.post(conversation, json={"message": "Ja, den er ledig."}, headers=auth)
    # The same words again after the other person has answered are a new message.
    client.post(conversation, json={"message": "Er den ledig? Kan hente lørdag."}, headers=other_auth)
    messages = client.get(f"/api/v1/conversations/{first['id']}", headers=auth).json()["messages"]
    assert [m["body"] for m in messages] == [
        "Er den ledig? Kan hente lørdag.",
        "Ja, den er ledig.",
        "Er den ledig? Kan hente lørdag.",
    ]


def test_identical_items_in_a_shop_feed_stay_separate(client, auth):
    result = sync(client, auth, [item("A", title="Volvo V60"), item("B", title="Volvo V60")]).json()
    assert result["created"] == 2 and len({entry["id"] for entry in result["listings"]}) == 2


def test_the_county_follows_from_the_place(client, auth):
    bergen = call(client, "create_listing", {**SOFA, "county": None}, headers=auth)["structuredContent"]
    assert bergen["county"] == "vestland"
    as_county = {**SOFA, "title": "Spisebord i eik", "county": "Trondheim", "location": None}
    trondheim = call(client, "create_listing", as_county, headers=auth)["structuredContent"]
    assert trondheim["county"] == "trondelag" and trondheim["place"].startswith("Trondheim")
    unknown = {**SOFA, "title": "Lenestol i skinn", "county": None, "location": "Hytta vår"}
    result = call(client, "create_listing", unknown, headers=auth)["structuredContent"]
    assert result["county"] is None and "No county is set" in result["next_steps"]
    search = call(client, "search_listings", {"county": "Bergen"})
    assert search["isError"] and "location='Bergen'" in search["content"][0]["text"]


def test_attribute_filters_know_the_category_and_say_when_they_exclude_everything(client, auth):
    make_listing(client, auth)  # a bike in good condition
    norwegian = call(client, "search_listings", {"category": "sykler", "attributes": {"tilstand": "good"}})
    assert norwegian["structuredContent"]["total"] == 1
    unknown = call(client, "search_listings", {"category": "sykler", "attributes": {"farge": "rød"}})
    text = unknown["content"][0]["text"]
    assert unknown["isError"] and "bike_type" in text and "area_m2" not in text
    nothing = call(
        client, "search_listings", {"category": "sykler", "attributes": {"condition": "for_parts"}}
    )
    assert (
        nothing["structuredContent"]["total"] == 0 and "without them" in nothing["structuredContent"]["hint"]
    )
    condition = {t["name"]: t for t in call_tools(client)}["list_categories"]
    assert condition  # the meaning of each condition value is in the category schema
    schema = call(client, "list_categories", {"category": "sykler"})["structuredContent"]
    assert "lightly used" in str(schema)


def test_next_steps_lead_from_draft_to_sale(client, auth, other_auth):
    draft = call(client, "create_listing", {**SOFA, "status": "inactive"}, headers=auth)["structuredContent"]
    assert "hidden draft" in draft["next_steps"] and "status='active'" in draft["next_steps"]
    published = call(client, "update_listing", {"listing_id": draft["id"], "status": "active"}, headers=auth)
    assert "Published" in published["structuredContent"]["next_steps"]
    asked = call(
        client, "send_message", {"listing_id": draft["id"], "message": "Er sofaen ledig?"}, headers=other_auth
    )["structuredContent"]
    sold = call(client, "update_listing", {"listing_id": draft["id"], "status": "sold"}, headers=auth)
    assert "record_sale(conversation_id)" in sold["structuredContent"]["next_steps"]
    assert f"{asked['id']} (Ola" in sold["structuredContent"]["next_steps"]
    about = call(client, "list_conversations", {"listing_id": draft["id"]}, headers=auth)["structuredContent"]
    assert [c["id"] for c in about["conversations"]] == [asked["id"]]
    assert call(client, "list_conversations", {"listing_id": 1}, headers=auth)["structuredContent"] == {
        "conversations": []
    }
    statuses = {t["name"]: t for t in call_tools(client, auth)}["update_listing"]["inputSchema"]
    assert statuses["properties"]["status"]["enum"] == ["active", "sold", "inactive"]


def test_agents_are_told_when_alerts_cannot_be_e_mailed(app, client, auth, settings):
    app.state.mailer = MemoryMailer(settings)
    assert call(client, "whoami", headers=auth)["structuredContent"]["email_verified"] is False
    saved = call(client, "save_search", {"query": "iphone", "price_max": 4000}, headers=auth)[
        "structuredContent"
    ]
    assert saved["email_alerts"] is False and "confirms their e-mail address" in saved["next_steps"]
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    checked = call(client, "check_saved_searches", headers=auth)["structuredContent"]
    assert checked["saved_searches"][0]["email_alerts"] is True


def call_tools(client, headers=None):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={**HEADERS, **(headers or {})},
    ).json()["result"]["tools"]


def test_a_photo_link_lets_the_user_add_photos_from_the_phone(app, client, auth):
    from conftest import PHOTO as photo
    from fastapi.testclient import TestClient

    created = call(client, "create_listing", SOFA, headers=auth)["structuredContent"]
    link = created["photo_upload_url"]
    assert "photo_upload_url" in created["next_steps"]
    path = link.removeprefix("http://testserver")
    with TestClient(app) as phone:  # not logged in
        page = phone.get(path)
        assert page.status_code == 200 and "IKEA Ektorp sofa" in page.text
        assert page.headers["referrer-policy"] == "no-referrer"
        token = path.split("t=")[1]
        sent = phone.post(
            f"/annonse/{created['id']}/bilder/lenke",
            data={"csrf_token": phone.cookies["ft_csrf"], "t": token},
            files={"images": ("sofa.png", photo, "image/png")},
        )
        assert sent.status_code == 200 and "Bildene er lagt til" in sent.text
        assert phone.get(f"/annonse/{created['id']}/bilder?t=1.forged").status_code == 403
        assert phone.get(f"/annonse/{created['id'] + 1}/bilder?t={token}").status_code in (403, 404)
    assert len(client.get(f"/api/v1/listings/{created['id']}").json()["images"]) == 1
    owner_view = call(client, "get_listing", {"listing_id": created["id"]}, headers=auth)["structuredContent"]
    assert owner_view["photo_upload_url"].startswith(f"http://testserver/annonse/{created['id']}/bilder?t=")
    assert (
        "photo_upload_url"
        not in call(client, "get_listing", {"listing_id": created["id"]})["structuredContent"]
    )
