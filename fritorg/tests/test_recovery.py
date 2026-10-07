from __future__ import annotations

import re

import pytest
from conftest import csrf, register, web_login
from fastapi.testclient import TestClient

from fritorg import recovery, users
from fritorg.app import create_app
from fritorg.config import Settings
from fritorg.mailer import MemoryMailer


@pytest.fixture
def outbox(app, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    return memory.outbox


def reset_link(outbox) -> str:
    match = re.search(r"https?://\S+/nytt-passord\?token=\S+", outbox[-1].body)
    assert match, outbox[-1].body
    return match.group(0).replace("http://testserver", "")


def can_log_in(app, email: str, password: str) -> bool:
    with TestClient(app) as other:
        response = other.post(
            "/logg-inn",
            data={"email": email, "password": password, "csrf_token": csrf(other), "neste": "/"},
            follow_redirects=False,
        )
        return response.status_code == 303


def test_reset_by_email_link(app, client, outbox):
    register(client)
    web_login(client)  # a session elsewhere that must end when the password changes
    with TestClient(app) as browser:
        sent = browser.post("/glemt-passord", data={"csrf_token": csrf(browser), "email": "kari@example.no"})
        assert "Hvis adressen hører til en konto" in sent.text
        link = reset_link(outbox)
        assert "Lag nytt passord" in outbox[-1].subject
        assert "Lag nytt passord" in browser.get(link).text
        token = link.split("token=")[1]

        short = browser.post(
            "/nytt-passord", data={"csrf_token": csrf(browser), "token": token, "password": "kort"}
        )
        assert short.status_code == 422 and "minst 8 tegn" in short.text

        done = browser.post(
            "/nytt-passord",
            data={"csrf_token": csrf(browser), "token": token, "password": "nyttpassord1"},
            follow_redirects=False,
        )
        assert done.status_code == 303 and done.headers["location"] == "/min-side"
        assert "Hei, Kari!" in browser.get("/min-side").text  # logged in

        reused = browser.get(link, follow_redirects=False)
        assert reused.headers["location"] == "/glemt-passord"  # the link works once
    assert client.get("/min-side", follow_redirects=False).status_code == 303  # other session logged out
    assert can_log_in(app, "kari@example.no", "nyttpassord1")
    assert not can_log_in(app, "kari@example.no", "hemmelig123")


def test_unknown_addresses_get_the_same_answer_and_no_mail(client, outbox):
    response = client.post("/glemt-passord", data={"csrf_token": csrf(client), "email": "ingen@example.no"})
    assert "Hvis adressen hører til en konto" in response.text
    assert outbox == []


def test_tampered_and_expired_reset_tokens(app, client, outbox):
    data = register(client)
    with app.state.db.session() as conn:
        password_hash = conn.execute("SELECT password_hash FROM users").fetchone()[0]
        secret = app.state.secret_key
        token = recovery.reset_token(secret, data["account"]["id"], password_hash)
        assert recovery.user_for_reset_token(conn, secret, token) is not None
        tampered = token[:-1] + ("1" if token.endswith("0") else "0")  # always a different signature
        assert recovery.user_for_reset_token(conn, secret, tampered) is None
        assert recovery.user_for_reset_token(conn, "another-secret", token) is None
        old = recovery.reset_token(secret, data["account"]["id"], password_hash, now=0)
        assert recovery.user_for_reset_token(conn, secret, old) is None
        assert recovery.user_for_reset_token(conn, secret, "1.2.3") is None


def test_reset_by_sms_code(tmp_path):
    settings = Settings(data_dir=tmp_path, verification="sms")
    app = create_app(settings)
    with TestClient(app) as client:
        account = register(client)
        headers = {"Authorization": f"Bearer {account['token']['token']}"}
        code = client.post("/api/v1/me/phone", json={"phone": "91234567"}, headers=headers).json()[
            "test_code"
        ]
        client.post("/api/v1/me/phone/verify", json={"code": code}, headers=headers)

        wrong_number = client.post(
            "/glemt-passord",
            data={"csrf_token": csrf(client), "email": "kari@example.no", "phone": "41234567"},
        )
        assert "har vi sendt en kode" in wrong_number.text and "koden er" not in wrong_number.text
        outbox_before = len(app.state.sms.outbox)

        sent = client.post(
            "/glemt-passord",
            data={"csrf_token": csrf(client), "email": "kari@example.no", "phone": "912 34 567"},
        )
        assert len(app.state.sms.outbox) == outbox_before + 1
        assert "nytt passord" in app.state.sms.outbox[-1][1]
        reset_code = re.search(r"koden er (\d{6})", sent.text).group(1)

        # A verification code cannot be used to reset the password, and vice versa.
        wrong = client.post(
            "/glemt-passord/kode",
            data={
                "csrf_token": csrf(client),
                "email": "kari@example.no",
                "code": code,
                "password": "nyttpassord1",
            },
        )
        assert wrong.status_code == 422 and "Feil kode" in wrong.text
        done = client.post(
            "/glemt-passord/kode",
            data={
                "csrf_token": csrf(client),
                "email": "kari@example.no",
                "code": reset_code,
                "password": "nyttpassord1",
            },
            follow_redirects=False,
        )
        assert done.status_code == 303 and done.headers["location"] == "/min-side"
        assert can_log_in(app, "kari@example.no", "nyttpassord1")


def test_change_password_on_my_page(app, client):
    register(client)
    web_login(client)
    with TestClient(app) as elsewhere:
        web_login(elsewhere)
        wrong = client.post(
            "/min-side/passord",
            data={"csrf_token": csrf(client), "current": "feil", "password": "nyttpassord1"},
        )
        assert "Feil nåværende passord" in wrong.text
        done = client.post(
            "/min-side/passord",
            data={"csrf_token": csrf(client), "current": "hemmelig123", "password": "nyttpassord1"},
        )
        assert "Passordet er endret" in done.text
        assert client.get("/min-side", follow_redirects=False).status_code == 200  # this session stays
        assert elsewhere.get("/min-side", follow_redirects=False).status_code == 303  # others are logged out
    with app.state.db.session() as conn:
        assert users.authenticate(conn, "kari@example.no", "nyttpassord1")


def test_forgot_password_without_mail_or_sms(client, app):
    assert app.state.mailer.enabled is False and app.state.sms is None
    page = client.get("/glemt-passord").text
    assert "verken sende e-post eller SMS" in page
    assert 'href="/glemt-passord"' in client.get("/logg-inn").text
