"""Listing images: type sniffing, storage on disk and ordering."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

from . import fraud
from .errors import NotFound, PayloadTooLarge, ValidationProblem
from .listings import Image, add_risk_flag, check_owner, get_listing
from .util import now_iso

EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def sniff_image_type(data: bytes) -> str | None:
    """Detect the real image type from magic bytes (never trust the client's content type)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_base64_image(value: str) -> bytes:
    """Accept plain base64 or a data URL (data:image/png;base64,...)."""
    if value.startswith("data:"):
        value = value.split(",", 1)[-1]
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        raise ValidationProblem.field("image_base64", "Ugyldig base64-data.") from None


def add_image(
    conn: sqlite3.Connection,
    uploads_dir: Path,
    user_id: int,
    listing_id: int,
    data: bytes,
    *,
    alt_text: str | None = None,
    max_bytes: int,
    max_images: int,
    is_admin: bool = False,
) -> Image:
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    if len(data) > max_bytes:
        raise PayloadTooLarge(f"Bildet er for stort (maks {max_bytes // (1024 * 1024)} MB).")
    content_type = sniff_image_type(data)
    if content_type is None:
        raise ValidationProblem.field(
            "image",
            "Ukjent bildeformat. Bruk JPEG, PNG, WebP eller GIF.",
            hint="Supported: JPEG, PNG, WebP, GIF.",
        )
    if len(listing.images) >= max_images:
        raise ValidationProblem.field("image", f"En annonse kan ha maks {max_images} bilder.")

    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.{EXTENSIONS[content_type]}"
    temporary = uploads_dir / f".{filename}.tmp"
    temporary.write_bytes(data)
    os.replace(temporary, uploads_dir / filename)

    alt = " ".join((alt_text or "").split())[:200] or None
    position = max((image.position for image in listing.images), default=-1) + 1
    digest = hashlib.sha256(data).hexdigest()
    try:
        # A photo already used by another seller is a classic sign of a fake listing.
        if fraud.image_reused_by_other_seller(conn, listing.user_id, digest):
            add_risk_flag(conn, listing_id, "reused_image")
        cursor = conn.execute(
            "INSERT INTO listing_images (listing_id, filename, content_type, size_bytes, alt_text, position, sha256, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (listing_id, filename, content_type, len(data), alt, position, digest, now_iso()),
        )
        conn.execute("UPDATE listings SET updated_at = ? WHERE id = ?", (now_iso(), listing_id))
    except BaseException:
        remove_files(uploads_dir, [filename])
        raise
    return Image(cursor.lastrowid, listing_id, filename, content_type, alt, position)  # type: ignore[arg-type]


def delete_image(
    conn: sqlite3.Connection,
    uploads_dir: Path,
    user_id: int,
    listing_id: int,
    image_id: int,
    is_admin: bool = False,
) -> None:
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    image = next((i for i in listing.images if i.id == image_id), None)
    if image is None:
        raise NotFound(f"Bilde {image_id} finnes ikke på annonse {listing_id}.")
    conn.execute("DELETE FROM listing_images WHERE id = ?", (image_id,))
    conn.execute("UPDATE listings SET updated_at = ? WHERE id = ?", (now_iso(), listing_id))
    remove_files(uploads_dir, [image.filename])


def remove_files(uploads_dir: Path, filenames: list[str]) -> None:
    for name in filenames:
        try:
            (uploads_dir / Path(name).name).unlink()
        except FileNotFoundError:
            pass
