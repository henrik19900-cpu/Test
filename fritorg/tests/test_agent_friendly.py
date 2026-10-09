"""What makes Fritorg easy and safe for AI agents beyond the basic tools (see test_mcp.py for those)."""

from __future__ import annotations

import base64

from conftest import PHOTO, make_listing
from test_inventory import item, sync
from test_mcp import call

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
