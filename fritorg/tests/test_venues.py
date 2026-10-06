from __future__ import annotations

import pytest

from fritorg import imports, ops, venues
from fritorg.navjobs import HttpResponse

HEADER = "Ressursid,Sted,Ressurs,Hjemmeside,Epost,Gateadresse,Postnr,Poststed,Bydel,latitude,longitude"
ROWS = [
    "1,Stavanger idrettshall,Sal A,https://www.stavanger.kommune.no/,hall@stavanger.kommune.no,Gunnar Warebergs gate 3,4009,Stavanger,Hillevåg,58.95,5.70",
    "2,Hundvåg idrettspark,Kunstgressbane 1,0,privat.person@gmail.com,Austbøsvingene 56,4085,Hundvåg,4,58.98,5.75",
    "3,Bruktmarked i Byparken,Stand 1,0,,Byparken,4006,Stavanger,Storhaug,58.97,5.73",
    "4,Stavanger svømmehall,Basseng,0,,Tjodolvs gate 54,4041,Hafrsfjord,Madla,58.94,5.68",
] + [f"{n},Kulturhuset,Grupperom {n},0,,Kulturveien {n},4010,Stavanger,Tasta,58.9,5.7" for n in range(5, 15)]
SKIPPED = [
    "90,Testbygg 2.0,Møterom,0,,Testveien 1,4010,Stavanger,Tasta,58.9,5.7",
    "91,Kulturhuset,Nordkronen amp 40 ikke tilgjengelig amp 41,0,,Kulturveien 1,4010,Stavanger,Tasta,58.9,5.7",
]


def csv_text(rows=ROWS) -> str:
    return "﻿" + "\n".join([HEADER, *rows]) + "\n"


class FakeCsv:
    def __init__(self, text: str):
        self.text = text
        self.status = 200

    def __call__(self, url, headers):
        assert url == venues.CSV_URL
        return HttpResponse(self.status, {}, self.text.encode())


def stavanger(app) -> dict[str, dict]:
    with app.state.db.session() as conn:
        rows = conn.execute("SELECT * FROM listings WHERE source = 'stavanger'").fetchall()
    return {row["source_id"]: dict(row) for row in rows}


def test_parse_maps_venues():
    items = {item.source_id: item for item in venues.parse(csv_text([*ROWS, *SKIPPED]))}
    assert "90" not in items and "91" not in items  # test entries and unavailable resources
    assert venues._clean("Grus 4  amp  40 20 x 40 amp  41 ") == "Grus 4 (20 x 40)"
    hall = items["1"].values
    assert hall["title"] == "Sal A – Stavanger idrettshall" and hall["category"] == "lokaler"
    assert hall["type"] == "rent" and hall["county"] == "rogaland"
    assert hall["location"] == "Hillevåg, Stavanger" and hall["postal_code"] == "4009"
    assert hall["attributes"] == {"venue_type": "sports_hall"}
    assert items["2"].values["location"] == "Hundvåg"  # "4" is not a district
    assert items["2"].values["attributes"]["venue_type"] == "field"
    assert items["3"].values["attributes"]["venue_type"] == "market"
    assert items["4"].values["attributes"]["venue_type"] == "pool"
    assert items["5"].values["attributes"]["venue_type"] == "room"
    assert all(item.apply_url == venues.BOOKING_URL for item in items.values())
    assert "gmail" not in repr(items)  # contact e-mails are left out


def test_sync_creates_updates_and_removes(app, client):
    fake = FakeCsv(csv_text())
    report = venues.sync(app.state.db, app.state.settings, http=fake)
    assert report.created == len(ROWS)
    listing_id = stavanger(app)["1"]["id"]
    page = client.get(f"/annonse/{listing_id}").text
    assert "Se ledige tider og book" in page and venues.BOOKING_URL in page
    assert "Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Stavanger kommune" in page
    assert "Utleier" in page and "Stavanger kommune" in page and "/melding" not in page
    assert client.get("/api/v1/listings", params={"category": "lokaler"}).json()["total"] == len(ROWS)
    data = client.get(f"/api/v1/listings/{listing_id}").json()
    assert data["source"]["licence_url"] == "https://data.norge.no/nlod/no/2.0"
    assert data["source"]["action"] == "Se ledige tider og book"

    assert venues.sync(app.state.db, app.state.settings, http=fake).unchanged == len(ROWS)
    fake.text = csv_text([ROWS[0].replace("Sal A", "Sal A og B"), *ROWS[2:]])
    report = venues.sync(app.state.db, app.state.settings, http=fake)
    assert (report.updated, report.removed) == (1, 1)
    assert stavanger(app)["1"]["title"] == "Sal A og B – Stavanger idrettshall"
    assert "2" not in stavanger(app)


def test_a_broken_file_keeps_the_venues(app):
    venues.sync(app.state.db, app.state.settings, http=FakeCsv(csv_text()))
    with pytest.raises(RuntimeError, match="only 1 rows"):
        venues.sync(app.state.db, app.state.settings, http=FakeCsv(csv_text(ROWS[:1])))
    assert len(stavanger(app)) == len(ROWS)
    app.state.settings.stavanger_import = True
    assert any(c.ok is False and "Stavanger" in c.text for c in ops.doctor(app.state.settings))
    with app.state.db.session() as conn:
        assert imports.status(conn, "stavanger")["active_listings"] == len(ROWS)
