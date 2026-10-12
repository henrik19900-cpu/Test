"""Request-scoped helpers shared by the API, MCP and web routers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from urllib.parse import urlencode

from fastapi import Request

from .config import Settings
from .db import Database
from .ratelimit import RateLimiter


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = request.app.state.db.connect()
    try:
        yield conn
    finally:
        conn.close()


def base_url(request: Request) -> str:
    configured = request.app.state.settings.base_url
    return configured or str(request.base_url).rstrip("/")


def client_ip(request: Request) -> str:
    # Uvicorn rewrites request.client from X-Forwarded-For for trusted proxies (--forwarded-allow-ips).
    return request.client.host if request.client else "unknown"


def url_with_query(base: str, path: str, params: list[tuple[str, str]]) -> str:
    query = urlencode([(k, v) for k, v in params if v not in (None, "")])
    return f"{base}{path}?{query}" if query else f"{base}{path}"


def replace_params(request: Request, **updates: object) -> list[tuple[str, str]]:
    """The request's query params with some keys replaced (None removes a key)."""
    items = [(k, v) for k, v in request.query_params.multi_items() if k not in updates]
    for key, value in updates.items():
        if value is not None:
            items.append((key, str(value)))
    return items
