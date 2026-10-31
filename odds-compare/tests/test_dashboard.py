from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import load_fixture, raw_event

from oddscompare import config, dashboard, db, fetch
from oddscompare.matching import Aliases
from oddscompare.sources.nt import parse_event_groups
from oddscompare.sources.reference import parse_odds

ROOT = Path(__file__).parents[1]
NT_SAMPLE = load_fixture("nt_sample.json")
REF_SAMPLE = load_fixture("odds_api_io_sample.json")
FIXTURE_NOW = datetime.fromisoformat(NT_SAMPLE["fetched_at_utc"])
KICKOFF = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def store(conn, nt_odds, ref_odds, when=NOW, sid="1", kickoff=KICKOFF, league="Norge - Eliteserien"):
    nt = raw_event(
        source_event_id=sid,
        odds=dict(zip(("home", "draw", "away"), nt_odds, strict=True)),
        kickoff_utc=kickoff,
        league=league,
    )
    event_id = db.linked_event(conn, nt.source, sid) or db.create_event(conn, nt)
    db.link(conn, nt, event_id)
    db.add_snapshot(conn, event_id, nt, when)
    if ref_odds:
        ref = raw_event(
            source="odds_api_io",
            source_event_id=f"r{sid}",
            odds=dict(zip(("home", "draw", "away"), ref_odds, strict=True)),
            kickoff_utc=kickoff,
        )
        db.link(conn, ref, event_id)
        db.add_snapshot(conn, event_id, ref, when)
    return event_id


def test_cards_carry_the_specification_numbers(conn):
    store(conn, (1.70, 3.70, 4.90), (1.80, 3.80, 4.60))
    [card] = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    assert card.fair_odds == pytest.approx([1.86, 3.94, 4.77], abs=0.005)
    assert [round(e * 100, 1) for e in card.ev] == [-8.8, -6.0, 2.8]
    assert round(card.nt_margin * 100, 1) == 6.3
    assert card.best_ev == pytest.approx(0.028, abs=0.001)


def test_cards_are_sorted_by_best_ev_and_those_without_reference_come_last(conn):
    store(conn, (2.05, 3.10, 3.30), (2.10, 3.40, 3.70), sid="a")  # best EV -6.2 %
    store(conn, (1.70, 3.70, 4.90), (1.80, 3.80, 4.60), sid="b")  # best EV +2.8 %
    store(conn, (2.00, 3.00, 4.00), None, sid="c")
    cards = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    assert [c.nt_odds[0] for c in cards] == [1.70, 2.05, 2.00]
    assert dashboard.filter_cards(cards, [], 0.0, show_all=False) == cards[:1]
    assert dashboard.filter_cards(cards, [], -0.10, show_all=False) == cards[:2]
    assert dashboard.filter_cards(cards, [], 0.0, show_all=True) == cards
    assert dashboard.filter_cards(cards, ["England - Premier League"], 0.0, show_all=True) == []


def test_the_margin_method_changes_the_numbers(conn):
    store(conn, (1.30, 5.50, 11.0), (1.25, 6.0, 12.0))
    by_method = {
        m: dashboard.load_cards(conn, "odds_api_io", m, NOW, NOW + timedelta(days=7))[0].fair_odds
        for m in ("proportional", "power", "shin")
    }
    assert by_method["power"][2] > by_method["proportional"][2]  # long shots get longer
    assert by_method["shin"][2] > by_method["proportional"][2]


def test_matches_that_kicked_off_or_are_outside_the_window_are_left_out(conn):
    store(conn, (2.0, 3.0, 4.0), None, sid="past", kickoff=NOW - timedelta(minutes=1))
    store(conn, (2.0, 3.0, 4.0), None, sid="soon", kickoff=NOW + timedelta(hours=3))
    store(conn, (2.0, 3.0, 4.0), None, sid="later", kickoff=NOW + timedelta(days=3))
    in_48h = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, dashboard.window_end("48 t", NOW))
    assert len(in_48h) == 1


def test_window_end_today_is_midnight_in_oslo():
    assert dashboard.window_end("I dag", NOW) == datetime(
        2026, 10, 31, 23, 0, tzinfo=UTC
    )  # 00:00 in Oslo (CET)
    # 23:30 UTC is already 00:30 the next day in Oslo, so «today» runs to the midnight after that.
    assert dashboard.window_end("I dag", datetime(2026, 10, 31, 23, 30, tzinfo=UTC)) == datetime(
        2026, 11, 1, 23, 0, tzinfo=UTC
    )
    assert dashboard.window_end("7 dager", NOW) == NOW + timedelta(days=7)


@pytest.mark.parametrize(
    ("ev", "css"), [(0.001, "pos"), (0.0, "neutral"), (-0.05, "neutral"), (-0.051, "neg"), (None, "none")]
)
def test_ev_colours(ev, css):
    assert dashboard.ev_class(ev) == css


def test_stale_odds_are_flagged(conn):
    store(conn, (2.0, 3.0, 4.0), (2.1, 3.2, 3.9), when=NOW - timedelta(minutes=45))
    [card] = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    assert card.stale(NOW, timedelta(minutes=30)) == ["norsk_tipping", "referanse"]
    assert card.stale(NOW, timedelta(minutes=60)) == []


def test_history_has_nt_and_fair_odds_per_outcome(conn):
    event_id = store(conn, (2.0, 3.0, 4.0), (2.1, 3.2, 3.9), when=NOW)
    store(conn, (2.1, 3.0, 3.8), (2.2, 3.2, 3.7), when=NOW + timedelta(minutes=15))
    frame = dashboard.history(conn, event_id, "odds_api_io", "proportional")
    assert (
        len(frame) == 12
        and set(frame["serie"]) == {"Norsk Tipping", "Fair"}
        and set(frame["utfall"]) == {"H", "U", "B"}
    )
    assert frame["tid"].iloc[0].tzinfo is not None


def test_summary(conn):
    store(conn, (1.70, 3.70, 4.90), (1.80, 3.80, 4.60), sid="b")
    store(conn, (2.00, 3.00, 4.00), None, sid="c")
    stats = dashboard.summary(
        dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    )
    assert stats["matches"] == 2 and stats["positive"] == 1
    assert round(stats["nt_margin"] * 100, 1) == 6.3


def test_alias_suggestions_from_near_misses(conn):
    nt = raw_event(home="Odd", away="Sandnes Ulf")
    db.record_unmatched(conn, nt, "Odds BK - Sandnes Ulf", 85.7, NOW)
    swapped = raw_event(home="GAIS", away="AIK", source_event_id="2")
    db.record_unmatched(conn, swapped, "AIK - GAIS (hjemme og borte byttet)", 100, NOW)
    far = raw_event(home="Bossekop", away="Alta", source_event_id="3")
    db.record_unmatched(conn, far, "Tromsø - Alta", 40, NOW)
    rows = dashboard.unmatched(conn, NOW)
    assert [r["raw_home"] for r in rows] == ["GAIS", "Odd", "Bossekop"]
    assert dashboard.alias_suggestions(rows, Aliases()) == {"Odd": ["Odds BK"]}


def test_fetch_status_shows_the_newest_row_per_source(conn):
    db.log_fetch(conn, "odds_api_io", NOW - timedelta(minutes=15), "ok", 80)
    db.log_fetch(conn, "odds_api_io", NOW, "error", error="kvoten er brukt opp")
    db.log_fetch(conn, "norsk_tipping", NOW, "ok", 300)
    status = {r["source"]: (r["status"], r["error"]) for r in dashboard.fetch_status(conn)}
    assert status == {"odds_api_io": ("error", "kvoten er brukt opp"), "norsk_tipping": ("ok", None)}
    assert dashboard.last_success(conn, "odds_api_io") == NOW - timedelta(minutes=15)


# The page itself, run headless with Streamlit's test harness against a database filled by a fetch round.


class ShiftedNT:
    """Norsk Tipping from the fixture, moved so its matches lie ahead of the real clock."""

    name = "norsk_tipping"

    def __init__(self, shift):
        self.shift = shift

    def fetch(self, days_ahead):
        events = parse_event_groups(NT_SAMPLE["event_groups"], FIXTURE_NOW, days_ahead)
        return [e.model_copy(update={"kickoff_utc": e.kickoff_utc + self.shift}) for e in events]


class ShiftedReference(ShiftedNT):
    name = "odds_api_io"

    def fetch(self, days_ahead, want=None):
        events = parse_odds(REF_SAMPLE["odds"], REF_SAMPLE["bookmaker"])
        return [e.model_copy(update={"kickoff_utc": e.kickoff_utc + self.shift}) for e in events]


@pytest.fixture
def filled_app(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "team_aliases.yaml").write_text(
        (ROOT / "data" / "team_aliases.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text("reference:\n  source: odds_api_io\n", encoding="utf-8")
    cfg = config.load(tmp_path / "config.yaml")
    now = datetime.now(UTC)
    shift = now - FIXTURE_NOW
    fetch.run_once(
        cfg, nt=ShiftedNT(shift), reference=ShiftedReference(shift), clock=lambda: now, sleep=lambda s: None
    )
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def test_the_page_shows_cards_sorted_by_ev(filled_app):
    app = filled_app.run()
    assert not app.exception
    assert [m.label for m in app.metric] == ["Kamper", "Med EV > 0", "Snittmargin NT / referanse"]
    cards = [m.value for m in app.markdown if 'class="oc-teams"' in m.value]
    assert cards, "no cards with the default filters"
    best_per_card = [max(map(_number, card.split("EV ")[1:])) for card in cards]
    assert best_per_card == sorted(best_per_card, reverse=True)
    assert all(b >= 0 for b in best_per_card)  # minimum EV 0 % by default


def _number(text: str) -> float:
    """«+2,8 %…» as shown on a card, to 2.8."""
    return float(text.split(" %")[0].replace(",", ".").replace("−", "-"))


def test_show_all_and_the_unmatched_tab(filled_app):
    app = filled_app.run()
    default = len([m for m in app.markdown if 'class="oc-teams"' in m.value])
    app.toggle[0].set_value(True).run()
    assert not app.exception
    shown = len([m for m in app.markdown if 'class="oc-teams"' in m.value])
    assert shown >= default and shown == min(84, 24)  # one page of cards
    assert any("Alle kommende" in i.value for i in app.info) or app.dataframe
