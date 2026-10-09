from __future__ import annotations

import io

import pytest
from conftest import PHOTO, make_image, make_listing
from PIL import Image as PILImage

from fritorg import images
from fritorg.errors import ValidationProblem


def _open(data: bytes) -> PILImage.Image:
    return PILImage.open(io.BytesIO(data))


def test_gps_and_other_metadata_are_removed():
    exif = PILImage.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[0x8825] = {1: "N", 2: (59.0, 54.0, 49.0), 3: "E", 4: (10.0, 45.0, 7.0)}  # GPS: somewhere in Oslo
    photo = make_image(3, fmt="JPEG", exif=exif.tobytes())
    assert _open(photo).getexif()  # the original has metadata

    processed = images.process_image(photo)
    for data in (processed.full, processed.thumb):
        cleaned = _open(data)
        assert cleaned.format == "WEBP"
        assert not cleaned.getexif()
        assert "exif" not in cleaned.info and "xmp" not in cleaned.info


def test_large_photos_are_downscaled_with_thumbnails():
    processed = images.process_image(make_image(4, size=(4000, 3000), fmt="JPEG"))
    assert (processed.width, processed.height) == (1600, 1200)
    assert max(_open(processed.thumb).size) == 640


def test_phone_rotation_is_applied():
    exif = PILImage.Exif()
    exif[0x0112] = 6  # "rotate 90° clockwise" flag that phones set
    processed = images.process_image(make_image(5, size=(800, 600), fmt="JPEG", exif=exif.tobytes()))
    assert (processed.width, processed.height) == (600, 800)


def test_transparency_and_animation_are_handled():
    transparent = io.BytesIO()
    PILImage.new("RGBA", (300, 200), (255, 0, 0, 0)).save(transparent, format="PNG")
    assert _open(images.process_image(transparent.getvalue()).full).mode == "RGBA"

    animated = io.BytesIO()
    frames = [PILImage.new("RGB", (120, 80), color) for color in ("red", "blue")]
    frames[0].save(animated, format="GIF", save_all=True, append_images=frames[1:])
    assert images.process_image(animated.getvalue()).width == 120


@pytest.mark.parametrize(
    "data",
    [
        b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>",
        b"<html><script>alert(1)</script></html>",
        PHOTO[:200],  # truncated: valid header, broken image
        b"\xff\xd8\xff" + b"not really a jpeg",
    ],
)
def test_broken_and_fake_images_are_rejected(data):
    with pytest.raises(ValidationProblem):
        images.process_image(data)


def test_decompression_bombs_are_rejected(monkeypatch):
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 10_000)
    with pytest.raises(ValidationProblem):
        images.process_image(make_image(6, size=(400, 300)))


def test_perceptual_hash_survives_resizing_and_jpeg():
    original = images.process_image(PHOTO).dhash
    copy = io.BytesIO()
    _open(PHOTO).resize((320, 240)).save(copy, format="JPEG", quality=60)
    distance = bin(int(original, 16) ^ int(images.process_image(copy.getvalue()).dhash, 16)).count("1")
    assert distance <= images.SIMILAR_BITS
    different = images.process_image(make_image(9)).dhash
    assert bin(int(original, 16) ^ int(different, 16)).count("1") > images.SIMILAR_BITS


def test_image_limit_per_listing(app, client, auth):
    app.state.settings.max_images_per_listing = 2
    listing = make_listing(client, auth)
    for seed in (11, 12):
        response = client.post(
            f"/api/v1/listings/{listing['id']}/images",
            files={"file": ("p.png", make_image(seed), "image/png")},
            headers=auth,
        )
        assert response.status_code == 201
    third = client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("p.png", make_image(13), "image/png")},
        headers=auth,
    )
    assert third.status_code == 422
