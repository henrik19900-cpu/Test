"""Page features: sharing previews, the web app manifest and similar listings."""

from __future__ import annotations

from conftest import PHOTO, make_listing, register, web_login


def test_sharing_previews(client, auth):
    home = client.get("/").text
    assert '<meta property="og:site_name" content="Fritorg">' in home
    assert '<meta property="og:image" content="http://testserver/static/og.png">' in home
    assert client.get("/static/og.png").headers["content-type"] == "image/png"

    listing = make_listing(client, auth)
    page = client.get(f"/annonse/{listing['id']}").text
    assert '<meta property="og:type" content="product">' in page
    assert 'og:title" content="Terrengsykkel Trek Marlin 7 – 6 500 kr"' in page
    assert '<meta name="twitter:card" content="summary">' in page
    assert page.count('property="og:title"') == 1

    client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("bike.png", PHOTO, "image/png")},
        headers=auth,
    )
    page = client.get(f"/annonse/{listing['id']}").text
    assert '<meta name="twitter:card" content="summary_large_image">' in page
    assert 'property="og:image:width"' in page


def test_web_app_manifest(client):
    response = client.get("/manifest.webmanifest")
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["short_name"] == "Fritorg" and manifest["start_url"] == "/"
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200
    assert '<link rel="manifest" href="/manifest.webmanifest">' in client.get("/").text


def test_similar_listings(client, auth, other_auth):
    listing = make_listing(client, auth)
    make_listing(client, auth, title="Sykkel fra samme selger")  # shown under the seller's listings instead
    # Another seller's text (copied text from someone else would be held for review).
    similar = make_listing(
        client,
        other_auth,
        title="Hybridsykkel Merida",
        county="vestland",
        description="Hybridsykkel, 21 gir, i god stand.",
    )
    make_listing(
        client,
        other_auth,
        category="mobler",
        title="Spisebord i eik",
        description="Spisebord i eik.",
        attributes={},
    )
    page = client.get(f"/annonse/{listing['id']}").text
    section = page[page.index('id="lignende"') :]
    assert "Hybridsykkel Merida" in section and f"/annonse/{similar['id']}" in section
    assert "Spisebord" not in section and "Sykkel fra samme selger" not in section


def test_head_requests(client):
    for path in ("/", "/sok?q=sykkel", "/llms.txt", "/feed.atom", "/api/v1/listings"):
        response = client.head(path)
        assert response.status_code == 200, path
        assert response.content == b""
    assert client.head("/annonse/999999").status_code == 404


def test_wording_follows_the_listing_type(client, auth):
    wanted = make_listing(
        client,
        auth,
        category="mobler",
        type="wanted",
        title="Ønsker meg en sofa",
        description="Ser etter en pen sofa til stua.",
        price=3000,
        attributes={},
    )
    register(client, email="ola@example.no", name="Ola Hansen")
    web_login(client, email="ola@example.no")
    page = client.get(f"/annonse/{wanted['id']}").text
    assert (
        "Ønskes av" in page
        and "Svar på annonsen" in page
        and "Jeg så at du ønsker «Ønsker meg en sofa»" in page
    )
    assert "Kontakt selger" not in page

    client.patch(f"/api/v1/listings/{wanted['id']}", json={"status": "sold"}, headers=auth)
    page = client.get(f"/annonse/{wanted['id']}").text
    assert "merket som funnet" in page and '<span class="tag tag-sold">Funnet</span>' in page


def test_login_page_says_why(client):
    assert "Logg inn for å legge ut annonsen din" in client.get("/logg-inn?neste=/ny-annonse").text
    assert "Logg inn for å lagre søket" in client.get("/logg-inn?neste=/sok%3Fq%3Dsykkel").text
    assert "Logg inn for å" not in client.get("/logg-inn").text


def test_search_titles(client):
    cases = {
        "/sok?category=bil&county=oslo": "Bil i Oslo",
        "/sok?category=bil": "Bil",
        "/sok?q=sofa": "Søk etter «sofa»",
        "/sok?q=sofa&category=mobler": "«sofa» i Møbler og interiør",
        "/sok?county=vestland": "Annonser i Vestland",
        "/sok": "Alle annonser",
    }
    for url, title in cases.items():
        page = client.get(url).text
        assert f"<title>{title} – Fritorg</title>" in page, url
