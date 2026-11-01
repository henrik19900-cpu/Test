import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oddscompare import db
from oddscompare.sources import RawEvent

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw_event(source="norsk_tipping", source_event_id="1", home="Fredrikstad", away="Rosenborg", **kwargs):
    defaults = {
        "league": "Norge - Eliteserien",
        "kickoff_utc": datetime(2026, 11, 1, 15, 0, tzinfo=UTC),
        "odds": {"home": 2.10, "draw": 3.40, "away": 3.70},
    }
    return RawEvent(
        source=source, source_event_id=source_event_id, home=home, away=away, **(defaults | kwargs)
    )


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()
