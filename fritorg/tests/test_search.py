from __future__ import annotations

import pytest

from fritorg import listings, users
from fritorg.db import Database
from fritorg.errors import ValidationProblem
from fritorg.listings import SearchParams, build_fts_query


@pytest.fixture
def conn(tmp_path):
    db = Database(tmp_path / "search.sqlite3")
    db.init()
    with db.session() as connection:
        yield connection


@pytest.fixture
def seller(conn):
    return users.create_user(conn, "selger@example.no", "Selger", "hemmelig123")


def add(conn, seller, **data):
    base = {"category": "mobler", "title": "Ting", "description": "En helt vanlig ting til salgs."}
    base.update(data)
    return listings.create_listing(conn, seller.id, base)


def ids(conn, **params):
    return [item.id for item in listings.search(conn, SearchParams(**params)).items]


def test_substring_search_handles_norwegian_compounds(conn, seller):
    corner = add(conn, seller, title="Hjørnesofa i grå velur")
    sleeper = add(conn, seller, title="Sovesofa fra IKEA")
    add(conn, seller, title="Spisebord i eik")
    assert set(ids(conn, q="sofa")) == {corner, sleeper}
    assert ids(conn, q="HJØRNE sofa") == [corner]
    assert ids(conn, q="velur grå") == [corner]


def test_short_terms_fall_back_to_like(conn, seller):
    tv = add(conn, seller, category="elektronikk", title="TV 55 tommer", attributes={})
    add(conn, seller, title="Sofa")
    assert ids(conn, q="tv") == [tv]
    assert ids(conn, q="tv 55") == [tv]


def test_category_names_in_both_languages_are_searchable(conn, seller):
    car = add(conn, seller, category="bil", title="Volvo V70", attributes={"make": "Volvo", "fuel": "diesel"})
    assert ids(conn, q="cars") == [car]
    assert ids(conn, q="diesel") == [car]


def test_title_matches_rank_above_description_matches(conn, seller):
    in_description = add(conn, seller, title="Stol", description="Passer fint sammen med en sofa i stua.")
    in_title = add(conn, seller, title="Sofa", description="Pent brukt, tre seter, ingen flekker.")
    assert ids(conn, q="sofa") == [in_title, in_description]


def test_attribute_filters(conn, seller):
    old = add(conn, seller, category="bil", attributes={"make": "Volvo", "year": 2010, "fuel": "diesel"})
    new = add(conn, seller, category="bil", attributes={"make": "Tesla", "year": 2021, "fuel": "electric"})
    hybrid = add(conn, seller, category="bil", attributes={"make": "Toyota", "year": 2019, "fuel": "hybrid"})

    def by_attr(*expressions):
        filters = listings.attr_filters_from_params([("attr", e) for e in expressions])
        return set(ids(conn, attrs=filters))

    assert by_attr("year:2015..") == {new, hybrid}
    assert by_attr("year:..2019") == {old, hybrid}
    assert by_attr("year:2015..2020") == {hybrid}
    assert by_attr("fuel:electric,hybrid") == {new, hybrid}
    assert by_attr("make:TESLA") == {new}
    assert set(ids(conn, attrs=listings.attr_filters_from_object({"year": {"min": 2020}}))) == {new}
    form_style = listings.attr_filters_from_params([("a.year.min", "2011"), ("a.fuel", "diesel")])
    assert set(ids(conn, attrs=form_style)) == set()


def test_bad_attribute_filters_explain_the_syntax(conn):
    for expression in ("colour:red", "year", "fuel:wood", "year:abc.."):
        with pytest.raises(ValidationProblem) as error:
            listings.attr_filters_from_params([("attr", expression)])
        assert "attr=key:value" in (error.value.hint or "")


def test_location_filter_ignores_case_of_norwegian_letters(conn, seller):
    tromso = add(conn, seller, location="Tromsø")
    add(conn, seller, location="Bergen")
    assert ids(conn, location="TROMSØ") == [tromso]
    assert ids(conn, location="trom") == [tromso]


def test_status_filters_and_owner_views(conn, seller):
    active = add(conn, seller)
    sold = add(conn, seller, status="sold")
    hidden = add(conn, seller, status="inactive")
    assert ids(conn) == [active]
    assert set(ids(conn, status="any")) == {active, sold}
    assert ids(conn, status="sold") == [sold]
    with pytest.raises(ValidationProblem):
        ids(conn, status="all")
    assert set(ids(conn, status="all", include_hidden=True, user_id=seller.id)) == {active, sold, hidden}


def test_index_follows_updates_and_deletes(conn, seller):
    listing_id = add(conn, seller, title="Gammel tittel")
    listings.update_listing(conn, seller.id, listing_id, {"title": "Splitter ny lampe"})
    assert ids(conn, q="gammel") == []
    assert ids(conn, q="lampe") == [listing_id]
    listings.delete_listing(conn, seller.id, listing_id)
    assert ids(conn, q="lampe") == []
    assert conn.execute("SELECT COUNT(*) FROM listings_fts").fetchone()[0] == 0


def test_fts_query_escaping():
    assert build_fts_query('sofa "OR" grå') == ('"sofa" AND "grå"', ["or"])
    assert build_fts_query("e-bike 26") == ('"e-bike"', ["26"])
    assert build_fts_query("   ") == (None, [])


def test_queries_with_fts_syntax_do_not_crash(conn, seller):
    add(conn, seller, title="Sofa")
    for query in ['"', "sofa*", "NEAR(sofa", "a:b", "AND OR NOT", "%_\\", "(((", "^sofa"]:
        listings.search(conn, SearchParams(q=query))


def test_price_sorting_puts_missing_prices_last(conn, seller):
    cheap = add(conn, seller, price=100)
    expensive = add(conn, seller, price=900)
    unknown = add(conn, seller)
    assert ids(conn, sort="price_asc") == [cheap, expensive, unknown]
    assert ids(conn, sort="price_desc") == [expensive, cheap, unknown]


def test_updated_since(conn, seller):
    listing_id = add(conn, seller)
    conn.execute("UPDATE listings SET updated_at = '2020-01-01T00:00:00Z' WHERE id = ?", (listing_id,))
    newer = add(conn, seller)
    assert ids(conn, updated_since="2025-01-01") == [newer]
    with pytest.raises(ValidationProblem):
        ids(conn, updated_since="i går")
