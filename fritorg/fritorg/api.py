"""REST API v1. Reading never needs a key; writing needs a free personal token."""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import images, listings, messages, serializers, taxonomy, users
from .config import Settings
from .deps import base_url, client_ip, get_conn, get_settings, replace_params, url_with_query
from .errors import NotFound, RateLimited, Unauthorized
from .listings import SORTS, SearchParams
from .ratelimit import RateLimiter
from .schemas import (
    AccountOut,
    AuthOut,
    CategoryOut,
    ContactIn,
    ConversationOut,
    CountyOut,
    ImageUploadOut,
    ListingCreate,
    ListingOut,
    ListingUpdate,
    LoginIn,
    NewTokenOut,
    Problem,
    RegisterIn,
    ReplyIn,
    ReportIn,
    ReportOut,
    SearchOut,
    TokenCreateIn,
    TokenOut,
    UserPublicOut,
)

ERROR_RESPONSES = {
    status: {"model": Problem, "content": {"application/problem+json": {}}}
    for status in (401, 403, 404, 422, 429)
}

router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)

bearer = HTTPBearer(
    auto_error=False,
    description="Personal API token (free). Create one at /min-side, or with POST /api/v1/auth/register.",
)

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

AUTH_HINT = (
    "Send 'Authorization: Bearer <token>'. Get a free token with POST /api/v1/auth/register (new account) "
    "or POST /api/v1/auth/token (existing account), or create one at /min-side."
)


def optional_user(
    request: Request,
    conn: Conn,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> users.User | None:
    if credentials is None:
        return None
    user = users.user_for_token(conn, credentials.credentials)
    if user is None:
        raise Unauthorized("Ugyldig eller tilbakekalt API-nøkkel.", hint=AUTH_HINT)
    request.state.user = user
    return user


def require_user(user: Annotated[users.User | None, Depends(optional_user)]) -> users.User:
    if user is None:
        raise Unauthorized("Denne handlingen krever innlogging med API-nøkkel.", hint=AUTH_HINT)
    return user


OptionalUser = Annotated[users.User | None, Depends(optional_user)]
CurrentUser = Annotated[users.User, Depends(require_user)]


def _account(conn: sqlite3.Connection, user: users.User) -> dict:
    counts = {status: 0 for status in taxonomy.STATUSES}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM listings WHERE user_id = ? GROUP BY status", (user.id,)
    ):
        counts[row["status"]] = row["n"]
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "member_since": user.created_at,
        "unread_messages": messages.unread_count(conn, user.id),
        "listings": counts,
    }


def _new_token(token: str, record: users.ApiToken, base: str) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "hint": record.hint,
        "created_at": record.created_at,
        "last_used_at": record.last_used_at,
        "token": token,
        "mcp_url": f"{base}/mcp/{token}",
    }


def _limit(limiter: RateLimiter, bucket: str, key: str, limit: int, window: int, message: str) -> None:
    decision = limiter.hit(bucket, key, limit, window)
    if not decision.allowed:
        raise RateLimited(message, retry_after=decision.reset_in)


# --- Discovery ------------------------------------------------------------------------------------


@router.get("", summary="API index", tags=["meta"])
def api_index(request: Request) -> dict:
    """Entry point with links to everything an agent needs."""
    base = base_url(request)
    return {
        "name": f"{request.app.state.settings.site_name} API",
        "version": "v1",
        "description": "Free Norwegian classifieds marketplace. Reading needs no key; writing needs a free token.",
        "links": {
            "openapi": f"{base}/openapi.json",
            "docs": f"{base}/api/docs",
            "llms_txt": f"{base}/llms.txt",
            "agent_guide": f"{base}/for-agenter.md",
            "mcp": f"{base}/mcp",
            "categories": f"{base}/api/v1/categories",
            "counties": f"{base}/api/v1/counties",
            "search": f"{base}/api/v1/listings?q=sykkel",
            "export": f"{base}/api/v1/export/listings.ndjson",
            "register": f"{base}/api/v1/auth/register",
        },
    }


@router.get("/categories", response_model=list[CategoryOut], tags=["categories"], summary="Category tree")
def list_categories(request: Request, conn: Conn) -> list[dict]:
    """All category groups with subcategories, allowed listing types and attribute schemas."""
    counts = listings.category_counts(conn)
    base = base_url(request)
    return [serializers.category_dict(taxonomy.CATEGORIES[g], base, counts) for g in taxonomy.GROUPS]


@router.get("/categories/{slug}", response_model=CategoryOut, tags=["categories"], summary="One category")
def get_category(slug: str, request: Request, conn: Conn) -> dict:
    category = taxonomy.get_category(slug)
    if category is None:
        raise NotFound(f"Kategorien {slug!r} finnes ikke.", hint=taxonomy.suggest_category(slug))
    return serializers.category_dict(category, base_url(request), listings.category_counts(conn))


@router.get("/counties", response_model=list[CountyOut], tags=["categories"], summary="Counties (fylker)")
def list_counties() -> list[dict]:
    return [{"slug": c.slug, "name": c.name} for c in taxonomy.COUNTIES.values()]


# --- Listings ------------------------------------------------------------------------------------


@router.get("/listings", response_model=SearchOut, tags=["listings"], summary="Search listings")
def search_listings(
    request: Request,
    response: Response,
    conn: Conn,
    q: Annotated[
        str | None, Query(description="Free text. Matches substrings, so 'sofa' also finds 'hjørnesofa'.")
    ] = None,
    category: Annotated[
        str | None,
        Query(
            description="Category or group slug, e.g. 'bil' or 'torget'.",
            json_schema_extra={"enum": taxonomy.ALL_SLUGS},
        ),
    ] = None,
    type: Annotated[
        str | None,
        Query(description="Listing type.", json_schema_extra={"enum": list(taxonomy.LISTING_TYPES)}),
    ] = None,
    county: Annotated[
        str | None, Query(description="County slug.", json_schema_extra={"enum": list(taxonomy.COUNTIES)})
    ] = None,
    location: Annotated[str | None, Query(description="Part of the place name, e.g. 'Bergen'.")] = None,
    price_min: Annotated[int | None, Query(ge=0, description="Minimum price in NOK.")] = None,
    price_max: Annotated[
        int | None, Query(ge=0, description="Maximum price in NOK. 0 finds free items.")
    ] = None,
    attr: Annotated[
        list[str],
        Query(
            description="Attribute filters, repeatable: `key:value`, `key:v1,v2`, `key:min..max`, `key:min..`, "
            "`key:..max`. Example: attr=fuel:electric&attr=year:2018..",
        ),
    ] = [],  # noqa: B006 - FastAPI copies query defaults
    seller_id: Annotated[int | None, Query(description="Only listings from this seller.")] = None,
    status: Annotated[
        Literal["active", "sold", "any"], Query(description="'any' = active and sold listings.")
    ] = "active",
    updated_since: Annotated[
        str | None, Query(description="ISO 8601 timestamp; only listings created or changed since then.")
    ] = None,
    has_images: Annotated[bool, Query(description="Only listings with at least one image.")] = False,
    sort: Annotated[
        str | None,
        Query(
            description="Defaults to relevance with q, else newest.", json_schema_extra={"enum": list(SORTS)}
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Search active listings. All filters combine with AND."""
    params = SearchParams(
        q=q,
        category=category,
        type=type,
        county=county,
        location=location,
        price_min=price_min,
        price_max=price_max,
        attrs=listings.attr_filters_from_params(request.query_params.multi_items()),
        user_id=seller_id,
        status=status,
        updated_since=updated_since,
        has_images=has_images,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    result = listings.search(conn, params)
    base = base_url(request)
    next_url = None
    if result.has_more:
        next_url = url_with_query(
            base, request.url.path, replace_params(request, offset=result.params.offset + result.params.limit)
        )
        response.headers["Link"] = f'<{next_url}>; rel="next"'
    return serializers.search_dict(result, base, next_url)


@router.get("/listings/{listing_id}", response_model=ListingOut, tags=["listings"], summary="Get a listing")
def get_listing(listing_id: int, request: Request, conn: Conn, user: OptionalUser) -> dict:
    """A listing. Show `safety_warnings` to your user; the owner also gets `moderation` details."""
    viewer = user.id if user else None
    admin = bool(user and user.is_admin)
    listing = listings.get_visible_listing(conn, listing_id, viewer, admin)
    owner_view = admin or listing.user_id == viewer
    return serializers.listing_detail(listing, base_url(request), owner_view=owner_view)


@router.post(
    "/listings", status_code=201, response_model=ListingOut, tags=["listings"], summary="Create a listing"
)
def create_listing(
    body: ListingCreate,
    request: Request,
    response: Response,
    conn: Conn,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    """Create a listing (free). Add images afterwards with POST /api/v1/listings/{id}/images.

    Listings with strong fraud signals get status `review` and are published after a manual check;
    `moderation.reasons` explains why.
    """
    listing_id = listings.create_listing(
        conn,
        user.id,
        body.model_dump(),
        via=_channel(request),
        max_per_day=settings.max_listings_per_day,
        new_account_max_per_day=settings.new_account_max_listings_per_day,
    )
    base = base_url(request)
    response.headers["Location"] = f"{base}/api/v1/listings/{listing_id}"
    return serializers.listing_detail(listings.get_listing(conn, listing_id), base, owner_view=True)


@router.patch(
    "/listings/{listing_id}", response_model=ListingOut, tags=["listings"], summary="Update a listing"
)
def update_listing(
    listing_id: int, body: ListingUpdate, request: Request, conn: Conn, user: CurrentUser
) -> dict:
    """Change some fields. Use status 'sold' when the item is sold and 'inactive' to hide it."""
    changes = body.model_dump(exclude_unset=True)
    listing = listings.update_listing(conn, user.id, listing_id, changes, is_admin=user.is_admin)
    return serializers.listing_detail(listing, base_url(request), owner_view=True)


@router.delete("/listings/{listing_id}", status_code=204, tags=["listings"], summary="Delete a listing")
def delete_listing(listing_id: int, conn: Conn, user: CurrentUser, settings: SettingsDep) -> Response:
    filenames = listings.delete_listing(conn, user.id, listing_id, is_admin=user.is_admin)
    images.remove_files(settings.uploads_dir, filenames)
    return Response(status_code=204)


@router.post(
    "/listings/{listing_id}/images",
    status_code=201,
    response_model=ImageUploadOut,
    tags=["listings"],
    summary="Add an image",
)
def upload_image(
    listing_id: int,
    request: Request,
    conn: Conn,
    user: CurrentUser,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP or GIF, max 8 MB.")],
    alt_text: Annotated[
        str | None, Form(description="Short description of the image (accessibility).")
    ] = None,
) -> dict:
    data = file.file.read(settings.max_image_bytes + 1)
    image = images.add_image(
        conn,
        settings.uploads_dir,
        user.id,
        listing_id,
        data,
        alt_text=alt_text,
        max_bytes=settings.max_image_bytes,
        max_images=settings.max_images_per_listing,
        is_admin=user.is_admin,
    )
    status = listings.get_listing(conn, listing_id).status
    return {**serializers.image_dict(image, base_url(request)), "listing_status": status}


@router.delete(
    "/listings/{listing_id}/images/{image_id}", status_code=204, tags=["listings"], summary="Delete an image"
)
def delete_image(
    listing_id: int, image_id: int, conn: Conn, user: CurrentUser, settings: SettingsDep
) -> Response:
    images.delete_image(conn, settings.uploads_dir, user.id, listing_id, image_id, is_admin=user.is_admin)
    return Response(status_code=204)


@router.post(
    "/listings/{listing_id}/reports",
    status_code=202,
    response_model=ReportOut,
    tags=["listings"],
    summary="Report a listing",
)
def report_listing(listing_id: int, body: ReportIn, request: Request, conn: Conn, user: OptionalUser) -> dict:
    """Flag fraud, spam or illegal content for moderation. No account needed."""
    _limit(
        request.app.state.limiter,
        "report",
        client_ip(request),
        20,
        3600,
        "For mange rapporter. Prøv igjen senere.",
    )
    report_id = listings.create_report(
        conn, listing_id, body.reason, body.comment, user.id if user else None, via=_channel(request)
    )
    return {"id": report_id, "status": "received"}


@router.get(
    "/users/{user_id}", response_model=UserPublicOut, tags=["listings"], summary="Public seller profile"
)
def get_user(user_id: int, request: Request, conn: Conn) -> dict:
    user = users.get_user(conn, user_id)
    if user is None:
        raise NotFound(f"Bruker {user_id} finnes ikke.")
    active = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE user_id = ? AND status = 'active'", (user_id,)
    ).fetchone()[0]
    return {
        "id": user.id,
        "name": user.name,
        "member_since": user.created_at,
        "active_listings": active,
        "url": f"{base_url(request)}/bruker/{user.id}",
    }


@router.get("/export/listings.ndjson", tags=["listings"], summary="Bulk export (NDJSON)")
def export_listings(request: Request) -> StreamingResponse:
    """Every active and sold listing as one JSON object per line. Use this instead of crawling page by page."""
    db = request.app.state.db
    base = base_url(request)

    def generate():
        with db.session() as conn:
            for listing in listings.iter_public_listings(conn):
                yield json.dumps(serializers.listing_detail(listing, base), ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'inline; filename="fritorg-listings.ndjson"'},
    )


# --- Accounts ----------------------------------------------------------------------------------


@router.post(
    "/auth/register", status_code=201, response_model=AuthOut, tags=["account"], summary="Create account"
)
def register(body: RegisterIn, request: Request, conn: Conn, settings: SettingsDep) -> dict:
    """Create a free account and get an API token in one step. Agents may do this on behalf of their user."""
    limiter = request.app.state.limiter
    _limit(
        limiter,
        "register",
        client_ip(request),
        settings.max_registrations_per_hour,
        3600,
        "For mange nye kontoer fra denne adressen. Prøv igjen om en time.",
    )
    user = users.create_user(conn, body.email, body.name, body.password, via=_channel(request))
    token, record = users.create_api_token(conn, user.id, body.token_name)
    base = base_url(request)
    return {"account": _account(conn, user), "token": _new_token(token, record, base)}


@router.post(
    "/auth/token", status_code=201, response_model=AuthOut, tags=["account"], summary="Log in, get a token"
)
def login(body: LoginIn, request: Request, conn: Conn, settings: SettingsDep) -> dict:
    _limit(
        request.app.state.limiter,
        "auth",
        client_ip(request),
        settings.rate_limit_auth_per_10min,
        600,
        "For mange innloggingsforsøk. Vent litt og prøv igjen.",
    )
    user = users.authenticate(conn, body.email, body.password)
    token, record = users.create_api_token(conn, user.id, body.token_name)
    return {"account": _account(conn, user), "token": _new_token(token, record, base_url(request))}


@router.get("/me", response_model=AccountOut, tags=["account"], summary="Your account")
def me(conn: Conn, user: CurrentUser) -> dict:
    return _account(conn, user)


@router.get("/me/listings", response_model=SearchOut, tags=["account"], summary="Your listings")
def my_listings(
    request: Request,
    conn: Conn,
    user: CurrentUser,
    status: Annotated[Literal["active", "sold", "inactive", "all"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """All your listings, including hidden ones."""
    params = SearchParams(
        user_id=user.id, status=status, include_hidden=True, sort="newest", limit=limit, offset=offset
    )
    return serializers.search_dict(listings.search(conn, params), base_url(request), None)


@router.get("/me/tokens", response_model=list[TokenOut], tags=["account"], summary="Your API tokens")
def list_tokens(conn: Conn, user: CurrentUser) -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "hint": t.hint,
            "created_at": t.created_at,
            "last_used_at": t.last_used_at,
        }
        for t in users.list_api_tokens(conn, user.id)
    ]


@router.post(
    "/me/tokens", status_code=201, response_model=NewTokenOut, tags=["account"], summary="New API token"
)
def create_token(body: TokenCreateIn, request: Request, conn: Conn, user: CurrentUser) -> dict:
    token, record = users.create_api_token(conn, user.id, body.name)
    return _new_token(token, record, base_url(request))


@router.delete("/me/tokens/{token_id}", status_code=204, tags=["account"], summary="Revoke an API token")
def revoke_token(token_id: int, conn: Conn, user: CurrentUser) -> Response:
    users.revoke_api_token(conn, user.id, token_id)
    return Response(status_code=204)


# --- Messages ---------------------------------------------------------------------------------


@router.get(
    "/conversations", response_model=list[ConversationOut], tags=["messages"], summary="Your conversations"
)
def list_conversations(
    request: Request, conn: Conn, user: CurrentUser, unread: Annotated[bool, Query()] = False
) -> list[dict]:
    base = base_url(request)
    return [
        serializers.conversation_dict(c, user.id, base, with_messages=False)
        for c in messages.list_conversations(conn, user.id, unread_only=unread)
    ]


@router.post(
    "/conversations",
    status_code=201,
    response_model=ConversationOut,
    tags=["messages"],
    summary="Contact a seller",
)
def contact_seller(
    body: ContactIn, request: Request, conn: Conn, user: CurrentUser, settings: SettingsDep
) -> dict:
    """Send a message about a listing. Reuses your existing conversation with the seller if there is one."""
    conversation_id = messages.contact_seller(
        conn,
        body.listing_id,
        user.id,
        body.message,
        via=_channel(request),
        max_per_day=settings.max_messages_per_day,
        new_account_max_per_day=settings.new_account_max_messages_per_day,
    )
    conversation = messages.get_conversation(conn, conversation_id, user.id)
    return serializers.conversation_dict(conversation, user.id, base_url(request), with_messages=True)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationOut,
    tags=["messages"],
    summary="Read a conversation",
)
def get_conversation(conversation_id: int, request: Request, conn: Conn, user: CurrentUser) -> dict:
    """All messages in the conversation. Marks incoming messages as read."""
    conversation = messages.get_conversation(conn, conversation_id, user.id)
    return serializers.conversation_dict(conversation, user.id, base_url(request), with_messages=True)


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=201,
    response_model=ConversationOut,
    tags=["messages"],
    summary="Reply in a conversation",
)
def reply(
    conversation_id: int,
    body: ReplyIn,
    request: Request,
    conn: Conn,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    messages.reply(
        conn,
        conversation_id,
        user.id,
        body.message,
        via=_channel(request),
        max_per_day=settings.max_messages_per_day,
        new_account_max_per_day=settings.new_account_max_messages_per_day,
    )
    conversation = messages.get_conversation(conn, conversation_id, user.id)
    return serializers.conversation_dict(conversation, user.id, base_url(request), with_messages=True)


@router.post(
    "/conversations/{conversation_id}/reports",
    status_code=202,
    response_model=ReportOut,
    tags=["messages"],
    summary="Report the other party",
)
def report_conversation(
    conversation_id: int, body: ReportIn, request: Request, conn: Conn, user: CurrentUser
) -> dict:
    """Report the other person in a conversation, e.g. for a fake payment link or a request for BankID codes."""
    conversation = messages.get_conversation(conn, conversation_id, user.id, mark_read=False)
    report_id = listings.create_report(
        conn,
        conversation.listing_id,
        body.reason,
        body.comment,
        user.id,
        via=_channel(request),
        reported_user_id=conversation.other_id(user.id),
        conversation_id=conversation.id,
    )
    return {"id": report_id, "status": "received"}


def _channel(request: Request) -> str:
    return getattr(request.state, "channel", "api")
