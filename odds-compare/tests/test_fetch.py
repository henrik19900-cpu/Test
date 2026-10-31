from datetime import datetime, timedelta

import pytest
from conftest import load_fixture

from oddscompare import config, db, fetch
from oddscompare.sources import SourceError
from oddscompare.sources.nt import parse_event_groups
from oddscompare.sources.reference import parse_odds

NT_SAMPLE = load_fixture("nt_sample.json")
REF_SAMPLE = load_fixture("odds_api_io_sample.json")
NOW = datetime.fromisoformat(NT_SAMPLE["fetched_at_utc"])
N = 84  # the fixture's matches within the default 7 days (four more come later)


class FakeNT:
    name = "norsk_tipping"

    def __init__(self, fail=None):
        self.fail = fail
        self.calls = 0

    def fetch(self, days_ahead):
        self.calls += 1
        if self.fail:
            raise self.fail
        return parse_event_groups(NT_SAMPLE["event_groups"], NOW, days_ahead)


class FakeReference:
    name = "odds_api_io"

    def __init__(self, fail=None):
        self.fail = fail
        self.calls = 0
        self.kept = None

    def fetch(self, days_ahead, want=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        events = parse_odds(REF_SAMPLE["odds"], REF_SAMPLE["bookmaker"])
        events = [e for e in events if want is None or want(e.home, e.away, e.kickoff_utc)]
        self.kept = len(events)
        return events


@pytest.fixture
def cfg(tmp_path):
    root = tmp_path
    (root / "data").mkdir()
    (root / "data" / "team_aliases.yaml").write_text(
        (config.Path(__file__).parents[1] / "data" / "team_aliases.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return config.Config().resolve(root)


def run(cfg, conn, nt, ref, when=NOW):
    sleeps = []
    report = fetch.run_once(cfg, conn, nt, ref, sleep=sleeps.append, clock=lambda: when)
    return report, sleeps


def test_a_round_stores_both_sources_and_pairs_them(cfg, conn):
    ref = FakeReference()
    report, _ = run(cfg, conn, FakeNT(), ref)
    assert [(s.name, s.status, s.n_events) for s in report.sources] == [
        ("norsk_tipping", "ok", N),
        ("odds_api_io", "ok", ref.kept),
    ]
    assert report.matched == N and report.unmatched == 0
    assert ref.kept < 98  # the distractors nobody can match were not fetched
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == N
    assert (
        conn.execute(
            "SELECT COUNT(DISTINCT event_id) FROM latest_odds WHERE source = 'odds_api_io'"
        ).fetchone()[0]
        == N
    )
    assert [tuple(r) for r in conn.execute("SELECT source, status FROM fetch_log")] == [
        ("norsk_tipping", "ok"),
        ("odds_api_io", "ok"),
    ]


def test_a_second_round_adds_snapshots_to_the_same_events(cfg, conn):
    run(cfg, conn, FakeNT(), FakeReference())
    run(cfg, conn, FakeNT(), FakeReference(), when=NOW + timedelta(minutes=15))
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == N
    assert conn.execute("SELECT COUNT(DISTINCT fetched_at_utc) FROM odds_snapshots").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM latest_odds").fetchone()[0] == N * 2 * 3


def test_a_failing_reference_does_not_stop_norsk_tipping(cfg, conn):
    ref = FakeReference(fail=SourceError("Odds-API.io svarte 502"))
    report, sleeps = run(cfg, conn, FakeNT(), ref)
    assert ref.calls == 3 and sleeps == [2.0, 4.0]  # three attempts, exponential backoff
    assert [(s.name, s.status) for s in report.sources] == [("norsk_tipping", "ok"), ("odds_api_io", "error")]
    assert report.ok
    row = conn.execute("SELECT status, error FROM fetch_log WHERE source = 'odds_api_io'").fetchone()
    assert tuple(row) == ("error", "Odds-API.io svarte 502")
    assert conn.execute("SELECT COUNT(DISTINCT event_id) FROM latest_odds").fetchone()[0] == N


def test_a_failing_norsk_tipping_does_not_stop_the_reference(cfg, conn):
    run(cfg, conn, FakeNT(), FakeReference())  # an earlier round knows the matches
    nt = FakeNT(fail=SourceError("Norsk Tipping krever nå innlogging", retryable=False))
    report, sleeps = run(cfg, conn, nt, FakeReference(), when=NOW + timedelta(minutes=15))
    assert nt.calls == 1 and sleeps == []  # not retried: another attempt would not help
    assert [(s.name, s.status) for s in report.sources] == [("norsk_tipping", "error"), ("odds_api_io", "ok")]
    newest = conn.execute(
        "SELECT MAX(fetched_at_utc) FROM odds_snapshots WHERE source = 'odds_api_io'"
    ).fetchone()[0]
    assert newest == db.iso(NOW + timedelta(minutes=15))


def test_both_failing_is_reported(cfg, conn):
    report, _ = run(
        cfg, conn, FakeNT(fail=RuntimeError("bug")), FakeReference(fail=SourceError("x", retryable=False))
    )
    assert not report.ok
    assert report.sources[0].error == "RuntimeError: bug"


def test_unmatched_matches_are_logged_with_their_best_candidate(cfg, conn):
    (cfg.aliases).write_text("", encoding="utf-8")  # without aliases some clubs are not recognised
    report, _ = run(cfg, conn, FakeNT(), FakeReference())
    assert 0 < report.unmatched < N * 0.25
    row = conn.execute("SELECT best_candidate, score FROM unmatched WHERE raw_home = 'Odd'").fetchone()
    assert row["best_candidate"] == "Odds BK - Sandnes Ulf" and 80 <= row["score"] < 90
    # Once the alias is added, the next round matches it and clears it from the list.
    cfg.aliases.write_text("Odd: [Odds BK]\n", encoding="utf-8")
    run(cfg, conn, FakeNT(), FakeReference(), when=NOW + timedelta(minutes=15))
    assert conn.execute("SELECT COUNT(*) FROM unmatched WHERE raw_home = 'Odd'").fetchone()[0] == 0


def test_a_cached_norsk_tipping_answer_is_not_stored_twice(cfg, conn):
    nt = FakeNT()
    nt.fetched_at = NOW  # as NorskTipping reports when it serves its cache
    run(cfg, conn, nt, FakeReference())
    run(cfg, conn, nt, FakeReference(), when=NOW + timedelta(minutes=2))
    rows = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT fetched_at_utc) FROM odds_snapshots WHERE source = 'norsk_tipping'"
    ).fetchone()
    assert tuple(rows) == (N * 3, 1)


def test_run_forever_refuses_short_intervals(cfg):
    with pytest.raises(ValueError):
        fetch.run_forever(cfg, 4)


def test_summary_mentions_errors():
    report = fetch.FetchReport(
        started_at=NOW, sources=[fetch.SourceReport("odds_api_io", "error", error="kvoten er brukt opp")]
    )
    assert "FEIL – kvoten er brukt opp" in fetch.summary(report)


def test_config_file_is_valid(tmp_path):
    cfg = config.load(config.Path(__file__).parents[1] / "config.yaml")
    assert cfg.margin_method == "proportional" and cfg.interval_minutes >= 5
    assert cfg.database.is_absolute()
    bad = tmp_path / "config.yaml"
    bad.write_text("interval_minutes: 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config.load(bad)
