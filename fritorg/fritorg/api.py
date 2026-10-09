"""REST API v1. Reading never needs a key; writing needs a free personal token."""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import (
    favorites,
    identity,
    images,
    inventory,
    listings,
    messages,
    moderation,
    phone,
    privacy,
    ratings,
    saved_searches,
    serializers,
    taxonomy,
    users,
)
from .config import Settings
from .deps import base_url, client_ip, get_conn, get_settings, replace_params, url_with_query
from .errors import Conflict, Forbidden, NotFound, RateLimited, Unauthorized
from .listings import SORTS, SearchParams
from .mailer import notify_new_message, notify_rating, notify_trade, send_verification
from .ratelimit import RateLimiter
from .schemas import (
    AccountOut,
    AppealIn,
    AppealOut,
    AuthOut,
    BlockedOut,
    CategoryOut,
    ContactIn,
    ConversationOut,
    CountyOut,
    DeviceStartIn,
    DeviceStartOut,
    DeviceTokenIn,
    FavoritesOut,
    FeedOut,
    FeedSyncIn,
    FeedSyncOut,
    ImageUploadOut,
    ListingCreate,
    ListingOut,
    ListingUpdate,
    LoginIn,
    NewTokenOut,
    PhoneCodeIn,
    PhoneCodeOut,
    PhoneIn,
    Problem,
    RatingIn,
    RatingsOut,
    RegisterIn,
    ReplyIn,
    ReportIn,
    ReportOut,
    SavedSearchIn,
    SavedSearchOut,
    SavedSearchUpdate,
    SearchOut,
    TokenCreateIn,
    TokenOut,
    TradeOut,
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
    "Send 'Authorization: Bearer <token>'. To get one, start POST /api/v1/auth/device and give your user the link "
    "to approve (they log in, or create a free account), or ask them to create a token at /min-side."
)


def _bankid_only(request: Request) -> None:
    if request.app.state.settings.bankid_required:
        base = base_url(request)
        raise Forbidden(
            "Kontoer lages og brukes med BankID av personen selv.",
            hint=f"Start POST {base}/api/v1/auth/device and give your user the verification link; they log in "
            f"with BankID (creating a free account if needed) and approve. Or they create a token at {base}/min-side.",
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


def _account(conn: sqlite3.Connection, user: users.User, settings: Settings) -> dict:
    counts = {status: 0 for status in taxonomy.STATUSES}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM listings WHERE user_id = ? GROUP BY status", (user.id,)
    ):
        counts[row["status"]] = row["n"]
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "verified": user.is_verified,
        "verification": user.verification,
        "verification_required": phone.verification_needed(settings, user),
        "phone_hint": user.phone_hint,
        "email_verified": user.email_verified_at is not None,
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
    after_id: Annotated[
        int | None,
        Query(
            ge=0,
            le=2**63 - 1,
            description="Only listings added after this one (ids only grow). To follow new listings, poll with "
            "the highest id you have seen, or save the search: POST /api/v1/me/saved-searches.",
        ),
    ] = None,
    sort: Annotated[
        str | None,
        Query(
            description="Defaults to relevance with q, else newest.", json_schema_extra={"enum": list(SORTS)}
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=listings.MAX_OFFSET)] = 0,
) -> dict:
    """Search active listings. All filters combine with AND. For more than the first 25 000, use the export."""
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
        after_id=after_id,
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
    `moderation.reasons` explains why. Needs a verified mobile number (403 `verification_required`).
    """
    phone.ensure_verified(settings, user, base_url(request))
    listing_id = listings.create_listing(
        conn,
        user.id,
        body.model_dump(),
        via=_channel(request),
        max_per_day=settings.max_listings_per_day,
        new_account_max_per_day=settings.new_account_max_listings_per_day,
        active_days=settings.listing_days,
        reuse_recent=True,
    )
    base = base_url(request)
    response.headers["Location"] = f"{base}/api/v1/listings/{listing_id}"
    return serializers.listing_detail(listings.get_listing(conn, listing_id), base, owner_view=True)


@router.patch(
    "/listings/{listing_id}", response_model=ListingOut, tags=["listings"], summary="Update a listing"
)
def update_listing(
    listing_id: int,
    body: ListingUpdate,
    request: Request,
    conn: Conn,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    """Change some fields. Use status 'sold' when the item is sold and 'inactive' to hide it."""
    changes = body.model_dump(exclude_unset=True)
    if not _only_hides(changes):
        phone.ensure_verified(settings, user, base_url(request))
    listing = listings.update_listing(
        conn, user.id, listing_id, changes, is_admin=user.is_admin, active_days=settings.listing_days
    )
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
    phone.ensure_verified(settings, user, base_url(request))
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
    "/listings/{listing_id}/appeal",
    status_code=201,
    response_model=AppealOut,
    tags=["listings"],
    summary="Appeal a removal",
)
def appeal_removal(listing_id: int, body: AppealIn, request: Request, conn: Conn, user: CurrentUser) -> dict:
    """The owner of a listing a moderator removed asks for a new look, once per removal. A moderator either
    publishes it again or upholds the decision and answers by e-mail; `moderation.appeal` on the listing
    shows the status."""
    return serializers.appeal_dict(
        moderation.appeal(conn, user.id, listing_id, body.text, via=_channel(request))
    )


@router.post(
    "/listings/{listing_id}/reports",
    status_code=202,
    response_model=ReportOut,
    tags=["listings"],
    summary="Report a listing",
)
def report_listing(
    listing_id: int, body: ReportIn, request: Request, conn: Conn, user: OptionalUser, settings: SettingsDep
) -> dict:
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
        conn,
        listing_id,
        body.reason,
        body.comment,
        user.id if user else None,
        via=_channel(request),
        verified_only=listings.reports_need_verified(settings),
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
        "verified": user.is_verified,
        "verification": user.verification,
        "member_since": user.created_at,
        "active_listings": active,
        "url": f"{base_url(request)}/bruker/{user.id}",
        "rating": serializers.rating_summary_dict(ratings.summary(conn, user.id)),
    }


@router.get(
    "/users/{user_id}/ratings", response_model=RatingsOut, tags=["listings"], summary="Ratings of a user"
)
def user_ratings(user_id: int, conn: Conn) -> dict:
    """Ratings from people who traded with the user, newest first. A rating is shown when both in the trade
    have rated, or when the 14 days for rating are over."""
    if users.get_user(conn, user_id) is None:
        raise NotFound(f"Bruker {user_id} finnes ikke.")
    return {
        "summary": serializers.rating_summary_dict(ratings.summary(conn, user_id)),
        "items": [serializers.rating_dict(r) for r in ratings.ratings_for_user(conn, user_id)],
    }


@router.post(
    "/ratings/{rating_id}/reports",
    status_code=202,
    response_model=ReportOut,
    tags=["listings"],
    summary="Report a rating",
)
def report_rating(rating_id: int, body: ReportIn, request: Request, conn: Conn, user: CurrentUser) -> dict:
    """Flag a false or abusive rating for moderation."""
    _limit(
        request.app.state.limiter,
        "report",
        client_ip(request),
        20,
        3600,
        "For mange rapporter. Prøv igjen senere.",
    )
    report_id = ratings.report_rating(
        conn, rating_id, body.reason, body.comment, user.id, via=_channel(request)
    )
    return {"id": report_id, "status": "received"}


@router.get("/export/listings.ndjson", tags=["listings"], summary="Bulk export (NDJSON)")
def export_listings(request: Request) -> StreamingResponse:
    """Every active and sold listing as one JSON object per line. Use this instead of crawling page by page.

    Job ads imported from Nav (arbeidsplassen.no) are left out: their terms require removing ads at once
    when they end, which a copy cannot do. Get them from Nav's own open feed:
    https://navikt.github.io/pam-stilling-feed/ (they are in search results and listing pages here).
    """
    db = request.app.state.db
    base = base_url(request)

    def generate():
        with db.session() as conn:
            for listing in listings.iter_public_listings(conn, include_imported=False):
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
    """Create a free account with email and password and get an API token in one step.

    The account must then confirm a Norwegian mobile number (POST /api/v1/me/phone) before it can post or
    send messages. Not available on servers that use BankID: use the device flow there.
    """
    _bankid_only(request)
    limiter = request.app.state.limiter
    _limit(
        limiter,
        "register",
        client_ip(request),
        settings.max_registrations_per_hour,
        3600,
        "For mange nye kontoer fra denne adressen. Prøv igjen om en time.",
    )
    user = users.register(
        conn, limiter, client_ip(request), body.email, body.name, body.password, _channel(request)
    )
    token, record = users.create_api_token(conn, user.id, body.token_name)
    base = base_url(request)
    send_verification(
        request.app.state.mailer, request.app.state.secret_key, base, user.id, user.name, user.email
    )
    return {"account": _account(conn, user, settings), "token": _new_token(token, record, base)}


@router.post(
    "/auth/token", status_code=201, response_model=AuthOut, tags=["account"], summary="Log in, get a token"
)
def login(body: LoginIn, request: Request, conn: Conn, settings: SettingsDep) -> dict:
    """Get a token with email and password. Not available on servers that use BankID: use the device flow."""
    _bankid_only(request)
    _limit(
        request.app.state.limiter,
        "auth",
        client_ip(request),
        settings.rate_limit_auth_per_10min,
        600,
        "For mange innloggingsforsøk. Vent litt og prøv igjen.",
    )
    user = users.check_password(conn, request.app.state.limiter, body.email, body.password)
    token, record = users.create_api_token(conn, user.id, body.token_name)
    return {
        "account": _account(conn, user, request.app.state.settings),
        "token": _new_token(token, record, base_url(request)),
    }


@router.post(
    "/auth/device",
    status_code=201,
    response_model=DeviceStartOut,
    tags=["account"],
    summary="Ask a person for access (device flow)",
)
def device_start(body: DeviceStartIn, request: Request, conn: Conn) -> dict:
    """The easiest way for an agent to get a token (OAuth 2.0 device flow, RFC 8628).

    1. Call this endpoint. 2. Give your user `verification_uri_complete` (or the URL and `user_code`).
    They log in (or create a free account) and approve.
    3. Poll POST /api/v1/auth/device/token with the `device_code` every `interval` seconds.
    """
    _limit(
        request.app.state.limiter,
        "device",
        client_ip(request),
        30,
        3600,
        "For mange forespørsler. Prøv igjen senere.",
    )
    grant = identity.start_device_grant(conn, body.client_name)
    base = base_url(request)
    return {
        "device_code": grant.device_code,
        "user_code": grant.user_code,
        "verification_uri": f"{base}/koble-til",
        "verification_uri_complete": f"{base}/koble-til?kode={grant.user_code}",
        "expires_in": grant.expires_in,
        "interval": grant.interval,
    }


@router.post(
    "/auth/device/token",
    status_code=201,
    response_model=AuthOut,
    tags=["account"],
    summary="Poll for the token (device flow)",
)
def device_token(body: DeviceTokenIn, request: Request, conn: Conn) -> dict:
    """Returns the token once the person has approved. Until then: 400 with code `authorization_pending`
    (keep polling), `slow_down` (poll less often), `access_denied` or `expired_token` (start again)."""
    user_id = identity.poll_device_grant(conn, body.device_code)
    user = users.get_user(conn, user_id)
    if user is None or user.banned_at:
        raise Unauthorized("Kontoen finnes ikke lenger.")
    token, record = users.create_api_token(conn, user.id, identity.grant_client_name(conn, body.device_code))
    return {
        "account": _account(conn, user, request.app.state.settings),
        "token": _new_token(token, record, base_url(request)),
    }


@router.get("/me", response_model=AccountOut, tags=["account"], summary="Your account")
def me(conn: Conn, user: CurrentUser, settings: SettingsDep) -> dict:
    """Your account. If `verification_required` is true, verify a mobile number before posting or messaging."""
    return _account(conn, user, settings)


@router.put("/me/feeds/{feed}", response_model=FeedSyncOut, tags=["listings"], summary="Sync an inventory")
def sync_feed(
    feed: str, body: FeedSyncIn, request: Request, conn: Conn, user: CurrentUser, settings: SettingsDep
) -> dict:
    """For businesses: send everything that should be on Fritorg for one feed, each item with your own
    `external_id`. New items are created, changed ones updated, and (with `remove_missing`) items no longer
    in the list are deleted. Unchanged items are skipped, so repeat the same call as often as you like,
    e.g. every hour. Every sync keeps the listings active.

    Photos: upload them for new listings with POST /api/v1/listings/{id}/images (ids are in the response).
    """
    phone.ensure_verified(settings, user, base_url(request))
    items = [item.model_dump() for item in body.listings]
    result = inventory.sync(conn, settings, user, feed, items, remove_missing=body.remove_missing)
    return result.__dict__


@router.get("/me/feeds", response_model=list[FeedOut], tags=["listings"], summary="Your synced feeds")
def list_feeds(conn: Conn, user: CurrentUser) -> list[dict]:
    return inventory.feeds(conn, user.id)


@router.delete("/me/feeds/{feed}", status_code=204, tags=["listings"], summary="Delete a synced feed")
def delete_feed(feed: str, conn: Conn, user: CurrentUser, settings: SettingsDep) -> Response:
    """Delete every listing in the feed."""
    inventory.remove_feed(conn, settings, user, feed)
    return Response(status_code=204)


@router.get("/me/export", tags=["account"], summary="All your data (GDPR)")
def export_my_data(request: Request, conn: Conn, user: CurrentUser) -> JSONResponse:
    """Everything Fritorg stores about the account: profile, listings, conversations, tokens and reports."""
    data = privacy.export_user(conn, user, base_url(request))
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


def _sms_sender(request: Request) -> phone.SmsSender:
    sender = request.app.state.sms
    if sender is None:
        raise NotFound(
            "Bekreftelse med mobilnummer er ikke slått på her.",
            hint="This server does not verify phone numbers; no verification is needed.",
        )
    return sender


@router.post(
    "/me/phone",
    status_code=202,
    response_model=PhoneCodeOut,
    tags=["account"],
    summary="Verify your mobile number (1/2)",
)
def start_phone_verification(
    body: PhoneIn, request: Request, conn: Conn, user: CurrentUser, settings: SettingsDep
) -> dict:
    """Send a 6-digit code by SMS to the user's Norwegian mobile number.

    Every account must confirm a number before it can create listings or send messages, and each number can
    belong to one account only. Ask your user for their number, then for the code they receive.
    """
    sent = phone.start(
        conn,
        _sms_sender(request),
        request.app.state.secret_key,
        settings,
        user.id,
        body.phone,
        limiter=request.app.state.limiter,
        client_ip=client_ip(request),
    )
    return {
        "status": "code_sent",
        "phone_hint": sent.phone_hint,
        "expires_in": sent.expires_in,
        "next": f'Ask the user for the code and POST {base_url(request)}/api/v1/me/phone/verify with {{"code": "..."}}.',
        "test_code": sent.test_code,
    }


@router.post(
    "/me/phone/verify", response_model=AccountOut, tags=["account"], summary="Verify your mobile number (2/2)"
)
def confirm_phone_verification(
    body: PhoneCodeIn, request: Request, conn: Conn, user: CurrentUser, settings: SettingsDep
) -> dict:
    """Confirm the code from the SMS. Five wrong attempts invalidate the code."""
    _sms_sender(request)
    phone.confirm(conn, request.app.state.secret_key, user.id, body.code)
    verified = users.get_user(conn, user.id)
    if verified is None:
        raise Conflict("Kontoen finnes ikke lenger.")
    return _account(conn, verified, settings)


@router.get("/me/listings", response_model=SearchOut, tags=["account"], summary="Your listings")
def my_listings(
    request: Request,
    conn: Conn,
    user: CurrentUser,
    status: Annotated[Literal["active", "sold", "inactive", "all"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=listings.MAX_OFFSET)] = 0,
) -> dict:
    """All your listings, including hidden ones. `deletes_at` marks old listings about to be deleted automatically."""
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


# --- Blocking ------------------------------------------------------------------------------------


@router.get("/me/blocks", response_model=list[BlockedOut], tags=["messages"], summary="People you blocked")
def list_blocks(conn: Conn, user: CurrentUser) -> list[dict]:
    return [
        {"user_id": b["id"], "name": b["name"], "blocked_at": b["created_at"]}
        for b in messages.blocked_users(conn, user.id)
    ]


@router.put("/me/blocks/{user_id}", status_code=204, tags=["messages"], summary="Block someone")
def block_user(user_id: int, conn: Conn, user: CurrentUser) -> Response:
    """No messages either way until unblocked. The other person is not told."""
    messages.block(conn, user.id, user_id)
    return Response(status_code=204)


@router.delete("/me/blocks/{user_id}", status_code=204, tags=["messages"], summary="Unblock someone")
def unblock_user(user_id: int, conn: Conn, user: CurrentUser) -> Response:
    messages.unblock(conn, user.id, user_id)
    return Response(status_code=204)


# --- Favourites and saved searches ------------------------------------------------------------


@router.get("/me/favorites", response_model=FavoritesOut, tags=["account"], summary="Your favourites")
def list_favorites(
    request: Request,
    conn: Conn,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Listings the user has saved, most recently saved first. Sold ones stay until removed."""
    items, total = favorites.saved_listings(conn, user.id, limit, offset)
    base = base_url(request)
    return {"total": total, "items": [serializers.listing_summary(item, base) for item in items]}


@router.put("/me/favorites/{listing_id}", status_code=204, tags=["account"], summary="Save a listing")
def add_favorite(listing_id: int, conn: Conn, user: CurrentUser) -> Response:
    """Add a listing to the user's favourites (idempotent). Sellers see how many saved it, never who."""
    favorites.add(conn, user.id, listing_id)
    return Response(status_code=204)


@router.delete("/me/favorites/{listing_id}", status_code=204, tags=["account"], summary="Remove a favourite")
def remove_favorite(listing_id: int, conn: Conn, user: CurrentUser) -> Response:
    favorites.remove(conn, user.id, listing_id)
    return Response(status_code=204)


@router.get(
    "/me/saved-searches", response_model=list[SavedSearchOut], tags=["account"], summary="Your saved searches"
)
def list_saved_searches(request: Request, conn: Conn, user: CurrentUser) -> list[dict]:
    """Saved searches with the number of new matches since the user last looked."""
    base = base_url(request)
    return [serializers.saved_search_dict(saved, base) for saved in saved_searches.list_for(conn, user.id)]


@router.post(
    "/me/saved-searches",
    status_code=201,
    response_model=SavedSearchOut,
    tags=["account"],
    summary="Save a search",
)
def create_saved_search(
    body: SavedSearchIn, request: Request, response: Response, conn: Conn, user: CurrentUser
) -> dict:
    """Follow a search: new matches are counted from now, and with `notify` the user gets an e-mail about
    them (at most hourly, only to a verified address). Saving the same filters again returns the existing
    search (200)."""
    params = SearchParams(
        q=body.q,
        category=body.category,
        type=body.type,
        county=body.county,
        location=body.location,
        price_min=body.price_min,
        price_max=body.price_max,
        attrs=[listings.parse_attr_expression(expression) for expression in body.attr],
        user_id=body.seller_id,
        has_images=body.has_images,
    )
    notify = body.notify if "notify" in body.model_fields_set else None
    saved, created = saved_searches.create(conn, user.id, params, notify=notify)
    if not created:
        response.status_code = 200
    return serializers.saved_search_dict(saved, base_url(request))


@router.get(
    "/me/saved-searches/{search_id}/new",
    response_model=SearchOut,
    tags=["account"],
    summary="New matches of a saved search",
)
def saved_search_new_matches(
    search_id: int,
    request: Request,
    conn: Conn,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Listings published since the user last looked, newest first (drafts and listings that waited for
    review count from when they were published). Mark them as seen with PATCH {"seen": true}."""
    saved = saved_searches.get(conn, user.id, search_id)
    return serializers.search_dict(
        saved_searches.new_matches(conn, saved, limit=limit), base_url(request), None
    )


@router.patch(
    "/me/saved-searches/{search_id}",
    response_model=SavedSearchOut,
    tags=["account"],
    summary="Change a saved search",
)
def update_saved_search(
    search_id: int, body: SavedSearchUpdate, request: Request, conn: Conn, user: CurrentUser
) -> dict:
    saved = saved_searches.get(conn, user.id, search_id)
    if body.notify is not None:
        saved = saved_searches.set_notify(conn, user.id, search_id, body.notify)
    if body.seen:
        saved = saved_searches.mark_seen(conn, user.id, search_id)
    else:
        saved.new_count = saved_searches.new_matches(conn, saved, limit=1).total
    return serializers.saved_search_dict(saved, base_url(request))


@router.delete(
    "/me/saved-searches/{search_id}", status_code=204, tags=["account"], summary="Delete a saved search"
)
def delete_saved_search(search_id: int, conn: Conn, user: CurrentUser) -> Response:
    saved_searches.delete(conn, user.id, search_id)
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
    phone.ensure_verified(settings, user, base_url(request))
    sent = messages.contact_seller(
        conn,
        body.listing_id,
        user.id,
        body.message,
        via=_channel(request),
        max_per_day=settings.max_messages_per_day,
        new_account_max_per_day=settings.new_account_max_messages_per_day,
    )
    if not sent.repeated:
        notify_new_message(request.app.state.mailer, base_url(request), conn, sent.conversation_id, user.id)
    conversation = messages.get_conversation(conn, sent.conversation_id, user.id)
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


@router.delete(
    "/conversations/{conversation_id}", status_code=204, tags=["messages"], summary="Delete a conversation"
)
def delete_conversation(conversation_id: int, conn: Conn, user: CurrentUser) -> Response:
    """Delete the conversation from your inbox. The other person keeps their copy, and a new message from
    either of you brings it back. Once both have deleted it, it is deleted for good."""
    messages.hide_conversation(conn, conversation_id, user.id)
    return Response(status_code=204)


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
    phone.ensure_verified(settings, user, base_url(request))
    sent = messages.reply(
        conn,
        conversation_id,
        user.id,
        body.message,
        via=_channel(request),
        max_per_day=settings.max_messages_per_day,
        new_account_max_per_day=settings.new_account_max_messages_per_day,
    )
    if not sent.repeated:
        notify_new_message(request.app.state.mailer, base_url(request), conn, conversation_id, user.id)
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


@router.post(
    "/conversations/{conversation_id}/trade",
    status_code=201,
    response_model=TradeOut,
    tags=["messages"],
    summary="Record a trade",
)
def record_trade(
    conversation_id: int, request: Request, conn: Conn, user: CurrentUser, settings: SettingsDep
) -> dict:
    """The seller records that the listing went to the other person in the conversation (both must have
    written in it). The listing is marked as sold, and both may rate each other with POST /trades/{id}/rating.
    Recording it again returns the same trade."""
    trade, new = ratings.record_trade(conn, conversation_id, user.id, active_days=settings.listing_days)
    if new:
        notify_trade(
            request.app.state.mailer,
            base_url(request),
            conn,
            conversation_id,
            trade.seller_id,
            trade.buyer_id,
            trade.listing_title,
            ratings.RATE_DAYS,
        )
    return serializers.trade_dict(trade, user.id)


@router.get("/me/trades", response_model=list[TradeOut], tags=["account"], summary="Your trades and ratings")
def my_trades(conn: Conn, user: CurrentUser) -> list[dict]:
    """Trades you took part in, newest first. `can_rate` marks the ones you can still rate."""
    return [serializers.trade_dict(t, user.id) for t in ratings.trades_for_user(conn, user.id)]


@router.post(
    "/trades/{trade_id}/rating",
    status_code=201,
    response_model=TradeOut,
    tags=["account"],
    summary="Rate a trade",
)
def rate_trade(trade_id: int, body: RatingIn, request: Request, conn: Conn, user: CurrentUser) -> dict:
    """Rate the other person in a trade, once, within 14 days. The rating can't be changed. It is shown when
    both have rated, or when the 14 days are over, so neither answers a rating they have read."""
    trade = ratings.rate(conn, trade_id, user.id, body.score, body.comment, via=_channel(request))
    if not trade.they_rated:
        notify_rating(
            request.app.state.mailer,
            base_url(request),
            conn,
            trade.conversation_id,
            user.id,
            trade.other_id(user.id),
        )
    return serializers.trade_dict(trade, user.id)


def _channel(request: Request) -> str:
    return getattr(request.state, "channel", "api")


def _only_hides(changes: dict) -> bool:
    """Marking a listing as sold or hiding it is always allowed, even before verification."""
    return set(changes) <= {"status"} and changes.get("status") in ("sold", "inactive")
