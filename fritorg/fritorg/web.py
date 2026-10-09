"""HTML pages for people. Every page works without JavaScript, and key pages have
Markdown and JSON twins (`.md` / `.json` suffix or the Accept header) for agents."""

from __future__ import annotations

import hmac
import sqlite3
from typing import Annotated, Any
from urllib.parse import parse_qsl

import markdown
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.datastructures import FormData, UploadFile

from . import (
    alerts,
    discovery,
    favorites,
    images,
    listings,
    messages,
    moderation,
    phone,
    privacy,
    ratings,
    recovery,
    saved_searches,
    serializers,
    taxonomy,
    users,
)
from .deps import base_url, client_ip, get_conn, replace_params, url_with_query
from .errors import AppError, Conflict, Forbidden, NotFound, RateLimited, ValidationProblem
from .listings import SearchParams
from .mailer import (
    notify_appeal_upheld,
    notify_moderation,
    notify_new_message,
    notify_rating,
    notify_trade,
    send_verification,
    verify_email,
)
from .templating import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    current_user,
    redirect,
    render,
    render_error,
    safe_next,
)

router = APIRouter(include_in_schema=False)
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
PAGE_SIZE = 24
MAX_PAGE = 1000


async def get_form(request: Request) -> FormData:
    return await request.form(max_files=20, max_fields=200)


Form = Annotated[FormData, Depends(get_form)]


# --- Helpers -------------------------------------------------------------------------------------


def preferred_format(request: Request) -> str:
    """Pick html, json or markdown from the Accept header (browsers get HTML)."""
    best, best_q = "html", 0.0
    for part in request.headers.get("accept", "").split(","):
        media, _, params = part.strip().partition(";")
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        kind = {
            "text/html": "html",
            "application/xhtml+xml": "html",
            "application/json": "json",
            "text/markdown": "markdown",
            "text/x-markdown": "markdown",
        }.get(media.strip().lower())
        if kind and q > best_q:
            best, best_q = kind, q
    return best


def markdown_response(text: str) -> PlainTextResponse:
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8", headers={"Vary": "Accept"})


def json_response(data: Any) -> JSONResponse:
    return JSONResponse(data, headers={"Vary": "Accept"})


def check_csrf(request: Request, form: FormData) -> None:
    sent = str(form.get("csrf_token") or "")
    expected = request.cookies.get(CSRF_COOKIE, "")
    if not expected or not hmac.compare_digest(sent, expected):
        error = AppError("Skjemaet har utløpt. Gå tilbake, last inn siden på nytt og prøv igjen.")
        error.status, error.code = 403, "csrf_failed"
        raise error


def login_redirect(request: Request) -> Response:
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return redirect(url_with_query("", "/logg-inn", [("neste", target)]))


def must_verify(request: Request, user: users.User) -> bool:
    return phone.verification_needed(request.app.state.settings, user)


def verification_redirect(target: str) -> Response:
    return redirect(
        url_with_query("", "/verifiser-telefon", [("neste", target)]),
        flash="Bekreft mobilnummeret ditt først. Det tar under ett minutt.",
    )


def _problem_text(exc: AppError) -> str:
    """The message without the field prefix, for showing next to a form field."""
    if exc.errors and exc.errors[0].get("message"):
        return str(exc.errors[0]["message"])
    return exc.message


def _int_param(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def search_params_from_request(request: Request, limit: int = PAGE_SIZE) -> SearchParams:
    """Lenient parsing for web URLs: invalid values are ignored instead of failing the page."""
    params = listings.params_from_query(request.query_params.multi_items(), limit=limit)
    page = min(max(1, _int_param(request.query_params.get("side")) or 1), MAX_PAGE)
    params.offset = (page - 1) * limit
    return params


def api_query(params: SearchParams) -> list[tuple[str, str]]:
    """The equivalent /api/v1/listings query for a search (used in <link rel=alternate>)."""
    items: list[tuple[str, str]] = []
    for key in ("q", "category", "type", "county", "location", "price_min", "price_max", "sort"):
        value = getattr(params, key)
        if value not in (None, ""):
            items.append((key, str(value)))
    items += [("attr", f.to_expression()) for f in params.attrs]
    if params.user_id:
        items.append(("seller_id", str(params.user_id)))
    if params.status != "active":
        items.append(("status", params.status))
    return items


# --- Home and search -----------------------------------------------------------------------------


@router.get("/")
def home(request: Request, conn: Conn) -> Response:
    recent = discovery.recent_listings(conn, 12)
    counts = listings.category_counts(conn)
    if preferred_format(request) == "markdown":
        return home_markdown(request, conn)
    base = base_url(request)
    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": request.app.state.settings.site_name,
        "url": f"{base}/",
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{base}/sok?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }
    jobs = listings.search(conn, SearchParams(category="jobb", sort="newest", limit=8), count=False)
    return render(
        request,
        conn,
        "index.html",
        {
            "recent": recent.items,
            "jobs": jobs.items,
            "jobs_total": counts.get("jobb", 0),
            "counts": counts,
            "total": sum(counts.get(group, 0) for group in taxonomy.GROUPS),
            "website_jsonld": serializers.jsonld_script(website),
        },
    )


@router.get("/index.md")
def home_markdown(request: Request, conn: Conn) -> Response:
    base = base_url(request)
    counts = listings.category_counts(conn)
    recent = discovery.recent_listings(conn, 20)
    lines = [discovery.render_doc(request, "home.md").rstrip(), "", "## Kategorier", ""]
    for group_slug in taxonomy.GROUPS:
        group = taxonomy.CATEGORIES[group_slug]
        lines.append(
            f"- [{group.name}]({base}/sok?category={group.slug}) ({counts.get(group.slug, 0)} annonser)"
        )
        for child_slug in group.children:
            child = taxonomy.CATEGORIES[child_slug]
            lines.append(
                f"  - [{child.name}]({base}/sok?category={child.slug}) ({counts.get(child.slug, 0)})"
            )
    lines += ["", "## Nyeste annonser", ""]
    for item in recent.items:
        lines.append(
            f"- [{item.title}]({base}/annonse/{item.id}) — {item.price_text() or item.type_label}, {item.place}"
        )
    return markdown_response("\n".join(lines) + "\n")


def _search_title(params: SearchParams) -> str:
    """A heading that reads well and works as a page title: "Bil i Oslo", "«sofa» i Møbler og interiør"."""
    category = taxonomy.CATEGORIES[params.category].name if params.category else None
    county = taxonomy.COUNTIES[params.county].name if params.county else None
    if params.q:
        places = [part for part in (category, county) if part]
        return f"«{params.q}» i {', '.join(places)}" if places else f"Søk etter «{params.q}»"
    if category:
        return f"{category} i {county}" if county else category
    return f"Annonser i {county}" if county else "Alle annonser"


@router.get("/sok")
def search_page(request: Request, conn: Conn) -> Response:
    return _search(request, conn, preferred_format(request))


@router.get("/sok.md")
def search_markdown(request: Request, conn: Conn) -> Response:
    return _search(request, conn, "markdown")


@router.get("/sok.json")
def search_json(request: Request, conn: Conn) -> Response:
    return _search(request, conn, "json")


def _search(request: Request, conn: sqlite3.Connection, fmt: str) -> Response:
    params = search_params_from_request(request)
    try:
        result = listings.search(conn, params)
    except ValidationProblem:
        params = SearchParams(q=params.q, limit=PAGE_SIZE)
        result = listings.search(conn, params)
    base = base_url(request)
    page = params.offset // params.limit + 1
    next_url = None
    if result.has_more and page < MAX_PAGE:
        next_url = url_with_query(base, request.url.path, replace_params(request, side=page + 1))
    title = _search_title(params)
    if fmt == "json":
        return json_response(serializers.search_dict(result, base, next_url))
    query = url_with_query("", "", api_query(params)).lstrip("?")
    api_url = f"/api/v1/listings?{query}" if query else "/api/v1/listings"
    if fmt == "markdown":
        return markdown_response(serializers.search_markdown(result, base, title, next_url, base + api_url))

    category = taxonomy.get_category(params.category)
    leaf = category if category and category.is_leaf else None
    selected_attrs: dict[str, Any] = {}
    for flt in params.attrs:
        if flt.values:
            selected_attrs[flt.key] = flt.values[0]
        if flt.min is not None:
            selected_attrs[f"{flt.key}.min"] = flt.min
        if flt.max is not None:
            selected_attrs[f"{flt.key}.max"] = flt.max
    pages = max(1, -(-result.total // params.limit), page + 1 if next_url else page)
    user = current_user(request, conn)
    save_query = saved_searches.canonical_query(params)
    return render(
        request,
        conn,
        "search.html",
        {
            "save_query": save_query,
            "filter_count": sum(
                1
                for value in (
                    params.category,
                    params.type,
                    params.county,
                    params.location,
                    params.price_min,
                    params.price_max,
                )
                if value not in (None, "")
            )
            + len(params.attrs)
            + params.has_images
            + (params.status != "active"),
            "saved_search": saved_searches.find(conn, user.id, params) if user and save_query else None,
            "new_after": _int_param(request.query_params.get("nye")),
            "result": result,
            "params": params,
            "header_q": params.q,
            "title": title,
            "category": category,
            "leaf": leaf,
            "selected_attrs": selected_attrs,
            "page": page,
            "pages": min(pages, MAX_PAGE),
            "page_url": lambda n: url_with_query(
                "", "/sok", replace_params(request, side=n if n > 1 else None)
            ),
            "sort_url": lambda s: url_with_query("", "/sok", replace_params(request, sort=s, side=None)),
            "api_url": api_url,
            "feed_url": f"/feed.atom?{request.url.query}" if request.url.query else "/feed.atom",
            "md_url": f"/sok.md?{request.url.query}" if request.url.query else "/sok.md",
            "counts": listings.category_counts(conn),
        },
    )


# --- Listing pages ------------------------------------------------------------------------------


def _viewer(request: Request, conn: sqlite3.Connection) -> tuple[int | None, bool]:
    user = current_user(request, conn)
    return (user.id if user else None), bool(user and user.is_admin)


@router.get("/annonse/{listing_id:int}.json")
def listing_json(listing_id: int, request: Request, conn: Conn) -> Response:
    viewer, admin = _viewer(request, conn)
    listing = listings.get_visible_listing(conn, listing_id, viewer, admin)
    return json_response(serializers.listing_detail(listing, base_url(request)))


@router.get("/annonse/{listing_id:int}.md")
def listing_markdown(listing_id: int, request: Request, conn: Conn) -> Response:
    viewer, admin = _viewer(request, conn)
    listing = listings.get_visible_listing(conn, listing_id, viewer, admin)
    return markdown_response(serializers.listing_markdown(listing, base_url(request)))


@router.get("/annonse/{listing_id:int}")
def listing_page(listing_id: int, request: Request, conn: Conn) -> Response:
    viewer, admin = _viewer(request, conn)
    listing = listings.get_visible_listing(conn, listing_id, viewer, admin)
    fmt = preferred_format(request)
    base = base_url(request)
    if fmt == "json":
        return json_response(serializers.listing_detail(listing, base))
    if fmt == "markdown":
        return markdown_response(serializers.listing_markdown(listing, base))
    conversation_id = None
    if viewer and viewer != listing.user_id:
        row = conn.execute(
            "SELECT id FROM conversations WHERE listing_id = ? AND buyer_id = ?", (listing.id, viewer)
        ).fetchone()
        conversation_id = row["id"] if row else None
    more = (
        []
        if listing.is_imported
        else listings.search(conn, SearchParams(user_id=listing.user_id, limit=5), count=False).items
    )
    is_owner = viewer == listing.user_id
    counter = request.app.state.views
    if not is_owner and listing.is_public:
        counter.add(listing.id, client_ip(request), request.headers.get("user-agent", ""))
    return render(
        request,
        conn,
        "listing.html",
        {
            "listing": listing,
            "is_owner": is_owner,
            "is_admin": admin,
            "conversation_id": conversation_id,
            "favorite_count": favorites.count_for(conn, listing.id) if is_owner else 0,
            "views": listing.views + counter.pending(listing.id) if is_owner else 0,
            "response_time": None
            if listing.is_imported
            else messages.response_time_text(messages.response_time_hours(conn, listing.user_id)),
            "jsonld": serializers.jsonld_script(serializers.listing_jsonld(listing, base)),
            "breadcrumbs_jsonld": serializers.jsonld_script(serializers.breadcrumbs_jsonld(listing, base)),
            "more_from_seller": [item for item in more if item.id != listing.id][:4],
            "similar": _similar(conn, listing),
        },
        headers={"Vary": "Accept"},
    )


def _similar(conn: sqlite3.Connection, listing: listings.Listing, count: int = 4) -> list[listings.Listing]:
    """Other active listings in the same category, nearby first. The seller's own are shown separately."""
    if not listing.is_public:
        return []
    found: list[listings.Listing] = []
    searches = [SearchParams(category=listing.category, limit=count + 5)]
    if listing.county:
        searches.insert(0, SearchParams(category=listing.category, county=listing.county, limit=count + 5))
    for params in searches:
        for item in listings.search(conn, params, count=False).items:
            same_seller = item.user_id == listing.user_id and not listing.is_imported
            if item.id != listing.id and not same_seller and item.id not in {f.id for f in found}:
                found.append(item)
        if len(found) >= count:
            break
    return found[:count]


@router.post("/annonse/{listing_id:int}/melding")
def contact_seller(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return redirect(f"/logg-inn?neste=/annonse/{listing_id}")
    if must_verify(request, user):
        return verification_redirect(f"/annonse/{listing_id}#kontakt")
    settings = request.app.state.settings
    try:
        sent = messages.contact_seller(
            conn,
            listing_id,
            user.id,
            str(form.get("message") or ""),
            max_per_day=settings.max_messages_per_day,
            new_account_max_per_day=settings.new_account_max_messages_per_day,
        )
    except (ValidationProblem, RateLimited, Forbidden) as exc:
        return redirect(f"/annonse/{listing_id}#kontakt", flash=exc.message)
    if not sent.repeated:
        notify_new_message(request.app.state.mailer, base_url(request), conn, sent.conversation_id, user.id)
    return redirect(f"/meldinger/{sent.conversation_id}", flash="Meldingen er sendt.")


@router.post("/annonse/{listing_id:int}/rapporter")
def report_listing(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    decision = request.app.state.limiter.hit("report", client_ip(request), 20, 3600)
    if not decision.allowed:
        raise RateLimited("For mange rapporter. Prøv igjen senere.", retry_after=decision.reset_in)
    user = current_user(request, conn)
    try:
        listings.create_report(
            conn,
            listing_id,
            str(form.get("reason") or ""),
            str(form.get("comment") or ""),
            user.id if user else None,
            verified_only=listings.reports_need_verified(request.app.state.settings),
        )
    except (ValidationProblem, RateLimited) as exc:
        return redirect(f"/annonse/{listing_id}", flash=exc.message)
    return redirect(f"/annonse/{listing_id}", flash="Takk! Vi ser på annonsen.")


@router.post("/annonse/{listing_id:int}/status")
def change_status(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    status = str(form.get("status") or "")
    if status == "active" and must_verify(request, user):
        return verification_redirect(f"/annonse/{listing_id}")
    days = request.app.state.settings.listing_days
    listings.set_status(conn, user.id, listing_id, status, is_admin=user.is_admin, active_days=days)
    labels = {
        "sold": f"Annonsen er merket som {listings.get_listing(conn, listing_id).shown_status.lower()}.",
        "inactive": "Annonsen er skjult.",
        "active": f"Annonsen er aktiv de neste {days} dagene." if days else "Annonsen er aktiv.",
    }
    return redirect(
        safe_next(str(form.get("neste") or ""), f"/annonse/{listing_id}"), flash=labels.get(status)
    )


@router.post("/annonse/{listing_id:int}/klage")
def appeal_removal(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    try:
        moderation.appeal(conn, user.id, listing_id, str(form.get("text") or ""))
    except (ValidationProblem, Forbidden) as exc:
        return redirect(f"/annonse/{listing_id}#klage", flash=exc.message)
    return redirect(
        f"/annonse/{listing_id}",
        flash="Klagen er sendt. En moderator ser på saken på nytt og svarer på e-post.",
    )


@router.post("/annonse/{listing_id:int}/slett")
def delete_listing(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    filenames = listings.delete_listing(conn, user.id, listing_id, is_admin=user.is_admin)
    images.remove_files(request.app.state.settings.uploads_dir, filenames)
    return redirect("/min-side", flash="Annonsen er slettet.")


# --- Create and edit -----------------------------------------------------------------------------


def _form_values(form: FormData, category: taxonomy.Category) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for attr in category.attributes:
        raw = form.get(f"attr.{attr.key}")
        if attr.type == "boolean":
            if raw:
                attributes[attr.key] = True
        elif isinstance(raw, str) and raw.strip():
            attributes[attr.key] = raw
    return {
        "category": category.slug,
        "type": str(form.get("type") or "") or None,
        "title": str(form.get("title") or ""),
        "description": str(form.get("description") or ""),
        "price": str(form.get("price") or "") or None,
        "price_unit": str(form.get("price_unit") or "total"),
        "county": str(form.get("county") or "") or None,
        "location": str(form.get("location") or ""),
        "postal_code": str(form.get("postal_code") or ""),
        "attributes": attributes,
    }


def _errors_by_field(exc: ValidationProblem) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors:
        errors.setdefault(str(error.get("field", "")), str(error.get("message", "")))
    return errors


def _listing_form(
    request: Request,
    conn: sqlite3.Connection,
    category: taxonomy.Category,
    values: dict[str, Any],
    errors: dict[str, str] | None = None,
    listing: listings.Listing | None = None,
    status: int = 200,
) -> Response:
    return render(
        request,
        conn,
        "listing_form.html",
        {"category": category, "values": values, "errors": errors or {}, "listing": listing},
        status=status,
    )


def _upload_images(
    request: Request,
    conn: sqlite3.Connection,
    user: users.User,
    listing_id: int,
    uploads: list[Any],
    alt: str,
) -> list[str]:
    settings = request.app.state.settings
    problems = []
    for upload in uploads:
        if not isinstance(upload, UploadFile) or not upload.filename:
            continue
        data = upload.file.read(settings.max_image_bytes + 1)
        try:
            images.add_image(
                conn,
                settings.uploads_dir,
                user.id,
                listing_id,
                data,
                alt_text=alt,
                max_bytes=settings.max_image_bytes,
                max_images=settings.max_images_per_listing,
                is_admin=user.is_admin,
            )
        except AppError as exc:
            problems.append(f"{upload.filename}: {exc.message}")
    return problems


@router.get("/ny-annonse")
def new_listing(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    if must_verify(request, user):
        return verification_redirect(
            request.url.path + (f"?{request.url.query}" if request.url.query else "")
        )
    category = taxonomy.get_category(request.query_params.get("category"))
    if category is None or not category.is_leaf:
        return render(request, conn, "choose_category.html", {"selected_group": category})
    values = {
        "category": category.slug,
        "type": request.query_params.get("type") or category.types[0],
        "attributes": {},
    }
    return _listing_form(request, conn, category, values)


@router.post("/ny-annonse")
def create_listing(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    if must_verify(request, user):
        return verification_redirect("/ny-annonse")
    category = taxonomy.get_category(str(form.get("category") or ""))
    if category is None or not category.is_leaf:
        return redirect("/ny-annonse", flash="Velg en kategori først.")
    values = _form_values(form, category)
    settings = request.app.state.settings
    try:
        listing_id = listings.create_listing(
            conn,
            user.id,
            values,
            max_per_day=settings.max_listings_per_day,
            new_account_max_per_day=settings.new_account_max_listings_per_day,
            active_days=settings.listing_days,
            reuse_recent=True,
        )
    except ValidationProblem as exc:
        return _listing_form(request, conn, category, values, _errors_by_field(exc), status=422)
    problems = _upload_images(request, conn, user, listing_id, form.getlist("images"), values["title"])
    if listings.get_listing(conn, listing_id).status == "review":
        message = "Takk! Annonsen blir publisert så snart en moderator har sett på den."
    else:
        message = "Annonsen er publisert!"
    if problems:
        message += " Noen bilder ble ikke lagt til: " + "; ".join(problems)
    return redirect(f"/annonse/{listing_id}", flash=message)


def _own_listing(
    request: Request, conn: sqlite3.Connection, listing_id: int
) -> tuple[users.User, listings.Listing]:
    user = current_user(request, conn)
    if user is None:
        raise AppError("Du må logge inn.")
    listing = listings.get_listing(conn, listing_id)
    if listing.user_id != user.id and not user.is_admin:
        raise NotFound(f"Annonse {listing_id} finnes ikke.")
    return user, listing


@router.get("/annonse/{listing_id:int}/rediger")
def edit_listing(listing_id: int, request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    if must_verify(request, user):
        return verification_redirect(f"/annonse/{listing_id}/rediger")
    owner, listing = _own_listing(request, conn, listing_id)
    if listing.status == "removed" and not owner.is_admin:
        flash = "Annonsen er fjernet av en moderator og kan ikke endres."
        if listing.can_appeal:
            flash += " Du kan klage på avgjørelsen."
        return redirect(f"/annonse/{listing_id}#klage", flash=flash)
    values = {name: getattr(listing, name) for name in listings.EDITABLE_FIELDS}
    return _listing_form(request, conn, listing.category_obj, values, listing=listing)


@router.post("/annonse/{listing_id:int}/rediger")
def update_listing(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    viewer = current_user(request, conn)
    if viewer is None:
        return login_redirect(request)
    if must_verify(request, viewer):
        return verification_redirect(f"/annonse/{listing_id}/rediger")
    user, listing = _own_listing(request, conn, listing_id)
    category = taxonomy.get_category(str(form.get("category") or "")) or listing.category_obj
    if not category.is_leaf:
        category = listing.category_obj
    values = _form_values(form, category)
    try:
        updated = listings.update_listing(
            conn,
            user.id,
            listing_id,
            values,
            merge_attributes=False,
            is_admin=user.is_admin,
            active_days=request.app.state.settings.listing_days,
        )
    except ValidationProblem as exc:
        return _listing_form(
            request, conn, category, values, _errors_by_field(exc), listing=listing, status=422
        )
    flash = "Endringene er lagret."
    if updated.status == "review" and listing.status != "review":
        flash += " Annonsen er sendt til kontroll hos en moderator før den blir synlig igjen."
    return redirect(f"/annonse/{listing_id}", flash=flash)


@router.post("/annonse/{listing_id:int}/bilder")
def upload_images(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    viewer = current_user(request, conn)
    if viewer is None:
        return login_redirect(request)
    if must_verify(request, viewer):
        return verification_redirect(f"/annonse/{listing_id}/rediger")
    user, listing = _own_listing(request, conn, listing_id)
    alt = str(form.get("alt_text") or "") or listing.title
    problems = _upload_images(request, conn, user, listing_id, form.getlist("images"), alt)
    flash = (
        "Bildene er lagt til." if not problems else "Noen bilder ble ikke lagt til: " + "; ".join(problems)
    )
    if listing.status != "review" and listings.get_listing(conn, listing_id).status == "review":
        flash += " Annonsen er sendt til kontroll hos en moderator."
    return redirect(f"/annonse/{listing_id}/rediger#bilder", flash=flash)


def _photo_link_listing(request: Request, conn: sqlite3.Connection, listing_id: int, token: str):
    """The listing and its owner for a photo link (images.photo_link_token), or the error page to show."""
    listing = listings.get_listing(conn, listing_id)
    owner = users.get_user(conn, listing.user_id)
    if owner is None or not images.photo_link_valid(
        request.app.state.secret_key, token, listing.id, owner.id
    ):
        return render_error(
            request,
            403,
            "Lenken er utløpt eller ugyldig. Be assistenten om en ny lenke, eller legg til bildene under "
            "«Rediger annonsen» når du er logget inn.",
        )
    if listing.status == "removed" or listing.is_imported:
        return render_error(request, 403, "Denne annonsen kan ikke få flere bilder.")
    return listing, owner


@router.get("/annonse/{listing_id:int}/bilder")
def photo_link_page(listing_id: int, request: Request, conn: Conn) -> Response:
    token = request.query_params.get("t", "")
    found = _photo_link_listing(request, conn, listing_id, token)
    if isinstance(found, Response):
        return found
    listing, _ = found
    response = render(
        request,
        conn,
        "photo_upload.html",
        {"listing": listing, "token": token, "max_images": request.app.state.settings.max_images_per_listing},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"  # the link works like a key
    return response


@router.post("/annonse/{listing_id:int}/bilder/lenke")
def photo_link_upload(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    token = str(form.get("t") or "")
    found = _photo_link_listing(request, conn, listing_id, token)
    if isinstance(found, Response):
        return found
    listing, owner = found
    problems = _upload_images(request, conn, owner, listing.id, form.getlist("images"), listing.title)
    flash = (
        "Bildene er lagt til." if not problems else "Noen bilder ble ikke lagt til: " + "; ".join(problems)
    )
    return redirect(url_with_query("", f"/annonse/{listing.id}/bilder", [("t", token)]), flash=flash)


@router.post("/annonse/{listing_id:int}/bilder/{image_id:int}/hovedbilde")
def make_main_image(listing_id: int, image_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    images.make_main(conn, user.id, listing_id, image_id, is_admin=user.is_admin)
    return redirect(f"/annonse/{listing_id}/rediger#bilder", flash="Hovedbildet er byttet.")


@router.post("/annonse/{listing_id:int}/bilder/{image_id:int}/slett")
def delete_image(listing_id: int, image_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    if current_user(request, conn) is None:
        return login_redirect(request)
    user, _ = _own_listing(request, conn, listing_id)
    images.delete_image(
        conn, request.app.state.settings.uploads_dir, user.id, listing_id, image_id, is_admin=user.is_admin
    )
    return redirect(f"/annonse/{listing_id}/rediger#bilder", flash="Bildet er fjernet.")


# --- Messages -----------------------------------------------------------------------------------


@router.get("/meldinger")
def inbox(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    return render(request, conn, "inbox.html", {"conversations": messages.list_conversations(conn, user.id)})


@router.get("/meldinger/{conversation_id:int}")
def conversation_page(conversation_id: int, request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    conversation = messages.get_conversation(conn, conversation_id, user.id)
    other = conversation.other_id(user.id)
    quick_replies: tuple[str, ...] = ()
    trade_button = trade_done = None
    if conversation.role(user.id) == "seller" and conversation.listing_id:
        listing = conn.execute(
            "SELECT type, status FROM listings WHERE id = ?", (conversation.listing_id,)
        ).fetchone()
        if listing and listing["status"] in ("active", "sold", "inactive"):
            words = listings.TYPE_WORDS.get(listing["type"], listings.TYPE_WORDS["sell"])
            quick_replies = words.replies
            if words.traded:
                trade_button = words.traded.format(name=conversation.other_name(user.id))
                trade_done = words.done.lower()
    trade = ratings.trade_for_conversation(conn, conversation_id, user.id)
    return render(
        request,
        conn,
        "conversation.html",
        {
            "conversation": conversation,
            "blocked_by_me": messages.has_blocked(conn, user.id, other),
            "blocked_me": messages.has_blocked(conn, other, user.id),
            "quick_replies": quick_replies,
            "trade": trade,
            "trade_button": trade_button
            if trade is None and ratings.tradeable(conn, conversation, user.id)
            else None,
            "trade_done": trade_done,
        },
    )


@router.post("/meldinger/{conversation_id:int}/handel")
def record_trade(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    settings = request.app.state.settings
    try:
        trade, new = ratings.record_trade(conn, conversation_id, user.id, active_days=settings.listing_days)
    except (ValidationProblem, Forbidden) as exc:
        return redirect(f"/meldinger/{conversation_id}", flash=exc.message)
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
    return redirect(
        f"/meldinger/{conversation_id}#vurdering",
        flash="Handelen er registrert. Nå kan dere gi hverandre en vurdering.",
    )


@router.post("/meldinger/{conversation_id:int}/vurdering")
def rate_trade(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    trade = ratings.trade_for_conversation(conn, conversation_id, user.id)
    if trade is None:
        raise NotFound(f"Samtale {conversation_id} har ingen registrert handel.")
    score = str(form.get("score") or "")
    try:
        trade = ratings.rate(
            conn, trade.id, user.id, int(score) if score.isdecimal() else 0, str(form.get("comment") or "")
        )
    except ValidationProblem as exc:
        return redirect(f"/meldinger/{conversation_id}#vurdering", flash=exc.message)
    if not trade.they_rated:
        notify_rating(
            request.app.state.mailer,
            base_url(request),
            conn,
            conversation_id,
            user.id,
            trade.other_id(user.id),
        )
    return redirect(f"/meldinger/{conversation_id}#vurdering", flash="Takk for vurderingen!")


@router.post("/meldinger/{conversation_id:int}/blokker")
def block_in_conversation(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    conversation = messages.get_conversation(conn, conversation_id, user.id, mark_read=False)
    messages.block(conn, user.id, conversation.other_id(user.id))
    name = conversation.other_name(user.id)
    return redirect(
        f"/meldinger/{conversation_id}",
        flash=f"{name} er blokkert. Dere kan ikke sende meldinger til hverandre. Svindel? Rapporter også gjerne.",
    )


@router.post("/meldinger/{conversation_id:int}/opphev-blokkering")
def unblock_in_conversation(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    conversation = messages.get_conversation(conn, conversation_id, user.id, mark_read=False)
    messages.unblock(conn, user.id, conversation.other_id(user.id))
    return redirect(f"/meldinger/{conversation_id}", flash="Blokkeringen er opphevet.")


@router.post("/min-side/blokkert/{blocked_id:int}/opphev")
def unblock_user(blocked_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    messages.unblock(conn, user.id, blocked_id)
    return redirect("/min-side#blokkert", flash="Blokkeringen er opphevet.")


@router.post("/meldinger/{conversation_id:int}")
def reply(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    if must_verify(request, user):
        return verification_redirect(f"/meldinger/{conversation_id}")
    settings = request.app.state.settings
    try:
        sent = messages.reply(
            conn,
            conversation_id,
            user.id,
            str(form.get("message") or ""),
            max_per_day=settings.max_messages_per_day,
            new_account_max_per_day=settings.new_account_max_messages_per_day,
        )
    except (ValidationProblem, RateLimited, Forbidden) as exc:
        return redirect(f"/meldinger/{conversation_id}", flash=exc.message)
    if not sent.repeated:
        notify_new_message(request.app.state.mailer, base_url(request), conn, conversation_id, user.id)
    return redirect(f"/meldinger/{conversation_id}#siste")


@router.post("/meldinger/{conversation_id:int}/slett")
def delete_conversation(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    messages.hide_conversation(conn, conversation_id, user.id)
    return redirect("/meldinger", flash="Samtalen er slettet fra innboksen din.")


@router.post("/meldinger/{conversation_id:int}/rapporter")
def report_conversation(conversation_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    conversation = messages.get_conversation(conn, conversation_id, user.id, mark_read=False)
    listings.create_report(
        conn,
        conversation.listing_id,
        str(form.get("reason") or "fraud"),
        str(form.get("comment") or ""),
        user.id,
        reported_user_id=conversation.other_id(user.id),
        conversation_id=conversation.id,
    )
    return redirect(f"/meldinger/{conversation_id}", flash="Takk! En moderator ser på saken.")


# --- Favourites and saved searches ------------------------------------------------------------


@router.post("/annonse/{listing_id:int}/favoritt")
def toggle_favorite(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return redirect(url_with_query("", "/logg-inn", [("neste", f"/annonse/{listing_id}")]))
    target = safe_next(str(form.get("neste") or ""), f"/annonse/{listing_id}")
    if form.get("action") == "remove":
        favorites.remove(conn, user.id, listing_id)
        return redirect(target, flash="Fjernet fra favorittene.")
    try:
        favorites.add(conn, user.id, listing_id)
    except ValidationProblem as exc:
        return redirect(target, flash=exc.message)
    return redirect(target, flash="Lagret i favorittene dine.")


@router.get("/favoritter")
def favorites_page(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    page = min(max(1, _int_param(request.query_params.get("side")) or 1), MAX_PAGE)
    items, total = favorites.saved_listings(conn, user.id, PAGE_SIZE * 2, (page - 1) * PAGE_SIZE * 2)
    return render(
        request,
        conn,
        "favorites.html",
        {
            "mail_enabled": request.app.state.mailer.enabled,
            "items": items,
            "total": total,
            "page": page,
            "pages": max(1, -(-total // (PAGE_SIZE * 2))),
            "page_url": lambda n: "/favoritter" + (f"?side={n}" if n > 1 else ""),
        },
    )


@router.post("/favoritter/varsel")
def favorite_price_alerts(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    on = form.get("price_alerts") == "1"
    conn.execute("UPDATE users SET price_alerts = ? WHERE id = ?", (int(on), user.id))
    return redirect(
        "/favoritter",
        flash="Du får e-post når prisen settes ned." if on else "E-post om prisendringer er slått av.",
    )


@router.post("/lagrede-sok")
def save_search(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    params = listings.params_from_query(parse_qsl(str(form.get("query") or "")))
    query = saved_searches.canonical_query(params)
    back = f"/sok?{query}" if query else "/sok"
    user = current_user(request, conn)
    if user is None:
        return redirect(url_with_query("", "/logg-inn", [("neste", back)]))
    try:
        _, created = saved_searches.create(conn, user.id, params)
    except ValidationProblem as exc:
        return redirect(back, flash=_problem_text(exc))
    if not created:
        flash = "Du har allerede lagret dette søket."
    elif not request.app.state.mailer.enabled:
        flash = "Søket er lagret. Nye treff ser du under Lagrede søk."
    elif user.email_verified_at:
        flash = "Søket er lagret. Du får e-post når det kommer nye treff."
    else:
        flash = "Søket er lagret. Bekreft e-postadressen din på Min side for å få nye treff på e-post."
    return redirect(back, flash=flash)


@router.get("/lagrede-sok")
def saved_searches_page(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    return render(
        request,
        conn,
        "saved_searches.html",
        {
            "searches": saved_searches.list_for(conn, user.id),
            "mail_enabled": request.app.state.mailer.enabled,
            "max_saved": saved_searches.MAX_SAVED,
        },
    )


@router.get("/varsler/av")
def unsubscribe_page(request: Request, conn: Conn) -> Response:
    """From the link in an alert e-mail: confirm turning alerts off (works without logging in)."""
    token = request.query_params.get("token", "")
    target = alerts.unsubscribe_target(conn, request.app.state.secret_key, token)
    return render(
        request,
        conn,
        "unsubscribe.html",
        {"token": token, "target": target[2] if target else None, "done": False},
        status=200 if target else 404,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/varsler/av")
def unsubscribe(request: Request, conn: Conn, form: Form) -> Response:
    """Turn alerts off. Also the one-click target of the List-Unsubscribe header (RFC 8058), so it needs
    no form token: the signed link is the permission."""
    token = request.query_params.get("token", "") or str(form.get("token") or "")
    target = alerts.unsubscribe(conn, request.app.state.secret_key, token)
    if form.get("List-Unsubscribe") == "One-Click":
        return PlainTextResponse("ok" if target else "invalid", status_code=200 if target else 404)
    return render(
        request,
        conn,
        "unsubscribe.html",
        {"token": token, "target": target, "done": target is not None},
        status=200 if target else 404,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/lagrede-sok/{search_id:int}")
def open_saved_search(search_id: int, request: Request, conn: Conn) -> Response:
    """Show a saved search's matches (new ones are marked) and count them as seen."""
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    seen_before = saved_searches.get(conn, user.id, search_id).seen_id
    saved = saved_searches.mark_seen(conn, user.id, search_id)
    return redirect(
        url_with_query("", "/sok", [*parse_qsl(saved.query), ("sort", "newest"), ("nye", str(seen_before))])
    )


@router.post("/lagrede-sok/{search_id:int}/varsel")
def saved_search_alerts(search_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    notify = form.get("notify") == "1"
    saved = saved_searches.set_notify(conn, user.id, search_id, notify)
    flash = f"E-postvarsel er slått {'på' if notify else 'av'} for «{saved.name}»."
    return redirect(f"/lagrede-sok#s{search_id}", flash=flash)


@router.post("/lagrede-sok/{search_id:int}/slett")
def delete_saved_search(search_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    saved_searches.delete(conn, user.id, search_id)
    return redirect("/lagrede-sok", flash="Søket er slettet.")


# --- Account ----------------------------------------------------------------------------------


def _my_page(
    request: Request, conn: sqlite3.Connection, user: users.User, new_token: str | None = None
) -> Response:
    mine = listings.search(conn, SearchParams(user_id=user.id, status="all", include_hidden=True, limit=100))
    counter = request.app.state.views
    return render(
        request,
        conn,
        "my_page.html",
        {
            "my_listings": mine.items,
            "views": {item.id: item.views + counter.pending(item.id) for item in mine.items},
            "blocked": messages.blocked_users(conn, user.id),
            "tokens": users.list_api_tokens(conn, user.id),
            "new_token": new_token,
            "mail_enabled": request.app.state.mailer.enabled,
            "delete_after_days": request.app.state.settings.delete_after_days,
        },
    )


@router.get("/min-side")
def my_page(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    return _my_page(request, conn, user)


@router.post("/min-side/nokler")
def create_token(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    token, _ = users.create_api_token(conn, user.id, str(form.get("name") or "API-nøkkel"))
    response = _my_page(request, conn, user, new_token=token)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/min-side/nokler/{token_id:int}/slett")
def revoke_token(token_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    users.revoke_api_token(conn, user.id, token_id)
    return redirect("/min-side#nokler", flash="Nøkkelen er slettet.")


@router.get("/min-side/data.json")
def download_my_data(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    data = privacy.export_user(conn, user, base_url(request))
    return JSONResponse(
        data,
        headers={
            "Content-Disposition": f'attachment; filename="fritorg-data-{user.id}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/bekreft-epost")
def confirm_email(request: Request, conn: Conn) -> Response:
    ok = verify_email(conn, request.app.state.secret_key, request.query_params.get("token", ""))
    if ok:
        return redirect(
            "/min-side", flash="Takk! E-postadressen er bekreftet. Nå får du varsler om nye meldinger."
        )
    return redirect("/min-side", flash="Lenken er ugyldig eller utløpt. Be om en ny på Min side.")


@router.post("/min-side/navn")
def change_name(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    try:
        users.update_name(conn, user, str(form.get("name") or ""))
    except ValidationProblem as exc:
        return redirect("/min-side#konto", flash=_problem_text(exc))
    return redirect("/min-side#konto", flash="Visningsnavnet er endret.")


@router.post("/min-side/epost")
def change_email(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    decision = request.app.state.limiter.hit("verify", str(user.id), 5, 3600)
    if not decision.allowed:
        raise RateLimited("For mange forsøk. Prøv igjen om en time.", retry_after=decision.reset_in)
    email = str(form.get("email") or "").strip()
    state = request.app.state
    if email and email.casefold() != user.email.casefold():
        try:
            users.update_email(conn, user.id, email)
        except AppError as exc:
            return redirect("/min-side#konto", flash=exc.message)
    else:
        email = user.email
    if not state.mailer.enabled:
        return redirect("/min-side#konto", flash="E-postadressen er lagret.")
    send_verification(state.mailer, state.secret_key, base_url(request), user.id, user.name, email)
    return redirect("/min-side#konto", flash=f"Vi har sendt en bekreftelseslenke til {email}.")


@router.post("/min-side/slett-konto")
def delete_account(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    if user.has_password:
        try:
            users.check_password(conn, request.app.state.limiter, user.email, str(form.get("password") or ""))
        except RateLimited as exc:
            return redirect("/min-side#slett", flash=exc.message)
        except AppError:
            return redirect("/min-side#slett", flash="Feil passord. Kontoen ble ikke slettet.")
    elif str(form.get("confirm") or "").strip().upper() != "SLETT":
        return redirect("/min-side#slett", flash="Skriv SLETT for å bekrefte. Kontoen ble ikke slettet.")
    if users.under_review(conn, user.id):
        contact = request.app.state.settings.contact_email
        return redirect(
            "/min-side#slett",
            flash="Kontoen kan ikke slettes akkurat nå, fordi en moderator behandler en rapport om deg eller en "
            "av annonsene dine. Prøv igjen når saken er avgjort"
            + (f", eller skriv til {contact}." if contact else "."),
        )
    filenames = users.delete_user(conn, user.id)
    images.remove_files(request.app.state.settings.uploads_dir, filenames)
    response = redirect("/", flash="Kontoen din og alt innholdet ditt er slettet.")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


def _start_session(
    request: Request, conn: sqlite3.Connection, user: users.User, target: str, flash: str
) -> Response:
    token = users.create_session(conn, user.id)
    response = redirect(target, flash=flash)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=users.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookies_secure,
        path="/",
    )
    return response


@router.get("/logg-inn")
def login_page(request: Request, conn: Conn) -> Response:
    if current_user(request, conn):
        return redirect(safe_next(request.query_params.get("neste")))
    return render(
        request, conn, "login.html", {"next": safe_next(request.query_params.get("neste")), "values": {}}
    )


@router.post("/logg-inn")
def login(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    settings = request.app.state.settings
    target = safe_next(str(form.get("neste") or ""))
    if settings.bankid_required:
        return redirect(url_with_query("", "/bankid/start", [("neste", target)]))
    email = str(form.get("email") or "")
    decision = request.app.state.limiter.hit(
        "auth", client_ip(request), settings.rate_limit_auth_per_10min, 600
    )
    if not decision.allowed:
        raise RateLimited(
            "For mange innloggingsforsøk. Vent litt og prøv igjen.", retry_after=decision.reset_in
        )
    try:
        user = users.check_password(conn, request.app.state.limiter, email, str(form.get("password") or ""))
    except AppError as exc:
        error = exc.message
        if isinstance(exc, Forbidden) and settings.contact_email:  # a closed account can still complain
            error += f" Mener du at det er feil, kan du klage til {settings.contact_email}."
        return render(
            request,
            conn,
            "login.html",
            {"next": target, "error": error, "values": {"email": email}},
            status=exc.status,
        )
    return _start_session(request, conn, user, target, f"Velkommen tilbake, {user.first_name}!")


@router.get("/registrer")
def register_page(request: Request, conn: Conn) -> Response:
    if current_user(request, conn):
        return redirect("/min-side")
    return render(
        request,
        conn,
        "register.html",
        {"values": {}, "errors": {}, "next": request.query_params.get("neste")},
    )


@router.post("/registrer")
def register(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    settings = request.app.state.settings
    values = {"email": str(form.get("email") or ""), "name": str(form.get("name") or "")}
    target = safe_next(str(form.get("neste") or ""), "/min-side")
    if settings.bankid_required:
        return redirect(url_with_query("", "/bankid/start", [("neste", target)]))
    decision = request.app.state.limiter.hit(
        "register", client_ip(request), settings.max_registrations_per_hour, 3600
    )
    if not decision.allowed:
        raise RateLimited(
            "For mange nye kontoer fra denne adressen. Prøv igjen om en time.", retry_after=decision.reset_in
        )
    if not form.get("terms"):
        errors = {"terms": "Du må godta vilkårene."}
        return render(
            request, conn, "register.html", {"values": values, "errors": errors, "next": target}, status=422
        )
    try:
        user = users.register(
            conn,
            request.app.state.limiter,
            client_ip(request),
            values["email"],
            values["name"],
            str(form.get("password") or ""),
            "web",
        )
    except AppError as exc:
        errors = _errors_by_field(exc) if isinstance(exc, ValidationProblem) else {"email": exc.message}
        return render(
            request,
            conn,
            "register.html",
            {"values": values, "errors": errors, "next": target},
            status=exc.status,
        )
    state = request.app.state
    send_verification(state.mailer, state.secret_key, base_url(request), user.id, user.name, user.email)
    welcome = f"Velkommen til {settings.site_name}, {user.first_name}!"
    if must_verify(request, user):
        verify = url_with_query("", "/verifiser-telefon", [("neste", target)])
        return _start_session(
            request, conn, user, verify, welcome + " Bekreft mobilnummeret ditt for å komme i gang."
        )
    return _start_session(request, conn, user, target, welcome)


# --- Mobile number verification ------------------------------------------------------------------


def _verify_page(
    request: Request,
    conn: sqlite3.Connection,
    user: users.User,
    target: str,
    errors: dict[str, str] | None = None,
    values: dict[str, str] | None = None,
    status: int = 200,
) -> Response:
    context = {
        "next": target,
        "pending_hint": phone.pending_hint(conn, user.id),
        "errors": errors or {},
        "values": values or {},
    }
    response = render(request, conn, "verify_phone.html", context, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/verifiser-telefon")
def verify_phone_page(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    target = safe_next(request.query_params.get("neste"), "/min-side")
    if request.app.state.sms is None:
        return redirect(target)
    return _verify_page(request, conn, user, target)


@router.post("/verifiser-telefon")
def send_phone_code(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    target = safe_next(str(form.get("neste") or ""), "/min-side")
    state = request.app.state
    if state.sms is None:
        return redirect(target)
    number = str(form.get("phone") or "")
    try:
        sent = phone.start(
            conn,
            state.sms,
            state.secret_key,
            state.settings,
            user.id,
            number,
            limiter=state.limiter,
            client_ip=client_ip(request),
        )
    except (ValidationProblem, Conflict, RateLimited, phone.SmsError) as exc:
        errors = {"phone": _problem_text(exc)}
        return _verify_page(request, conn, user, target, errors, {"phone": number}, status=exc.status)
    flash = f"Vi har sendt en kode til {sent.phone_hint}."
    if sent.test_code:
        flash += f" Testmodus, ingen SMS er sendt: koden er {sent.test_code}."
    return redirect(url_with_query("", "/verifiser-telefon", [("neste", target)]) + "#kode", flash=flash)


@router.post("/verifiser-telefon/kode")
def confirm_phone_code(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    target = safe_next(str(form.get("neste") or ""), "/min-side")
    state = request.app.state
    if state.sms is None:
        return redirect(target)
    try:
        phone.confirm(conn, state.secret_key, user.id, str(form.get("code") or ""))
    except (ValidationProblem, Conflict) as exc:
        return _verify_page(request, conn, user, target, {"code": _problem_text(exc)}, status=exc.status)
    return redirect(
        target, flash="Takk! Mobilnummeret er bekreftet. Nå kan du legge ut annonser og sende meldinger."
    )


# --- Forgotten and changed passwords ------------------------------------------------------------


def _forgot_page(
    request: Request,
    conn: sqlite3.Connection,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    status: int = 200,
) -> Response:
    state = request.app.state
    context = {
        "values": values or {},
        "errors": errors or {},
        "mail_enabled": state.mailer.enabled,
        "sms_enabled": state.sms is not None,
    }
    return render(request, conn, "forgot_password.html", context, status=status)


@router.get("/glemt-passord")
def forgot_password_page(request: Request, conn: Conn) -> Response:
    if request.app.state.settings.bankid_required:
        return redirect("/logg-inn")
    return _forgot_page(request, conn)


@router.post("/glemt-passord")
def forgot_password(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    state = request.app.state
    if state.settings.bankid_required:
        return redirect("/logg-inn")
    decision = state.limiter.hit("reset", client_ip(request), 10, 3600)
    if not decision.allowed:
        raise RateLimited("For mange forsøk. Prøv igjen om en time.", retry_after=decision.reset_in)
    email = str(form.get("email") or "").strip()
    number = str(form.get("phone") or "").strip()
    values = {"email": email, "phone": number}
    user = users.get_user_by_email(conn, email) if email else None
    usable = user is not None and user.has_password and not user.banned_at
    # The answer is the same whether or not the address has an account.
    if number and state.sms is not None:
        try:
            sent = None
            if usable:
                sent = phone.start(
                    conn,
                    state.sms,
                    state.secret_key,
                    state.settings,
                    user.id,
                    number,
                    limiter=state.limiter,
                    client_ip=client_ip(request),
                    purpose="reset",
                )
            else:
                phone.normalize_mobile(number)
        except (ValidationProblem, RateLimited, phone.SmsError) as exc:
            return _forgot_page(request, conn, values, {"phone": _problem_text(exc)}, status=exc.status)
        flash = "Hvis e-postadressen og mobilnummeret hører til samme konto, har vi sendt en kode på SMS."
        if sent and sent.test_code:
            flash += f" Testmodus, ingen SMS er sendt: koden er {sent.test_code}."
        return redirect(url_with_query("", "/glemt-passord/kode", [("epost", email)]), flash=flash)
    if not state.mailer.enabled:
        error = "Vi kan ikke sende e-post her." + (" Bruk mobilnummeret ditt i stedet." if state.sms else "")
        return _forgot_page(request, conn, values, {"email": error}, status=422)
    if usable:
        recovery.send_reset_link(state.mailer, conn, state.secret_key, base_url(request), user)
    return redirect(
        "/logg-inn",
        flash="Hvis adressen hører til en konto, har vi sendt en lenke for å lage nytt passord. "
        "Sjekk e-posten din, også søppelposten.",
    )


@router.get("/glemt-passord/kode")
def reset_code_page(request: Request, conn: Conn) -> Response:
    email = request.query_params.get("epost", "")
    return render(request, conn, "reset_code.html", {"email": email, "errors": {}})


@router.post("/glemt-passord/kode")
def reset_with_code(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    state = request.app.state
    decision = state.limiter.hit("reset-code", client_ip(request), 30, 3600)
    if not decision.allowed:
        raise RateLimited("For mange forsøk. Prøv igjen om en time.", retry_after=decision.reset_in)
    email = str(form.get("email") or "").strip()
    password = str(form.get("password") or "")
    user = users.get_user_by_email(conn, email) if email else None
    errors: dict[str, str] = {}
    if user is None or not user.has_password or user.banned_at or state.sms is None:
        errors["code"] = "Feil kode. Be om en ny kode."
    elif users.validate_password(password):  # before the code is used up
        errors["password"] = users.validate_password(password)[0]["message"]
    else:
        try:
            phone.confirm_reset(conn, state.secret_key, user.id, str(form.get("code") or ""))
        except ValidationProblem as exc:
            errors["code"] = _problem_text(exc)
    if errors:
        return render(request, conn, "reset_code.html", {"email": email, "errors": errors}, status=422)
    assert user is not None
    users.set_password(conn, user.id, password)
    users.forget_wrong_passwords(state.limiter, user.email)
    return _start_session(request, conn, user, "/min-side", "Passordet er endret, og du er logget inn.")


@router.get("/nytt-passord")
def new_password_page(request: Request, conn: Conn) -> Response:
    token = request.query_params.get("token", "")
    account = recovery.user_for_reset_token(conn, request.app.state.secret_key, token)
    if account is None:
        return redirect(
            "/glemt-passord", flash="Lenken er ugyldig, utløpt eller allerede brukt. Be om en ny."
        )
    response = render(request, conn, "new_password.html", {"token": token, "account": account, "errors": {}})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/nytt-passord")
def set_new_password(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    token = str(form.get("token") or "")
    account = recovery.user_for_reset_token(conn, request.app.state.secret_key, token)
    if account is None:
        return redirect(
            "/glemt-passord", flash="Lenken er ugyldig, utløpt eller allerede brukt. Be om en ny."
        )
    try:
        users.set_password(conn, account.id, str(form.get("password") or ""))
    except ValidationProblem as exc:
        context = {"token": token, "account": account, "errors": {"password": _problem_text(exc)}}
        return render(request, conn, "new_password.html", context, status=422)
    users.forget_wrong_passwords(request.app.state.limiter, account.email)
    return _start_session(request, conn, account, "/min-side", "Passordet er endret, og du er logget inn.")


@router.post("/min-side/passord")
def change_password(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    settings = request.app.state.settings
    decision = request.app.state.limiter.hit(
        "auth", client_ip(request), settings.rate_limit_auth_per_10min, 600
    )
    if not decision.allowed:
        raise RateLimited("For mange forsøk. Vent litt og prøv igjen.", retry_after=decision.reset_in)
    try:
        users.check_password(conn, request.app.state.limiter, user.email, str(form.get("current") or ""))
    except RateLimited as exc:
        return redirect("/min-side#passord", flash=exc.message)
    except AppError:
        return redirect("/min-side#passord", flash="Feil nåværende passord. Passordet ble ikke endret.")
    try:
        users.set_password(
            conn, user.id, str(form.get("password") or ""), keep_session=request.cookies.get(SESSION_COOKIE)
        )
    except ValidationProblem as exc:
        return redirect("/min-side#passord", flash=_problem_text(exc))
    return redirect(
        "/min-side#passord", flash="Passordet er endret. Andre steder du var logget inn, er logget ut."
    )


@router.post("/logg-ut")
def logout(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    users.delete_session(conn, request.cookies.get(SESSION_COOKIE))
    response = redirect("/", flash="Du er logget ut.")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/bruker/{user_id:int}")
def user_page(user_id: int, request: Request, conn: Conn) -> Response:
    seller = users.get_user(conn, user_id)
    if seller is None or seller.banned_at:  # a closed account has no public profile
        raise NotFound(f"Bruker {user_id} finnes ikke.")
    result = listings.search(conn, SearchParams(user_id=user_id, status="any", limit=60))
    response_time = messages.response_time_text(messages.response_time_hours(conn, user_id))
    return render(
        request,
        conn,
        "user.html",
        {
            "seller": seller,
            "result": result,
            "response_time": response_time,
            "rating": ratings.summary(conn, user_id),
            "ratings": ratings.ratings_for_user(conn, user_id),
        },
    )


@router.post("/vurdering/{rating_id:int}/rapporter")
def report_rating(rating_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    decision = request.app.state.limiter.hit("report", client_ip(request), 20, 3600)
    if not decision.allowed:
        raise RateLimited("For mange rapporter. Prøv igjen senere.", retry_after=decision.reset_in)
    rating = ratings.get_visible_rating(conn, rating_id)
    ratings.report_rating(
        conn, rating_id, str(form.get("reason") or "other"), str(form.get("comment") or ""), user.id
    )
    return redirect(f"/bruker/{rating.rated_id}#vurderinger", flash="Takk! En moderator ser på vurderingen.")


# --- Moderation ------------------------------------------------------------------------------


def _require_moderator(request: Request, conn: sqlite3.Connection) -> users.User | None:
    """The logged-in moderator, None if not logged in. Other users get a 404 (the page is not advertised)."""
    user = current_user(request, conn)
    if user is not None and not user.is_admin:
        raise NotFound("Siden finnes ikke.")
    return user


@router.get("/moderering")
def moderation_page(request: Request, conn: Conn) -> Response:
    if _require_moderator(request, conn) is None:
        return login_redirect(request)
    return render(
        request,
        conn,
        "moderation.html",
        {
            "stats": moderation.stats(conn),
            "queue": moderation.review_queue(conn),
            "cases": moderation.open_reports(conn),
            "reported_ratings": moderation.reported_ratings(conn),
            "appeals": moderation.open_appeals(conn),
            "flagged": moderation.flagged_messages(conn),
        },
    )


@router.post("/moderering/annonse/{listing_id:int}/godkjenn")
def approve_listing(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    moderator = _require_moderator(request, conn)
    if moderator is None:
        return login_redirect(request)
    moderation.approve_listing(conn, moderator, listing_id)
    notify_moderation(request.app.state.mailer, base_url(request), conn, listing_id, approved=True)
    return redirect("/moderering", flash=f"Annonse {listing_id} er godkjent og publisert.")


@router.post("/moderering/annonse/{listing_id:int}/fjern")
def remove_listing(listing_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    moderator = _require_moderator(request, conn)
    if moderator is None:
        return login_redirect(request)
    note = str(form.get("note") or "")
    try:
        moderation.remove_listing(conn, moderator, listing_id, note)
    except ValidationProblem as exc:
        return redirect("/moderering", flash=exc.message)
    images.rename_files(conn, request.app.state.settings.uploads_dir, listing_id)
    notify_moderation(
        request.app.state.mailer, base_url(request), conn, listing_id, approved=False, note=note
    )
    return redirect("/moderering", flash=f"Annonse {listing_id} er fjernet.")


@router.post("/moderering/vurdering/{rating_id:int}/fjern")
def remove_rating(rating_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    moderator = _require_moderator(request, conn)
    if moderator is None:
        return login_redirect(request)
    try:
        moderation.remove_rating(conn, moderator, rating_id, str(form.get("note") or ""))
    except ValidationProblem as exc:
        return redirect("/moderering#vurderinger", flash=exc.message)
    return redirect("/moderering#vurderinger", flash="Vurderingen er fjernet.")


@router.post("/moderering/klage/{appeal_id:int}")
def decide_appeal(appeal_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    moderator = _require_moderator(request, conn)
    if moderator is None:
        return login_redirect(request)
    reverse = form.get("decision") == "reverse"
    try:
        decision = moderation.decide_appeal(
            conn, moderator, appeal_id, reverse=reverse, note=str(form.get("note") or "")
        )
    except ValidationProblem as exc:
        return redirect("/moderering#klager", flash=exc.message)
    mailer, listing_id = request.app.state.mailer, decision["listing_id"]
    if reverse:
        notify_moderation(mailer, base_url(request), conn, listing_id, approved=True)
        return redirect("/moderering#klager", flash=f"Annonse {listing_id} er publisert igjen.")
    notify_appeal_upheld(mailer, conn, listing_id, decision["note"])
    return redirect("/moderering#klager", flash="Avgjørelsen står, og annonsøren har fått svar.")


@router.post("/moderering/rapporter/avvis")
def dismiss_reports(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    moderator = _require_moderator(request, conn)
    if moderator is None:
        return login_redirect(request)
    ids = [int(value) for value in form.getlist("report_id") if str(value).isdigit()]
    moderation.dismiss_reports(conn, moderator, ids)
    return redirect("/moderering", flash="Rapportene er avvist.")


@router.post("/moderering/bruker/{user_id:int}/steng")
def ban_user(user_id: int, request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    moderator = _require_moderator(request, conn)
    if moderator is None:
        return login_redirect(request)
    try:
        moderation.ban_user(conn, moderator, user_id, str(form.get("reason") or ""))
    except ValidationProblem as exc:
        return redirect("/moderering", flash=exc.message)
    return redirect("/moderering", flash="Kontoen er stengt, og annonsene er skjult.")


# --- Documents (Markdown source, HTML for people) -----------------------------------------------

DOCS = {
    "hjelp": ("hjelp.md", "Hjelp"),
    "for-agenter": ("for-agenter.md", "For AI-agenter"),
    "for-bedrifter": ("for-bedrifter.md", "For bedrifter"),
    "trygg-handel": ("trygg-handel.md", "Trygg handel"),
    "om": ("om.md", "Om Fritorg"),
    "vilkar": ("vilkar.md", "Vilkår og personvern"),
}


def _doc(request: Request, conn: sqlite3.Connection, slug: str, fmt: str) -> Response:
    filename, title = DOCS[slug]
    text = discovery.render_doc(request, filename)
    if fmt == "markdown":
        return markdown_response(text)
    html = markdown.markdown(text, extensions=["extra", "sane_lists", "toc"])
    # Wide code blocks and tables scroll sideways; tabindex lets keyboard users scroll them too.
    html = (
        html.replace("<pre>", '<pre tabindex="0">')
        .replace("<table>", '<div class="table-wrap" tabindex="0" role="region" aria-label="Tabell"><table>')
        .replace("</table>", "</table></div>")
    )
    return render(
        request, conn, "doc.html", {"title": title, "content": html, "slug": slug}, headers={"Vary": "Accept"}
    )


@router.get("/hjelp")
def help_page(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "hjelp", preferred_format(request))


@router.get("/hjelp.md")
def help_markdown(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "hjelp", "markdown")


@router.get("/for-agenter")
def agents_page(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "for-agenter", preferred_format(request))


@router.get("/for-agenter.md")
def agents_markdown(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "for-agenter", "markdown")


@router.get("/for-bedrifter")
def business_page(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "for-bedrifter", preferred_format(request))


@router.get("/for-bedrifter.md")
def business_markdown(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "for-bedrifter", "markdown")


@router.get("/trygg-handel")
def safety_page(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "trygg-handel", preferred_format(request))


@router.get("/trygg-handel.md")
def safety_markdown(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "trygg-handel", "markdown")


@router.get("/om")
def about_page(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "om", preferred_format(request))


@router.get("/om.md")
def about_markdown(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "om", "markdown")


@router.get("/vilkar")
def terms_page(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "vilkar", preferred_format(request))


@router.get("/vilkar.md")
def terms_markdown(request: Request, conn: Conn) -> Response:
    return _doc(request, conn, "vilkar", "markdown")


__all__ = ["router", "search_params_from_request", "render_error"]
