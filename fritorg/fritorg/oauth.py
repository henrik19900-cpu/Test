"""Sign-in for AI assistants: OAuth 2.1 as the MCP specification describes it.

An assistant that supports MCP sign-in (Claude, ChatGPT, Claude Code, Cursor, VS Code and others) is given
{base}/mcp/konto. Without a token that URL answers 401 with a link to the metadata here (RFC 9728), and the
assistant registers itself (RFC 7591), sends the person to /oauth/authorize to log in and approve, and trades
the one-time code for a token (PKCE, RFC 7636). The token is an ordinary personal API token named after the
assistant, so the person sees it on Min side and can delete it there. Codes and secrets are stored as hashes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import FormData

from . import users
from .db import transaction
from .deps import base_url, client_ip, get_conn
from .errors import AppError
from .security import hash_token
from .templating import csp_allowing_form_action, current_user, redirect, render, render_error
from .util import iso_ago, iso_in, now_iso

router = APIRouter(include_in_schema=False)
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

ACCOUNT_PATH = "/mcp/konto"  # the MCP address that asks the assistant to sign in
SCOPE = "fritorg"
CODE_MINUTES = 10
MAX_REDIRECT_URIS = 10
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# Schemes a redirect may never use; other app schemes (cursor://, vscode://) are allowed.
_UNSAFE_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob", "filesystem", "ws", "wss"}
_SCHEME = re.compile(r"[a-z][a-z0-9+.\-]*")
_HOST = re.compile(r"[A-Za-z0-9.\-:\[\]]+")


async def _get_form(request: Request) -> FormData:
    return await request.form(max_files=0, max_fields=50)


Form = Annotated[FormData, Depends(_get_form)]


@dataclass
class Client:
    client_id: str
    name: str
    redirect_uris: list[str]
    secret_hash: str | None


def challenge(base: str, path: str = ACCOUNT_PATH, error: str | None = None) -> str:
    """The WWW-Authenticate value that tells an MCP client where to sign in."""
    value = f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource{path}"'
    return value + (f', error="{error}"' if error else "")


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


# --- Metadata ------------------------------------------------------------------------------------


def _resource_metadata(request: Request, resource: str) -> JSONResponse:
    base = base_url(request)
    return JSONResponse(
        {
            "resource": resource,
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [SCOPE],
            "resource_name": request.app.state.settings.site_name,
            "resource_documentation": f"{base}/for-agenter",
        }
    )


@router.get("/.well-known/oauth-protected-resource")
def protected_resource(request: Request) -> JSONResponse:
    return _resource_metadata(request, base_url(request))


@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_mcp(request: Request) -> JSONResponse:
    return _resource_metadata(request, f"{base_url(request)}/mcp")


@router.get("/.well-known/oauth-protected-resource/mcp/konto")
def protected_mcp_account(request: Request) -> JSONResponse:
    return _resource_metadata(request, f"{base_url(request)}{ACCOUNT_PATH}")


@router.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request) -> JSONResponse:
    base = base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "scopes_supported": [SCOPE],
            "authorization_response_iss_parameter_supported": True,
            "service_documentation": f"{base}/for-agenter",
        }
    )


# --- Registration (RFC 7591) ----------------------------------------------------------------------


def redirect_problem(uri: Any) -> str | None:
    """Why a redirect URI is refused, or None. https anywhere, http only back to this machine (an app that
    listens on localhost), or an app's own scheme; never one that runs code or reads files."""
    if not isinstance(uri, str) or not 8 <= len(uri) <= 500 or any(c.isspace() for c in uri):
        return "must be an absolute URI of at most 500 characters"
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if not _SCHEME.fullmatch(scheme) or scheme in _UNSAFE_SCHEMES:
        return f"the scheme {parts.scheme!r} is not allowed"
    if parts.fragment:
        return "must not have a fragment"
    if scheme == "https" and not parts.hostname:
        return "needs a host"
    if scheme == "http" and parts.hostname not in _LOOPBACK:
        return "http is only allowed for localhost; use https"
    if parts.netloc and not _HOST.fullmatch(parts.netloc.rsplit("@", 1)[-1]):
        return "has an invalid host"
    if "@" in parts.netloc:
        return "must not contain user information"
    return None


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())[:60]
    if users.RESERVED_NAME.search(name):  # "Fritorg kundeservice" must not ask people for access
        return "Ukjent app"
    return name or "AI-assistent"


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        return None


@router.post("/oauth/register", status_code=201)
def register(request: Request, conn: Conn, body: Annotated[Any, Depends(_json_body)]) -> Response:
    decision = request.app.state.limiter.hit("oauth-register", client_ip(request), 20, 3600)
    if not decision.allowed:
        return _oauth_error("slow_down", "Too many registrations from this address. Try again later.", 429)
    if not isinstance(body, dict):
        return _oauth_error("invalid_client_metadata", "Send the client metadata as a JSON object.")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECT_URIS:
        return _oauth_error("invalid_redirect_uri", f"redirect_uris must list 1 to {MAX_REDIRECT_URIS} URIs.")
    for uri in uris:
        problem = redirect_problem(uri)
        if problem:
            return _oauth_error("invalid_redirect_uri", f"{uri!r}: {problem}.")
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in ("none", "client_secret_post", "client_secret_basic"):
        return _oauth_error("invalid_client_metadata", f"Unsupported token_endpoint_auth_method {method!r}.")
    client_id = "fc_" + secrets.token_urlsafe(18)
    secret = None if method == "none" else "fs_" + secrets.token_urlsafe(32)
    name = _clean_name(body.get("client_name"))
    now = now_iso()
    with transaction(conn):
        conn.execute(
            "INSERT INTO oauth_clients (client_id, secret_hash, name, redirect_uris, created_at) VALUES (?, ?, ?, ?, ?)",
            (client_id, hash_token(secret) if secret else None, name, json.dumps(uris), now),
        )
    answer: dict[str, Any] = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "scope": SCOPE,
    }
    if secret:
        answer.update(client_secret=secret, client_secret_expires_at=0)
    return JSONResponse(answer, status_code=201, headers={"Cache-Control": "no-store"})


def _client(conn: sqlite3.Connection, client_id: str | None) -> Client | None:
    if not client_id:
        return None
    row = conn.execute("SELECT * FROM oauth_clients WHERE client_id = ?", (client_id,)).fetchone()
    if row is None:
        return None
    return Client(row["client_id"], row["name"], json.loads(row["redirect_uris"]), row["secret_hash"])


def _redirect_allowed(client: Client, uri: str) -> bool:
    """Exactly a registered URI; for an app on this machine (localhost) any port, as RFC 8252 asks."""
    if uri in client.redirect_uris:
        return True
    asked = urlsplit(uri)
    if asked.scheme != "http" or asked.hostname not in _LOOPBACK:
        return False
    for registered in client.redirect_uris:
        known = urlsplit(registered)
        if (known.scheme, known.hostname, known.path, known.query) == (
            asked.scheme,
            asked.hostname,
            asked.path,
            asked.query,
        ):
            return True
    return False


def _with_params(uri: str, params: dict[str, str | None]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + [
        (k, v) for k, v in params.items() if v is not None
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _form_action(uri: str) -> str:
    """The CSP source that lets the consent form send the browser on to the app's redirect URI."""
    parts = urlsplit(uri)
    if parts.scheme in ("http", "https") and _HOST.fullmatch(parts.netloc):
        return f"{parts.scheme}://{parts.netloc}"
    return f"{parts.scheme}:"


def _where(uri: str) -> str:
    parts = urlsplit(uri)
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return "et program på denne datamaskinen"
    if parts.scheme == "https":
        return parts.hostname or uri
    return f"appen som bruker adresser som begynner med «{parts.scheme}:»"


# --- Authorization -------------------------------------------------------------------------------


def _check_request(conn: sqlite3.Connection, params: dict[str, str]) -> tuple[Client, str] | str:
    """The client and redirect URI of an authorization request, or why it is refused (shown, never sent on)."""
    client = _client(conn, params.get("client_id"))
    if client is None:
        return "Appen er ukjent. Prøv å koble til på nytt fra assistenten."
    uri = params.get("redirect_uri") or (client.redirect_uris[0] if len(client.redirect_uris) == 1 else "")
    if not uri or not _redirect_allowed(client, uri):
        return "Adressen appen vil sende deg tilbake til, er ikke registrert. Prøv å koble til på nytt."
    return client, uri


def _request_error(params: dict[str, str], base: str) -> tuple[str, str] | None:
    """An error to send back to the app (it is known and its redirect URI checked), or None."""
    if params.get("response_type") != "code":
        return "unsupported_response_type", "Only response_type=code is supported."
    if params.get("code_challenge_method") != "S256" or not re.fullmatch(
        r"[A-Za-z0-9\-._~]{43,128}", params.get("code_challenge") or ""
    ):
        return "invalid_request", "PKCE with code_challenge_method=S256 is required."
    resource = params.get("resource")
    if resource and not (resource == base or resource.startswith(base + "/")):
        return "invalid_target", f"The resource must be on {base}."
    return None


_FIELDS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "resource",
)


@router.get("/oauth/authorize")
def authorize(request: Request, conn: Conn) -> Response:
    base = base_url(request)
    params = {k: v for k, v in request.query_params.items() if k in _FIELDS}
    checked = _check_request(conn, params)
    if isinstance(checked, str):
        return render_error(request, 400, checked)
    client, uri = checked
    problem = _request_error(params, base)
    if problem:
        return redirect(
            _with_params(
                uri,
                {
                    "error": problem[0],
                    "error_description": problem[1],
                    "state": params.get("state"),
                    "iss": base,
                },
            )
        )
    user = current_user(request, conn)
    if user is None:
        target = request.url.path + "?" + request.url.query
        return redirect("/logg-inn?" + urlencode({"neste": target}))  # the login page says to log in first
    response = render(
        request,
        conn,
        "oauth_consent.html",
        {"client": client, "where": _where(uri), "fields": {**params, "redirect_uri": uri}},
    )
    # The form sends the browser on to the app, so this page's CSP must allow that address.
    response.headers["Content-Security-Policy"] = csp_allowing_form_action(_form_action(uri))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/oauth/authorize")
def decide(request: Request, conn: Conn, form: Form) -> Response:
    from .web import check_csrf  # web builds on the same helpers

    check_csrf(request, form)
    base = base_url(request)
    params = {k: str(form.get(k) or "") for k in _FIELDS if form.get(k)}
    checked = _check_request(conn, params)
    if isinstance(checked, str):
        return render_error(request, 400, checked)
    client, uri = checked
    problem = _request_error(params, base)
    state = params.get("state")
    if problem:
        return redirect(
            _with_params(
                uri, {"error": problem[0], "error_description": problem[1], "state": state, "iss": base}
            )
        )
    user = current_user(request, conn)
    if user is None:
        return render_error(request, 401, "Du er logget ut. Start tilkoblingen på nytt fra assistenten.")
    if form.get("decision") != "approve":
        return redirect(_with_params(uri, {"error": "access_denied", "state": state, "iss": base}))
    code = secrets.token_urlsafe(32)
    with transaction(conn):
        conn.execute(
            "INSERT INTO oauth_codes (code_hash, client_id, user_id, redirect_uri, code_challenge, created_at, "
            "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                hash_token(code),
                client.client_id,
                user.id,
                uri,
                params["code_challenge"],
                now_iso(),
                iso_in(minutes=CODE_MINUTES),
            ),
        )
    return redirect(_with_params(uri, {"code": code, "state": state, "iss": base}))


# --- Token ---------------------------------------------------------------------------------------


def _client_credentials(request: Request, form: FormData) -> tuple[str | None, str | None]:
    header = request.headers.get("authorization", "")
    if header[:6].lower() == "basic ":
        try:
            client_id, _, secret = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return None, None
        return unquote(client_id), unquote(secret)
    return (str(form.get("client_id") or "") or None), (str(form.get("client_secret") or "") or None)


@router.post("/oauth/token")
def token(request: Request, conn: Conn, form: Form) -> Response:
    decision = request.app.state.limiter.hit("oauth-token", client_ip(request), 60, 600)
    if not decision.allowed:
        return _oauth_error("slow_down", "Too many requests. Try again later.", 429)
    if form.get("grant_type") != "authorization_code":
        return _oauth_error("unsupported_grant_type", "Only grant_type=authorization_code is supported.")
    client_id, secret = _client_credentials(request, form)
    client = _client(conn, client_id)
    if client is None:
        return _oauth_error("invalid_client", "Unknown client.", 401)
    if client.secret_hash and not (secret and hmac.compare_digest(hash_token(secret), client.secret_hash)):
        return _oauth_error("invalid_client", "Wrong client secret.", 401)
    code = str(form.get("code") or "")
    row = conn.execute("SELECT * FROM oauth_codes WHERE code_hash = ?", (hash_token(code),)).fetchone()
    if row is None or row["client_id"] != client.client_id or row["expires_at"] < now_iso():
        return _oauth_error("invalid_grant", "The code is unknown, expired or for another client.")
    if str(form.get("redirect_uri") or row["redirect_uri"]) != row["redirect_uri"]:
        return _oauth_error(
            "invalid_grant", "redirect_uri differs from the one in the authorization request."
        )
    verifier = str(form.get("code_verifier") or "")
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    if not hmac.compare_digest(expected, row["code_challenge"]):
        return _oauth_error("invalid_grant", "code_verifier does not match the code_challenge.")
    with transaction(conn):
        used = conn.execute(
            "UPDATE oauth_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL",
            (now_iso(), row["code_hash"]),
        ).rowcount
        if used != 1:
            return _oauth_error("invalid_grant", "The code has already been used.")
        # Signing in again replaces the token this app had, so tokens do not pile up.
        conn.execute(
            "DELETE FROM api_tokens WHERE user_id = ? AND oauth_client_id = ?",
            (row["user_id"], client.client_id),
        )
        conn.execute(
            "UPDATE oauth_clients SET last_used_at = ? WHERE client_id = ?", (now_iso(), client.client_id)
        )
    try:
        access, record = users.create_api_token(conn, row["user_id"], client.name)
    except AppError as exc:  # too many tokens already
        return _oauth_error("invalid_request", exc.message)
    conn.execute("UPDATE api_tokens SET oauth_client_id = ? WHERE id = ?", (client.client_id, record.id))
    return JSONResponse(
        {"access_token": access, "token_type": "Bearer", "scope": SCOPE},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def purge(conn: sqlite3.Connection) -> int:
    """Used and expired codes go after a day; apps that never got a token after a week."""
    codes = conn.execute("DELETE FROM oauth_codes WHERE created_at < ?", (iso_ago(days=1),)).rowcount
    clients = conn.execute(
        "DELETE FROM oauth_clients WHERE last_used_at IS NULL AND created_at < ?", (iso_ago(days=7),)
    ).rowcount
    return codes + clients
