"""Blocking, response times, quick replies, main photos, view counts and breadcrumbs."""

from __future__ import annotations

import json
import re

from conftest import csrf, make_image, make_listing, register, web_login

from fritorg import maintenance, messages
from fritorg.util import iso_ago

BROWSER = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"}


def _conversation(client, buyer_auth, listing_id, text="Hei! Er den ledig?"):
    response = client.post(
        "/api/v1/conversations", json={"listing_id": listing_id, "message": text}, headers=buyer_auth
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def test_blocking_stops_messages_both_ways(client, auth, other_auth):
    listing = make_listing(client, auth)
    conversation_id = _conversation(client, other_auth, listing["id"])
    web_login(client)  # the seller, Kari
    page = client.get(f"/meldinger/{conversation_id}").text
    assert "Blokker Ola H" in page or "Blokker Ola" in page

    client.post(f"/meldinger/{conversation_id}/blokker", data={"csrf_token": csrf(client)})
    page = client.get(f"/meldinger/{conversation_id}").text
    assert "Du har blokkert" in page and 'name="message"' not in page

    # Neither side can write: the buyer gets a clear 403, also for a new listing.
    blocked = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"message": "Hallo?"}, headers=other_auth
    )
    assert blocked.status_code == 403 and "kan ikke sende meldinger" in blocked.json()["detail"]
    other_listing = make_listing(client, auth, title="Sykkelhjelm", price=200)
    again = client.post(
        "/api/v1/conversations",
        json={"listing_id": other_listing["id"], "message": "Hei"},
        headers=other_auth,
    )
    assert again.status_code == 403
    own = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"message": "Hei"}, headers=auth
    )
    assert own.status_code == 403 and "Du har blokkert" in own.json()["detail"]

    assert [b["name"] for b in client.get("/api/v1/me/blocks", headers=auth).json()] == ["Ola Hansen"]
    assert "Blokkerte brukere (1)" in client.get("/min-side").text
    other_id = client.get("/api/v1/me", headers=other_auth).json()["id"]
    client.post(f"/min-side/blokkert/{other_id}/opphev", data={"csrf_token": csrf(client)})
    assert client.get("/api/v1/me/blocks", headers=auth).json() == []
    ok = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"message": "Ja, ledig."}, headers=auth
    )
    assert ok.status_code in (200, 201)

    assert client.put(f"/api/v1/me/blocks/{other_id}", headers=auth).status_code == 204
    me = client.get("/api/v1/me", headers=auth).json()["id"]
    assert client.put(f"/api/v1/me/blocks/{me}", headers=auth).status_code == 422
    assert client.put("/api/v1/me/blocks/999999", headers=auth).status_code == 404


def test_response_time(app, client, auth, other_auth):
    listing = make_listing(client, auth)
    seller_id = client.get("/api/v1/me", headers=auth).json()["id"]
    buyers = [other_auth] + [
        {
            "Authorization": f"Bearer {register(client, email=f'k{n}@example.no', name=f'Kjøper {n}')['token']['token']}"
        }
        for n in range(2)
    ]
    with app.state.db.session() as conn:
        assert messages.response_time_text(messages.response_time_hours(conn, seller_id)) is None
    for buyer in buyers:
        conversation_id = _conversation(client, buyer, listing["id"])
        client.post(
            f"/api/v1/conversations/{conversation_id}/messages", json={"message": "Ja!"}, headers=auth
        )
    with app.state.db.session() as conn:
        hours = messages.response_time_hours(conn, seller_id)
        assert hours is not None and hours < 1
    assert "Svarer vanligvis innen en time" in client.get(f"/annonse/{listing['id']}").text
    assert "Svarer vanligvis innen en time" in client.get(f"/bruker/{seller_id}").text

    # Slow or unanswered conversations count too.
    with app.state.db.session() as conn:
        conn.execute("UPDATE conversations SET created_at = ?", (iso_ago(days=3),))
        conn.execute("DELETE FROM messages WHERE sender_id = ?", (seller_id,))
        assert messages.response_time_text(messages.response_time_hours(conn, seller_id)) is None
    assert messages.response_time_text(0.5) == "Svarer vanligvis innen en time"
    assert messages.response_time_text(3) == "Svarer vanligvis innen noen timer"
    assert messages.response_time_text(20) == "Svarer vanligvis innen et døgn"


def test_quick_replies(client, auth, other_auth):
    listing = make_listing(client, auth)
    conversation_id = _conversation(client, other_auth, listing["id"])
    web_login(client)
    page = client.get(f"/meldinger/{conversation_id}").text
    assert "Hurtigsvar" in page and "Beklager, den er solgt." in page
    client.post(
        f"/meldinger/{conversation_id}",
        data={"csrf_token": csrf(client), "message": "Ja, den er fortsatt til salgs."},
    )
    thread = client.get(f"/api/v1/conversations/{conversation_id}", headers=other_auth).json()
    assert thread["messages"][-1]["body"] == "Ja, den er fortsatt til salgs."


def test_buyers_get_no_quick_replies(client, auth, other_auth):
    listing = make_listing(client, auth)
    conversation_id = _conversation(client, other_auth, listing["id"])
    web_login(client, email="ola@example.no")
    assert "Hurtigsvar" not in client.get(f"/meldinger/{conversation_id}").text


def test_choose_main_photo(client, auth):
    listing = make_listing(client, auth)
    for seed in (1, 2):
        client.post(
            f"/api/v1/listings/{listing['id']}/images",
            files={"file": ("photo.png", make_image(seed + 10), "image/png")},
            headers=auth,
        )
    before = [i["id"] for i in client.get(f"/api/v1/listings/{listing['id']}").json()["images"]]
    web_login(client)
    assert "Gjør til hovedbilde" in client.get(f"/annonse/{listing['id']}/rediger").text
    client.post(f"/annonse/{listing['id']}/bilder/{before[1]}/hovedbilde", data={"csrf_token": csrf(client)})
    after = [i["id"] for i in client.get(f"/api/v1/listings/{listing['id']}").json()["images"]]
    assert after == [before[1], before[0]]
    assert (
        client.post(
            f"/annonse/{listing['id']}/bilder/999999/hovedbilde", data={"csrf_token": csrf(client)}
        ).status_code
        == 404
    )


def test_views_are_counted_for_the_owner(app, client, auth, settings):
    listing = make_listing(client, auth)
    lid = listing["id"]
    client.get(f"/annonse/{lid}", headers=BROWSER)
    client.get(f"/annonse/{lid}", headers=BROWSER)  # a reload counts once
    client.get(f"/annonse/{lid}", headers={"User-Agent": "Googlebot/2.1"})  # bots don't count
    client.get(f"/annonse/{lid}.json", headers=BROWSER)  # machine-readable twins don't count
    assert app.state.views.pending(lid) == 1

    web_login(client)
    page = client.get(f"/annonse/{lid}", headers=BROWSER).text  # the owner's own visit doesn't count
    assert "Sett 1 gang" in page
    maintenance.run(app.state.db, settings, views=app.state.views)
    assert app.state.views.pending(lid) == 0
    assert client.get(f"/api/v1/listings/{lid}", headers=auth).json()["views"] == 1
    assert client.get(f"/api/v1/listings/{lid}").json()["views"] is None  # only for the owner
    assert "sett 1 gang" in client.get("/min-side").text


def test_breadcrumbs_for_search_engines(client, auth):
    listing = make_listing(client, auth)
    page = client.get(f"/annonse/{listing['id']}").text
    blocks = [
        json.loads(block) for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page)
    ]
    crumbs = next(b for b in blocks if b.get("@type") == "BreadcrumbList")
    names = [item["name"] for item in crumbs["itemListElement"]]
    assert names == ["Forside", "Torget", "Sykler", "Terrengsykkel Trek Marlin 7"]
