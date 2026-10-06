from __future__ import annotations

import io
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from PIL import ImageDraw

from fritorg.app import create_app
from fritorg.config import Settings


def make_image(
    seed: int = 1, size: tuple[int, int] = (800, 600), fmt: str = "PNG", **save_args: Any
) -> bytes:
    """A photo-like test image with enough structure for perceptual hashing."""
    import random

    rng = random.Random(seed)
    image = PILImage.new("RGB", size, (rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    draw = ImageDraw.Draw(image)
    width, height = size
    for _ in range(14):
        x, y = rng.randrange(width), rng.randrange(height)
        draw.rectangle(
            [x, y, x + rng.randrange(width // 2), y + rng.randrange(height // 2)],
            fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)),
        )
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_args)
    return buffer.getvalue()


PHOTO = make_image(1)


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Most tests use simple password accounts; test_bankid.py covers the BankID flows.
    return Settings(data_dir=tmp_path / "data", bankid_mode="off")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def register(
    client: TestClient,
    email: str = "kari@example.no",
    name: str = "Kari Nordmann",
    password: str = "hemmelig123",
) -> dict[str, Any]:
    response = client.post("/api/v1/auth/register", json={"email": email, "name": name, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {register(client)['token']['token']}"}


@pytest.fixture
def other_auth(client: TestClient) -> dict[str, str]:
    data = register(client, email="ola@example.no", name="Ola Hansen")
    return {"Authorization": f"Bearer {data['token']['token']}"}


def make_listing(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "category": "sykler",
        "title": "Terrengsykkel Trek Marlin 7",
        "description": "Lite brukt terrengsykkel med nylig service.",
        "price": 6500,
        "county": "oslo",
        "location": "Majorstuen",
        "attributes": {"bike_type": "terrain", "brand": "Trek", "condition": "good"},
    }
    body.update(overrides)
    response = client.post("/api/v1/listings", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def csrf(client: TestClient) -> str:
    """Load a page so the CSRF cookie is set, and return its value for form posts."""
    if "ft_csrf" not in client.cookies:
        client.get("/")
    return client.cookies["ft_csrf"]


def web_login(client: TestClient, email: str = "kari@example.no", password: str = "hemmelig123") -> None:
    response = client.post(
        "/logg-inn",
        data={"email": email, "password": password, "csrf_token": csrf(client), "neste": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


@pytest.fixture
def live_server(app: FastAPI) -> Iterator[str]:
    """Run the app in a real uvicorn server (for clients that need actual HTTP)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
