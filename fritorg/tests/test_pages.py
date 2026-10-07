"""Page features: sharing previews, the web app manifest and similar listings."""

from __future__ import annotations

from conftest import PHOTO, make_listing


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
