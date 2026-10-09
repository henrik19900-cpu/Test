from __future__ import annotations

import pytest
from conftest import PHOTO, register
from fastapi.testclient import TestClient

from fritorg.app import create_app
from fritorg.config import Settings


def item(external_id: str, **overrides) -> dict:
    data = {
        "external_id": external_id,
        "category": "bil",
        "title": f"Volvo V60 {external_id}",
        "description": "Pent brukt bil med full servicehistorikk.",
        "price": 239000,
        "county": "oslo",
        "location": "Oslo",
        "attributes": {"make": "Volvo", "model": "V60", "year": 2019, "fuel": "diesel"},
    }
    data.update(overrides)
    return data


def sync(client, auth, items, feed="bruktbiler", **body):
    return client.put(f"/api/v1/me/feeds/{feed}", json={"listings": items, **body}, headers=auth)


def test_full_sync_creates_updates_and_removes(client, auth):
    first = sync(client, auth, [item("A"), item("B"), item("C")])
    assert first.status_code == 200, first.text
    result = first.json()
    assert (result["created"], result["updated"], result["unchanged"], result["removed"]) == (3, 0, 0, 0)
    ids = {entry["external_id"]: entry["id"] for entry in result["listings"]}
    assert client.get("/api/v1/listings", params={"q": "volvo"}).json()["total"] == 3

    again = sync(client, auth, [item("A"), item("B"), item("C")]).json()
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 3)

    changed = sync(client, auth, [item("A", price=199000), item("B")]).json()
    assert (changed["updated"], changed["unchanged"], changed["removed"]) == (1, 1, 1)
    assert client.get(f"/api/v1/listings/{ids['A']}").json()["price"] == 199000
    assert client.get(f"/api/v1/listings/{ids['C']}").status_code == 404
    assert {e["id"] for e in changed["listings"]} == {ids["A"], ids["B"]}  # same listings, same ids

    added = sync(client, auth, [item("D")], remove_missing=False).json()
    assert added["created"] == 1 and added["removed"] == 0
    assert client.get("/api/v1/me/feeds", headers=auth).json() == [
        {"feed": "bruktbiler", "listings": 3, "active": 3}
    ]
    assert client.delete("/api/v1/me/feeds/bruktbiler", headers=auth).status_code == 204
    assert client.get("/api/v1/listings", params={"q": "volvo"}).json()["total"] == 0


def test_bad_items_are_reported_and_the_rest_synced(client, auth):
    result = sync(client, auth, [item("A"), item("B", category="finnes-ikke"), item("C", price=-5)])
    assert result.status_code == 422  # price below 0 fails the schema for the whole request
    result = sync(client, auth, [item("A"), item("B", category="finnes-ikke")]).json()
    assert result["created"] == 1 and [f["external_id"] for f in result["failed"]] == ["B"]
    assert "finnes-ikke" in result["failed"][0]["detail"]

    duplicate = sync(client, auth, [item("A"), item("A")])
    assert duplicate.status_code == 422 and "flere ganger" in duplicate.json()["detail"]
    bad_name = sync(client, auth, [item("A")], feed="Bruktbiler!")
    assert bad_name.status_code in (404, 422)


def test_sync_keeps_moderation_and_sold_status_and_renews(app, client, auth):
    result = sync(client, auth, [item("A"), item("B"), item("C", status="inactive")]).json()
    ids = {entry["external_id"]: entry["id"] for entry in result["listings"]}
    assert {e["external_id"]: e["status"] for e in result["listings"]}["C"] == "inactive"
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET status = 'removed' WHERE id = ?", (ids["A"],))
        conn.execute("UPDATE listings SET status = 'sold' WHERE id = ?", (ids["B"],))
        conn.execute("UPDATE listings SET expires_at = '2001-01-01T00:00:00Z'")
    again = sync(client, auth, [item("A"), item("B"), item("C")]).json()
    statuses = {e["external_id"]: e["status"] for e in again["listings"]}
    assert statuses == {"A": "removed", "B": "sold", "C": "active"}
    with app.state.db.session() as conn:
        assert conn.execute("SELECT MIN(expires_at) FROM listings").fetchone()[0] > "2026"


def test_photos_are_added_to_synced_listings(client, auth):
    listing_id = sync(client, auth, [item("A")]).json()["listings"][0]["id"]
    upload = client.post(
        f"/api/v1/listings/{listing_id}/images", files={"file": ("p.png", PHOTO, "image/png")}, headers=auth
    )
    assert upload.status_code == 201
    assert sync(client, auth, [item("A")]).json()["unchanged"] == 1
    assert client.get(f"/api/v1/listings/{listing_id}").json()["image_count"] == 1


def test_limits_and_verification(tmp_path):
    settings = Settings(data_dir=tmp_path, verification="sms", max_synced_listings=2)
    with TestClient(create_app(settings)) as client:
        data = register(client)
        auth = {"Authorization": f"Bearer {data['token']['token']}"}
        refused = sync(client, auth, [item("A")])
        assert refused.status_code == 403 and refused.json()["code"] == "verification_required"
        code = client.post("/api/v1/me/phone", json={"phone": "91234567"}, headers=auth).json()["test_code"]
        client.post("/api/v1/me/phone/verify", json={"code": code}, headers=auth)
        assert sync(client, auth, [item("A"), item("B")]).status_code == 200
        too_many = sync(client, auth, [item("C")], feed="annet")
        assert too_many.status_code == 422 and "maks 2" in too_many.json()["detail"]


@pytest.mark.parametrize("path", ["/for-bedrifter", "/for-bedrifter.md"])
def test_business_guide(client, path):
    page = client.get(path)
    assert page.status_code == 200 and "/api/v1/me/feeds/bruktbiler" in page.text
