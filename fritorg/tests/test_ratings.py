"""Ratings between buyers and sellers: recorded trades, rating once each, revealing both together,
reports and moderation, and the same through the web pages and MCP."""

from __future__ import annotations

from conftest import csrf, make_listing, register, web_login
from fastapi.testclient import TestClient
from test_mcp import call

from fritorg import maintenance, ratings, users
from fritorg.mailer import MemoryMailer
from fritorg.util import iso_ago


def _talk(client, seller, buyer, **listing_fields):
    """A listing from `seller` that `buyer` asked about and the seller answered. Returns (listing, conversation)."""
    listing = make_listing(client, seller, **listing_fields)
    conversation = client.post(
        "/api/v1/conversations", json={"listing_id": listing["id"], "message": "Er den ledig?"}, headers=buyer
    ).json()
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"message": "Ja, kom i kveld."},
        headers=seller,
    )
    return listing, conversation


def _ratings_of(client, user_id):
    return client.get(f"/api/v1/users/{user_id}/ratings").json()


def test_both_rate_after_the_seller_records_the_trade(client, auth, other_auth):
    listing = make_listing(client, auth)
    conversation = client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Er den ledig?"},
        headers=other_auth,
    ).json()
    early = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth)
    assert early.status_code == 422  # the seller has not written yet
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"message": "Ja, kom i kveld."},
        headers=auth,
    )
    assert (
        client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=other_auth).status_code
        == 403
    )

    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    assert trade["role"] == "seller" and trade["other_party"]["name"] == "Ola Hansen" and trade["can_rate"]
    assert client.get(f"/api/v1/listings/{listing['id']}").json()["status"] == "sold"
    again = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    assert again["id"] == trade["id"]

    mine = client.get("/api/v1/me/trades", headers=other_auth).json()
    assert [t["id"] for t in mine] == [trade["id"]] and mine[0]["role"] == "buyer" and mine[0]["can_rate"]
    rated = client.post(
        f"/api/v1/trades/{trade['id']}/rating",
        json={"score": 5, "comment": "Rask og hyggelig."},
        headers=other_auth,
    ).json()
    assert rated["my_rating"]["score"] == 5 and rated["their_rating"] is None and not rated["can_rate"]
    # Not shown until the seller has rated too (or two weeks have passed).
    assert _ratings_of(client, listing["seller_id"]) == {
        "summary": {"count": 0, "average": None},
        "items": [],
    }
    assert client.get("/api/v1/me/trades", headers=auth).json()[0]["they_rated"] is True
    assert client.get("/api/v1/me/trades", headers=auth).json()[0]["their_rating"] is None

    seller_view = client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 4}, headers=auth).json()
    assert (
        seller_view["their_rating"]["score"] == 5
        and seller_view["their_rating"]["comment"] == "Rask og hyggelig."
    )
    shown = _ratings_of(client, listing["seller_id"])
    assert shown["summary"] == {"count": 1, "average": 5.0}
    assert (
        shown["items"][0]["rater"]["name"] == "Ola Hansen"
        and shown["items"][0]["listing_title"] == listing["title"]
    )
    buyer_id = trade["other_party"]["id"]
    assert _ratings_of(client, buyer_id)["summary"] == {"count": 1, "average": 4.0}
    assert client.get(f"/api/v1/listings/{listing['id']}").json()["seller"]["rating"] == {
        "count": 1,
        "average": 5.0,
    }
    assert client.get(f"/api/v1/users/{buyer_id}").json()["rating"] == {"count": 1, "average": 4.0}

    twice = client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 1}, headers=auth)
    assert twice.status_code == 422 and "allerede" in twice.json()["detail"]
    stranger = {
        "Authorization": f"Bearer {register(client, email='per@example.no', name='Per')['token']['token']}"
    }
    assert (
        client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 1}, headers=stranger).status_code
        == 404
    )


def test_one_rating_is_shown_after_two_weeks(app, client, auth, other_auth):
    listing, conversation = _talk(client, auth, other_auth)
    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 2}, headers=other_auth)
    assert _ratings_of(client, listing["seller_id"])["summary"]["count"] == 0
    with app.state.db.session() as conn:
        conn.execute("UPDATE trades SET created_at = ?", (iso_ago(days=ratings.REVEAL_DAYS + 1),))
    assert _ratings_of(client, listing["seller_id"])["summary"] == {"count": 1, "average": 2.0}
    # The seller sees it now too, without rating back.
    assert client.get("/api/v1/me/trades", headers=auth).json()[0]["their_rating"]["score"] == 2


def test_rules_for_scores_comments_and_the_deadline(app, client, auth, other_auth):
    _, conversation = _talk(client, auth, other_auth)
    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    url = f"/api/v1/trades/{trade['id']}/rating"
    assert client.post(url, json={"score": 6}, headers=other_auth).status_code == 422
    for comment in ("Se https://example.com", "Ring meg på 912 34 567", "Skriv til ola@example.no"):
        response = client.post(url, json={"score": 5, "comment": comment}, headers=other_auth)
        assert response.status_code == 422 and "lenker" in response.json()["detail"], comment
    with app.state.db.session() as conn:
        conn.execute("UPDATE trades SET created_at = ?", (iso_ago(days=ratings.RATE_DAYS + 1),))
    late = client.post(url, json={"score": 5}, headers=other_auth)
    assert late.status_code == 422 and "Fristen" in late.json()["detail"]
    assert client.get("/api/v1/me/trades", headers=other_auth).json()[0]["can_rate"] is False


def test_job_ads_and_removed_listings_are_not_traded(app, client, auth, other_auth):
    _, job_talk = _talk(
        client,
        auth,
        other_auth,
        category="jobb-it",
        type="job",
        title="Utvikler søkes",
        description="Vi søker en utvikler til teamet vårt.",
        attributes={},
        price=None,
    )
    assert client.post(f"/api/v1/conversations/{job_talk['id']}/trade", headers=auth).status_code == 422
    listing, conversation = _talk(
        client, auth, other_auth, title="Sofa", description="God og pen sofa med tre seter.", attributes={}
    )
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET status = 'removed' WHERE id = ?", (listing["id"],))
    assert client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).status_code == 422


def test_trades_and_ratings_on_the_web_pages(app, client, auth, other_auth):
    _, conversation = _talk(client, auth, other_auth)
    web_login(client)
    page = client.get(f"/meldinger/{conversation['id']}").text
    assert "Ble det en avtale?" in page and "Solgt til Ola Hansen" in page
    response = client.post(
        f"/meldinger/{conversation['id']}/handel", data={"csrf_token": csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 303
    page = client.get(f"/meldinger/{conversation['id']}").text
    assert "Hvordan var handelen med Ola Hansen?" in page and "Solgt til Ola Hansen" not in page

    with TestClient(app) as buyer:
        web_login(buyer, email="ola@example.no")
        buyer.post(
            f"/meldinger/{conversation['id']}/vurdering",
            data={"csrf_token": csrf(buyer), "score": "5", "comment": "Alt som avtalt."},
        )
        page = buyer.get(f"/meldinger/{conversation['id']}").text
        assert "Du ga Kari Nordmann" in page and "5 av 5" in page
        bad = buyer.post(
            f"/meldinger/{conversation['id']}/vurdering", data={"csrf_token": csrf(buyer), "score": "4"}
        )
        assert "allerede" in bad.text

    page = client.get(f"/meldinger/{conversation['id']}").text
    assert "Ola Hansen har vurdert deg" in page
    client.post(f"/meldinger/{conversation['id']}/vurdering", data={"csrf_token": csrf(client), "score": "4"})
    page = client.get(f"/meldinger/{conversation['id']}").text
    assert "Ola Hansen ga deg" in page and "Alt som avtalt." in page

    seller_id = client.get("/api/v1/me", headers=auth).json()["id"]
    profile = client.get(f"/bruker/{seller_id}").text
    assert "5,0 av 5" in profile and "1 vurdering" in profile and "Alt som avtalt." in profile
    listing_id = conversation["listing_id"]
    assert "5,0 av 5" in client.get(f"/annonse/{listing_id}").text


def test_reported_ratings_go_to_the_moderators(app, client, auth, other_auth):
    listing, conversation = _talk(client, auth, other_auth)
    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    client.post(
        f"/api/v1/trades/{trade['id']}/rating", json={"score": 1, "comment": "Elendig."}, headers=other_auth
    )
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 5}, headers=auth)
    rating_id = _ratings_of(client, listing["seller_id"])["items"][0]["id"]
    report = client.post(
        f"/api/v1/ratings/{rating_id}/reports", json={"reason": "offensive", "comment": "Usant"}, headers=auth
    )
    assert report.status_code == 202

    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = 'kari@example.no'")
    web_login(client)
    page = client.get("/moderering").text
    assert "Rapporterte vurderinger (1)" in page and "Elendig." in page
    assert "Rapporter (0)" in page  # not mixed in with reports about listings and users
    client.post(
        f"/moderering/vurdering/{rating_id}/fjern", data={"csrf_token": csrf(client), "note": "Usaklig"}
    )
    assert _ratings_of(client, listing["seller_id"])["summary"]["count"] == 0
    assert "Rapporterte vurderinger (0)" in client.get("/moderering").text
    assert client.get("/api/v1/me/trades", headers=other_auth).json()[0]["my_rating"] is None


def test_ratings_from_closed_accounts_do_not_count(app, client, auth, other_auth):
    listing, conversation = _talk(client, auth, other_auth)
    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 5}, headers=other_auth)
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 5}, headers=auth)
    assert _ratings_of(client, listing["seller_id"])["summary"]["count"] == 1
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET banned_at = '2026-01-01T00:00:00Z' WHERE email = 'ola@example.no'")
    assert _ratings_of(client, listing["seller_id"])["summary"]["count"] == 0


def test_ratings_outlive_the_listing_but_not_the_accounts(app, client, auth, other_auth, settings):
    listing, conversation = _talk(client, auth, other_auth)
    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 5}, headers=other_auth)
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 4}, headers=auth)
    with app.state.db.session() as conn:  # deleted automatically a year after it was sold
        conn.execute("UPDATE listings SET updated_at = ?", (iso_ago(days=400),))
    maintenance.run(app.state.db, settings)
    with app.state.db.session() as conn:
        conn.execute("UPDATE listings SET deletion_notice_at = ?", (iso_ago(days=20),))
    assert maintenance.run(app.state.db, settings).deleted == 1
    assert _ratings_of(client, listing["seller_id"])["summary"]["count"] == 1
    export = client.get("/api/v1/me/export", headers=other_auth).json()
    assert export["trades"][0]["listing_id"] is None and export["trades"][0]["my_rating"]["score"] == 5

    with app.state.db.session() as conn:
        users.delete_user(conn, trade["other_party"]["id"])
    assert _ratings_of(client, listing["seller_id"])["summary"]["count"] == 0


def test_agents_record_trades_and_rate_through_mcp(app, client, auth, other_auth):
    listing, conversation = _talk(client, auth, other_auth)
    trade = call(client, "record_sale", {"conversation_id": conversation["id"]}, headers=auth)[
        "structuredContent"
    ]
    assert trade["role"] == "seller"
    pending = call(client, "list_trades", headers=other_auth)["structuredContent"]["trades"]
    assert pending[0]["can_rate"] is True
    rated = call(
        client,
        "rate_trade",
        {"trade_id": trade["id"], "score": 5, "comment": "Fin handel."},
        headers=other_auth,
    )["structuredContent"]
    assert rated["my_rating"]["score"] == 5
    call(client, "rate_trade", {"trade_id": trade["id"], "score": 5}, headers=auth)
    shown = call(client, "get_user_ratings", {"user_id": listing["seller_id"]})["structuredContent"]
    assert shown["summary"] == {"count": 1, "average": 5.0} and shown["items"][0]["comment"] == "Fin handel."


def test_people_are_asked_to_rate_by_email(app, client, auth, other_auth, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET email_verified_at = '2026-01-01T00:00:00Z'")
    _, conversation = _talk(client, auth, other_auth)
    memory.outbox.clear()  # the message notifications
    trade = client.post(f"/api/v1/conversations/{conversation['id']}/trade", headers=auth).json()
    assert [m.to for m in memory.outbox] == ["ola@example.no"]
    assert "Hvordan gikk handelen med Kari Nordmann?" == memory.outbox[0].subject
    assert f"/meldinger/{conversation['id']}#vurdering" in memory.outbox[0].body
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 5}, headers=other_auth)
    assert memory.outbox[-1].to == "kari@example.no" and "har vurdert handelen" in memory.outbox[-1].subject
    count = len(memory.outbox)
    client.post(f"/api/v1/trades/{trade['id']}/rating", json={"score": 5}, headers=auth)
    assert len(memory.outbox) == count  # both have rated: nobody needs a reminder
