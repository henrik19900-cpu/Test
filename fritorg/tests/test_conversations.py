"""Deleting conversations: each person deletes their own copy, a new message brings it back, and it is
deleted for good when both have deleted it, unless moderators may need it."""

from __future__ import annotations

from conftest import csrf, make_listing, web_login
from test_mcp import call


def _conversation(client, seller, buyer):
    listing = make_listing(client, seller)
    conversation = client.post(
        "/api/v1/conversations", json={"listing_id": listing["id"], "message": "Er den ledig?"}, headers=buyer
    ).json()
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"message": "Ja, den er det."},
        headers=seller,
    )
    return conversation["id"]


def _inbox(client, headers):
    return [c["id"] for c in client.get("/api/v1/conversations", headers=headers).json()]


def test_deleting_hides_it_for_me_until_someone_writes_again(client, auth, other_auth):
    conversation_id = _conversation(client, auth, other_auth)
    assert client.get("/api/v1/me", headers=other_auth).json()["unread_messages"] == 1
    assert client.delete(f"/api/v1/conversations/{conversation_id}", headers=other_auth).status_code == 204
    assert _inbox(client, other_auth) == [] and _inbox(client, auth) == [conversation_id]
    assert client.get("/api/v1/me", headers=other_auth).json()["unread_messages"] == 0
    # Still there for the other person, who writes again: it comes back.
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "Kommer du i dag?"},
        headers=auth,
    )
    assert _inbox(client, other_auth) == [conversation_id]
    messages = client.get(f"/api/v1/conversations/{conversation_id}", headers=other_auth).json()["messages"]
    assert len(messages) == 3


def test_deleted_for_good_when_both_have_deleted_it(app, client, auth, other_auth):
    conversation_id = _conversation(client, auth, other_auth)
    client.delete(f"/api/v1/conversations/{conversation_id}", headers=auth)
    client.delete(f"/api/v1/conversations/{conversation_id}", headers=other_auth)
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=auth).status_code == 404
    with app.state.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_conversations_moderators_may_need_are_kept(app, client, auth, other_auth):
    reported = _conversation(client, auth, other_auth)
    client.post(f"/api/v1/conversations/{reported}/reports", json={"reason": "fraud"}, headers=auth)
    client.delete(f"/api/v1/conversations/{reported}", headers=auth)
    client.delete(f"/api/v1/conversations/{reported}", headers=other_auth)
    assert _inbox(client, auth) == [] and _inbox(client, other_auth) == []
    with app.state.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversations WHERE id = ?", (reported,)).fetchone()[0] == 1

    listing = make_listing(client, auth, title="Leilighet til leie", description="Fin leilighet sentralt.")
    flagged = client.post(
        "/api/v1/conversations",
        json={"listing_id": listing["id"], "message": "Send meg BankID-koden din, så betaler jeg."},
        headers=other_auth,
    ).json()["id"]
    client.delete(f"/api/v1/conversations/{flagged}", headers=auth)
    client.delete(f"/api/v1/conversations/{flagged}", headers=other_auth)
    with app.state.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversations WHERE id = ?", (flagged,)).fetchone()[0] == 1
    # The data export still has them: they are stored.
    exported = client.get("/api/v1/me/export", headers=auth).json()["conversations"]
    assert {c["id"] for c in exported} == {reported, flagged}


def test_deleting_on_the_web_and_through_mcp(client, auth, other_auth):
    first = _conversation(client, auth, other_auth)
    web_login(client)
    response = client.post(
        f"/meldinger/{first}/slett", data={"csrf_token": csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "/meldinger"
    assert f"/meldinger/{first}" not in client.get("/meldinger").text
    result = call(client, "delete_conversation", {"conversation_id": first}, headers=other_auth)[
        "structuredContent"
    ]
    assert result == {"conversation_id": first, "deleted": True, "deleted_for_both": True}
    stranger = call(client, "delete_conversation", {"conversation_id": first}, headers=other_auth)
    assert stranger["isError"] is True
