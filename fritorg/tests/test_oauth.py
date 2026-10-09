"""Signing in AI assistants with OAuth (oauth.py): the official MCP client finds the login by itself, the
person approves, and the assistant gets a token the person can see and delete on Min side."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
from conftest import csrf, register, web_login
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class MemoryStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info


def test_the_official_mcp_client_signs_in_by_itself(live_server):
    """What Claude, ChatGPT and other assistants do when the person adds {base}/mcp/konto."""

    async def run() -> None:
        async with httpx2.AsyncClient(base_url=live_server) as browser:  # the person's browser
            await browser.post(
                "/api/v1/auth/register",
                json={"email": "kari@example.no", "name": "Kari Nordmann", "password": "hemmelig123"},
            )
            await browser.get("/logg-inn")
            await browser.post(
                "/logg-inn",
                data={
                    "email": "kari@example.no",
                    "password": "hemmelig123",
                    "csrf_token": browser.cookies["ft_csrf"],
                    "neste": "/",
                },
            )
            answer: dict[str, str] = {}

            async def approve(authorization_url: str) -> None:
                page = await browser.get(authorization_url)
                assert page.status_code == 200 and "vil koble seg til kontoen din" in page.text
                fields = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', page.text))
                done = await browser.post("/oauth/authorize", data={**fields, "decision": "approve"})
                assert done.status_code == 303
                answer.update(
                    {k: v[0] for k, v in parse_qs(urlsplit(done.headers["location"]).query).items()}
                )

            async def callback() -> AuthorizationCodeResult:
                return AuthorizationCodeResult(
                    code=answer["code"], state=answer.get("state"), iss=answer.get("iss")
                )

            sign_in = OAuthClientProvider(
                server_url=f"{live_server}/mcp/konto",
                client_metadata=OAuthClientMetadata(
                    client_name="Test-assistent",
                    redirect_uris=["http://127.0.0.1:9/callback"],
                    grant_types=["authorization_code"],
                    token_endpoint_auth_method="none",
                ),
                storage=MemoryStorage(),
                redirect_handler=approve,
                callback_handler=callback,
            )
            async with httpx2.AsyncClient(auth=sign_in) as http:
                async with Client(
                    streamable_http_client(f"{live_server}/mcp/konto", http_client=http)
                ) as mcp:
                    tools = {tool.name for tool in (await mcp.list_tools()).tools}
                    assert "create_listing" in tools
                    me = await mcp.call_tool("whoami", {})
                    assert me.structured_content["name"] == "Kari Nordmann"
            keys = (await browser.get("/min-side")).text
            assert "Test-assistent" in keys  # the person sees the access and can delete it

    asyncio.run(run())


def _pkce() -> tuple[str, str]:
    verifier = "v" * 20 + base64.urlsafe_b64encode(b"fritorg-test-verifier-123").decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register_client(client, uris=(CALLBACK,), **extra):
    return client.post(
        "/oauth/register", json={"client_name": "Claude", "redirect_uris": list(uris), **extra}
    )


def _authorize_url(client_id: str, challenge: str, redirect_uri: str = CALLBACK, **extra) -> str:
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        **extra,
    }
    return "/oauth/authorize?" + urlencode(query)


def _approve(client, url: str, decision: str = "approve"):
    page = client.get(url)
    fields = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', page.text))
    return page, client.post(
        "/oauth/authorize", data={**fields, "decision": decision}, follow_redirects=False
    )


def test_the_steps_and_what_is_refused(client):
    sign_in = client.post("/mcp/konto", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert sign_in.status_code == 401
    assert (
        'resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp/konto"'
        in (sign_in.headers["www-authenticate"])
    )
    resource = client.get("/.well-known/oauth-protected-resource/mcp/konto").json()
    assert resource["resource"] == "http://testserver/mcp/konto"
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["code_challenge_methods_supported"] == ["S256"] and server["registration_endpoint"]

    for bad in ("http://evil.example/cb", "javascript:alert(1)", "file:///etc/passwd", "https://x.no/#frag"):
        assert _register_client(client, [bad]).json()["error"] == "invalid_redirect_uri", bad
    client_id = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()

    # Not logged in: to the login page, and back here afterwards.
    first = client.get(_authorize_url(client_id, challenge), follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"].startswith(
        "/logg-inn?neste=%2Foauth%2Fauthorize"
    )
    register(client)
    web_login(client)
    # An address the app did not register is never sent anything.
    stranger = client.get(_authorize_url(client_id, challenge, "https://evil.example/cb"))
    assert stranger.status_code == 400
    no_pkce = client.get(_authorize_url(client_id, ""), follow_redirects=False)
    assert "error=invalid_request" in no_pkce.headers["location"]

    page, approved = _approve(client, _authorize_url(client_id, challenge))
    assert "«Claude»</strong> vil koble seg til" in page.text and "tilbake til claude.ai" in page.text
    assert "form-action 'self' https://claude.ai" in page.headers["content-security-policy"]
    sent = parse_qs(urlsplit(approved.headers["location"]).query)
    assert approved.headers["location"].startswith(CALLBACK) and sent["state"] == ["xyz"]
    assert sent["iss"] == ["http://testserver"]

    exchange = {
        "grant_type": "authorization_code",
        "code": sent["code"][0],
        "redirect_uri": CALLBACK,
        "client_id": client_id,
    }
    wrong = client.post("/oauth/token", data={**exchange, "code_verifier": "x" * 43})
    assert wrong.json()["error"] == "invalid_grant"
    token = client.post("/oauth/token", data={**exchange, "code_verifier": verifier}).json()["access_token"]
    again = client.post("/oauth/token", data={**exchange, "code_verifier": verifier})
    assert again.json()["error"] == "invalid_grant"  # a code works once
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/me", headers=headers).json()["name"] == "Kari Nordmann"
    mcp = client.post("/mcp/konto", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)
    assert "create_listing" in str(mcp.json())

    # Signing in again replaces the app's token instead of adding one.
    _, second = _approve(client, _authorize_url(client_id, challenge))
    code = parse_qs(urlsplit(second.headers["location"]).query)["code"][0]
    newer = client.post("/oauth/token", data={**exchange, "code": code, "code_verifier": verifier}).json()
    assert client.get("/api/v1/me", headers=headers).status_code == 401  # the first token is gone
    tokens = client.get(
        "/api/v1/me/tokens", headers={"Authorization": f"Bearer {newer['access_token']}"}
    ).json()
    assert sorted(t["name"] for t in tokens) == ["API", "Claude"]  # the account's own key, and the app's

    _, denied = _approve(client, _authorize_url(client_id, challenge), decision="deny")
    assert "error=access_denied" in denied.headers["location"]


def test_apps_on_the_same_machine_may_use_any_port(client):
    client_id = _register_client(client, ["http://127.0.0.1:33418/callback"]).json()["client_id"]
    _, challenge = _pkce()
    register(client)
    web_login(client)
    _, approved = _approve(client, _authorize_url(client_id, challenge, "http://127.0.0.1:51234/callback"))
    assert approved.headers["location"].startswith("http://127.0.0.1:51234/callback?code=")
    assert csrf(client)
