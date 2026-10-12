"""Password hashing and opaque tokens (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# OWASP's minimum for scrypt with 16 MiB of memory: about a fifth of a second per password. Hashes made
# with other values still work, and are made again with these when the person logs in.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 5
TOKEN_PREFIX = "ft_"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = stored.split("$")
        if algorithm != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest))
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _unb64(digest))


def needs_rehash(stored: str) -> bool:
    """A password hash made with other costs than today's (it is made again at the next login)."""
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    return parts[1:4] != [str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P)]


def new_token() -> str:
    """API/session token: 'ft_' + 43 url-safe chars. Only its SHA-256 hash is stored."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_hint(token: str) -> str:
    return f"{token[:7]}…{token[-4:]}"


def looks_like_token(value: str) -> bool:
    return value.startswith(TOKEN_PREFIX) and 20 <= len(value) <= 100
