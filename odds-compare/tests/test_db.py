from datetime import UTC, datetime, timedelta

from conftest import raw_event

from oddscompare import db


def test_schema_is_created_once_and_versioned(tmp_path):
    path = tmp_path / "odds.db"
    db.connect(path).close()
    conn = db.connect(path)  # opening again does not run the migrations twice
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    assert {"events", "source_events", "odds_snapshots", "unmatched", "fetch_log", "latest_odds"} <= names


def test_latest_odds_shows_the_newest_snapshot_per_source(conn):
    nt = raw_event()
    event_id = db.create_event(conn, nt)
    db.link(conn, nt, event_id)
    first = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    db.add_snapshot(conn, event_id, nt, first)
    db.add_snapshot(
        conn,
        event_id,
        nt.model_copy(update={"odds": {"home": 2.2, "draw": 3.3, "away": 3.6}}),
        first + timedelta(minutes=15),
    )
    ref = raw_event(source="odds_api_io", source_event_id="99", odds={"home": 2.0, "draw": 3.5, "away": 4.0})
    db.add_snapshot(conn, event_id, ref, first)

    rows = conn.execute("SELECT source, outcome, odds FROM latest_odds ORDER BY source, outcome").fetchall()
    assert [tuple(r) for r in rows] == [
        ("norsk_tipping", "away", 3.6),
        ("norsk_tipping", "draw", 3.3),
        ("norsk_tipping", "home", 2.2),
        ("odds_api_io", "away", 4.0),
        ("odds_api_io", "draw", 3.5),
        ("odds_api_io", "home", 2.0),
    ]
    assert conn.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0] == 9  # the history is kept


def test_links_find_their_event(conn):
    nt = raw_event()
    event_id = db.create_event(conn, nt)
    db.link(conn, nt, event_id)
    assert db.linked_event(conn, "norsk_tipping", "1") == event_id
    assert db.linked_event(conn, "norsk_tipping", "2") is None


def test_unmatched_is_updated_in_place_and_cleared(conn):
    nt = raw_event()
    seen = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    db.record_unmatched(conn, nt, "Fredrikstad FK - Rosenborg BK", 85.0, seen)
    db.record_unmatched(conn, nt, "Fredrikstad FK - Rosenborg BK", 86.0, seen + timedelta(minutes=15))
    rows = conn.execute("SELECT score, last_seen_utc FROM unmatched").fetchall()
    assert [tuple(r) for r in rows] == [(86.0, "2026-10-31T10:15:00Z")]
    db.clear_unmatched(conn, "norsk_tipping", [(nt.home, nt.away, nt.kickoff_utc)])
    assert conn.execute("SELECT COUNT(*) FROM unmatched").fetchone()[0] == 0


def test_prune_deletes_old_events_with_their_snapshots(conn):
    now = datetime(2026, 10, 31, tzinfo=UTC)
    old = raw_event(source_event_id="old", kickoff_utc=now - timedelta(days=91))
    new = raw_event(source_event_id="new", kickoff_utc=now - timedelta(days=89))
    for raw in (old, new):
        event_id = db.create_event(conn, raw)
        db.link(conn, raw, event_id)
        db.add_snapshot(conn, event_id, raw, raw.kickoff_utc)
    conn.commit()

    assert db.prune(conn, 90, now=now) == 1
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0] == 3
    assert db.linked_event(conn, "norsk_tipping", "old") is None


def test_fetch_log(conn):
    db.log_fetch(
        conn, "odds_api_io", datetime(2026, 10, 31, tzinfo=UTC), "error", error="kvoten er brukt opp"
    )
    row = conn.execute("SELECT source, status, n_events, error FROM fetch_log").fetchone()
    assert tuple(row) == ("odds_api_io", "error", 0, "kvoten er brukt opp")


def test_latest_odds_survives_out_of_order_inserts_and_pruning(conn):
    raw = raw_event()
    event_id = db.create_event(conn, raw)
    newer, older = datetime(2026, 10, 31, 11, tzinfo=UTC), datetime(2026, 10, 31, 10, tzinfo=UTC)
    db.add_snapshot(
        conn, event_id, raw.model_copy(update={"odds": {"home": 2.5, "draw": 3.0, "away": 3.0}}), newer
    )
    db.add_snapshot(conn, event_id, raw, older)  # a late write of an older snapshot does not win
    db.add_snapshot(conn, event_id, raw, newer)  # nor does the same snapshot twice
    assert conn.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0] == 6
    assert conn.execute("SELECT odds FROM latest_odds WHERE outcome = 'home'").fetchone()[0] == 2.5
    conn.commit()
    db.prune(conn, 0, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert conn.execute("SELECT COUNT(*) FROM latest_fetch").fetchone()[0] == 0


def test_thin_deletes_old_odds_but_keeps_each_sources_latest(conn):
    """The watcher's database: a week of matches checked hourly would grow by about 30 MB a day."""
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    raw = raw_event(kickoff_utc=now + timedelta(days=5))
    event_id = db.create_event(conn, raw)
    for hours in (30, 20, 6, 1):
        odds = {"home": 2.0 + hours / 100, "draw": 3.4, "away": 3.7}
        db.add_snapshot(conn, event_id, raw.model_copy(update={"odds": odds}), now - timedelta(hours=hours))
    reference = raw.model_copy(update={"source": "oddslink"})
    db.add_snapshot(conn, event_id, reference, now - timedelta(hours=30))  # its only odds, so its latest
    conn.commit()
    assert db.thin(conn, timedelta(hours=12), now=now) == 6  # Norsk Tipping's from 30 and 20 hours ago
    kept = conn.execute(
        "SELECT source, COUNT(DISTINCT fetched_at_utc) FROM odds_snapshots GROUP BY source ORDER BY source"
    ).fetchall()
    assert [tuple(r) for r in kept] == [("norsk_tipping", 2), ("oddslink", 1)]
    assert (
        conn.execute(
            "SELECT odds FROM latest_odds WHERE source = 'norsk_tipping' AND outcome = 'home'"
        ).fetchone()[0]
        == 2.01
    )
