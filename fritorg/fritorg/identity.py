"""BankID: accounts belong to a verified person.

Real BankID runs through OpenID Connect (authorization code flow with PKCE), so any BankID
OIDC provider works: BankID's own OIDC service, Signicat, Idura/Criipto and others. The
provider is configured with FRITORG_BANKID_ISSUER, _CLIENT_ID and _CLIENT_SECRET.

For development there is a simulator that imitates a BankID login with any test identity.
It refuses to run on an https base URL unless explicitly allowed.

The person's identifier (e.g. the national identity number) is never stored: only an HMAC
of it, keyed with the server secret. That is enough to enforce "one person, one account"
and to keep banned people from coming back with a fresh account.

This module also holds the device authorization flow that lets an AI agent get a token
once a logged-in (BankID-verified) person approves it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .db import transaction
from .errors import AppError
from .security import hash_token
from .util import iso_ago, iso_in, now_iso

logger = logging.getLogger(__name__)

SIMULATED_ISSUER = "simulated-bankid"
LOGIN_STATE_MINUTES = 15
PENDING_MINUTES = 30
DEVICE_CODE_MINUTES = 10
DEVICE_POLL_SECONDS = 5
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"  # no vowels, so codes never spell words


class IdentityError(AppError):
    status = 400
    code = "bankid_failed"
    title = "BankID login failed"


def load_secret_key(settings: Settings) -> str:
    """FRITORG_SECRET_KEY, or a random key kept next to the database (created on first start)."""
    if settings.secret_key:
        return settings.secret_key
    path = Path(settings.data_dir) / "secret_key"
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    path.write_text(key)
    path.chmod(0o600)
    return key


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class VerifiedIdentity:
    issuer: str
    subject: str
    name: str
    given_name: str | None = None
    family_name: str | None = None

    @property
    def display_name(self) -> str:
        """Public name derived from BankID, e.g. "Kari N." – nobody can pose as "Fritorg Support"."""
        parts = self.name.split()
        given_parts = (self.given_name or "").split() or parts[:1]
        family_parts = (self.family_name or "").split() or parts[1:]
        if not given_parts:
            return "Bruker"
        given = given_parts[0].capitalize() if given_parts[0].isupper() else given_parts[0]
        return f"{given} {family_parts[-1][:1].upper()}." if family_parts else given


def identity_hash(secret: str, identity: VerifiedIdentity) -> str:
    message = f"{identity.issuer}|{identity.subject}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


HttpFn = Callable[[str, dict[str, str] | None, dict[str, str]], dict[str, Any]]


def http_json(url: str, form: dict[str, str] | None, headers: dict[str, str]) -> dict[str, Any]:
    """GET (form=None) or form-POST to an identity provider and parse the JSON answer."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - configured https URL
            return json.load(response)
    except urllib.error.HTTPError as exc:
        logger.warning("BankID provider returned %s for %s: %s", exc.code, url, exc.read()[:500])
        raise IdentityError("BankID-innloggingen feilet. Prøv igjen.") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("BankID provider unreachable (%s): %s", url, exc)
        raise IdentityError("Fikk ikke kontakt med BankID. Prøv igjen om litt.") from None


class OidcProvider:
    """BankID through any OpenID Connect provider (authorization code flow with PKCE)."""

    via = "bankid"

    def __init__(self, settings: Settings, http: HttpFn = http_json):
        if not (settings.bankid_issuer and settings.bankid_client_id and settings.bankid_client_secret):
            raise RuntimeError(
                "FRITORG_BANKID=oidc needs FRITORG_BANKID_ISSUER, FRITORG_BANKID_CLIENT_ID and "
                "FRITORG_BANKID_CLIENT_SECRET (from your BankID provider)."
            )
        self.settings = settings
        self.http = http
        self._metadata: dict[str, Any] | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            url = f"{self.settings.bankid_issuer}/.well-known/openid-configuration"
            self._metadata = self.http(url, None, {})
        return self._metadata

    def authorization_url(self, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.bankid_client_id or "",
            "redirect_uri": redirect_uri,
            "scope": self.settings.bankid_scope,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "ui_locales": "nb",
        }
        if self.settings.bankid_acr_values:
            params["acr_values"] = self.settings.bankid_acr_values
        return f"{self.metadata['authorization_endpoint']}?{urllib.parse.urlencode(params)}"

    def exchange(self, code: str, redirect_uri: str, code_verifier: str, nonce: str) -> VerifiedIdentity:
        client_id = self.settings.bankid_client_id or ""
        basic = base64.b64encode(
            f"{urllib.parse.quote(client_id, safe='')}:{urllib.parse.quote(self.settings.bankid_client_secret or '', safe='')}".encode()
        ).decode()
        tokens = self.http(
            self.metadata["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "client_id": client_id,
            },
            {"Authorization": f"Basic {basic}"},
        )
        claims = self._validate_id_token(tokens.get("id_token", ""), nonce)
        if "name" not in claims and tokens.get("access_token") and self.metadata.get("userinfo_endpoint"):
            info = self.http(
                self.metadata["userinfo_endpoint"],
                None,
                {"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if info.get("sub") == claims.get("sub"):
                claims = {**info, **claims}
        subject = claims.get(self.settings.bankid_id_claim)
        if not subject:
            raise IdentityError("BankID ga ikke noen identitet tilbake.")
        name = claims.get("name") or " ".join(
            p for p in (claims.get("given_name"), claims.get("family_name")) if p
        )
        return VerifiedIdentity(
            issuer=str(claims["iss"]),
            subject=str(subject),
            name=str(name or "Bruker"),
            given_name=claims.get("given_name"),
            family_name=claims.get("family_name"),
        )

    def _validate_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        # The ID token comes straight from the token endpoint over TLS, which OpenID Connect Core
        # (section 3.1.3.7) accepts in place of a signature check. The claims are still checked.
        try:
            claims = json.loads(_unb64url(id_token.split(".")[1]))
        except (IndexError, ValueError):
            raise IdentityError("Ugyldig svar fra BankID.") from None
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        problems = [
            claims.get("iss") != self.metadata.get("issuer"),
            self.settings.bankid_client_id not in audiences,
            not isinstance(claims.get("exp"), int | float) or claims["exp"] < time.time() - 60,
            not hmac.compare_digest(str(claims.get("nonce", "")), nonce),
        ]
        if any(problems):
            logger.warning("Rejected BankID ID token (checks failed: %s)", problems)
            raise IdentityError("BankID-svaret kunne ikke bekreftes. Prøv igjen.")
        return claims


class SimulatedProvider:
    """Development stand-in for BankID: a local page where you type a name and a test identity."""

    via = "bankid-simulert"

    def __init__(self, settings: Settings, secret: str):
        self.settings = settings
        self.secret = secret

    def authorization_url(self, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        return "/bankid/simulator?" + urllib.parse.urlencode({"state": state, "nonce": nonce})

    def make_code(self, name: str, subject: str, nonce: str) -> str:
        payload = _b64url(
            json.dumps({"n": name, "s": subject, "nonce": nonce, "exp": time.time() + 300}).encode()
        )
        signature = _b64url(hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def exchange(self, code: str, redirect_uri: str, code_verifier: str, nonce: str) -> VerifiedIdentity:
        payload, _, signature = code.partition(".")
        expected = _b64url(hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise IdentityError("Ugyldig innlogging.")
        data = json.loads(_unb64url(payload))
        if data["exp"] < time.time() or not hmac.compare_digest(data["nonce"], nonce):
            raise IdentityError("Innloggingen er utløpt. Prøv igjen.")
        return VerifiedIdentity(issuer=SIMULATED_ISSUER, subject=data["s"], name=data["n"])


Provider = OidcProvider | SimulatedProvider


def create_provider(settings: Settings, secret: str) -> Provider | None:
    mode = settings.bankid_mode
    if mode == "off":
        return None
    if mode == "simulated":
        if (
            settings.base_url
            and settings.base_url.startswith("https://")
            and not settings.allow_simulated_bankid
        ):
            raise RuntimeError(
                "Simulated BankID must not run in production. Configure real BankID (FRITORG_BANKID=oidc) "
                "or set FRITORG_ALLOW_SIMULATED_BANKID=1 for a demo site."
            )
        return SimulatedProvider(settings, secret)
    if mode == "oidc":
        return OidcProvider(settings)
    raise RuntimeError(f"Unknown FRITORG_BANKID mode {mode!r}: use simulated, oidc or off.")


# --- Login flow ---------------------------------------------------------------------------------


def start_login(
    conn: sqlite3.Connection, provider: Provider, redirect_uri: str, return_to: str | None
) -> str:
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    with transaction(conn):
        conn.execute("DELETE FROM login_states WHERE created_at < ?", (iso_ago(minutes=LOGIN_STATE_MINUTES),))
        conn.execute(
            "INSERT INTO login_states (state_hash, nonce, code_verifier, return_to, created_at) VALUES (?, ?, ?, ?, ?)",
            (hash_token(state), nonce, verifier, return_to, now_iso()),
        )
    return provider.authorization_url(redirect_uri, state, nonce, challenge)


def login_nonce(conn: sqlite3.Connection, state: str) -> str | None:
    row = conn.execute(
        "SELECT nonce FROM login_states WHERE state_hash = ? AND created_at > ?",
        (hash_token(state), iso_ago(minutes=LOGIN_STATE_MINUTES)),
    ).fetchone()
    return row["nonce"] if row else None


def finish_login(
    conn: sqlite3.Connection, provider: Provider, redirect_uri: str, state: str, code: str
) -> tuple[VerifiedIdentity, str | None]:
    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM login_states WHERE state_hash = ? AND created_at > ?",
            (hash_token(state), iso_ago(minutes=LOGIN_STATE_MINUTES)),
        ).fetchone()
        conn.execute("DELETE FROM login_states WHERE state_hash = ?", (hash_token(state),))
    if row is None:
        raise IdentityError("Innloggingen er utløpt eller ugyldig. Prøv igjen.")
    identity = provider.exchange(code, redirect_uri, row["code_verifier"], row["nonce"])
    return identity, row["return_to"]


def create_pending(
    conn: sqlite3.Connection, identity: VerifiedIdentity, hashed: str, via: str, return_to: str | None
) -> str:
    token = secrets.token_urlsafe(32)
    with transaction(conn):
        conn.execute(
            "DELETE FROM pending_identities WHERE created_at < ?", (iso_ago(minutes=PENDING_MINUTES),)
        )
        conn.execute(
            "INSERT INTO pending_identities (token_hash, identity_hash, verified_name, display_name, verified_via, "
            "return_to, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (hash_token(token), hashed, identity.name, identity.display_name, via, return_to, now_iso()),
        )
    return token


def get_pending(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    return conn.execute(
        "SELECT * FROM pending_identities WHERE token_hash = ? AND created_at > ?",
        (hash_token(token), iso_ago(minutes=PENDING_MINUTES)),
    ).fetchone()


def delete_pending(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM pending_identities WHERE token_hash = ?", (hash_token(token),))


# --- Device authorization for agents ---------------------------------------------------------


@dataclass
class DeviceGrant:
    device_code: str
    user_code: str
    expires_in: int
    interval: int


def _new_user_code() -> str:
    letters = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


def normalize_user_code(value: str) -> str:
    letters = "".join(c for c in value.upper() if c in USER_CODE_ALPHABET)
    return f"{letters[:4]}-{letters[4:8]}" if len(letters) == 8 else ""


def start_device_grant(conn: sqlite3.Connection, client_name: str) -> DeviceGrant:
    device_code = secrets.token_urlsafe(32)
    name = " ".join(client_name.split())[:60] or "AI-agent"
    with transaction(conn):
        conn.execute("DELETE FROM device_grants WHERE expires_at < ?", (iso_ago(days=1),))
        while True:
            user_code = _new_user_code()
            if not conn.execute("SELECT 1 FROM device_grants WHERE user_code = ?", (user_code,)).fetchone():
                break
        conn.execute(
            "INSERT INTO device_grants (device_code_hash, user_code, client_name, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (hash_token(device_code), user_code, name, now_iso(), iso_in(minutes=DEVICE_CODE_MINUTES)),
        )
    return DeviceGrant(device_code, user_code, DEVICE_CODE_MINUTES * 60, DEVICE_POLL_SECONDS)


def pending_grant(conn: sqlite3.Connection, user_code: str) -> sqlite3.Row | None:
    code = normalize_user_code(user_code)
    if not code:
        return None
    return conn.execute(
        "SELECT * FROM device_grants WHERE user_code = ? AND status = 'pending' AND expires_at > ?",
        (code, now_iso()),
    ).fetchone()


def decide_grant(conn: sqlite3.Connection, user_code: str, user_id: int, approve: bool) -> bool:
    cursor = conn.execute(
        "UPDATE device_grants SET status = ?, user_id = ? WHERE user_code = ? AND status = 'pending' AND expires_at > ?",
        ("approved" if approve else "denied", user_id, normalize_user_code(user_code), now_iso()),
    )
    return cursor.rowcount == 1


class DeviceFlowError(AppError):
    """OAuth 2.0 device flow errors (RFC 8628): authorization_pending, slow_down, access_denied, expired_token."""

    status = 400
    title = "Device authorization not complete"

    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message, hint=hint)
        self.code = code


def poll_device_grant(conn: sqlite3.Connection, device_code: str) -> int:
    """Returns the approving user's id once; raises DeviceFlowError until then."""
    error: DeviceFlowError | None = None
    user_id = 0
    with transaction(conn):  # commit the poll time even when the answer is "not yet"
        row = conn.execute(
            "SELECT * FROM device_grants WHERE device_code_hash = ?", (hash_token(device_code),)
        ).fetchone()
        if row is None or row["expires_at"] < now_iso():
            error = DeviceFlowError("expired_token", "Koden er utløpt. Start på nytt.")
        elif row["status"] == "denied":
            error = DeviceFlowError("access_denied", "Brukeren avviste forespørselen.")
        elif row["status"] == "used":
            error = DeviceFlowError("expired_token", "Koden er allerede brukt.")
        elif row["status"] == "pending":
            too_soon = row["polled_at"] is not None and row["polled_at"] > iso_ago(
                seconds=DEVICE_POLL_SECONDS - 1
            )
            conn.execute("UPDATE device_grants SET polled_at = ? WHERE id = ?", (now_iso(), row["id"]))
            if too_soon:
                error = DeviceFlowError(
                    "slow_down",
                    "Vent litt mellom hver sjekk.",
                    hint=f"Poll at most every {DEVICE_POLL_SECONDS} seconds.",
                )
            else:
                error = DeviceFlowError(
                    "authorization_pending",
                    "Venter på at brukeren godkjenner.",
                    hint=f"Keep polling every {DEVICE_POLL_SECONDS} seconds until the user has approved.",
                )
        else:
            conn.execute("UPDATE device_grants SET status = 'used' WHERE id = ?", (row["id"],))
            user_id = int(row["user_id"])
    if error is not None:
        raise error
    return user_id


def grant_client_name(conn: sqlite3.Connection, device_code: str) -> str:
    row = conn.execute(
        "SELECT client_name FROM device_grants WHERE device_code_hash = ?", (hash_token(device_code),)
    ).fetchone()
    return row["client_name"] if row else "AI-agent"
