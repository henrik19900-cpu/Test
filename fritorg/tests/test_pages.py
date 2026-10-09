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


def test_share_button_is_an_extra(client, auth):
    listing = make_listing(client, auth)
    page = client.get(f"/annonse/{listing['id']}").text
    assert f'data-share-url="http://testserver/annonse/{listing["id"]}"' in page and " hidden>" in page
    script = client.get("/static/app.js")
    assert script.status_code == 200 and "navigator.share" in script.text
    assert '<script src="/static/app.js' in page


def test_help_page(client):
    page = client.get("/hjelp").text
    assert "<h1" in page and "Hva koster det?" in page and "Lagre søket" in page
    assert '<a href="/hjelp">Hjelp</a>' in client.get("/").text
    assert client.get("/hjelp.md").headers["content-type"].startswith("text/markdown")


def test_cards_say_how_new_a_listing_is(client, auth):
    from fritorg.util import format_ago_no, iso_ago, now_iso

    assert format_ago_no(now_iso()) == "i dag"  # (five minutes ago is yesterday just after midnight)
    assert format_ago_no(iso_ago(days=1)) == "i går"
    assert format_ago_no(iso_ago(days=3)) == "3 dager siden"
    assert format_ago_no("2001-03-05T12:00:00Z") == "5. mars 2001"

    make_listing(
        client,
        auth,
        category="jobb-it",
        type="job",
        title="Utvikler til lite team",
        description="Vi søker en utvikler med erfaring fra Python.",
        price=None,
        attributes={"employer": "Firma AS", "deadline": "2030-12-01"},
    )
    page = client.get("/sok?category=jobb").text
    assert "Søknadsfrist 1. des. 2030" in page and "· <time" in page and ">i dag</time>" in page


def test_moderators_see_key_numbers(app, client, auth):
    make_listing(client, auth)
    with app.state.db.session() as conn:
        conn.execute("UPDATE users SET is_admin = 1")
    web_login(client)
    page = client.get("/moderering").text
    assert "Nøkkeltall" in page and "Aktive annonser" in page and "<dd>1</dd>" in page


def test_postal_code_fills_in_place_and_county(client, auth):
    from fritorg import postcodes

    assert postcodes.lookup("8601").place == "Mo i Rana" and postcodes.lookup("8601").county == "nordland"
    assert postcodes.lookup("0150").county == "oslo" and postcodes.lookup("9170").county == "svalbard"
    assert postcodes.lookup("0000") is None and postcodes.lookup(None) is None

    listing = make_listing(client, auth, county=None, location=None, postal_code="5003")
    assert (listing["location"], listing["county"]) == ("Bergen", "vestland")
    # What the seller wrote wins.
    listing = make_listing(
        client, auth, title="Sykkel nummer to", county="oslo", location="Grünerløkka", postal_code="5003"
    )
    assert (listing["location"], listing["county"]) == ("Grünerløkka", "oslo")
    assert "Bergen" in client.get("/sok?county=vestland").text


def test_the_terms_explain_deleting_conversations_without_automatic_deletion_too(client, settings):
    settings.delete_after_days = 0
    assert "slette en samtale" in client.get("/vilkar").text
