from __future__ import annotations

import re

import pytest
from conftest import csrf, make_listing, register, web_login

from fritorg import mailer
from fritorg.config import Settings
from fritorg.mailer import Mail, Mailer, MemoryMailer


@pytest.fixture
def outbox(app, settings):
    memory = MemoryMailer(settings)
    app.state.mailer = memory
    return memory.outbox


def verify_link(mail: Mail) -> str:
    match = re.search(r"https?://\S+/bekreft-epost\?token=\S+", mail.body)
    assert match, mail.body
    return match.group(0).replace("http://testserver", "")


def bearer(data):
    return {"Authorization": f"Bearer {data['token']['token']}"}


def test_registration_sends_a_verification_link(client, outbox):
    data = register(client)
    assert data["account"]["email_verified"] is False
    assert [m.to for m in outbox] == ["kari@example.no"]
    assert "Bekreft" in outbox[0].subject

    web_login(client)
    response = client.get(verify_link(outbox[0]))
    assert "bekreftet" in response.text
    assert client.get("/api/v1/me", headers=bearer(data)).json()["email_verified"] is True


def test_tampered_and_foreign_tokens_are_rejected(client, outbox, app):
    register(client)
    link = verify_link(outbox[0])
    assert mailer.check_verification_token(app.state.secret_key, link.split("token=")[1] + "x") is None
    assert mailer.check_verification_token("another-secret", link.split("token=")[1]) is None


def test_new_messages_notify_verified_recipients_once_until_read(client, outbox):
    seller = register(client)
    buyer = register(client, email="ola@example.no", name="Ola Hansen")
    listing = make_listing(client, bearer(seller))
    client.get(verify_link(outbox[0]))  # the seller confirms the address
    outbox.clear()

    def send(text):
        return client.post(
            "/api/v1/conversations",
            json={"listing_id": listing["id"], "message": text},
            headers=bearer(buyer),
        ).json()

    conversation = send("Hei! Er sykkelen ledig?")
    assert [m.to for m in outbox] == ["kari@example.no"]
    assert "Ola H" in outbox[0].body and f"/meldinger/{conversation['id']}" in outbox[0].body
    assert "Er sykkelen ledig" not in outbox[0].body  # the message itself stays on the site

    send("Kan jeg hente i kveld?")
    assert len(outbox) == 1  # no new mail until the seller has read the conversation

    client.get(f"/api/v1/conversations/{conversation['id']}", headers=bearer(seller))
    send("Hallo?")
    assert len(outbox) == 2

    # The buyer never verified the address, so replies do not mail them.
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"message": "Ja!"},
        headers=bearer(seller),
    )
    assert len(outbox) == 2


def test_changing_email_requires_new_verification(client, outbox, app):
    data = register(client)
    client.get(verify_link(outbox[0]))
    web_login(client)
    client.post("/min-side/epost", data={"csrf_token": csrf(client), "email": "kari.ny@example.no"})
    me = client.get("/api/v1/me", headers=bearer(data)).json()
    assert me["email"] == "kari.ny@example.no" and me["email_verified"] is False
    assert outbox[-1].to == "kari.ny@example.no"
    # The old link no longer verifies anything: it names the old address.
    client.get(verify_link(outbox[0]))
    assert client.get("/api/v1/me", headers=bearer(data)).json()["email_verified"] is False
    client.get(verify_link(outbox[-1]))
    assert client.get("/api/v1/me", headers=bearer(data)).json()["email_verified"] is True


def test_moderation_decisions_are_mailed(app, client, outbox):
    from fritorg import users

    seller = register(client)
    client.get(verify_link(outbox[0]))
    listing = make_listing(
        client,
        bearer(seller),
        description="Betaling via Western Union. Sender varen når pengene er mottatt.",
    )
    assert listing["status"] == "review"

    register(client, email="mod@example.no", name="Mona Moe")
    with app.state.db.session() as conn:
        users.set_admin(conn, users.get_user_by_email(conn, "mod@example.no").id)
    web_login(client, "mod@example.no")
    outbox.clear()
    client.post(
        f"/moderering/annonse/{listing['id']}/fjern", data={"csrf_token": csrf(client), "note": "Svindel"}
    )
    assert outbox[0].to == "kari@example.no" and "Svindel" in outbox[0].body


def test_no_mail_without_smtp(client, app):
    assert app.state.mailer.enabled is False
    register(client)  # nothing to send, nothing breaks


def test_smtp_delivery(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context):
            sent["tls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    settings = Settings(
        smtp_host="smtp.example.no",
        smtp_username="fritorg",
        smtp_password="pw",
        smtp_from="Fritorg <post@fritorg.example>",
    )
    Mailer(settings).send_now(Mail("kari@example.no", "Hei", "Tekst"))
    assert sent["server"] == ("smtp.example.no", 587) and sent["tls"] and sent["login"] == ("fritorg", "pw")
    assert sent["message"]["To"] == "kari@example.no"
    assert sent["message"]["From"] == "Fritorg <post@fritorg.example>"
