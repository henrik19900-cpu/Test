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


def test_the_page_shows_every_match_best_ev_first(filled_app):
    app = filled_app.run()
    assert not app.exception
    assert [m.label for m in app.metric] == ["Kamper", "Med EV > 0", "Snittmargin NT / referanse"]
    best = [_best_ev(card) for card in _cards(app)]
    assert len(best) == 24  # a full page: all matches by default, not only value bets
    priced = [b for b in best if b is not None]
    assert priced == sorted(priced, reverse=True) and best[: len(priced)] == priced  # no EV comes last
    assert min(priced) < 0  # matches under the minimum EV are shown too


def _cards(app) -> list[str]:
    return [m.value for m in app.markdown if 'class="oc-teams"' in m.value]


def _best_ev(card: str) -> float | None:
    """The best «EV +2,8 %» on a card, as 2.8; None when the card has no EV."""
    values = []
    for text in card.split("EV ")[1:]:
        try:
            values.append(float(text.split(" %")[0].replace(",", ".").replace("−", "-")))
        except ValueError:
            pass
    return max(values, default=None)


def test_value_bets_only_and_the_unmatched_tab(filled_app):
    app = filled_app.run()
    everything = len(_cards(app))
    [value_only] = [t for t in app.toggle if t.label == "Bare verdispill"]
    value_only.set_value(True).run()
    assert not app.exception
    best = [_best_ev(card) for card in _cards(app)]
    assert 0 < len(best) < everything and all(b is not None and b >= 0 for b in best)  # minimum EV 0 %
    assert any("Alle kommende" in i.value for i in app.info) or app.dataframe


def test_searching_for_a_team(filled_app):
    app = filled_app.run()
    [search] = [t for t in app.text_input if t.label == "Søk etter lag"]
    search.set_value("bodo").run()  # without ø
    assert not app.exception
    cards = _cards(app)
    assert cards and all("Bodø/Glimt" in card for card in cards)
    [search] = [t for t in app.text_input if t.label == "Søk etter lag"]  # from the new run
    search.set_value("Ingen slikt lag").run()
    assert not _cards(app) and any("Ingen kamper med «Ingen slikt lag»" in i.value for i in app.info)


def test_search_cards_ignores_case_special_letters_and_club_words(conn):
    store(conn, (2.05, 3.60, 3.30), (2.10, 3.40, 3.70), sid="1")
    cards = dashboard.load_cards(conn, "odds_api_io", "proportional", NOW, NOW + timedelta(days=7))
    [card] = cards
    home = card.home
    assert dashboard.search_cards(cards, "") == cards and dashboard.search_cards(cards, "  ") == cards
    assert dashboard.search_cards(cards, home.upper()[:4]) == cards
    assert dashboard.search_cards(cards, f"FK {home}") == cards  # club words are left out
    assert dashboard.search_cards(cards, "zzz") == []


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


def card_with_competitors(nt, books, ref=None):
    return dashboard.Card(
        event_id=1, league="L", home="A", away="B", kickoff_utc=KICKOFF, nt_odds=list(nt), nt_fetched=NOW,
        ref_odds=list(ref) if ref else None, competitors={f"the_odds_api:{k}": list(v) for k, v in books.items()},
    )  # fmt: skip


def test_where_norsk_tipping_stands_on_each_outcome():
    card = card_with_competitors(
        (4.10, 3.85, 1.77), {"betsson": (4.20, 3.80, 1.80), "unibet_se": (4.10, 3.70, 1.85)}
    )
    assert card.position(0) == (2, 3, pytest.approx(4.10 / 4.20 - 1))  # Betsson higher; Unibet equal
    assert card.position(1) == (1, 3, 0.0)  # best
    assert card.position(2)[0] == 3 and card.nt_worst(2)
    assert card.nt_worst(0)  # shares the lowest price with Unibet, as a shared best price counts as best
    assert not card.nt_worst(1)
    assert card.margin_place() == (3, 3)  # the highest margin of the three
    assert card_with_competitors((2, 3, 4), {}).position(0) is None


def test_the_market_summary():
    cards = [
        card_with_competitors(
            (2.00, 3.40, 3.80),
            {"betsson": (2.10, 3.40, 3.70), "unibet_se": (2.05, 3.30, 3.90)},
            ref=(2.08, 3.55, 4.00),
        ),
        card_with_competitors((1.50, 4.00, 6.00), {"betsson": (1.55, 4.10, 6.50)}),
        card_with_competitors((2.50, 3.00, 3.00), {}),  # no competitors: left out
    ]
    m = dashboard.market(cards)
    assert (m.matches, m.outcomes) == (2, 6)
    assert m.best_share == pytest.approx(1 / 6)  # only the draw in the first match, shared with Betsson
    assert m.worst_share == pytest.approx(4 / 6)
    names = [name for name, _, _ in m.margins]
    assert names[0] == "Pinnacle" and set(names) == {"Norsk Tipping", "Pinnacle", "Betsson", "Unibet"}
    betsson = next(h for h in m.head_to_head if h.name == "Betsson")
    assert (betsson.outcomes, betsson.nt_higher, betsson.equal, betsson.nt_lower) == (6, 1, 1, 4)
    assert betsson.mean_gap < 0 and betsson.nt_margin > betsson.margin
    empty = dashboard.market([])
    assert empty.best_share is None and empty.margins == [] and empty.head_to_head == []


def test_the_market_tab_and_the_positions_on_the_cards(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    conn = db.connect(tmp_path / "data" / "odds.db")
    now = datetime.now(UTC)
    db.log_fetch(conn, "norsk_tipping", now, "ok", 1)
    nt = raw_event(
        source_event_id="m1",
        kickoff_utc=now + timedelta(days=1),
        odds={"home": 2.00, "draw": 3.40, "away": 3.80},
    )
    event_id = db.create_event(conn, nt)
    db.link(conn, nt, event_id)
    db.add_snapshot(conn, event_id, nt, now)
    for key, (h, d, a) in {
        "betsson": (2.10, 3.40, 3.70),
        "unibet_se": (2.05, 3.30, 3.90),
        "coolbet": (2.08, 3.35, 3.75),
    }.items():
        db.add_snapshot(
            conn,
            event_id,
            nt.model_copy(
                update={"source": f"the_odds_api:{key}", "odds": {"home": h, "draw": d, "away": a}}
            ),
            now,
        )
    ref = nt.model_copy(update={"source": "the_odds_api", "odds": {"home": 2.08, "draw": 3.55, "away": 4.00}})
    db.add_snapshot(conn, event_id, ref, now)
    conn.commit()
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception  # every match is shown by default
    [card] = [m.value for m in app.markdown if 'class="oc-teams"' in m.value]
    assert "Dårligst av 4" in card and "Best av 4" in card and "Nr. 2 av 4" in card
    assert "(høyest av 4)" in card
    [tab] = [t for t in app.tabs if t.label == "NT mot markedet"]
    assert [m.label for m in tab.metric][:2] == ["NT har beste odds", "NT har dårligste odds"]
    assert any("beste odds på" in m.value for m in tab.markdown)
    assert tab.get("plotly_chart") and len(tab.dataframe) == 2
    assert any(
        "Her har Norsk Tipping best odds** (1 utfall" in m.value for m in tab.markdown
    )  # the shared draw
    [best_only] = [t for t in app.toggle if t.label == "Bare der NT har best odds"]
    app = best_only.set_value(True).run()
    assert len([m for m in app.markdown if 'class="oc-teams"' in m.value]) == 1


def test_the_outcomes_where_norsk_tipping_has_the_best_price():
    alone = card_with_competitors(
        (2.20, 3.40, 3.10),
        {"betsson": (2.10, 3.40, 3.30), "unibet_se": (2.05, 3.30, 3.40)},
        ref=(2.08, 3.55, 4.00),
    )
    behind = card_with_competitors((1.50, 4.00, 6.00), {"betsson": (1.55, 4.10, 6.50)})
    best = dashboard.nt_best([behind, alone])
    assert [(b.outcome, b.shared) for b in best] == [(0, False), (1, True)]  # biggest lead first
    home = best[0]
    assert (
        home.runner_up == "Betsson"
        and home.runner_up_odds == 2.10
        and home.lead == pytest.approx(2.20 / 2.10 - 1)
    )
    assert best[1].runner_up == "Betsson" and best[1].lead == 0.0
    assert alone.nt_best_outcomes() == [0, 1] and behind.nt_best_outcomes() == []
    assert dashboard.filter_cards([alone, behind], [], 0.05, False, nt_best_only=True) == [alone]


def test_without_reference_odds_the_page_shows_norsk_tippings_odds_and_offers_the_fetch(
    tmp_path, monkeypatch
):
    """As on a new Streamlit Cloud app: no reference odds yet, and the sidebar is hidden on a phone."""
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    shift = datetime.now(UTC) - FIXTURE_NOW
    monkeypatch.setattr(fetch, "build_sources", lambda cfg: (ShiftedNT(shift), ShiftedReference(shift)))
    real_run_once, asked = fetch.run_once, []

    def run_once(cfg, include_reference=False, **kwargs):
        if include_reference:
            asked.append(len(cfg.reference.the_odds_api.leagues))
            return fetch.FetchReport(started_at=datetime.now(UTC))
        return real_run_once(cfg, **kwargs)

    monkeypatch.setattr(fetch, "run_once", run_once)
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception and asked == []  # opening the page spends nothing
    assert [m for m in app.markdown if 'class="oc-teams"' in m.value]  # Norsk Tipping's odds, without EV
    assert any("Ingen referanseodds er hentet her ennå" in i.value for i in app.info)
    [button] = [b for b in app.button if b.label.startswith("Oppdater referanseodds")]
    assert "opptil 21 kreditter" in button.label
    app = button.click().run()
    assert not app.exception and asked == [21]
    assert any("Ferdig på" in s.value for s in app.success)  # the result shows on the page, too


def test_secrets_that_cannot_be_read_are_reported_with_how_to_fix_them(tmp_path, monkeypatch):
    """A value without quotes is not valid TOML; Streamlit then raises on every use of st.secrets."""
    import streamlit
    from streamlit.errors import StreamlitSecretNotFoundError

    class Unreadable:
        def __getattr__(self, name):
            raise StreamlitSecretNotFoundError("Error parsing secrets file at /app/.streamlit/secrets.toml")

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    db.log_fetch(db.connect(tmp_path / "data" / "odds.db"), "norsk_tipping", datetime.now(UTC), "ok", 0)
    monkeypatch.setattr(streamlit, "secrets", Unreadable())
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    [error] = [e.value for e in app.error if "Secrets" in e.value]
    assert "kunne ikke leses" in error and 'THE_ODDS_API_KEY = "nøkkelen"' in error


def test_the_app_reads_the_stored_bet_log_back_after_a_restart(tmp_path, monkeypatch):
    import streamlit

    from oddscompare import bets, remote

    before = db.connect(tmp_path / "before.db")
    bet_id = bets.add(
        before, nt_event_id="1", league="England - Championship", home="Wrexham", away="Middlesbrough",
        kickoff_utc=datetime.now(UTC) + timedelta(days=1), outcome="home", odds=4.10, stake=250.0,
    )  # fmt: skip
    stored = {remote.BETS: bets.to_csv(bets.all_bets(before))}

    class Store:
        def get(self, key):
            return stored.get(key)

        def put(self, key, value):
            stored[key] = value

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    db.log_fetch(db.connect(tmp_path / "data" / "odds.db"), "norsk_tipping", datetime.now(UTC), "ok", 0)
    monkeypatch.setattr(remote, "store_from_env", lambda: Store())
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    streamlit.cache_resource.clear()  # a new app process
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    [tab] = [t for t in app.tabs if t.label == "Mine spill"]
    assert tab.metric[0].label == "Spill" and tab.metric[0].value == "1"
    assert any("lagres i databasen" in c.value for c in tab.caption)
    assert bets.all_bets(db.connect(tmp_path / "data" / "odds.db"))[0]["id"] == bet_id
    streamlit.cache_resource.clear()


def test_code_changed_on_disk_is_imported_again(filled_app):
    """As on Streamlit Cloud after a pull: the new app.py reruns while the old modules are still loaded."""
    import os
    import sys

    import oddscompare.dashboard as loaded

    def package():
        return {n: m for n, m in sys.modules.items() if n == "oddscompare" or n.startswith("oddscompare.")}

    before = package()
    path = Path(loaded.__file__)
    stat = path.stat()
    search_cards = loaded.search_cards
    try:
        app = filled_app.run()
        assert not app.exception and sys.modules["oddscompare.dashboard"] is loaded  # nothing changed
        app.run()
        assert sys.modules["oddscompare.dashboard"] is loaded
        del loaded.search_cards  # the code loaded before the pull...
        os.utime(path, (stat.st_atime, stat.st_mtime + 30))  # ...and the file the pull changed
        app.run()
        assert not app.exception and sys.modules["oddscompare.dashboard"] is not loaded
        assert sys.modules["oddscompare.dashboard"].search_cards
    finally:
        loaded.search_cards = search_cards
        os.utime(path, (stat.st_atime, stat.st_mtime))
        for name in package():
            del sys.modules[name]
        sys.modules.update(before)


def test_the_update_buttons_fetch_norsk_tipping_now_and_reference_odds(tmp_path, monkeypatch):
    """On the page, where a phone shows them: Norsk Tipping now (free), and the reference (credits)."""
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    shift = datetime.now(UTC) - FIXTURE_NOW
    nt_calls, asked = [], []

    class CountingNT(ShiftedNT):
        def fetch(self, days_ahead):
            nt_calls.append(1)
            return super().fetch(days_ahead)

    monkeypatch.setattr(fetch, "build_sources", lambda cfg: (CountingNT(shift), ShiftedReference(shift)))
    real_run_once = fetch.run_once

    def run_once(cfg, include_reference=False, **kwargs):
        if include_reference:
            asked.append(len(cfg.reference.the_odds_api.leagues))
            return fetch.FetchReport(started_at=datetime.now(UTC))
        return real_run_once(cfg, **kwargs)

    monkeypatch.setattr(fetch, "run_once", run_once)
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception and len(nt_calls) == 1 and asked == []  # old odds: fetched once on opening
    assert any("Norsk Tipping: " in c.value and "aldri hentet" in c.value for c in app.caption)
    [nt_button] = [b for b in app.button if b.label == "Oppdater Norsk Tipping"]
    app = nt_button.click().run()
    assert not app.exception and len(nt_calls) == 2 and asked == []  # fresh, but fetched again when asked
    [ref_button] = [b for b in app.button if b.label.startswith("Oppdater referanseodds")]
    app = ref_button.click().run()
    assert not app.exception and asked == [21]


def test_with_oddslink_the_button_costs_one_request(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("reference:\n  source: oddslink\n", encoding="utf-8")
    db.log_fetch(db.connect(tmp_path / "data" / "odds.db"), "norsk_tipping", datetime.now(UTC), "ok", 0)
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert any(b.label == "Oppdater referanseodds (1 forespørsel)" for b in app.button)
    assert any("Én forespørsel henter alle ligaene" in c.value for c in app.caption)
    assert "OddsLink" in app.caption[0].value  # «Norsk Tipping mot margin-fri referanse (OddsLink: Pinnacle)»


def test_a_sure_bet_is_found_with_its_profit_and_stake_split():
    sure = card_with_competitors(
        (2.30, 3.20, 3.00), {"betsson": (2.00, 3.60, 3.50), "unibet_se": (2.10, 3.40, 4.20)}
    )
    sure.competitors_fetched = {"the_odds_api:betsson": NOW - timedelta(hours=2)}  # Unibet's time unknown
    close = card_with_competitors(
        (2.00, 3.40, 3.80), {"betsson": (2.10, 3.40, 3.70), "unibet_se": (2.05, 3.30, 3.90)}
    )
    far = card_with_competitors((1.50, 4.00, 6.00), {"betsson": (1.55, 4.10, 6.50)})
    found, closest = dashboard.arbitrages([far, close, sure])
    [a] = found
    assert a.card is sure and a.odds == [2.30, 3.60, 4.20]
    assert a.books == [["Norsk Tipping"], ["Betsson"], ["Unibet"]]
    assert a.fetched == [NOW, NOW - timedelta(hours=2), None]
    assert a.total == pytest.approx(1 / 2.30 + 1 / 3.60 + 1 / 4.20)  # 0.951
    assert a.profit == pytest.approx(1 / a.total - 1) and round(a.profit * 100, 1) == 5.2
    split = a.split(1000)  # 1000 × (1/odds) / total, in whole kroner
    assert split.stakes == [457, 292, 250] and split.staked == 999
    assert split.returns == pytest.approx([1051.1, 1051.2, 1050.0])
    assert split.guaranteed == pytest.approx(1050.0) and split.profit == pytest.approx(51.0)
    # Not sure bets, but the closest, by the sum of 1/odds: 1.027 and 1.043.
    assert [b.card for b in closest] == [close, far]
    assert closest[0].total - 1 == pytest.approx(1 / 2.10 + 1 / 3.40 + 1 / 3.90 - 1)
    assert (
        closest[0].books[1] == ["Norsk Tipping", "Betsson"] and closest[0].profit < 0
    )  # a shared best price


def test_sure_bets_use_only_the_bookmakers_picked_and_leave_exchanges_out_by_default():
    card = card_with_competitors(
        (2.30, 3.20, 3.00),
        {"betsson": (2.00, 3.60, 3.30), "betfair_ex_eu": (2.10, 3.40, 4.40)},
        ref=(2.05, 3.50, 4.50),
    )
    books = dashboard.arbitrage_books([card])
    assert books == [dashboard.NT, dashboard.REFERENCE, "the_odds_api:betfair_ex_eu", "the_odds_api:betsson"]
    assert dashboard.default_books(books) == [dashboard.NT, "the_odds_api:betsson"]
    sure, [a] = dashboard.arbitrages([card])  # Norsk Tipping and Betsson: 1.016, no sure bet
    assert not sure and a.odds == [2.30, 3.60, 3.30] and a.books[2] == ["Betsson"]
    [a], _ = dashboard.arbitrages([card], [*books[:1], *books[2:]])  # with Betfair, when picked
    assert a.odds == [2.30, 3.60, 4.40] and a.books[2] == ["Betfair Exchange"]
    [a], _ = dashboard.arbitrages([card], [dashboard.NT, dashboard.REFERENCE], "Pinnacle")
    assert a.odds == [2.30, 3.50, 4.50] and a.books == [["Norsk Tipping"], ["Pinnacle"], ["Pinnacle"]]
    _, [a] = dashboard.arbitrages([card], [dashboard.NT])
    assert a.odds == card.nt_odds and a.total - 1 == pytest.approx(card.nt_margin)
    assert dashboard.arbitrages([card], []) == ([], [])
    assert dashboard.is_exchange("the_odds_api:betfair_ex_uk")
    assert not dashboard.is_exchange("the_odds_api:betsson")


def test_the_sure_bet_tab(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text(
        "reference:\n  the_odds_api:\n    competitors: [unibet_se, betsson, betfair_ex_eu]\n",
        encoding="utf-8",
    )
    conn = db.connect(tmp_path / "data" / "odds.db")
    now = datetime.now(UTC)
    db.log_fetch(conn, "norsk_tipping", now, "ok", 2)
    matches = {  # Norsk Tipping, Betsson, Unibet, Betfair
        ("Brann", "Molde"): [(2.30, 3.20, 3.00), (2.00, 3.60, 3.30), (2.10, 3.40, 4.20), (2.20, 3.70, 4.50)],
        ("Viking", "Odd"): [(2.00, 3.40, 3.80), (2.10, 3.40, 3.70), (2.05, 3.30, 3.90), (2.30, 3.80, 4.20)],
    }
    for (home, away), (nt_odds, *books) in matches.items():
        nt = raw_event(
            source_event_id=home,
            home=home,
            away=away,
            kickoff_utc=now + timedelta(days=1),
            odds=dict(zip(("home", "draw", "away"), nt_odds, strict=True)),
        )
        event_id = db.create_event(conn, nt)
        db.link(conn, nt, event_id)
        db.add_snapshot(conn, event_id, nt, now)
        for key, odds in zip(("betsson", "unibet_se", "betfair_ex_eu"), books, strict=True):
            competitor = nt.model_copy(
                update={
                    "source": f"the_odds_api:{key}",
                    "odds": dict(zip(("home", "draw", "away"), odds, strict=True)),
                }
            )
            db.add_snapshot(conn, event_id, competitor, now)
    conn.commit()
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    [tab] = [t for t in app.tabs if t.label == "Sikker gevinst"]
    [picker] = [m for m in tab.multiselect if m.label == "Spillselskaper du har konto hos"]
    assert picker.value == ["norsk_tipping", "the_odds_api:betsson", "the_odds_api:unibet_se"]  # no exchange
    assert [n.value for n in tab.number_input if n.label == "Total innsats (kr)"] == [1000]
    [bet] = [
        m.value for m in tab.markdown if 'class="oc-arb-teams"' in m.value
    ]  # Viking – Odd only with Betfair
    assert "Brann – Molde" in bet and "457 kr" in bet and "+51 kr" in bet and "+5,1 %" in bet
    assert "Prisene ble hentet for under 1 min siden" in bet
    app = picker.unselect("the_odds_api:unibet_se").run()
    assert not app.exception
    [tab] = [t for t in app.tabs if t.label == "Sikker gevinst"]
    assert any("Ingen sikker gevinst" in i.value for i in tab.info)
    [closest] = tab.dataframe
    assert list(closest.value["Kamp"]) == ["Brann – Molde", "Viking – Odd"]
    assert any("annullere" in c.value for c in tab.caption)


def test_with_oddslink_the_cards_show_the_competitors_odds(tmp_path, monkeypatch):
    """The app took its competitor list from The Odds API's settings only, so with OddsLink none showed."""
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("reference:\n  source: oddslink\n", encoding="utf-8")
    conn = db.connect(tmp_path / "data" / "odds.db")
    now = datetime.now(UTC)
    kickoff = now + timedelta(hours=5)
    nt = raw_event(
        source_event_id="nt1", kickoff_utc=kickoff, odds={"home": 2.30, "draw": 3.40, "away": 3.10}
    )
    event_id = db.create_event(conn, nt)
    db.link(conn, nt, event_id)
    db.add_snapshot(conn, event_id, nt, now)
    for source, odds in {
        "oddslink": (2.20, 3.50, 3.40),
        "oddslink:unibet": (2.25, 3.45, 3.30),
        "oddslink:bet365": (2.40, 3.40, 3.20),
    }.items():
        raw = raw_event(source=source, source_event_id="o1", kickoff_utc=kickoff,
                        odds=dict(zip(("home", "draw", "away"), odds, strict=True)))  # fmt: skip
        db.link(conn, raw, event_id)
        db.add_snapshot(conn, event_id, raw, now)
    db.log_fetch(conn, "norsk_tipping", now, "ok", 1)
    conn.commit()
    monkeypatch.setenv("ODDSCOMPARE_CONFIG", str(tmp_path / "config.yaml"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert any(e.label.startswith("Konkurrentenes odds (2)") for e in app.expander)
    [picker] = [m for m in app.multiselect if m.label == "Spillselskaper du har konto hos"]
    assert set(picker.value) == {"norsk_tipping", "oddslink:unibet", "oddslink:bet365"}
