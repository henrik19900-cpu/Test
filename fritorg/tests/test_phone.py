from __future__ import annotations

import re
import urllib.parse

import pytest
from conftest import csrf, make_listing, register
from fastapi.testclient import TestClient
from test_mcp import call, rpc

from fritorg import listings, ops, phone, users
from fritorg.app import create_app
from fritorg.config import Settings
from fritorg.errors import ValidationProblem

NUMBER = "912 34 567"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", bankid_mode="off", verification="sms", sms_provider="console")


def bearer(data):
    return {"Authorization": f"Bearer {data['token']['token']}"}


def send_code(client, headers, number=NUMBER):
    return client.post("/api/v1/me/phone", json={"phone": number}, headers=headers)


def verify(client, headers, number=NUMBER):
    code = send_code(client, headers, number).json()["test_code"]
    response = client.post("/api/v1/me/phone/verify", json={"code": code}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_normalize_mobile():
    for raw in ("912 34 567", "+47 912 34 567", "0047 91234567", "4791234567", "912-34-567"):
        assert phone.normalize_mobile(raw) == "+4791234567"
    assert phone.normalize_mobile("412 34 567") == "+4741234567"
    for bad in ("22 33 44 55", "9123456", "+46 70 123 45 67", "912345678", "", "ring meg"):
        with pytest.raises(ValidationProblem):
            phone.normalize_mobile(bad)
    assert phone.phone_hint("+4791234567") == "+47 •••••567"


def test_unverified_accounts_must_verify_before_posting_or_messaging(client):
    seller = register(client)
    assert seller["account"]["verification_required"] is True
    refused = client.post(
        "/api/v1/listings",
        json={"category": "sykler", "title": "Sykkel", "description": "En fin sykkel til salgs."},
        headers=bearer(seller),
    )
    assert refused.status_code == 403
    problem = refused.json()
    assert problem["code"] == "verification_required"
    assert "/api/v1/me/phone" in problem["hint"] and "verify_phone" in problem["hint"]

    verify(client, bearer(seller))
    listing = make_listing(client, bearer(seller))
    buyer = register(client, email="ola@example.no", name="Ola Hansen")
    message = {"listing_id": listing["id"], "message": "Hei! Er den ledig?"}
    assert client.post("/api/v1/conversations", json=message, headers=bearer(buyer)).status_code == 403
    verify(client, bearer(buyer), "41234567")
    assert client.post("/api/v1/conversations", json=message, headers=bearer(buyer)).status_code == 201


def test_api_verification_flow(client):
    data = register(client)
    sent = send_code(client, bearer(data))
    assert sent.status_code == 202
    body = sent.json()
    assert body["phone_hint"] == "+47 •••••567" and body["expires_in"] == 600
    assert re.fullmatch(r"\d{6}", body["test_code"])  # console provider: development only

    wrong = "000000" if body["test_code"] != "000000" else "111111"
    failed = client.post("/api/v1/me/phone/verify", json={"code": wrong}, headers=bearer(data))
    assert failed.status_code == 422 and "4 forsøk igjen" in failed.json()["detail"]

    account = client.post(
        "/api/v1/me/phone/verify", json={"code": f" {body['test_code']} "}, headers=bearer(data)
    ).json()
    assert account["verified"] is True and account["verification"] == "phone"
    assert account["verification_required"] is False and account["phone_hint"] == "+47 •••••567"

    listing = make_listing(client, bearer(data))
    assert listing["seller"]["verified"] is True and listing["seller"]["verification"] == "phone"
    assert "Mobilnummer bekreftet" in client.get(f"/annonse/{listing['id']}").text
    profile = client.get(f"/api/v1/users/{data['account']['id']}").json()
    assert profile["verification"] == "phone"


def test_the_number_itself_is_never_stored(app, client):
    data = register(client)
    verify(client, bearer(data))
    with app.state.db.session() as conn:
        rows = [tuple(r) for r in conn.execute("SELECT * FROM users")]
        rows += [tuple(r) for r in conn.execute("SELECT * FROM phone_codes")]
    stored = " ".join(str(value) for row in rows for value in row)
    assert "91234567" not in stored and "912 34 567" not in stored
    assert "+47 •••••567" in stored


def test_five_wrong_codes_lock_the_code(client):
    data = register(client)
    code = send_code(client, bearer(data)).json()["test_code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/api/v1/me/phone/verify", json={"code": wrong}, headers=bearer(data))
    locked = client.post("/api/v1/me/phone/verify", json={"code": code}, headers=bearer(data))
    assert locked.status_code == 422 and "For mange feil forsøk" in locked.json()["detail"]
    # A new code works again.
    verify(client, bearer(data))


def test_expired_codes_are_refused(app, client):
    data = register(client)
    code = send_code(client, bearer(data)).json()["test_code"]
    with app.state.db.session() as conn:
        conn.execute("UPDATE phone_codes SET expires_at = '2000-01-01T00:00:00Z'")
    expired = client.post("/api/v1/me/phone/verify", json={"code": code}, headers=bearer(data))
    assert expired.status_code == 422 and "utløpt" in expired.json()["detail"]


def test_one_account_per_number(app, client):
    verify(client, bearer(register(client)))
    other = register(client, email="ola@example.no", name="Ola Hansen")
    # The same answer as for any number, so nobody can test which numbers have accounts.
    taken = send_code(client, bearer(other), "+47 912 34 567")
    assert taken.status_code == 202 and taken.json()["phone_hint"] == "+47 •••••567"
    assert taken.json()["test_code"] is None
    # The owner of the number gets an explanation instead of a code.
    to, message = app.state.sms.outbox[-1]
    assert to == "+4791234567" and "allerede knyttet til en konto" in message
    assert not re.search(r"\d{6}", message)
    guess = client.post("/api/v1/me/phone/verify", json={"code": "123456"}, headers=bearer(other))
    assert guess.status_code in (409, 422)  # a lucky guess still meets the check in confirm()
    assert client.get("/api/v1/me", headers=bearer(other)).json()["verified"] is False


def test_code_requests_are_rate_limited(client):
    data = register(client)
    for _ in range(phone.CODES_PER_HOUR_PER_USER):
        assert send_code(client, bearer(data)).status_code == 202
    limited = send_code(client, bearer(data))
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_daily_sms_limit_caps_costs(tmp_path):
    capped = Settings(data_dir=tmp_path, bankid_mode="off", verification="sms", sms_daily_limit=1)
    with TestClient(create_app(capped)) as client:
        assert send_code(client, bearer(register(client))).status_code == 202
        other = register(client, email="ola@example.no", name="Ola Hansen")
        assert send_code(client, bearer(other), "41234567").status_code == 429


def test_selling_and_hiding_is_allowed_before_verification(app, client):
    data = register(client)
    with app.state.db.session() as conn:  # e.g. a listing from before verification was turned on
        listing_id = listings.create_listing(
            conn,
            data["account"]["id"],
            {"category": "sykler", "title": "Gammel sykkel", "description": "Lagt ut før bekreftelse."},
        )
    headers = bearer(data)
    patch = f"/api/v1/listings/{listing_id}"
    assert client.patch(patch, json={"status": "sold"}, headers=headers).status_code == 200
    assert client.patch(patch, json={"title": "Ny tittel her"}, headers=headers).status_code == 403
    assert client.patch(patch, json={"status": "active"}, headers=headers).status_code == 403
    assert client.delete(patch, headers=headers).status_code == 204


def test_web_flow(client):
    response = client.post(
        "/registrer",
        data={
            "csrf_token": csrf(client),
            "name": "Kari Nordmann",
            "email": "kari@example.no",
            "password": "hemmelig123",
            "terms": "1",
            "neste": "/ny-annonse",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/verifiser-telefon?neste=%2Fny-annonse"

    gated = client.get("/ny-annonse", follow_redirects=False)
    assert gated.status_code == 303 and gated.headers["location"].startswith("/verifiser-telefon")
    page = client.get("/verifiser-telefon?neste=/ny-annonse")
    assert "Bekreft mobilnummeret ditt" in page.text and "Testmodus" in page.text

    invalid = client.post(
        "/verifiser-telefon",
        data={"csrf_token": csrf(client), "phone": "22 33 44 55", "neste": "/ny-annonse"},
    )
    assert invalid.status_code == 422 and "8 siffer" in invalid.text

    page = client.post(
        "/verifiser-telefon", data={"csrf_token": csrf(client), "phone": NUMBER, "neste": "/ny-annonse"}
    )
    assert "Sendt til +47 •••••567" in page.text
    code = re.search(r"koden er (\d{6})", page.text)  # test mode shows the code instead of sending it
    assert code, page.text

    wrong = client.post(
        "/verifiser-telefon/kode", data={"csrf_token": csrf(client), "code": "12345x", "neste": "/ny-annonse"}
    )
    assert wrong.status_code == 422 and "Feil kode" in wrong.text

    done = client.post(
        "/verifiser-telefon/kode",
        data={"csrf_token": csrf(client), "code": code.group(1), "neste": "/ny-annonse"},
        follow_redirects=False,
    )
    assert done.headers["location"] == "/ny-annonse"
    assert client.get("/ny-annonse").status_code == 200
    assert "Mobilnummer bekreftet" in client.get("/min-side").text


def test_listing_page_asks_unverified_buyers_to_verify(client):
    seller = register(client)
    verify(client, bearer(seller))
    listing = make_listing(client, bearer(seller))
    register(client, email="ola@example.no", name="Ola Hansen")
    client.post(
        "/logg-inn",
        data={"email": "ola@example.no", "password": "hemmelig123", "csrf_token": csrf(client), "neste": "/"},
    )
    page = client.get(f"/annonse/{listing['id']}").text
    assert (
        "Bekreft mobilnummer" in page and 'action="/annonse/' + str(listing["id"]) + '/melding"' not in page
    )
    sent = client.post(
        f"/annonse/{listing['id']}/melding",
        data={"csrf_token": csrf(client), "message": "Hei!"},
        follow_redirects=False,
    )
    assert sent.headers["location"].startswith("/verifiser-telefon")


def test_mcp_verify_phone_tool(client):
    data = register(client)
    headers = bearer(data)
    names = {
        t["name"]
        for t in client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers
        ).json()["result"]["tools"]
    }
    assert "verify_phone" in names

    whoami = call(client, "whoami", headers=headers)["structuredContent"]
    assert whoami["verification_required"] is True and "verify_phone" in whoami["next_steps"]

    listing = {"category": "sykler", "title": "Sykkel", "description": "En fin sykkel til salgs."}
    refused = call(client, "create_listing", listing, headers=headers)
    assert refused["isError"] and "verify_phone" in refused["content"][0]["text"]

    sent = call(client, "verify_phone", {"phone": NUMBER}, headers=headers)["structuredContent"]
    assert sent["status"] == "code_sent" and sent["phone_hint"] == "+47 •••••567"
    done = call(client, "verify_phone", {"code": sent["test_code"]}, headers=headers)["structuredContent"]
    assert done["verified"] is True
    created = call(client, "create_listing", listing, headers=headers)
    assert not created["isError"], created
    assert created["structuredContent"]["seller"]["verification"] == "phone"

    missing = call(client, "verify_phone", {}, headers=headers)
    assert missing["isError"]


def test_verify_phone_tool_is_hidden_without_sms(tmp_path):
    plain = Settings(data_dir=tmp_path, bankid_mode="off", verification="none")
    with TestClient(create_app(plain)) as client:
        headers = bearer(register(client))
        tools = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers
        ).json()["result"]["tools"]
        assert "verify_phone" not in {t["name"] for t in tools}
        hidden = rpc(
            client, "tools/call", {"name": "verify_phone", "arguments": {"phone": NUMBER}}, headers=headers
        )
        assert hidden.json()["error"]["code"] == -32602
        assert client.post("/api/v1/me/phone", json={"phone": NUMBER}, headers=headers).status_code == 404


def test_console_sms_is_refused_in_production(tmp_path):
    production = Settings(data_dir=tmp_path, base_url="https://fritorg.example", verification="sms")
    with pytest.raises(RuntimeError, match="console"):
        create_app(production)
    production.allow_console_sms = True  # an explicitly public demo site
    create_app(production)
    with pytest.raises(RuntimeError, match="FRITORG_SMS_URL"):
        phone.create_sender(Settings(data_dir=tmp_path, sms_provider="http"))
    with pytest.raises(RuntimeError, match="TWILIO"):
        phone.create_sender(Settings(data_dir=tmp_path, sms_provider="twilio"))


def test_sms_providers(monkeypatch):
    sent = []
    monkeypatch.setattr(phone, "_request", lambda url, data, headers: sent.append((url, data, headers)))

    phone.TwilioSms("AC123", "secret", "Fritorg").send("+4791234567", "123456 er koden")
    url, data, headers = sent[-1]
    assert url == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert urllib.parse.parse_qs(data.decode()) == {
        "To": ["+4791234567"],
        "From": ["Fritorg"],
        "Body": ["123456 er koden"],
    }
    assert headers["Authorization"].startswith("Basic ")

    phone.HttpSms("https://sms.example/send?to={to_digits}&text={message}").send("+4791234567", "Kode: 1 2")
    assert (
        sent[-1][0] == "https://sms.example/send?to=4791234567&text=Kode%3A%201%202" and sent[-1][1] is None
    )

    phone.HttpSms("https://sms.example/send?nr={to_local}&msg={message}", "POST").send("+4791234567", "Hei")
    url, data, headers = sent[-1]
    assert url == "https://sms.example/send" and data == b"nr=91234567&msg=Hei"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_sms_text_warns_against_sharing_the_code(app, client):
    verify(client, bearer(register(client)))
    to, message = app.state.sms.outbox[-1]
    assert to == "+4791234567"
    assert re.match(r"\d{6} er koden din hos Fritorg", message) and "Ikke del den" in message


def test_doctor_checks_sms(tmp_path, monkeypatch):
    console = ops.doctor(Settings(data_dir=tmp_path))
    assert any(c.ok is False and "console" in c.text for c in console)
    none = ops.doctor(Settings(data_dir=tmp_path, verification="none"))
    assert any(c.ok is False and "FRITORG_VERIFICATION" in c.text for c in none)

    sent = []
    monkeypatch.setattr(phone, "_request", lambda url, data, headers: sent.append(url))
    ready = Settings(
        data_dir=tmp_path, sms_provider="http", sms_url="https://sms.example/?to={to}&m={message}"
    )
    checks = ops.doctor(ready, test_sms_to=NUMBER)
    assert any(c.ok and "via http" in c.text for c in checks)
    assert any(c.ok and "Test-SMS sendt til +47 •••••567" in c.text for c in checks)
    assert sent and "%2B4791234567" in sent[0]


def test_seeded_demo_users_are_verified(tmp_path):
    from fritorg.seed import DEMO_EMAIL, seed

    demo = Settings(data_dir=tmp_path, verification="sms")
    app = create_app(demo)
    seed(app.state.db, demo)
    with app.state.db.session() as conn:
        user = users.get_user_by_email(conn, DEMO_EMAIL)
        assert user is not None and user.verification == "phone"
        assert not phone.verification_needed(demo, user)
