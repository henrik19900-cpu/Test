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
        "Disallow: /favoritter",
        "Disallow: /lagrede-sok",
        "Disallow: /varsler/",
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


SITEMAP_LISTINGS = 50_000  # the most URLs one sitemap file may hold
_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _xml(root: ET.Element) -> Response:
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + body,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/sitemap.xml")
def sitemap(request: Request, conn: Conn) -> Response:
    """A sitemap index: the pages, and the listings in files of up to 50 000 (by listing id)."""
    base = base_url(request)
    index = ET.Element("sitemapindex", xmlns=_SITEMAP_NS)
    ET.SubElement(ET.SubElement(index, "sitemap"), "loc").text = f"{base}/sitemap-sider.xml"
    # "+status": read the listings in id order (the status indexes would sort them all first).
    public = "SELECT id FROM listings WHERE +status IN ('active', 'sold') ORDER BY id"
    first = conn.execute(f"{public} LIMIT 1").fetchone()
    last = conn.execute(f"{public} DESC LIMIT 1").fetchone()
    if first and last:
        for part in range(first[0] // SITEMAP_LISTINGS, last[0] // SITEMAP_LISTINGS + 1):
            low = part * SITEMAP_LISTINGS
            if conn.execute(
                "SELECT 1 FROM listings l WHERE l.id >= ? AND l.id < ? AND +l.status IN ('active', 'sold') LIMIT 1",
                (low, low + SITEMAP_LISTINGS),
            ).fetchone():
                ET.SubElement(
                    ET.SubElement(index, "sitemap"), "loc"
                ).text = f"{base}/sitemap-annonser-{part}.xml"
    return _xml(index)


@router.get("/sitemap-sider.xml")
def sitemap_pages(request: Request) -> Response:
    base = base_url(request)
    urlset = ET.Element("urlset", xmlns=_SITEMAP_NS)
    paths = ["/", "/sok", "/hjelp", "/for-agenter", "/for-bedrifter", "/trygg-handel", "/om", "/vilkar"]
    paths += [f"/sok?category={slug}" for slug in taxonomy.ALL_SLUGS]
    for path in paths:
        ET.SubElement(ET.SubElement(urlset, "url"), "loc").text = base + path
    return _xml(urlset)


@router.get("/sitemap-annonser-{part:int}.xml")
def sitemap_listings(part: int, request: Request, conn: Conn) -> Response:
    """Public listings with ids from part * 50 000 up to the next part, in id order."""
    base = base_url(request)
    low = part * SITEMAP_LISTINGS
    rows = conn.execute(
        "SELECT l.id, l.updated_at FROM listings l WHERE l.id >= ? AND l.id < ? "
        f"AND +l.status IN ('active', 'sold') AND {listings.SELLER_OK} ORDER BY l.id",
        (low, low + SITEMAP_LISTINGS),
    ).fetchall()
    if not rows:
        raise NotFound("Det finnes ingen slik sitemap.")
    urlset = ET.Element("urlset", xmlns=_SITEMAP_NS)
    for row in rows:
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = listing_url(base, row["id"])
        ET.SubElement(url, "lastmod").text = row["updated_at"]
    return _xml(urlset)


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
    result = listings.search(conn, params, count=False)
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


@router.get("/manifest.webmanifest")
def web_manifest(request: Request) -> JSONResponse:
    """Lets people add the site to their phone's home screen, with its name and icon."""
    name = request.app.state.settings.site_name
    icons = [
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {
            "src": "/static/icon-maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ]
    return JSONResponse(
        {
            "name": f"{name} – gratis markedsplass",
            "short_name": name,
            "description": "Kjøp, selg og gi bort gratis i hele Norge.",
            "lang": "nb",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f5f6f2",
            "theme_color": "#0b6b4f",
            "icons": icons,
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/healthz")
def healthz(conn: Conn) -> JSONResponse:
    conn.execute("SELECT 1").fetchone()
    return JSONResponse({"status": "ok"})


def recent_listings(conn: sqlite3.Connection, limit: int = 12) -> listings.SearchResult:
    """Newest listings posted on the site itself; imported job ads would crowd them out."""
    return listings.search(
        conn, SearchParams(sort="newest", limit=limit, include_imported=False), count=False
    )
