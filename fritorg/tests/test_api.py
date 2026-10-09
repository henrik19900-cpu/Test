from __future__ import annotations

import json

from conftest import PHOTO, make_listing, register


def test_index_links_everything_an_agent_needs(client):
    data = client.get("/api/v1").json()
    for key in ("openapi", "llms_txt", "mcp", "categories", "search", "export", "register"):
        assert data["links"][key].startswith("http://testserver/")


def test_reading_needs_no_key_and_allows_any_origin(client, auth):
    make_listing(client, auth)
    response = client.get("/api/v1/listings", headers={"Origin": "https://some-agent.example"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.json()["total"] == 1
    assert 'rel="service-desc"' in response.headers["link"]
    assert int(response.headers["ratelimit-remaining"]) > 0


def test_categories_include_attribute_schemas(client):
    groups = client.get("/api/v1/categories").json()
    assert [g["slug"] for g in groups] == ["torget", "kjoretoy", "eiendom", "jobb", "tjenester"]
    car = client.get("/api/v1/categories/bil").json()
    assert car["is_leaf"] and car["parent"] == "kjoretoy"
    keys = {a["key"] for a in car["attributes"]}
    assert {"make", "year", "mileage_km", "fuel"} <= keys
    assert car["attributes_schema"]["properties"]["fuel"]["enum"][0] == "petrol"
    assert {t["slug"] for t in car["listing_types"]} == {"sell", "wanted", "rent"}


def test_unknown_category_suggests_alternatives(client):
    response = client.get("/api/v1/categories/cars")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "'bil'" in response.json()["hint"]


def test_counties(client):
    counties = client.get("/api/v1/counties").json()
    assert {"slug": "oslo", "name": "Oslo"} in counties
    assert len(counties) == 16


def test_create_get_update_delete_listing(client, auth):
    created = make_listing(client, auth)
    assert created["id"] >= 100001
    assert created["price_text"] == "6 500 kr"
    assert created["created_via"] == "api"
    assert created["attributes"] == {"bike_type": "terrain", "brand": "Trek", "condition": "good"}
    assert created["category_path"][0]["slug"] == "torget"
    assert created["links"]["markdown"].endswith(f"/annonse/{created['id']}.md")

    listing_id = created["id"]
    assert client.get(f"/api/v1/listings/{listing_id}").json()["title"] == created["title"]

    updated = client.patch(
        f"/api/v1/listings/{listing_id}",
        json={"price": 5900, "attributes": {"frame_size": "L", "brand": None}, "status": "sold"},
        headers=auth,
    ).json()
    assert updated["price"] == 5900
    assert updated["status"] == "sold"
    assert updated["attributes"] == {"bike_type": "terrain", "condition": "good", "frame_size": "L"}

    assert client.delete(f"/api/v1/listings/{listing_id}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/listings/{listing_id}").status_code == 404


def test_writing_requires_a_token(client):
    response = client.post(
        "/api/v1/listings", json={"category": "bil", "title": "Bil", "description": "x" * 20}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    problem = response.json()
    assert problem["code"] == "unauthorized"
    assert "/api/v1/auth/device" in problem["hint"]

    bad = client.get("/api/v1/me", headers={"Authorization": "Bearer ft_not-a-real-token-at-all-123456"})
    assert bad.status_code == 401


def test_only_the_owner_can_change_a_listing(client, auth, other_auth):
    listing = make_listing(client, auth)
    response = client.patch(f"/api/v1/listings/{listing['id']}", json={"price": 1}, headers=other_auth)
    assert response.status_code == 403
    assert client.delete(f"/api/v1/listings/{listing['id']}", headers=other_auth).status_code == 403


def test_validation_errors_are_problem_details_with_hints(client, auth):
    response = client.post(
        "/api/v1/listings",
        json={
            "category": "bil",
            "type": "give",
            "title": "Tesla",
            "description": "Fin bil til salgs.",
            "attributes": {"fuel": "wood", "colour": "red"},
        },
        headers=auth,
    )
    assert response.status_code == 422
    problem = response.json()
    fields = {e["field"] for e in problem["errors"]}
    assert {"type", "attributes.fuel", "attributes.colour"} <= fields
    assert "categories/bil" in problem["hint"]

    unknown_category = client.post(
        "/api/v1/listings",
        json={"category": "cars", "title": "Tesla", "description": "Fin bil til salgs."},
        headers=auth,
    ).json()
    assert "'bil'" in unknown_category["hint"]

    schema_error = client.post("/api/v1/listings", json={"title": "x"}, headers=auth)
    assert schema_error.status_code == 422
    assert schema_error.headers["content-type"].startswith("application/problem+json")
    assert any(e["field"].endswith("category") for e in schema_error.json()["errors"])


def test_give_away_is_free_and_jobs_have_no_price(client, auth):
    gift = make_listing(client, auth, category="mobler", type="give", price=500, attributes={})
    assert gift["price"] == 0 and gift["price_text"] == "Gis bort"
    job = client.post(
        "/api/v1/listings",
        json={"category": "jobb-it", "title": "Utvikler", "description": "Vi søker en utvikler.", "price": 1},
        headers=auth,
    )
    assert job.status_code == 422
    job = make_listing(
        client, auth, category="jobb-it", title="Utvikler", price=None, attributes={"employer": "Firma AS"}
    )
    assert job["type"] == "job" and job["price_text"] is None


def test_county_names_and_attribute_labels_are_accepted(client, auth):
    listing = make_listing(
        client,
        auth,
        category="bil",
        title="Volvo V70",
        county="Trøndelag",
        attributes={"make": "Volvo", "fuel": "Diesel", "year": "2014", "mileage_km": "198 000"},
    )
    assert listing["county"] == "trondelag"
    assert listing["attributes"] == {"make": "Volvo", "fuel": "diesel", "year": 2014, "mileage_km": 198000}


def test_search_filters_and_pagination(client, auth):
    make_listing(client, auth, title="Barnesykkel 16 tommer", price=600, attributes={"bike_type": "kids"})
    make_listing(
        client,
        auth,
        title="Elsykkel Cube",
        price=18500,
        county="vestland",
        attributes={"bike_type": "electric"},
    )
    make_listing(client, auth, category="mobler", title="Hjørnesofa i grå velur", price=4000, attributes={})

    def search(**params):
        return client.get("/api/v1/listings", params=params).json()

    assert search(q="sykkel")["total"] == 3
    assert search(q="sofa")["items"][0]["title"] == "Hjørnesofa i grå velur"
    assert search(category="torget")["total"] == 3
    assert search(category="mobler")["total"] == 1
    assert search(county="vestland")["total"] == 1
    assert search(price_max=1000)["total"] == 1
    assert search(attr="bike_type:electric,kids")["total"] == 2
    assert [i["price"] for i in search(sort="price_asc")["items"]] == [600, 4000, 18500]
    assert [i["price"] for i in search(sort="price_desc")["items"]] == [18500, 4000, 600]

    first = client.get("/api/v1/listings", params={"limit": 2})
    page = first.json()
    assert page["next"] and 'rel="next"' in first.headers["link"]
    second = client.get(page["next"].replace("http://testserver", "")).json()
    assert second["offset"] == 2
    assert {i["id"] for i in page["items"]}.isdisjoint({i["id"] for i in second["items"]})


def test_search_rejects_unknown_filters_helpfully(client):
    response = client.get("/api/v1/listings", params={"attr": "colour:red"})
    assert response.status_code == 422
    assert "attr=key:value" in response.json()["hint"]
    assert client.get("/api/v1/listings", params={"sort": "cheapest"}).status_code == 422


def test_hidden_listings_are_only_visible_to_the_owner(client, auth, other_auth):
    listing = make_listing(client, auth, status="inactive")
    assert client.get(f"/api/v1/listings/{listing['id']}").status_code == 404
    assert client.get(f"/api/v1/listings/{listing['id']}", headers=other_auth).status_code == 404
    assert client.get(f"/api/v1/listings/{listing['id']}", headers=auth).status_code == 200
    assert client.get("/api/v1/listings").json()["total"] == 0
    mine = client.get("/api/v1/me/listings", headers=auth).json()
    assert [i["status"] for i in mine["items"]] == ["inactive"]
    assert client.get("/api/v1/me/listings", params={"status": "active"}, headers=auth).json()["total"] == 0


def test_image_upload_and_delete(client, auth, settings):
    listing = make_listing(client, auth)
    response = client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("bike.png", PHOTO, "image/png")},
        data={"alt_text": "Sykkelen sett fra siden"},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    image = response.json()
    assert image["content_type"] == "image/webp"
    path = image["url"].replace("http://testserver", "")
    served = client.get(path)
    assert served.status_code == 200 and served.content.startswith(b"RIFF")
    assert served.headers["content-type"] == "image/webp"

    detail = client.get(f"/api/v1/listings/{listing['id']}").json()
    assert detail["thumbnail_url"] == image["thumbnail_url"] != image["url"]
    assert (image["width"], image["height"]) == (800, 600)
    assert detail["images"][0]["alt_text"] == "Sykkelen sett fra siden"
    assert client.get(image["thumbnail_url"].replace("http://testserver", "")).status_code == 200

    not_an_image = client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("evil.svg", b"<svg onload=alert(1)>", "image/png")},
        headers=auth,
    )
    assert not_an_image.status_code == 422

    assert (
        client.delete(f"/api/v1/listings/{listing['id']}/images/{image['id']}", headers=auth).status_code
        == 204
    )
    assert not list(settings.uploads_dir.rglob("*.webp"))  # the image and its thumbnail


def test_register_login_and_tokens(client):
    data = register(client, email="per@example.no", name="Per")
    assert data["account"]["email"] == "per@example.no"
    assert data["token"]["mcp_url"].endswith(data["token"]["token"])

    duplicate = client.post(
        "/api/v1/auth/register", json={"email": "PER@example.no", "name": "Per 2", "password": "hemmelig123"}
    )
    assert duplicate.status_code == 409

    wrong = client.post("/api/v1/auth/token", json={"email": "per@example.no", "password": "feil-passord"})
    assert wrong.status_code == 401

    login = client.post(
        "/api/v1/auth/token",
        json={"email": "per@example.no", "password": "hemmelig123", "token_name": "Claude"},
    )
    assert login.status_code == 201
    headers = {"Authorization": f"Bearer {login.json()['token']['token']}"}
    tokens = client.get("/api/v1/me/tokens", headers=headers).json()
    assert [t["name"] for t in tokens] == ["Claude", "API"]

    revoke = client.delete(f"/api/v1/me/tokens/{tokens[1]['id']}", headers=headers)
    assert revoke.status_code == 204
    old_headers = {"Authorization": f"Bearer {data['token']['token']}"}
    assert client.get("/api/v1/me", headers=old_headers).status_code == 401
    assert client.get("/api/v1/me", headers=headers).json()["name"] == "Per"


def test_conversations_between_buyer_and_seller(client, auth, other_auth):
    listing = make_listing(client, auth)
    started = client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Er sykkelen ledig?"},
        headers=other_auth,
    )
    assert started.status_code == 201
    conversation = started.json()
    assert conversation["role"] == "buyer"
    assert conversation["messages"][0]["from_me"] is True

    seller_view = client.get("/api/v1/conversations", headers=auth).json()
    assert seller_view[0]["unread"] == 1 and seller_view[0]["role"] == "seller"
    assert client.get("/api/v1/me", headers=auth).json()["unread_messages"] == 1

    reply = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages", json={"message": "Ja!"}, headers=auth
    ).json()
    assert [m["body"] for m in reply["messages"]] == ["Er sykkelen ledig?", "Ja!"]
    assert client.get("/api/v1/me", headers=auth).json()["unread_messages"] == 0

    again = client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Kan jeg hente i dag?"},
        headers=other_auth,
    ).json()
    assert again["id"] == conversation["id"]

    own = client.post(
        "/api/v1/conversations", json={"listing_id": listing["id"], "message": "Hei"}, headers=auth
    )
    assert own.status_code == 422

    stranger = register(client, email="x@example.no", name="Ukjent")
    stranger_headers = {"Authorization": f"Bearer {stranger['token']['token']}"}
    assert (
        client.get(f"/api/v1/conversations/{conversation['id']}", headers=stranger_headers).status_code == 404
    )


def test_report_listing_without_account(client, auth):
    listing = make_listing(client, auth)
    response = client.post(
        f"/api/v1/listings/{listing['id']}/reports", json={"reason": "fraud", "comment": "Rart"}
    )
    assert response.status_code == 202
    assert (
        client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "nope"}).status_code == 422
    )


def test_public_profile(client, auth):
    listing = make_listing(client, auth)
    profile = client.get(f"/api/v1/users/{listing['seller_id']}").json()
    assert profile == {
        "id": listing["seller_id"],
        "name": "Kari Nordmann",
        "verified": False,
        "verification": None,
        "member_since": profile["member_since"],
        "active_listings": 1,
        "url": f"http://testserver/bruker/{listing['seller_id']}",
        "rating": {"count": 0, "average": None},
    }
    assert "email" not in json.dumps(profile)


def test_bulk_export_streams_ndjson(client, auth):
    make_listing(client, auth)
    make_listing(client, auth, title="Sykkel nummer to")
    make_listing(client, auth, title="Skjult sykkel", status="inactive")
    response = client.get("/api/v1/export/listings.ndjson")
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert [line["title"] for line in lines] == ["Terrengsykkel Trek Marlin 7", "Sykkel nummer to"]


def test_daily_listing_quota(app, client, auth):
    app.state.settings.max_listings_per_day = 2
    make_listing(client, auth)
    make_listing(client, auth)
    response = client.post(
        "/api/v1/listings",
        json={"category": "sykler", "title": "Tredje sykkel", "description": "Enda en sykkel til salgs."},
        headers=auth,
    )
    assert response.status_code == 429
    assert "retry-after" in response.headers
