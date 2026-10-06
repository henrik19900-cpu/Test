from __future__ import annotations

import json

from conftest import csrf, make_listing, register, web_login


def test_people_can_download_everything_stored_about_them(app, client):
    seller = register(client)
    buyer = register(client, email="ola@example.no", name="Ola Hansen")
    seller_auth = {"Authorization": f"Bearer {seller['token']['token']}"}
    buyer_auth = {"Authorization": f"Bearer {buyer['token']['token']}"}
    listing = make_listing(client, seller_auth)
    client.post(
        "/api/v1/conversations", json={"listing_id": listing["id"], "message": "Hei!"}, headers=buyer_auth
    )
    client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "spam"}, headers=buyer_auth)

    data = client.get("/api/v1/me/export", headers=seller_auth).json()
    assert data["account"]["email"] == "kari@example.no"
    assert [item["title"] for item in data["listings"]] == [listing["title"]]
    assert data["conversations"][0]["messages"][0]["body"] == "Hei!"
    assert data["api_tokens"][0]["hint"] == seller["token"]["hint"]
    assert data["reports_about_you"] == [
        {"listing_id": listing["id"], "reason": "spam", "created_at": data["reports_about_you"][0]["created_at"],
         "resolution": None}
    ]  # fmt: skip
    text = json.dumps(data)
    assert seller["token"]["token"] not in text and "scrypt$" not in text and "ola@example.no" not in text

    mine = client.get("/api/v1/me/export", headers=buyer_auth).json()
    assert mine["reports_made"][0]["reason"] == "spam"

    web_login(client)
    download = client.get("/min-side/data.json")
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.json()["account"]["id"] == seller["account"]["id"]
    assert "Last ned dataene dine" in client.get("/min-side").text
    client.post("/logg-ut", data={"csrf_token": csrf(client)})
    assert client.get("/min-side/data.json", follow_redirects=False).status_code == 303
