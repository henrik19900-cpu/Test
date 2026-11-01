from datetime import UTC, datetime, timedelta

import pytest
from conftest import raw_event

from oddscompare import bets, config, db, fetch

KICKOFF = datetime(2026, 11, 4, 19, 45, tzinfo=UTC)
PLACED = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)


def log(conn, **kwargs):
    values = {
        "nt_event_id": "nt1",
        "league": "England - Championship",
        "home": "Wrexham",
        "away": "Middlesbrough",
        "kickoff_utc": KICKOFF,
        "outcome": "home",
        "odds": 3.70,
        "stake": 250,
        "fair_at_bet": 3.61,
        "fair_source_at_bet": "konkurrenter",
        "placed_at": PLACED,
    }
    return bets.add(conn, **(values | kwargs))


def row(conn, bet_id):
    return next(b for b in bets.all_bets(conn) if b["id"] == bet_id)


def test_profit_follows_the_result(conn):
    bet_id = log(conn)
    assert bets.profit(row(conn, bet_id)) is None
    bets.set_result(conn, bet_id, "won")
    assert bets.profit(row(conn, bet_id)) == pytest.approx(675.0)  # 250 x (3.70 - 1)
    bets.set_result(conn, bet_id, "lost")
    assert bets.profit(row(conn, bet_id)) == -250
    bets.set_result(conn, bet_id, "void")
    assert bets.profit(row(conn, bet_id)) == 0
    assert bets.ev_at_bet(row(conn, bet_id)) == pytest.approx(3.70 / 3.61 - 1)
    with pytest.raises(ValueError):
        bets.set_result(conn, bet_id, "maybe")


def test_bad_bets_are_refused(conn):
    with pytest.raises(ValueError):
        log(conn, outcome="1")
    bet_id = log(conn)
    with pytest.raises(ValueError):
        bets.update(conn, bet_id, odds=1.0, stake=100, note="")


def store_event(conn):
    nt = raw_event(source_event_id="nt1", home="Wrexham", away="Middlesbrough", kickoff_utc=KICKOFF)
    event_id = db.create_event(conn, nt)
    db.link(conn, nt, event_id)
    return event_id


def snapshot(conn, event_id, source, odds, at):
    raw = raw_event(
        source=source,
        source_event_id=f"{source}-x",
        odds=dict(zip(("home", "draw", "away"), odds, strict=True)),
    )
    db.add_snapshot(conn, event_id, raw, at)


def test_closing_odds_are_the_last_reference_odds_before_kickoff(conn):
    event_id = store_event(conn)
    bet_id = log(conn)
    snapshot(
        conn, event_id, "the_odds_api", (3.80, 3.80, 2.00), PLACED - timedelta(hours=1)
    )  # before the bet
    assert bets.update_closing(conn, "the_odds_api", []) == 1
    assert bets.clv(row(conn, bet_id)) is None  # these odds are older than the bet: no CLV yet
    snapshot(conn, event_id, "the_odds_api", (3.50, 3.70, 2.10), KICKOFF - timedelta(minutes=20))
    snapshot(
        conn, event_id, "the_odds_api", (2.50, 3.70, 3.00), KICKOFF + timedelta(minutes=50)
    )  # in play: ignored
    assert bets.update_closing(conn, "the_odds_api", [], reference_name="Pinnacle") == 1
    bet = row(conn, bet_id)
    fair_home = 1 / (1 / 3.50 / (1 / 3.50 + 1 / 3.70 + 1 / 2.10))
    assert bet["closing_fair"] == pytest.approx(fair_home)
    assert bet["closing_source"] == "Pinnacle"
    assert bets.clv(bet) == pytest.approx(3.70 / fair_home - 1)
    assert bets.update_closing(conn, "the_odds_api", []) == 0  # nothing newer


def test_closing_odds_from_the_competitors_when_the_reference_has_none(conn):
    event_id = store_event(conn)
    bet_id = log(conn)
    at = KICKOFF - timedelta(hours=2)
    books = {
        "the_odds_api:betsson": (3.40, 3.60, 2.00),
        "the_odds_api:unibet_se": (3.55, 3.75, 2.07),
        "the_odds_api:betway": (3.25, 3.75, 1.95),
    }
    for source, odds in books.items():
        snapshot(conn, event_id, source, odds, at)
    assert bets.update_closing(conn, "the_odds_api", list(books)[:2]) == 0  # two are too few
    assert bets.update_closing(conn, "the_odds_api", list(books)) == 1
    bet = row(conn, bet_id)
    assert bet["closing_source"] == "konkurrenter" and 3.4 < bet["closing_fair"] < 3.8


def test_estimate_needs_ten_bets_and_reports_its_uncertainty():
    assert bets.estimate([]).n == 0
    few = bets.estimate([0.05] * 9)
    assert few.mean == pytest.approx(0.05) and few.p is None and not few.enough
    values = [0.02, 0.04] * 5  # mean 3 %, sd about 1.05 %
    e = bets.estimate(values)
    assert e.mean == pytest.approx(0.03) and e.enough
    assert e.low < 0.03 < e.high and e.p < 0.001
    noisy = bets.estimate([0.5, -0.45] * 10)  # mean 2.5 %, huge spread: far from sure
    assert noisy.p > 0.3 and noisy.bets_needed > 1000


def test_summary(conn):
    won = log(conn, odds=3.70, stake=250)
    lost = log(conn, odds=2.00, stake=100, fair_at_bet=2.10)
    log(conn, odds=1.80, stake=50)  # still open
    bets.set_result(conn, won, "won")
    bets.set_result(conn, lost, "lost")
    s = bets.summarize(bets.all_bets(conn))
    assert (s.bets, s.open) == (3, 1)
    assert s.staked == 350 and s.profit == pytest.approx(575.0)
    assert s.roi == pytest.approx(575 / 350)
    assert s.expected_profit == pytest.approx(250 * (3.70 / 3.61 - 1) + 100 * (2.00 / 2.10 - 1))


def test_csv_round_trip(conn, tmp_path):
    bet_id = log(conn, note="første spill, «Wrexham»")
    bets.set_result(conn, bet_id, "won")
    text = bets.to_csv(bets.all_bets(conn))
    other = db.connect(tmp_path / "other.db")
    assert bets.from_csv(other, text) == 1
    assert dict(row(other, bet_id)) == dict(row(conn, bet_id))
    assert bets.from_csv(other, text) == 1  # importing again updates, not duplicates
    assert len(bets.all_bets(other)) == 1
    with pytest.raises(ValueError, match="mangler kolonnene"):
        bets.from_csv(other, "id,odds\n1,2.0\n")


def test_a_reference_fetch_updates_the_closing_odds(tmp_path):
    (tmp_path / "config.yaml").write_text("reference:\n  source: odds_api_io\n", encoding="utf-8")
    cfg = config.load(tmp_path / "config.yaml")
    conn = db.connect(cfg.database)
    nt_event = raw_event(source_event_id="nt1", kickoff_utc=KICKOFF)

    class NT:
        name = "norsk_tipping"

        def fetch(self, days_ahead):
            return [nt_event]

    class Reference:
        name = "odds_api_io"

        def fetch(self, days_ahead, want=None):
            return [
                raw_event(
                    source="odds_api_io",
                    source_event_id="r1",
                    kickoff_utc=KICKOFF,
                    odds={"home": 2.0, "draw": 3.5, "away": 4.0},
                )
            ]

    now = KICKOFF - timedelta(days=1)
    fetch.run_once(cfg, conn, NT(), Reference(), clock=lambda: now)  # Norsk Tipping only
    bet_id = log(conn, home=nt_event.home, away=nt_event.away, placed_at=now)
    later = now + timedelta(hours=2)
    fetch.run_once(cfg, conn, NT(), Reference(), clock=lambda: later, include_reference=True)
    bet = row(conn, bet_id)
    assert bet["closing_at_utc"] == db.iso(later) and bets.clv(bet) is not None
