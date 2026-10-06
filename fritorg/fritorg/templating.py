"""Jinja2 setup, cookies and helpers for rendering HTML pages."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import __version__, messages, taxonomy, users
from .listings import REPORT_REASONS, SORTS
from .util import format_date_no, format_datetime_no, format_number, truncate

SESSION_COOKIE = "ft_session"
CSRF_COOKIE = "ft_csrf"
FLASH_COOKIE = "ft_flash"
NBSP = "\u00a0"

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters.update(
    nok=lambda value: format_number(value, NBSP) + NBSP + "kr",
    number=lambda value: format_number(value, NBSP),
    date_no=format_date_no,
    datetime_no=format_datetime_no,
    shorten=truncate,
)
templates.env.globals.update(
    version=__version__,
    NBSP=NBSP,
    CATEGORIES=taxonomy.CATEGORIES,
    GROUPS=taxonomy.GROUPS,
    COUNTIES=taxonomy.COUNTIES,
    LISTING_TYPES=taxonomy.LISTING_TYPES,
    PRICE_UNIT_LABELS=taxonomy.PRICE_UNIT_LABELS,
    STATUSES=taxonomy.STATUSES,
    SORTS=SORTS,
    REPORT_REASONS=REPORT_REASONS,
)


def current_user(request: Request, conn: sqlite3.Connection) -> users.User | None:
    if not hasattr(request.state, "web_user"):
        request.state.web_user = users.user_for_session(conn, request.cookies.get(SESSION_COOKIE))
    return request.state.web_user


def base_context(request: Request, conn: sqlite3.Connection | None) -> dict[str, Any]:
    settings = request.app.state.settings
    user = current_user(request, conn) if conn is not None else None
    flash = request.cookies.get(FLASH_COOKIE)
    return {
        "user": user,
        "unread": messages.unread_count(conn, user.id) if (user and conn is not None) else 0,
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "flash": unquote(flash) if flash else None,
        "site_name": settings.site_name,
        "bankid_mode": settings.bankid_mode,
        "contact_email": settings.contact_email,
        "operator": settings.operator,
        "base": settings.base_url or str(request.base_url).rstrip("/"),
        "path": request.url.path,
    }


def render(
    request: Request,
    conn: sqlite3.Connection | None,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    ctx = base_context(request, conn)
    ctx.update(context or {})
    response = templates.TemplateResponse(request, name, ctx, status_code=status, headers=headers)
    if ctx["flash"]:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


def render_error(
    request: Request, status: int, message: str, headers: dict[str, str] | None = None
) -> HTMLResponse:
    titles = {
        401: "Du må logge inn",
        403: "Ingen tilgang",
        404: "Fant ikke siden",
        413: "For stor forespørsel",
        422: "Noe stemmer ikke",
        429: "Litt for mange forespørsler",
        500: "Noe gikk galt",
    }
    try:
        with request.app.state.db.session() as conn:
            return render(
                request,
                conn,
                "error.html",
                {"status": status, "title": titles.get(status, "Feil"), "message": message},
                status=status,
                headers=headers,
            )
    except Exception:  # never fail while reporting a failure
        return HTMLResponse(f"<h1>{status}</h1>", status_code=status, headers=headers)


def redirect(url: str, flash: str | None = None, status: int = 303) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status)
    if flash:
        response.set_cookie(FLASH_COOKIE, quote(flash), max_age=60, httponly=True, samesite="lax", path="/")
    return response


def safe_next(value: str | None, default: str = "/") -> str:
    """Only allow local redirect targets (no open redirects)."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default
