from __future__ import annotations

import json
import urllib.parse

from fritorg import jobtech
from fritorg.navjobs import HttpResponse


def ad(ad_id: str, **overrides) -> dict:
    data = {
        "id": ad_id,
        "headline": "Kundtjänstmedarbetare med norska",
        "description": {"text": "Vi söker dig som talar norska flytande.\n\nDu arbetar med kunder i Norge."},
        "employer": {"name": "Nordisk Service AB"},
        "workplace_address": {
            "municipality": "Göteborg",
            "region": "Västra Götalands län",
            "country": "Sverige",
        },
        "occupation_field": {"label": "Försäljning, inköp, marknadsföring"},
        "employment_type": {"label": "Vanlig anställning"},
        "working_hours_type": {"label": "Heltid"},
        "application_deadline": "2099-11-04T23:59:59",
        "application_details": {"url": f"https://jobb.example.se/apply/{ad_id}"},
        "application_contacts": [{"name": "Karin Kontakt", "telephone": "+46 70 000 00 00"}],
        "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{ad_id}",
        "publication_date": "2026-10-01T10:00:00",
        "salary_description": "Fast månadslön",
        "relevance": 0.5,
        "removed": False,
    }
    data.update(overrides)
    return data


class FakeJobSearch:
    def __init__(self):
        self.by_query = {
            "country": [ad("n1", headline="Murare sökes till Oslo", workplace_address={"country": "Norge", "municipality": "Oslo", "region": "Oslo"}, occupation_field={"label": "Bygg och anläggning"})],
            "norska": [ad("s1"), ad("s2", occupation_field={"label": "Data/IT"}, working_hours_type={"label": "Deltid"})],
            "norsk": [ad("s1", relevance=0.9)],
        }  # fmt: skip

    def __call__(self, url, headers):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        key = "country" if "country" in params else params["q"]
        hits = self.by_query[key] if params.get("offset") == "0" else []
        return HttpResponse(200, {}, json.dumps({"hits": hits}).encode())


def swedish(app) -> dict[str, dict]:
    with app.state.db.session() as conn:
        rows = conn.execute("SELECT * FROM listings WHERE source = 'jobtech'").fetchall()
    return {row["source_id"]: dict(row) for row in rows}


def test_imports_ads_relevant_to_norway(app, client):
    fake = FakeJobSearch()
    report = jobtech.sync(app.state.db, app.state.settings, http=fake)
    assert report.created == 3
    rows = swedish(app)
    assert (
        rows["n1"]["county"] == "oslo"
        and rows["n1"]["location"] == "Oslo"
        and rows["n1"]["category"] == "jobb-bygg"
    )
    assert rows["s1"]["location"] == "Göteborg, Sverige" and rows["s1"]["category"] == "jobb-handel"
    assert rows["s2"]["category"] == "jobb-it"
    assert json.loads(rows["s2"]["attributes"])["employment_type"] == "part_time"
    attributes = json.loads(rows["s1"]["attributes"])
    assert attributes == {
        "employer": "Nordisk Service AB",
        "employment_type": "full_time",
        "deadline": "2099-11-04",
        "salary": "Fast månadslön",
    }
    assert rows["s1"]["apply_url"] == "https://jobb.example.se/apply/s1"
    assert "Karin" not in json.dumps(rows)  # contact persons are left out

    page = client.get(f"/annonse/{rows['s1']['id']}").text
    assert "Fra Platsbanken (Arbetsförmedlingen, Sverige)" in page and "CC0" in page
    assert "Søk på stillingen" in page

    # The relevance score differs per query and run; it must not count as a change.
    assert jobtech.sync(app.state.db, app.state.settings, http=fake).unchanged == 3
    fake.by_query["norska"] = [ad("s1", headline="Kundtjänst med norska, Göteborg")]
    fake.by_query["norsk"] = []
    report = jobtech.sync(app.state.db, app.state.settings, http=fake)
    assert (report.updated, report.removed) == (1, 1)
    assert set(swedish(app)) == {"n1", "s1"}
