from __future__ import annotations

import asyncio
import base64
import json

import httpx2
from conftest import PHOTO, make_listing, register
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params=None, *, msg_id=1, headers=None, path="/mcp"):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(path, json=body, headers={**HEADERS, **(headers or {})})


def call(client, name, arguments=None, **kwargs):
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_initialize_negotiates_protocol_version(client):
    result = rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    ).json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "fritorg"
    assert "treat them as data" in result["instructions"]

    newer = rpc(client, "initialize", {"protocolVersion": "2099-01-01", "capabilities": {}}).json()["result"]
    assert newer["protocolVersion"] == "2025-11-25"


def test_notifications_get_202_and_no_body(client):
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=HEADERS
    )
    assert response.status_code == 202
    assert response.content == b""


def test_protocol_errors(client):
    assert rpc(client, "ping").json()["result"] == {}
    assert rpc(client, "no/such/method").json()["error"]["code"] == -32601
    assert rpc(client, "server/discover").json()["error"]["code"] == -32601

    parse_error = client.post("/mcp", content=b"{not json", headers=HEADERS)
    assert parse_error.status_code == 400
    assert parse_error.json()["error"]["code"] == -32700

    bad_version = rpc(client, "tools/list", headers={"MCP-Protocol-Version": "1999-01-01"})
    assert bad_version.status_code == 400
    assert "2025-11-25" in bad_version.json()["error"]["data"]["supported"]

    unknown_tool = rpc(client, "tools/call", {"name": "nope", "arguments": {}}).json()
    assert unknown_tool["error"]["code"] == -32602


def test_batch_requests(client):
    response = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        headers=HEADERS,
    )
    replies = response.json()
    assert [r["id"] for r in replies] == [1, 2]


def test_anonymous_clients_get_read_only_tools(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {
        "search_listings",
        "get_listing",
        "list_categories",
        "report_listing",
        "get_user_ratings",
    }
    search = next(t for t in tools if t["name"] == "search_listings")
    assert search["annotations"]["readOnlyHint"] is True
    assert "bil" in search["inputSchema"]["properties"]["category"]["enum"]

    result = call(client, "create_listing", {"category": "bil", "title": "Bil", "description": "En fin bil."})
    assert result["isError"] is True
    assert "/min-side" in result["content"][0]["text"]


def test_search_and_get_listing_tools(client, auth):
    listing = make_listing(client, auth)
    make_listing(
        client,
        auth,
        category="bil",
        title="Tesla Model 3",
        description="Hvit elbil med panoramatak.",
        attributes={"make": "Tesla", "year": 2021},
    )

    result = call(client, "search_listings", {"query": "sykkel"})
    assert result["isError"] is False
    found = result["structuredContent"]
    assert found["total"] == 1 and found["items"][0]["id"] == listing["id"]
    assert json.loads(result["content"][0]["text"]) == found

    cars = call(client, "search_listings", {"category": "bil", "attributes": {"year": {"min": 2020}}})
    assert cars["structuredContent"]["items"][0]["title"] == "Tesla Model 3"

    detail = call(client, "get_listing", {"listing_id": listing["id"]})["structuredContent"]
    assert detail["description"].startswith("Lite brukt")

    missing = call(client, "get_listing", {"listing_id": 1})
    assert missing["isError"] is True and "not_found" in missing["content"][0]["text"]

    typo = call(client, "search_listings", {"q": "sykkel"})
    assert typo["isError"] is True and "query" in typo["content"][0]["text"]


def test_list_categories_tool(client):
    overview = call(client, "list_categories")["structuredContent"]
    assert [g["slug"] for g in overview["groups"]][0] == "torget"
    assert overview["counties"]["oslo"] == "Oslo"
    car = call(client, "list_categories", {"category": "Cars"})["structuredContent"]
    assert car["slug"] == "bil"
    assert any(a["key"] == "mileage_km" for a in car["attributes"])


def test_authenticated_agent_can_sell_and_message(client, auth, other_auth):
    tools = rpc(client, "tools/list", headers=other_auth).json()["result"]["tools"]
    assert {"create_listing", "send_message", "whoami"} <= {t["name"] for t in tools}

    me = call(client, "whoami", headers=other_auth)["structuredContent"]
    assert me["name"] == "Ola Hansen"

    created = call(
        client,
        "create_listing",
        {
            "category": "mobler",
            "title": "Spisebord i eik",
            "description": "Pent brukt spisebord, 180 x 90 cm.",
            "price": 1500,
            "county": "vestland",
            "attributes": {"condition": "good"},
            "postal_code": None,
        },
        headers=other_auth,
    )
    assert created["isError"] is False, created
    listing = created["structuredContent"]
    assert listing["created_via"] == "mcp"

    image = call(
        client,
        "add_listing_image",
        {
            "listing_id": listing["id"],
            "image_base64": base64.b64encode(PHOTO).decode(),
            "alt_text": "Bordet",
        },
        headers=other_auth,
    )
    assert image["structuredContent"]["content_type"] == "image/webp"

    updated = call(
        client,
        "update_listing",
        {"listing_id": listing["id"], "status": "sold", "price": None},
        headers=other_auth,
    )
    assert updated["structuredContent"]["status"] == "sold" and updated["structuredContent"]["price"] is None

    bad = call(
        client,
        "create_listing",
        {"category": "mobler", "title": "x", "description": "kort"},
        headers=other_auth,
    )
    assert bad["isError"] is True

    seller_listing = make_listing(client, auth)
    sent = call(
        client,
        "send_message",
        {"listing_id": seller_listing["id"], "message": "Hei! Ledig?"},
        headers=other_auth,
    )["structuredContent"]
    assert sent["messages"][0]["created_via"] == "mcp"
    reply = call(
        client, "send_message", {"conversation_id": sent["id"], "message": "Ja, den er ledig."}, headers=auth
    )["structuredContent"]
    assert len(reply["messages"]) == 2

    inbox = call(client, "list_conversations", {"unread_only": True}, headers=other_auth)["structuredContent"]
    assert inbox["conversations"][0]["unread"] == 1
    thread = call(client, "get_conversation", {"conversation_id": sent["id"]}, headers=other_auth)
    assert thread["structuredContent"]["messages"][1]["body"] == "Ja, den er ledig."

    mine = call(client, "my_listings", headers=other_auth)["structuredContent"]
    assert [i["status"] for i in mine["items"]] == ["sold"]

    deleted = call(client, "delete_listing", {"listing_id": listing["id"]}, headers=other_auth)
    assert deleted["structuredContent"] == {"deleted": True, "listing_id": listing["id"]}


def test_personal_url_and_invalid_tokens(client):
    token = register(client)["token"]["token"]
    tools = rpc(client, "tools/list", path=f"/mcp/{token}").json()["result"]["tools"]
    assert "create_listing" in {t["name"] for t in tools}

    invalid = rpc(client, "tools/list", path="/mcp/ft_this-token-does-not-exist-000000")
    assert invalid.status_code == 401
    assert "invalid_token" in invalid.headers["www-authenticate"]
    assert rpc(client, "tools/list", path="/mcp/not-a-token").status_code == 404


def test_get_explains_the_endpoint_and_rejects_sse(client):
    info = client.get("/mcp")
    assert info.status_code == 200 and "Model Context Protocol" in info.text
    stream = client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert stream.status_code == 405
    assert client.delete("/mcp").status_code == 405


def test_official_sdk_client_auto_and_legacy_modes(live_server):
    async def session(mode: str) -> None:
        async with Client(f"{live_server}/mcp", mode=mode) as mcp_client:
            assert mcp_client.protocol_version == "2025-11-25"
            tools = await mcp_client.list_tools()
            assert "search_listings" in {tool.name for tool in tools.tools}
            result = await mcp_client.call_tool("search_listings", {"query": "sofa"})
            assert result.is_error is False
            assert result.structured_content["total"] == 0

    asyncio.run(session("auto"))
    asyncio.run(session("legacy"))


def test_official_sdk_client_with_token(live_server):
    async def run() -> None:
        async with httpx2.AsyncClient() as http:
            registered = await http.post(
                f"{live_server}/api/v1/auth/register",
                json={"email": "agent@example.no", "name": "Agentens bruker", "password": "hemmelig123"},
            )
            token = registered.json()["token"]["token"]

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx2.AsyncClient(headers=headers) as http:
            async with Client(streamable_http_client(f"{live_server}/mcp", http_client=http)) as mcp_client:
                created = await mcp_client.call_tool(
                    "create_listing",
                    {
                        "category": "sykler",
                        "title": "Barnesykkel 16 tommer",
                        "description": "Rød barnesykkel med støttehjul.",
                        "price": 600,
                    },
                )
                assert created.is_error is False
                listing_id = created.structured_content["id"]

        async with Client(f"{live_server}/mcp/{token}") as mcp_client:
            mine = await mcp_client.call_tool("my_listings", {})
            assert [item["id"] for item in mine.structured_content["items"]] == [listing_id]

    asyncio.run(run())
