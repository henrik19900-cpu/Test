"""Limits that stop guessing, scraping and pile-ons, from a review of how the site could be abused."""

from __future__ import annotations

import re

from conftest import csrf, make_listing, register
from test_mcp import HEADERS, call

from fritorg import listings, users
from fritorg.mailer import MemoryMailer

WRONG = "feil-passord"


def _login(client, email="kari@example.no", password="hemmelig123"):
    return client.post("/api/v1/auth/token", json={"email": email, "password": password})


def test_wrong_passwords_lock_the_account_for_a_while(app, client, settings):
    settings.rate_limit_auth_per_10min = 1000  # the limit per IP address is tested elsewhere
    register(client)
    register(client, email="ola@example.no", name="Ola Hansen")
    for _ in range(users.WRONG_PASSWORDS - 1):
        assert _login(client, password=WRONG).status_code == 401
    assert _login(client).status_code == 201  # the right password starts the count again
    for _ in range(users.WRONG_PASSWORDS):
        assert _login(client, email="KARI@example.no ", password=WRONG).status_code == 401
    locked = _login(client)  # even with the right password, whatever the spelling or address
    assert locked.status_code == 429 and "Retry-After" in locked.headers
    assert "Glemt passordet" in locked.json()["detail"]
    page = client.post(
        "/logg-inn",
        data={
            "email": "kari@example.no",
            "password": "hemmelig123",
            "csrf_token": csrf(client),
            "neste": "/",
        },
    )
    assert page.status_code == 429 and "For mange feil passord" in page.text
    assert _login(client, email="ola@example.no").status_code == 201  # other accounts are not affected

    # Addresses without an account are counted the same way, so the answer tells nothing.
    for _ in range(users.WRONG_PASSWORDS):
        assert _login(client, email="ingen@example.no", password=WRONG).status_code == 401
    assert _login(client, email="ingen@example.no", password=WRONG).status_code == 429

    later = app.state.limiter._clock() + 901
    app.state.limiter._clock = lambda: later
    assert _login(client).status_code == 201


def test_a_new_password_lifts_the_lock(app, client, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    register(client)
    for _ in range(users.WRONG_PASSWORDS):
        _login(client, password=WRONG)
    assert _login(client).status_code == 429
    client.post("/glemt-passord", data={"csrf_token": csrf(client), "email": "kari@example.no"})
    token = re.search(r"/nytt-passord\?token=(\S+)", memory.outbox[-1].body).group(1)
    client.post(
        "/nytt-passord", data={"csrf_token": csrf(client), "token": token, "password": "nyttpassord1"}
    )
    assert _login(client, password="nyttpassord1").status_code == 201


def test_asking_about_many_taken_addresses_stops_sign_ups(client):
    for i in range(users.TAKEN_PER_HOUR):
        register(client, email=f"person{i}@example.no", name="Kari Nordmann")
    for i in range(users.TAKEN_PER_HOUR):
        taken = client.post(
            "/api/v1/auth/register",
            json={"email": f"person{i}@example.no", "name": "Kari Nordmann", "password": "hemmelig123"},
        )
        assert taken.status_code == 409
    # Now new and taken addresses get the same answer.
    for email in ("person0@example.no", "ny@example.no"):
        refused = client.post(
            "/api/v1/auth/register", json={"email": email, "name": "Kari Nordmann", "password": "hemmelig123"}
        )
        assert refused.status_code == 429 and "Logg inn i stedet" in refused.json()["detail"]
    page = client.post(
        "/registrer",
        data={
            "csrf_token": csrf(client),
            "name": "Kari Nordmann",
            "email": "ny@example.no",
            "password": "hemmelig123",
            "terms": "1",
        },
    )
    assert page.status_code == 429 and "Logg inn i stedet" in page.text


def test_mcp_batches_are_capped_and_every_call_counts(app, client, settings):
    ping = [{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(1, 22)]
    too_big = client.post("/mcp", json=ping, headers=HEADERS)
    assert too_big.status_code == 400 and "at most 20" in too_big.json()["error"]["message"]
    assert len(client.post("/mcp", json=ping[:20], headers=HEADERS).json()) == 20

    settings.rate_limit_read_per_minute = 25  # 1 + 20 calls are used; a batch of 5 more is too much
    limited = client.post("/mcp", json=ping[:5], headers=HEADERS)
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_search_pages_stop_at_the_offset_limit(client, auth):
    make_listing(client, auth)
    result = call(client, "search_listings", {"offset": listings.MAX_OFFSET + 1})
    assert result["isError"] is True and "offset" in result["content"][0]["text"]
    assert call(client, "search_listings", {"offset": listings.MAX_OFFSET})["isError"] is False
    assert client.get("/api/v1/listings", params={"offset": listings.MAX_OFFSET + 1}).status_code == 422
    assert client.get("/api/v1/me/listings", params={"offset": 10**9}, headers=auth).status_code == 422


def test_the_last_page_that_can_be_asked_for_has_no_next_link(app, client, auth, monkeypatch):
    monkeypatch.setattr(listings, "MAX_OFFSET", 2)
    for i in range(5):
        make_listing(client, auth, title=f"Sykkel nummer {i} til salgs")
    first = client.get("/api/v1/listings", params={"limit": 2})
    assert first.json()["next"] and 'rel="next"' in first.headers["link"]
    last = client.get("/api/v1/listings", params={"limit": 2, "offset": 2})
    assert last.json()["next"] is None and 'rel="next"' not in last.headers["link"]


def test_reports_from_unverified_accounts_cannot_hide_a_listing(app, client, auth, settings):
    listing = make_listing(client, auth)
    settings.verification = "sms"  # reports now count only from people who confirmed a number
    reporters = [
        {
            "Authorization": f"Bearer {register(client, email=f'r{i}@example.no', name='Per Hansen')['token']['token']}"
        }
        for i in range(3)
    ]
    for headers in reporters:
        sent = client.post(
            f"/api/v1/listings/{listing['id']}/reports", json={"reason": "fraud"}, headers=headers
        )
        assert sent.status_code == 202
    assert client.get(f"/api/v1/listings/{listing['id']}").json()["status"] == "active"

    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET verified_at = '2026-01-01T00:00:00Z' WHERE email LIKE 'r%'")
    client.post(f"/api/v1/listings/{listing['id']}/reports", json={"reason": "fraud"}, headers=reporters[0])
    assert client.get(f"/api/v1/listings/{listing['id']}").status_code == 404  # hidden for review


def test_each_account_sends_a_limited_number_of_reports(app, client, auth, other_auth, monkeypatch):
    monkeypatch.setattr(listings, "REPORTS_PER_DAY", 2)
    first, second, third = (
        make_listing(client, auth, title=f"Sykkel nummer {i} til salgs") for i in range(3)
    )
    for listing in (first, second):
        assert (
            client.post(
                f"/api/v1/listings/{listing['id']}/reports", json={"reason": "spam"}, headers=other_auth
            ).status_code
            == 202
        )
    refused = client.post(
        f"/api/v1/listings/{third['id']}/reports", json={"reason": "spam"}, headers=other_auth
    )
    assert refused.status_code == 429
    result = call(client, "report_listing", {"listing_id": third["id"], "reason": "spam"}, headers=other_auth)
    assert result["isError"] is True


def test_anonymous_mcp_reports_are_limited_per_address(client, auth):
    listing = make_listing(client, auth)
    for _ in range(20):
        assert (
            call(client, "report_listing", {"listing_id": listing["id"], "reason": "spam"})["isError"]
            is False
        )
    assert call(client, "report_listing", {"listing_id": listing["id"], "reason": "spam"})["isError"] is True
