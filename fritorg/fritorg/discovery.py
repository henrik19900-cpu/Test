"""Machine-readable entry points: llms.txt, robots.txt, sitemap, Atom feeds and health."""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from . import listings, taxonomy
from .deps import base_url, get_conn
from .errors import NotFound
from .listings import SearchParams
from .serializers import listing_url
from .templating import templates
from .util import now_iso, to_iso, truncate, utcnow

router = APIRouter(include_in_schema=False)
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

AI_AGENTS = [
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "Applebot-Extended",
    "CCBot",
    "Meta-ExternalAgent",
    "MistralAI-User",
    "DuckAssistBot",
]


def render_doc(request: Request, name: str, **extra) -> str:
    """Render a Markdown document from templates/docs with the site's name and base URL."""
    settings = request.app.state.settings
    template = templates.env.get_template(f"docs/{name}")
    return template.render(base=base_url(request), site_name=settings.site_name, settings=settings, **extra)


def category_reference(base: str) -> str:
    """Markdown reference of every category and its attributes (part of llms-full.txt)."""
    lines = ["# Category and attribute reference", ""]
    lines.append(
        "Listing types: " + ", ".join(f"`{t.slug}` ({t.label_en})" for t in taxonomy.LISTING_TYPES.values())
    )
    lines.append("")
    lines.append(
        "Counties (`county`): " + ", ".join(f"`{c.slug}` ({c.name})" for c in taxonomy.COUNTIES.values())
    )
    lines.append("")
    for group_slug in taxonomy.GROUPS:
        group = taxonomy.CATEGORIES[group_slug]
        lines.append(f"## {group.name} (`{group.slug}`, {group.name_en})")
        lines.append("")
        lines.append("Allowed listing types: " + ", ".join(f"`{t}`" for t in group.types))
        lines.append("")
        for child_slug in group.children:
            child = taxonomy.CATEGORIES[child_slug]
            lines.append(f"### {child.name} (`{child.slug}`, {child.name_en})")
            for attr in child.attributes:
                detail = attr.type
                if attr.options:
                    detail += ": " + ", ".join(f"`{o.value}` ({o.label})" for o in attr.options)
                elif attr.unit:
                    detail += f", unit {attr.unit}"
                lines.append(f"- `{attr.key}` ({attr.label}) – {attr.description}. Type {detail}")
            lines.append("")
    lines.append(f"Machine-readable: {base}/api/v1/categories")
    return "\n".join(lines)


@router.get("/llms.txt")
def llms_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(render_doc(request, "llms.md"), media_type="text/plain; charset=utf-8")


@router.get("/llms-full.txt")
def llms_full_txt(request: Request) -> PlainTextResponse:
    base = base_url(request)
    parts = [render_doc(request, "llms.md"), render_doc(request, "for-agenter.md"), category_reference(base)]
    return PlainTextResponse("\n\n---\n\n".join(parts), media_type="text/plain; charset=utf-8")


@router.get("/robots.txt")
def robots_txt(request: Request) -> PlainTextResponse:
    base = base_url(request)
    lines = [
        "# Fritorg welcomes search engines and AI agents. No API key needed for reading.",
        f"# Prefer the API ({base}/openapi.json), MCP ({base}/mcp) or the bulk export",
        f"# ({base}/api/v1/export/listings.ndjson) over crawling HTML. Docs: {base}/llms.txt",
        "",
        "User-agent: *",
        "Allow: /",
        "Disallow: /min-side",
        "Disallow: /meldinger",
        "Disallow: /logg-inn",
        "Disallow: /registrer",
        "Disallow: /ny-annonse",
        "Disallow: /bankid/",
        "Disallow: /koble-til",
        "Disallow: /moderering",
        "Disallow: /bekreft-epost",
        "Disallow: /glemt-passord",
        "Disallow: /nytt-passord",
        "Disallow: /verifiser-telefon",
        "Content-Signal: search=yes, ai-input=yes, ai-train=yes",
        "",
    ]
    for agent in AI_AGENTS:
        lines += [f"User-agent: {agent}", "Allow: /", ""]
    lines.append(f"Sitemap: {base}/sitemap.xml")
    return PlainTextResponse("\n".join(lines) + "\n")


@router.get("/sitemap.xml")
def sitemap(request: Request, conn: Conn) -> Response:
    base = base_url(request)
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    def add(loc: str, lastmod: str | None = None) -> None:
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = loc
        if lastmod:
            ET.SubElement(url, "lastmod").text = lastmod

    for path in ("/", "/sok", "/for-agenter", "/om", "/vilkar"):
        add(base + path)
    for slug in taxonomy.ALL_SLUGS:
        add(f"{base}/sok?category={slug}")
    for count, listing in enumerate(listings.iter_public_listings(conn)):
        if count >= 45_000:
            break
        add(listing_url(base, listing.id), listing.updated_at)
    body = ET.tostring(urlset, encoding="unicode", xml_declaration=False)
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n' + body, media_type="application/xml")


def atom_feed(
    request: Request, result: listings.SearchResult, title: str, self_url: str, html_url: str
) -> Response:
    base = base_url(request)
    ns = "http://www.w3.org/2005/Atom"
    feed = ET.Element("feed", xmlns=ns)
    ET.SubElement(feed, "title").text = title
    ET.SubElement(feed, "id").text = self_url
    ET.SubElement(feed, "updated").text = max((i.updated_at for i in result.items), default=now_iso())
    ET.SubElement(feed, "link", rel="self", href=self_url)
    ET.SubElement(feed, "link", rel="alternate", type="text/html", href=html_url)
    ET.SubElement(feed, "generator").text = request.app.state.settings.site_name
    for item in result.items:
        url = listing_url(base, item.id)
        entry = ET.SubElement(feed, "entry")
        ET.SubElement(entry, "title").text = item.title
        ET.SubElement(entry, "id").text = url
        ET.SubElement(entry, "link", rel="alternate", type="text/html", href=url)
        ET.SubElement(entry, "link", rel="alternate", type="application/json", href=f"{url}.json")
        ET.SubElement(entry, "published").text = item.created_at
        ET.SubElement(entry, "updated").text = item.updated_at
        author = ET.SubElement(entry, "author")
        ET.SubElement(author, "name").text = item.seller_name
        ET.SubElement(entry, "category", term=item.category, label=item.category_obj.name)
        facts = " · ".join(p for p in (item.price_text(), item.place, item.type_label) if p)
        ET.SubElement(entry, "summary").text = f"{facts}\n\n{truncate(item.description, 400)}"
    body = ET.tostring(feed, encoding="unicode")
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + body, media_type="application/atom+xml; charset=utf-8"
    )


@router.get("/feed.atom")
def feed(request: Request, conn: Conn) -> Response:
    """Atom feed for any search: the same parameters as /sok, newest first. Subscribe to get new matches."""
    from .web import search_params_from_request

    params = search_params_from_request(request)
    params.sort, params.limit, params.offset = "newest", 50, 0
    result = listings.search(conn, params)
    query = request.url.query
    base = base_url(request)
    title = f"{request.app.state.settings.site_name}: " + (f"«{params.q}»" if params.q else "nyeste annonser")
    return atom_feed(
        request,
        result,
        title,
        f"{base}/feed.atom" + (f"?{query}" if query else ""),
        f"{base}/sok" + (f"?{query}" if query else ""),
    )


@router.get("/.well-known/security.txt")
def security_txt(request: Request) -> PlainTextResponse:
    """RFC 9116. Only published when FRITORG_CONTACT_EMAIL is set."""
    contact = request.app.state.settings.contact_email
    if not contact:
        raise NotFound("Ingen sikkerhetskontakt er satt opp.")
    base = base_url(request)
    expires = to_iso(utcnow() + timedelta(days=365))
    return PlainTextResponse(
        f"Contact: mailto:{contact}\nExpires: {expires}\nPreferred-Languages: no, en\n"
        f"Canonical: {base}/.well-known/security.txt\n"
    )


@router.get("/healthz")
def healthz(conn: Conn) -> JSONResponse:
    conn.execute("SELECT 1").fetchone()
    return JSONResponse({"status": "ok"})


def recent_listings(conn: sqlite3.Connection, limit: int = 12) -> listings.SearchResult:
    """Newest listings posted on the site itself; imported job ads would crowd them out."""
    return listings.search(conn, SearchParams(sort="newest", limit=limit, include_imported=False))
