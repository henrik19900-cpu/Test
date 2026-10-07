from __future__ import annotations

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import csrf, register, web_login
from fastapi.testclient import TestClient

from fritorg import identity, users
from fritorg.app import create_app
from fritorg.config import Settings


@pytest.fixture
def bankid_app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data", bankid_mode="simulated"))


@pytest.fixture
def bankid_client(bankid_app):
    with TestClient(bankid_app) as test_client:
        yield test_client


def simulated_login(client: TestClient, name: str, subject: str, neste: str = "/min-side"):
    """Walk through /bankid/start -> simulator -> callback. Returns the callback response."""
    start = client.get(f"/bankid/start?neste={neste}", follow_redirects=False)
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    assert client.get(start.headers["location"]).status_code == 200
    submitted = client.post(
        "/bankid/simulator",
        data={"csrf_token": csrf(client), "state": state, "name": name, "subject": subject},
        follow_redirects=False,
    )
    assert submitted.status_code == 303, submitted.text
    return client.get(submitted.headers["location"], follow_redirects=False)


def register_with_bankid(
    client: TestClient, name="Kari Nordmann", subject="01017012345", email="kari@example.no"
):
    callback = simulated_login(client, name, subject)
    assert callback.headers["location"] == "/registrer/fullfor"
    page = client.get("/registrer/fullfor")
    assert "Kari N." in page.text or name.split()[0] in page.text
    done = client.post(
        "/registrer/fullfor",
        data={"csrf_token": csrf(client), "email": email, "terms": "1"},
        follow_redirects=False,
    )
    assert done.status_code == 303, done.text
    return done


def test_account_creation_requires_bankid(bankid_client, bankid_app):
    page = bankid_client.get("/registrer")
    assert "Fortsett med BankID" in page.text
    assert "Testmodus" in page.text  # simulated BankID is clearly labelled

    blocked = bankid_client.post(
        "/api/v1/auth/register", json={"email": "x@example.no", "name": "X Y", "password": "hemmelig123"}
    )
    assert blocked.status_code == 403
    assert "/api/v1/auth/device" in blocked.json()["hint"]

    register_with_bankid(bankid_client)
    me = bankid_client.get("/min-side")
    assert "Hei, Kari!" in me.text and "Kari N." in me.text and "BankID-verifisert" in me.text

    with bankid_app.state.db.session() as conn:
        row = conn.execute("SELECT * FROM users").fetchone()
    assert row["name"] == "Kari N."
    assert row["verified_name"] == "Kari Nordmann"
    assert row["password_hash"] == users.UNUSABLE_PASSWORD
    assert "01017012345" not in json.dumps(dict(row))  # the identity number is never stored


def test_one_person_one_account(bankid_client, bankid_app):
    register_with_bankid(bankid_client)
    bankid_client.post("/logg-ut", data={"csrf_token": csrf(bankid_client)})

    again = simulated_login(bankid_client, "Kari Nordmann", "01017012345")
    assert again.headers["location"] == "/min-side"  # straight in, no second account
    with bankid_app.state.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        user_id = conn.execute("SELECT id FROM users").fetchone()["id"]
        users.ban_user(conn, user_id, "Svindel")

    bankid_client.cookies.clear()
    banned = simulated_login(bankid_client, "Kari Nordmann", "01017012345")
    assert banned.headers["location"] == "/"
    assert "/min-side" not in banned.headers["location"]


def test_password_login_redirects_to_bankid(bankid_client):
    response = bankid_client.post(
        "/logg-inn",
        data={"csrf_token": csrf(bankid_client), "email": "a@b.no", "password": "x"},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/bankid/start")


def test_tampered_simulator_code_is_rejected(bankid_client):
    start = bankid_client.get("/bankid/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = bankid_client.get(
        f"/bankid/callback?state={state}&code=eyJmYWtlIjoxfQ.forged", follow_redirects=False
    )
    assert response.headers["location"] == "/logg-inn"


def test_simulator_cannot_run_in_production(tmp_path):
    settings = Settings(data_dir=tmp_path, bankid_mode="simulated", base_url="https://fritorg.example")
    with pytest.raises(RuntimeError, match="Simulated BankID"):
        create_app(settings)
    allowed = Settings(
        data_dir=tmp_path,
        bankid_mode="simulated",
        base_url="https://demo.example",
        allow_simulated_bankid=True,
    )
    create_app(allowed)


def test_simulator_is_off_without_bankid(client):
    assert client.get("/bankid/simulator?state=x").status_code == 404
    assert client.get("/bankid/start").status_code == 404


# --- Real OpenID Connect, against a fake provider ---------------------------------------------------


class FakeProvider:
    issuer = "https://idp.example"

    def __init__(self):
        self.requests: list[tuple[str, dict | None, dict]] = []
        self.claims: dict = {}

    def __call__(self, url, form, headers):
        self.requests.append((url, form, headers))
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
            }
        if url == f"{self.issuer}/token":
            payload = base64.urlsafe_b64encode(json.dumps(self.claims).encode()).decode().rstrip("=")
            return {"id_token": f"eyJhbGciOiJSUzI1NiJ9.{payload}.signature", "access_token": "at"}
        raise AssertionError(f"unexpected request {url}")


@pytest.fixture
def oidc(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        bankid_mode="oidc",
        bankid_issuer="https://idp.example",
        bankid_client_id="fritorg-client",
        bankid_client_secret="s3cret",
        bankid_acr_values="urn:grn:authn:no:bankid",
    )
    app = create_app(settings)
    fake = FakeProvider()
    app.state.identity_provider = identity.OidcProvider(settings, http=fake)
    with TestClient(app) as test_client:
        yield test_client, fake


def _start_oidc(client):
    start = client.get("/bankid/start?neste=/ny-annonse", follow_redirects=False)
    location = urlparse(start.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://idp.example/authorize"
    return {key: values[0] for key, values in parse_qs(location.query).items()}


def test_oidc_login_flow(oidc):
    client, fake = oidc
    params = _start_oidc(client)
    assert params["client_id"] == "fritorg-client"
    assert params["redirect_uri"] == "http://testserver/bankid/callback"
    assert params["code_challenge_method"] == "S256"
    assert params["acr_values"] == "urn:grn:authn:no:bankid"

    fake.claims = {
        "iss": "https://idp.example",
        "aud": "fritorg-client",
        "exp": int(time.time()) + 300,
        "nonce": params["nonce"],
        "sub": "9578-6000-4-123456",
        "name": "OLA NORDMANN",
    }
    callback = client.get(f"/bankid/callback?state={params['state']}&code=auth-code", follow_redirects=False)
    assert callback.headers["location"] == "/registrer/fullfor"

    token_url, form, headers = fake.requests[-1]
    assert token_url == "https://idp.example/token"
    assert form["code"] == "auth-code" and form["grant_type"] == "authorization_code"
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
    )
    assert expected_challenge == params["code_challenge"]  # PKCE
    assert headers["Authorization"] == "Basic " + base64.b64encode(b"fritorg-client:s3cret").decode()

    page = client.get("/registrer/fullfor")
    assert "Ola N." in page.text
    done = client.post(
        "/registrer/fullfor",
        data={"csrf_token": csrf(client), "email": "ola@example.no", "terms": "1"},
        follow_redirects=False,
    )
    assert done.headers["location"] == "/ny-annonse"


@pytest.mark.parametrize(
    "change",
    [
        {"nonce": "wrong"},
        {"aud": "someone-else"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 3600},
    ],
)
def test_oidc_rejects_bad_id_tokens(oidc, change):
    client, fake = oidc
    params = _start_oidc(client)
    fake.claims = {
        "iss": "https://idp.example",
        "aud": ["fritorg-client"],
        "exp": int(time.time()) + 300,
        "nonce": params["nonce"],
        "sub": "x",
        "name": "Ola Nordmann",
        **change,
    }
    callback = client.get(f"/bankid/callback?state={params['state']}&code=c", follow_redirects=False)
    assert callback.headers["location"] == "/logg-inn"


def test_oidc_rejects_unknown_state(oidc):
    client, _ = oidc
    callback = client.get("/bankid/callback?state=made-up&code=c", follow_redirects=False)
    assert callback.headers["location"] == "/logg-inn"


def test_oidc_mode_requires_configuration(tmp_path):
    with pytest.raises(RuntimeError, match="FRITORG_BANKID_ISSUER"):
        create_app(Settings(data_dir=tmp_path, bankid_mode="oidc"))


# --- Device flow: an agent asks, a person approves -------------------------------------------------


def test_device_flow(client):
    register(client)
    start = client.post("/api/v1/auth/device", json={"client_name": "Claude"}).json()
    assert start["verification_uri_complete"].endswith(start["user_code"])

    def poll():
        return client.post("/api/v1/auth/device/token", json={"device_code": start["device_code"]})

    pending = poll()
    assert pending.status_code == 400 and pending.json()["code"] == "authorization_pending"
    assert poll().json()["code"] == "slow_down"

    assert client.get(f"/koble-til?kode={start['user_code']}", follow_redirects=False).status_code == 303
    web_login(client)
    page = client.get(f"/koble-til?kode={start['user_code'].lower().replace('-', '')}")
    assert "«Claude»" in page.text
    approved = client.post(
        "/koble-til",
        data={"csrf_token": csrf(client), "kode": start["user_code"], "decision": "approve"},
        follow_redirects=False,
    )
    assert approved.status_code == 303

    granted = poll()
    assert granted.status_code == 201
    token = granted.json()["token"]
    assert token["name"] == "Claude"
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token['token']}"})
    assert me.json()["email"] == "kari@example.no"
    assert poll().json()["code"] == "expired_token"  # one token per approval


def test_device_flow_denied_and_invalid_codes(client):
    register(client)
    web_login(client)
    start = client.post("/api/v1/auth/device", json={}).json()
    client.post(
        "/koble-til", data={"csrf_token": csrf(client), "kode": start["user_code"], "decision": "deny"}
    )
    denied = client.post("/api/v1/auth/device/token", json={"device_code": start["device_code"]})
    assert denied.json()["code"] == "access_denied"

    assert "ugyldig eller utløpt" in client.get("/koble-til?kode=XXXX-XXXX").text
    unknown = client.post("/api/v1/auth/device/token", json={"device_code": "nope"})
    assert unknown.json()["code"] == "expired_token"


def test_device_flow_with_bankid_account(bankid_client):
    start = bankid_client.post("/api/v1/auth/device", json={"client_name": "Min agent"}).json()
    # The person follows the link, logs in with BankID (creating the account) and approves.
    page = bankid_client.get(
        start["verification_uri_complete"].replace("http://testserver", ""), follow_redirects=False
    )
    assert page.headers["location"].startswith("/logg-inn")
    register_with_bankid(bankid_client, name="Sara Ahmed", subject="01017010004", email="sara@example.no")
    bankid_client.post(
        "/koble-til",
        data={"csrf_token": csrf(bankid_client), "kode": start["user_code"], "decision": "approve"},
    )
    granted = bankid_client.post(
        "/api/v1/auth/device/token", json={"device_code": start["device_code"]}
    ).json()
    assert granted["account"]["verified"] is True
    assert granted["account"]["name"] == "Sara A."


def test_seeded_demo_users_are_verified(bankid_app):
    from fritorg.seed import seed

    assert seed(bankid_app.state.db, bankid_app.state.settings) > 40
    with bankid_app.state.db.session() as conn:
        statuses = {row[0] for row in conn.execute("SELECT DISTINCT status FROM listings")}
        unverified = conn.execute("SELECT COUNT(*) FROM users WHERE verified_at IS NULL").fetchone()[0]
    assert statuses <= {"active", "sold"}
    assert unverified == 0
