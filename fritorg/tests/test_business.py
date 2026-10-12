"""Sellers who sell as a business (business.py): buyers see it, and the number is checked in Enhetsregisteret."""

from __future__ import annotations

import http.client
import io
import json
import urllib.error

import pytest
from conftest import csrf, make_listing, web_login

from fritorg import business
from fritorg.errors import ServiceUnavailable, ValidationProblem


@pytest.mark.parametrize("number", ["974760673", "974 760 673", "923.609.016"])
def test_organisation_numbers_with_a_valid_check_digit(number):
    assert len(business.clean_org_number(number)) == 9


@pytest.mark.parametrize("number", ["974760674", "12345678", "97476067x", ""])
def test_numbers_that_cannot_be_organisation_numbers(number):
    with pytest.raises(ValidationProblem):
        business.clean_org_number(number)


def test_buyers_see_who_the_business_is_and_their_rights(client, auth, other_auth):
    listing = make_listing(client, auth)
    page = client.get(f"/annonse/{listing['id']}").text
    assert "Selgeren er en privatperson" in page and "Bedrift</span>" not in page
    assert client.get(f"/api/v1/listings/{listing['id']}").json()["seller"]["type"] == "private"

    declared = client.put(
        "/api/v1/me/business", json={"org_number": "974 760 673", "name": "Sykkelbutikken AS"}, headers=auth
    ).json()
    assert (
        declared["business"]["org_number"] == "974760673" and declared["business"]["declared_by"] == "seller"
    )
    seller = client.get(f"/api/v1/listings/{listing['id']}").json()["seller"]
    assert seller["type"] == "business" and seller["business"]["name"] == "Sykkelbutikken AS"
    assert seller["business"]["registry_url"].endswith("/974760673")
    page = client.get(f"/annonse/{listing['id']}").text
    assert "Sykkelbutikken AS, org.nr." in page and "974\u00a0760\u00a0673" in page and "angrerett" in page
    assert '"@type": "Organization"' in page  # search engines see a business as the seller
    assert "**Bedrift:** Sykkelbutikken AS" in client.get(f"/annonse/{listing['id']}.md").text
    found = client.get("/api/v1/listings?q=trek").json()["items"][0]
    assert found["seller_type"] == "business"
    assert "Bedrift</span>" in client.get("/sok?q=trek").text
    assert client.get("/api/v1/users/1").json()["business"]["name"] == "Sykkelbutikken AS"

    assert client.delete("/api/v1/me/business", headers=auth).json()["business"] is None
    assert client.get(f"/api/v1/listings/{listing['id']}").json()["seller"]["type"] == "private"


def test_inventories_are_synced_only_by_businesses(client, auth):
    body = {
        "listings": [
            {
                "external_id": "1",
                "category": "sykler",
                "title": "Bysykkel",
                "description": "Fin bysykkel fra lageret vårt.",
            }
        ]
    }
    refused = client.put("/api/v1/me/feeds/lager", json=body, headers=auth)
    assert refused.status_code == 403 and "organisasjonsnummer" in refused.json()["detail"]


def test_declaring_on_min_side(client, auth):
    web_login(client)
    wrong = client.post("/min-side/bedrift", data={"csrf_token": csrf(client), "org_number": "123"})
    assert "9 sifre" in wrong.text
    done = client.post("/min-side/bedrift", data={"csrf_token": csrf(client), "org_number": "974760673"})
    assert "merket som fra bedriften Kari Nordmann" in done.text
    assert "Du selger som bedrift" in client.get("/min-side").text
    client.post("/min-side/bedrift/fjern", data={"csrf_token": csrf(client)})
    assert "Selger du som bedrift?" in client.get("/min-side").text


def _answer(status: int, body: dict | None = None):
    def fake(request, timeout):
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps(body).encode())

    return fake


def test_the_name_comes_from_enhetsregisteret(monkeypatch):
    monkeypatch.setattr(business.urllib.request, "urlopen", _answer(200, {"navn": "BRØNNØYSUNDREGISTRENE"}))
    assert business.registry_name("974760673") == "BRØNNØYSUNDREGISTRENE"
    monkeypatch.setattr(
        business.urllib.request, "urlopen", _answer(200, {"navn": "X", "slettedato": "2020-01-01"})
    )
    with pytest.raises(ValidationProblem, match="slettet"):
        business.registry_name("974760673")
    monkeypatch.setattr(business.urllib.request, "urlopen", _answer(404))
    with pytest.raises(ValidationProblem, match="finnes ikke"):
        business.registry_name("974760673")
    monkeypatch.setattr(business.urllib.request, "urlopen", _answer(500))
    with pytest.raises(ServiceUnavailable):
        business.registry_name("974760673")


def test_an_answer_from_the_register_that_breaks_off_asks_to_try_again(client, auth, settings, monkeypatch):
    class BrokenOff(io.BytesIO):
        def read(self, *args):  # the connection closed before the whole answer had come
            raise http.client.IncompleteRead(b'{"navn": "BR', 40)

    monkeypatch.setattr(business.urllib.request, "urlopen", lambda request, timeout: BrokenOff())
    settings.business_registry = "brreg"
    web_login(client)
    page = client.post("/min-side/bedrift", data={"csrf_token": csrf(client), "org_number": "974760673"})
    assert "Enhetsregisteret svarer ikke" in page.text


def test_a_business_named_like_a_service_people_trust_is_not_shown(client, auth, settings, monkeypatch):
    """Scams pretend to be Posten, Bring or the police, and anyone can type their organisation number."""
    settings.business_registry = "brreg"
    web_login(client)
    for registered, refused in (
        ("POSTEN NORGE AS", True),
        ("OSLO POLITIDISTRIKT", True),
        ("Vipps MobilePay AS", True),
        ("KOMPOSTEN AS", False),
        ("BRINGEBÆRGÅRDEN AS", False),
    ):
        monkeypatch.setattr(business, "registry_name", lambda number, registered=registered: registered)
        page = client.post("/min-side/bedrift", data={"csrf_token": csrf(client), "org_number": "974760673"})
        assert ("kan forveksles" in page.text) is refused, registered
