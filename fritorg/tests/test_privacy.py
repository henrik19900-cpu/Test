from __future__ import annotations

import json
import re

from conftest import csrf, make_listing, register, web_login

from fritorg import moderation, privacy, users
from fritorg.util import iso_ago

# Files a page makes the browser fetch: scripts, images and frames, and <link> (style sheets, icons).
RESOURCE = re.compile(
    r"<(?:script|img|iframe|source|video|audio|embed)\b[^>]*?\bsrc=[\"']([^\"']+)|<link\b[^>]*?\bhref=[\"']([^\"']+)",
    re.IGNORECASE,
)


def test_pages_make_browsers_fetch_nothing_from_other_sites(client, auth):
    listing = make_listing(client, auth)
    for path in ("/", "/sok?q=sykkel", f"/annonse/{listing['id']}", "/vilkar", "/logg-inn", "/api/docs"):
        page = client.get(path)
        assert page.status_code == 200, path
        for src, href in RESOURCE.findall(page.text):
            url = src or href
            # A file from another site tells that site the visitor's IP address and what they look at.
            assert not re.match(r"(?:[a-z]+:)?//", url) or url.startswith("http://testserver/"), (path, url)
    docs = client.get("/api/docs")
    for url in re.findall(r"(?:src|href)=\"(/static/[^\"]+)\"", docs.text):
        assert client.get(url).status_code == 200, url
    policy = docs.headers["content-security-policy"]  # nor may the script fetch anything from elsewhere
    assert "default-src 'self'" in policy and "http" not in policy


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
        {"listing_id": listing["id"], "rating_id": None, "reason": "spam",
         "created_at": data["reports_about_you"][0]["created_at"], "resolved_at": None, "resolution": None}
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


def test_the_export_does_not_tell_who_reported_you(client, auth, other_auth):
    listing = make_listing(client, auth)
    conversation = client.post(
        "/api/v1/conversations", json={"listing_id": listing["id"], "message": "Hei!"}, headers=other_auth
    ).json()["id"]
    reported = client.post(
        f"/api/v1/conversations/{conversation}/reports",
        json={"reason": "fraud", "comment": "Ba om BankID-koden min"},
        headers=other_auth,
    )
    assert reported.status_code == 202, reported.text
    about = client.get("/api/v1/me/export", headers=auth).json()["reports_about_you"]
    assert [r["reason"] for r in about] == ["fraud"]
    # The conversation would give the reporter away: they are the only other person in it.
    assert "conversation_id" not in about[0] and "BankID-koden" not in json.dumps(about)


def _rated_trade(client, seller_auth, buyer_auth):
    """A trade the seller recorded, rated by both. Returns the trade id."""
    listing = make_listing(client, seller_auth)
    conversation = client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Er den ledig?"},
        headers=buyer_auth,
    ).json()["id"]
    client.post(
        f"/api/v1/conversations/{conversation}/messages", json={"message": "Ja."}, headers=seller_auth
    )
    trade = client.post(f"/api/v1/conversations/{conversation}/trade", headers=seller_auth).json()["id"]
    client.post(
        f"/api/v1/trades/{trade}/rating", json={"score": 2, "comment": "Kom for sent"}, headers=buyer_auth
    )
    client.post(f"/api/v1/trades/{trade}/rating", json={"score": 5}, headers=seller_auth)
    return trade


def test_the_export_has_the_ratings_others_gave_you(app, client, auth, other_auth):
    _rated_trade(client, auth, other_auth)
    with app.state.db.session() as conn:  # a moderator removes Ola's rating of Kari
        moderator = users.create_user(conn, "mod@example.no", "Mona Berg", "hemmelig123")
        users.set_admin(conn, moderator.id)
        rating = conn.execute("SELECT id FROM ratings WHERE rater_id = 2").fetchone()["id"]
        moderation.remove_rating(conn, moderator, rating, "Ikke om handelen")
    received = client.get("/api/v1/me/export", headers=auth).json()["ratings_received"]
    assert [(r["score"], r["comment"], r["rater"]["name"]) for r in received] == [
        (2, "Kom for sent", "Ola Hansen")
    ]
    assert received[0]["removed_at"]  # still stored (for a year), so still in the person's copy


def test_the_export_says_which_assistants_have_access_and_what_notices_were_sent(app, client, auth):
    client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": ["https://claude.ai/cb"]})
    with app.state.db.session() as conn:
        users.create_api_token(conn, 1, "Claude")
        conn.execute(
            "UPDATE api_tokens SET oauth_client_id = (SELECT client_id FROM oauth_clients) WHERE name = 'Claude'"
        )
        conn.execute(
            "UPDATE users SET last_active_at = ?, inactivity_notice_at = ?, price_alerted_at = ? WHERE id = 1",
            (iso_ago(days=700), iso_ago(days=3), iso_ago(days=1)),
        )
        # Read directly: a request with the account's key would count as using it, and cancel the notice.
        data = privacy.export_user(conn, users.get_user(conn, 1), "http://testserver")
    assistant = next(t for t in data["api_tokens"] if t["name"] == "Claude")["assistant"]
    assert assistant["name"] == "Claude" and assistant["redirect_uris"] == ["https://claude.ai/cb"]
    account = data["account"]
    assert account["last_active_at"] and account["deletion_notice_sent_at"] and account["last_price_alert_at"]
