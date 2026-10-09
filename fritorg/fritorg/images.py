"""Listing images: validation, re-encoding, thumbnails and reuse detection.

Every upload is decoded and re-encoded with Pillow. That
* strips all metadata, including the GPS position phones store in photos (often the
  seller's home address),
* neutralises files that only pretend to be images,
* keeps pages fast: a WebP of at most 1600 px plus a 640 px thumbnail.

A perceptual hash (dHash) of each image makes it possible to spot photos that another
seller uploaded first, even after they were resized or re-compressed. Its four 16-bit quarters are
indexed, so a new photo is compared with the few earlier ones that share a quarter, not with every photo
on the site. Files are spread over 256 folders by the first two letters of their random name.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import re
import secrets
import sqlite3
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError

from .errors import NotFound, PayloadTooLarge, ValidationProblem
from .listings import Image, add_risk_flag, check_owner, get_listing
from .util import now_iso

PILImage.MAX_IMAGE_PIXELS = 40_000_000  # larger images are refused (decompression bombs)
MAX_SIDE = 1600
THUMB_SIDE = 640
SIMILAR_BITS = 5  # dHash distance below which two photos count as the same picture
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


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


@dataclass
class ProcessedImage:
    full: bytes
    thumb: bytes
    width: int
    height: int
    dhash: str


def dhash(image: PILImage.Image) -> str:
    """64-bit difference hash: robust against resizing and re-compression."""
    small = image.convert("L").resize((9, 8), PILImage.Resampling.LANCZOS)
    pixels = small.tobytes()  # one byte per pixel in mode "L"
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{bits:016x}"


def _encode(image: PILImage.Image, side: int, quality: int) -> tuple[bytes, int, int]:
    copy = image.copy()
    copy.thumbnail((side, side), PILImage.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format="WEBP", quality=quality, method=4)  # no exif/xmp/icc passed: metadata is dropped
    return buffer.getvalue(), copy.width, copy.height


def process_image(data: bytes) -> ProcessedImage:
    if sniff_image_type(data) is None:
        raise ValidationProblem.field(
            "image",
            "Ukjent bildeformat. Bruk JPEG, PNG, WebP eller GIF.",
            hint="Supported: JPEG, PNG, WebP, GIF.",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            with PILImage.open(io.BytesIO(data)) as opened:
                if opened.format not in ALLOWED_FORMATS:
                    raise ValueError(f"format {opened.format}")
                opened.seek(0)  # first frame of animations
                image = ImageOps.exif_transpose(opened)  # respect the phone's rotation flag
                image.load()
    except (
        UnidentifiedImageError,
        PILImage.DecompressionBombError,
        PILImage.DecompressionBombWarning,
        OSError,
        ValueError,
    ):
        raise ValidationProblem.field(
            "image",
            "Bildet kunne ikke leses, eller det er for stort.",
            hint="Send a normal photo, max 40 megapixels.",
        ) from None
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    full, width, height = _encode(image, MAX_SIDE, 82)
    thumb, _, _ = _encode(image, THUMB_SIDE, 76)
    return ProcessedImage(full, thumb, width, height, dhash(image))


def _informative(hash_hex: str) -> bool:
    """Near-uniform pictures (blank, one colour) have degenerate hashes that would match anything."""
    return 10 <= bin(int(hash_hex, 16)).count("1") <= 54


def hash_quarters(hash_hex: str | None) -> tuple[int | None, ...]:
    """The four 16-bit quarters of a dHash, for listing_images.hash_a..hash_d (None if uninformative).

    Two hashes at most three bits apart share at least one quarter, and most of those four or five bits
    apart do too, so looking up the quarters finds the earlier copies of a photo."""
    if not hash_hex or not _informative(hash_hex):
        return (None, None, None, None)
    value = int(hash_hex, 16)
    return tuple((value >> shift) & 0xFFFF for shift in (48, 32, 16, 0))


def reused_by_other_seller(conn: sqlite3.Connection, user_id: int, digest: str, perceptual: str) -> bool:
    """True if another seller uploaded this picture first (so the original owner is never flagged)."""
    quarters = hash_quarters(perceptual)
    rows = conn.execute(
        "SELECT i.id, i.sha256, i.dhash, l.user_id FROM listing_images i JOIN listings l ON l.id = i.listing_id "
        "WHERE substr(i.sha256, 1, 16) = ? OR i.hash_a = ? OR i.hash_b = ? OR i.hash_c = ? OR i.hash_d = ? "
        "ORDER BY i.id",
        (digest[:16], *quarters),
    ).fetchall()
    target = int(perceptual, 16)
    for row in rows:  # ordered oldest first: the first match is the original
        same = row["sha256"] == digest
        if not same and quarters[0] is not None and row["dhash"]:
            same = bin(int(row["dhash"], 16) ^ target).count("1") <= SIMILAR_BITS
        if same:
            return row["user_id"] != user_id
    return False


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
    if len(listing.images) >= max_images:
        raise ValidationProblem.field("image", f"En annonse kan ha maks {max_images} bilder.")
    processed = process_image(data)

    stem = secrets.token_hex(16)
    folder = uploads_dir / stem[:2]
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{stem[:2]}/{stem}.webp"
    for name, content in ((f"{stem}.webp", processed.full), (f"{stem}-t.webp", processed.thumb)):
        temporary = folder / f".{name}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, folder / name)

    alt = " ".join((alt_text or "").split())[:200] or None
    position = max((image.position for image in listing.images), default=-1) + 1
    digest = hashlib.sha256(data).hexdigest()
    try:
        # A photo already used by another seller is a classic sign of a fake listing.
        if reused_by_other_seller(conn, listing.user_id, digest, processed.dhash):
            add_risk_flag(conn, listing_id, "reused_image")
        cursor = conn.execute(
            "INSERT INTO listing_images (listing_id, filename, content_type, size_bytes, alt_text, position, sha256, "
            "dhash, hash_a, hash_b, hash_c, hash_d, width, height, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                listing_id,
                filename,
                "image/webp",
                len(processed.full),
                alt,
                position,
                digest,
                processed.dhash,
                *hash_quarters(processed.dhash),
                processed.width,
                processed.height,
                now_iso(),
            ),
        )
        conn.execute("UPDATE listings SET updated_at = ? WHERE id = ?", (now_iso(), listing_id))
    except BaseException:
        remove_files(uploads_dir, [filename])
        raise
    return Image(
        cursor.lastrowid,  # type: ignore[arg-type]
        listing_id,
        filename,
        "image/webp",
        alt,
        position,
        processed.width,
        processed.height,
    )


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


def make_main(
    conn: sqlite3.Connection, user_id: int, listing_id: int, image_id: int, is_admin: bool = False
) -> None:
    """Move a photo first: it becomes the one shown in search results and previews."""
    listing = get_listing(conn, listing_id)
    check_owner(listing, user_id, is_admin)
    if all(image.id != image_id for image in listing.images):
        raise NotFound(f"Bilde {image_id} finnes ikke på annonse {listing_id}.")
    order = [image_id] + [image.id for image in listing.images if image.id != image_id]
    conn.executemany(
        "UPDATE listing_images SET position = ? WHERE id = ?",
        [(position, i) for position, i in enumerate(order)],
    )
    conn.execute("UPDATE listings SET updated_at = ? WHERE id = ?", (now_iso(), listing_id))


_STORED_NAME = re.compile(r"(?:[0-9a-f]{2}/)?[0-9a-f]{32}\.webp")


def remove_files(uploads_dir: Path, filenames: list[str]) -> None:
    """Delete images and their thumbnails. Only names this module made are accepted (nothing else on disk)."""
    for name in filenames:
        if not _STORED_NAME.fullmatch(name):
            continue
        path = uploads_dir / name
        for candidate in (path, path.with_name(f"{path.stem}-t{path.suffix}")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
