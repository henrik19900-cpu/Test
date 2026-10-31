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


def test_cards_are_sorted_by_best_ev_and_those_without_reference_come_last(conn):  # the default order
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
    # The reference is fetched only when asked for, so its age is not a warning unless a limit is given.
    assert card.stale(NOW, timedelta(minutes=30)) == ["norsk_tipping"]
    assert card.stale(NOW, timedelta(minutes=30), timedelta(minutes=30)) == ["norsk_tipping", "referanse"]
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
        cfg,
        nt=ShiftedNT(shift),
        reference=ShiftedReference(shift),
        clock=lambda: now,
        sleep=lambda s: None,
        include_reference=True,
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


def test_the_button_fetches_reference_odds_only_when_pressed(filled_app, monkeypatch):
    shift = datetime.now(UTC) - FIXTURE_NOW
    calls = []

    class CountingReference(ShiftedReference):
        def fetch(self, days_ahead, want=None):
            calls.append(days_ahead)
            return super().fetch(days_ahead, want)

    monkeypatch.setattr(fetch, "build_sources", lambda cfg: (ShiftedNT(shift), CountingReference(shift)))
    app = filled_app.run()
    assert calls == []  # opening the page spends nothing
    [button] = [b for b in app.button if b.label == "Hent referanseodds"]
    app = button.click().run()
    assert not app.exception
    assert calls == [7]
    assert any("odds_api_io: 98 kamper" in s.value for s in app.success)


def test_competitors_and_the_best_price_per_outcome(conn):
    event_id = store(conn, (2.05, 3.60, 3.30), (2.10, 3.40, 3.70))
    ev = raw_event(source="the_odds_api:betsson", source_event_id="r1")
    db.add_snapshot(
        conn, event_id, ev.model_copy(update={"odds": {"home": 2.15, "draw": 3.40, "away": 3.30}}), NOW
    )
    db.add_snapshot(
        conn,
        event_id,
        ev.model_copy(
            update={"source": "the_odds_api:unibet_se", "odds": {"home": 2.15, "draw": 3.5, "away": 3.25}}
        ),
        NOW,
    )
    [card] = dashboard.load_cards(
        conn,
        "odds_api_io",
        "proportional",
        NOW,
        NOW + timedelta(days=7),
        ["the_odds_api:betsson", "the_odds_api:unibet_se", "the_odds_api:coolbet"],
    )
    assert card.competitors == {
        "the_odds_api:betsson": [2.15, 3.40, 3.30],
        "the_odds_api:unibet_se": [2.15, 3.5, 3.25],
    }
    assert card.best_prices() == [
        (2.15, ["Betsson", "Unibet"]),
        (3.60, ["Norsk Tipping"]),
        (3.30, ["Norsk Tipping", "Betsson"]),
    ]
    assert card.nt_share_of_best == 1.0  # Norsk Tipping is best on the draw
    assert dashboard.bookmaker_name("the_odds_api:leovegas_se") == "LeoVegas"


def test_sorting(conn):
    store(
        conn,
        (1.70, 3.70, 4.90),
        (1.80, 3.80, 4.60),
        sid="value",
        kickoff=KICKOFF + timedelta(days=2),
        league="England - Premier League",
    )
    store(
        conn,
        (2.05, 3.10, 3.30),
        (2.10, 3.40, 3.70),
        sid="early",
        kickoff=KICKOFF,
        league="Norge - Eliteserien",
    )
    store(
        conn,
        (2.00, 3.60, 4.00),
        None,
        sid="no-ref",
        kickoff=KICKOFF + timedelta(days=1),
        league="Spania - Primera Division",
    )
    cards = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    order = lambda name: [c.nt_odds[0] for c in dashboard.sort_cards(cards, name)]  # noqa: E731
    assert order("Beste EV") == [1.70, 2.05, 2.00]  # no reference odds last
    assert order("Avsparkstid") == [2.05, 2.00, 1.70]
    assert order("Liga") == [1.70, 2.05, 2.00]  # England, Norge, Spania
    assert order("Lavest NT-margin") == [2.00, 1.70, 2.05]  # 2.8 %, 6.3 %, 11.3 %
    assert list(dashboard.SORTS)[0] == "Beste EV"


def test_the_page_fetches_norsk_tipping_itself_when_its_odds_are_old(tmp_path, monkeypatch):
    """As on Streamlit Cloud, where no `oddscompare run` keeps the odds fresh."""
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    calls = []

    class CountingNT(ShiftedNT):
        def fetch(self, days_ahead):
            calls.append("nt")
            return super().fetch(days_ahead)

    class NeverReference(ShiftedReference):
        def fetch(self, days_ahead, want=None):
            raise AssertionError("reference odds only with the button")

    shift = datetime.now(UTC) - FIXTURE_NOW
    monkeypatch.setattr(fetch, "build_sources", lambda cfg: (CountingNT(shift), NeverReference(shift)))
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception and calls == ["nt"]
    assert app.metric[0].value == "84"  # the matches are on the page at once
    app.run()  # fresh now: no second fetch
    assert calls == ["nt"]


def test_fair_odds_from_the_competitors_when_the_reference_has_none(conn):
    event_id = store(conn, (2.00, 3.40, 3.60), None)
    books = {"betsson": (2.10, 3.40, 3.50), "unibet_se": (2.05, 3.50, 3.55), "coolbet": (2.15, 3.30, 3.45)}
    for key, (h, d, a) in books.items():
        raw = raw_event(
            source=f"the_odds_api:{key}", source_event_id=f"x-{key}", odds={"home": h, "draw": d, "away": a}
        )
        db.add_snapshot(conn, event_id, raw, NOW)
    sources = [f"the_odds_api:{k}" for k in books]
    [card] = dashboard.load_cards(conn, "the_odds_api", "proportional", NOW, NOW + timedelta(days=7), sources)
    assert card.fair_from == "konkurrenter" and card.ref_odds is None
    stats = dashboard.summary([card])  # margins are averaged over matches the reference priced: none here
    assert stats["positive"] in (0, 1) and stats["nt_margin"] is None and stats["ref_margin"] is None
    expected = dashboard.consensus([list(v) for v in books.values()], "proportional")
    assert card.fair_odds == pytest.approx([1 / p for p in expected])
    assert sum(expected) == pytest.approx(1.0)
    # Two competitors are too few to stand in for the reference.
    [card] = dashboard.load_cards(
        conn, "the_odds_api", "proportional", NOW, NOW + timedelta(days=7), sources[:2]
    )
    assert card.fair_odds is None and card.ev is None


def test_the_league_picker_limits_what_a_request_pays_for(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    db.log_fetch(db.connect(tmp_path / "data" / "odds.db"), "norsk_tipping", datetime.now(UTC), "ok", 0)
    asked = []

    def fake_run_once(cfg, include_reference=False, **kwargs):
        asked.append((include_reference, cfg.reference.the_odds_api.leagues))
        return fetch.FetchReport(started_at=datetime.now(UTC))

    monkeypatch.setattr(fetch, "run_once", fake_run_once)
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    [picker] = [m for m in app.multiselect if m.label == "Ligaer"]
    assert len(picker.value) == 21
    picker.set_value(["soccer_norway_eliteserien", "soccer_epl"]).run()
    assert any("opptil 2 kreditter" in c.value for c in app.caption)
    [button] = [b for b in app.button if b.label == "Hent referanseodds"]
    button.click().run()
    assert asked == [(True, ["soccer_norway_eliteserien", "soccer_epl"])]


def test_a_reference_with_an_unusually_wide_margin_is_flagged(conn):
    store(conn, (1.11, 7.8, 14.5), (1.15, 6.37, 11.08), sid="wide")  # Pinnacle at 11.7 %, as seen 31.10.2026
    store(conn, (2.05, 3.10, 3.30), (2.10, 3.40, 3.70), sid="normal")  # 4.1 %
    cards = {
        c.nt_odds[0]: c
        for c in dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    }
    assert cards[1.11].doubtful and not cards[2.05].doubtful


def test_the_home_screen_files_are_served():
    """The icon and manifest a phone reads for «Add to Home Screen» exist and are served by Streamlit."""
    import json
    import tomllib

    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["short_name"] == "Odds" and manifest["display"] == "standalone"
    for icon in manifest["icons"]:
        assert (ROOT / "static" / icon["src"]).exists()
    assert (ROOT / "static" / "apple-touch-icon.png").exists()
    for config_file in (ROOT / ".streamlit" / "config.toml", ROOT.parent / ".streamlit" / "config.toml"):
        assert tomllib.loads(config_file.read_text(encoding="utf-8"))["server"]["enableStaticServing"] is True


def test_a_bet_is_logged_from_a_card_and_shows_under_my_bets(filled_app):
    app = filled_app.run()
    [tab] = [t for t in app.tabs if t.label == "Mine spill"]
    assert any("Ingen spill ennå" in i.value for i in tab.info)
    save = [b for b in app.button if b.label == "Lagre spill"][0]
    stake = [n for n in app.number_input if n.label == "Innsats (kr)"][0]
    stake.set_value(250)
    app = save.click().run()
    assert not app.exception
    [tab] = [t for t in app.tabs if t.label == "Mine spill"]
    assert [(m.label, m.value) for m in tab.metric][0] == ("Spill", "1")
    assert any(b.label == "Last ned spillogg (CSV)" for b in app.get("download_button"))


def test_a_card_warns_when_norsk_tipping_moved_after_the_reference(conn):
    store(conn, (3.70, 3.65, 1.90), (3.40, 3.60, 2.00), when=NOW)
    [card] = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    assert not card.nt_moved
    store(conn, (3.70, 3.65, 1.90), None, when=NOW + timedelta(hours=1))  # unchanged
    [card] = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    assert not card.nt_moved
    store(conn, (4.10, 3.85, 1.77), None, when=NOW + timedelta(hours=16))  # moved, as Wrexham did 31.10
    [card] = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    assert card.nt_moved
