"""Accounts, web sessions and API tokens."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .db import transaction
from .errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationProblem
from .security import hash_password, hash_token, new_token, token_hint, verify_password
from .util import iso_ago, iso_in, now_iso

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_DAYS = 30
MAX_TOKENS_PER_USER = 25


@dataclass
class User:
    id: int
    email: str
    name: str
    is_admin: bool
    created_at: str
    banned_at: str | None = None
    ban_reason: str | None = None

    @property
    def is_new(self) -> bool:
        """Accounts younger than a day get stricter quotas."""
        return self.created_at > iso_ago(days=1)


@dataclass
class ApiToken:
    id: int
    name: str
    hint: str
    created_at: str
    last_used_at: str | None


def _user(row: sqlite3.Row) -> User:
    return User(
        row["id"],
        row["email"],
        row["name"],
        bool(row["is_admin"]),
        row["created_at"],
        row["banned_at"],
        row["ban_reason"],
    )


def normalize_name(name: str) -> str:
    return " ".join(name.split())


def validate_registration(email: str, name: str, password: str) -> list[dict[str, str]]:
    errors = []
    if not EMAIL_RE.match(email.strip()) or len(email) > 254:
        errors.append({"field": "email", "message": "Ugyldig e-postadresse."})
    if not 2 <= len(normalize_name(name)) <= 60:
        errors.append({"field": "name", "message": "Visningsnavnet må være mellom 2 og 60 tegn."})
    if len(password) < 8:
        errors.append({"field": "password", "message": "Passordet må ha minst 8 tegn."})
    elif len(password) > 200:
        errors.append({"field": "password", "message": "Passordet kan ha maks 200 tegn."})
    return errors


def create_user(conn: sqlite3.Connection, email: str, name: str, password: str, via: str = "web") -> User:
    errors = validate_registration(email, name, password)
    if errors:
        raise ValidationProblem.from_errors(errors)
    email = email.strip()
    password_hash = hash_password(password)  # slow on purpose; keep it outside the write lock
    with transaction(conn):
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise Conflict(
                "Det finnes allerede en konto med denne e-postadressen.",
                hint="Log in with POST /api/v1/auth/token to get a new API token for an existing account.",
            )
        cursor = conn.execute(
            "INSERT INTO users (email, name, password_hash, created_via, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, normalize_name(name), password_hash, via, now_iso()),
        )
    return get_user(conn, cursor.lastrowid)  # type: ignore[return-value]


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> User:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise Unauthorized("Feil e-postadresse eller passord.")
    if row["banned_at"]:
        raise Forbidden("Kontoen er stengt av en moderator.")
    return _user(row)


def get_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user(row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()
    return _user(row) if row else None


def delete_user(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """Delete an account with its listings, images, messages and tokens. Returns image files to remove."""
    rows = conn.execute(
        "SELECT i.filename FROM listing_images i JOIN listings l ON l.id = i.listing_id WHERE l.user_id = ?",
        (user_id,),
    ).fetchall()
    with transaction(conn):
        conn.execute(
            "DELETE FROM listings_fts WHERE rowid IN (SELECT id FROM listings WHERE user_id = ?)", (user_id,)
        )
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return [row["filename"] for row in rows]


def ban_user(conn: sqlite3.Connection, user_id: int, reason: str) -> None:
    """Close an account: it can no longer log in, and its listings disappear from public view."""
    with transaction(conn):
        conn.execute(
            "UPDATE users SET banned_at = ?, ban_reason = ? WHERE id = ?",
            (now_iso(), reason.strip()[:500], user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))


def unban_user(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET banned_at = NULL, ban_reason = NULL WHERE id = ?", (user_id,))


def set_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool = True) -> None:
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))


# --- Web sessions ------------------------------------------------------------------------


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = new_token()
    with transaction(conn):
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (hash_token(token), user_id, now_iso(), iso_in(days=SESSION_DAYS)),
        )
    return token


def user_for_session(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND u.banned_at IS NULL",
        (hash_token(token), now_iso()),
    ).fetchone()
    return _user(row) if row else None


def delete_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


# --- API tokens ----------------------------------------------------------------------------


def create_api_token(conn: sqlite3.Connection, user_id: int, name: str) -> tuple[str, ApiToken]:
    name = normalize_name(name)[:60] or "API-nøkkel"
    token = new_token()
    with transaction(conn):
        count = conn.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id = ?", (user_id,)).fetchone()[0]
        if count >= MAX_TOKENS_PER_USER:
            raise Conflict(
                f"Du kan ha maks {MAX_TOKENS_PER_USER} API-nøkler. Slett en gammel nøkkel først.",
                hint="Revoke unused tokens with DELETE /api/v1/me/tokens/{id}.",
            )
        cursor = conn.execute(
            "INSERT INTO api_tokens (user_id, name, token_hash, token_hint, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, hash_token(token), token_hint(token), now_iso()),
        )
    return token, ApiToken(cursor.lastrowid, name, token_hint(token), now_iso(), None)  # type: ignore[arg-type]


def user_for_token(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.*, t.id AS token_id, t.last_used_at FROM api_tokens t JOIN users u ON u.id = t.user_id "
        "WHERE t.token_hash = ? AND u.banned_at IS NULL",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    # Record usage, but at most every few minutes to keep reads cheap.
    if row["last_used_at"] is None or row["last_used_at"] < iso_ago(minutes=5):
        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now_iso(), row["token_id"]))
    return _user(row)


def list_api_tokens(conn: sqlite3.Connection, user_id: int) -> list[ApiToken]:
    rows = conn.execute("SELECT * FROM api_tokens WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    return [ApiToken(r["id"], r["name"], r["token_hint"], r["created_at"], r["last_used_at"]) for r in rows]


def revoke_api_token(conn: sqlite3.Connection, user_id: int, token_id: int) -> None:
    cursor = conn.execute("DELETE FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user_id))
    if cursor.rowcount == 0:
        raise NotFound(f"API-nøkkel {token_id} finnes ikke.")


def revoke_api_token_by_value(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM api_tokens WHERE token_hash = ?", (hash_token(token),))
