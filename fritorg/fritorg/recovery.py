"""Forgotten passwords: a reset link by e-mail, or a code by SMS to the account's confirmed number.

Reset links are signed and carry a fingerprint of the current password hash, so a link stops
working as soon as the password has been changed (it can be used once) and after an hour.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time

from .mailer import Mail, Mailer
from .users import UNUSABLE_PASSWORD, User, _user

RESET_MINUTES = 60


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), f"reset:{payload}".encode(), hashlib.sha256).hexdigest()[:32]


def reset_token(secret: str, user_id: int, password_hash: str, now: float | None = None) -> str:
    expires = int(now if now is not None else time.time()) + RESET_MINUTES * 60
    payload = f"{user_id}.{expires}.{_fingerprint(password_hash)}"
    return f"{payload}.{_sign(secret, payload)}"


def user_for_reset_token(conn: sqlite3.Connection, secret: str, token: str) -> User | None:
    parts = (token or "").split(".")
    if len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    payload = ".".join(parts[:3])
    if not hmac.compare_digest(parts[3], _sign(secret, payload)) or int(parts[1]) < time.time():
        return None
    row = conn.execute("SELECT * FROM users WHERE id = ?", (int(parts[0]),)).fetchone()
    if row is None or row["banned_at"] or row["password_hash"] == UNUSABLE_PASSWORD:
        return None
    if not hmac.compare_digest(parts[2], _fingerprint(row["password_hash"])):
        return None  # the password has changed since the link was made
    return _user(row)


def send_reset_link(mailer: Mailer, conn: sqlite3.Connection, secret: str, base: str, user: User) -> None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None or row["password_hash"] == UNUSABLE_PASSWORD:
        return
    link = f"{base}/nytt-passord?token={reset_token(secret, user.id, row['password_hash'])}"
    site = mailer.settings.site_name
    mailer.send_later(
        Mail(
            user.email,
            f"Lag nytt passord på {site}",
            f"Hei {user.name}!\n\nNoen, forhåpentligvis du, har bedt om å lage nytt passord for kontoen din på "
            f"{site}. Bruk denne lenken:\n\n{link}\n\nLenken virker i {RESET_MINUTES} minutter og kan brukes én "
            "gang. Har du ikke bedt om dette, kan du se bort fra e-posten. Passordet ditt er ikke endret.\n",
        )
    )
