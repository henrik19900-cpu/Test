import os
from datetime import UTC, datetime

import pytest

from oddscompare import bets, db, remote

KICKOFF = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)


class MemoryStore:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.puts = 0

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value):
        self.values[key] = value
        self.puts += 1


def bet(conn, home="Wrexham", stake=250.0):
    return bets.add(
        conn,
        nt_event_id="8911314.1",
        league="England - Championship",
        home=home,
        away="Middlesbrough",
        kickoff_utc=KICKOFF,
        outcome="home",
        odds=4.10,
        stake=stake,
        fair_at_bet=3.62,
        fair_source_at_bet="Pinnacle",
    )


@pytest.fixture
def fresh(tmp_path):
    """A second app process after a restart: an empty database."""
    return db.connect(tmp_path / "after-restart.db")


def test_the_bet_log_comes_back_after_a_restart(conn, fresh):
    store = MemoryStore()
    first = bet(conn)
    bets.set_result(conn, first, "lost")
    remote.backup_bets(conn, store, None)
    assert remote.restore_bets(fresh, store) == 1
    [row] = bets.all_bets(fresh)
    assert (row["id"], row["home"], row["odds"], row["stake"], row["result"]) == (
        first,
        "Wrexham",
        4.1,
        250.0,
        "lost",
    )


def test_it_is_written_only_when_it_changed(conn):
    store = MemoryStore()
    digest = remote.backup_bets(conn, store, None)
    assert store.puts == 1  # the empty log, so a deleted last bet is not read back
    assert remote.backup_bets(conn, store, digest) == digest and store.puts == 1
    bet(conn)
    digest = remote.backup_bets(conn, store, digest)
    assert store.puts == 3  # the previous version is kept, then the new one written
    assert remote.backup_bets(conn, store, digest) == digest and store.puts == 3


def test_the_previous_version_is_kept(conn):
    store = MemoryStore()
    bet(conn, home="Wrexham")
    digest = remote.backup_bets(conn, store, None)
    bet(conn, home="Brann")
    remote.backup_bets(conn, store, digest)
    assert "Brann" in store.values[remote.BETS] and "Brann" not in store.values[remote.PREVIOUS]
    assert "Wrexham" in store.values[remote.PREVIOUS]


def test_a_bet_made_before_the_stored_log_was_read_back_is_not_lost(conn, fresh):
    """The database did not answer when the app started, and a bet was logged meanwhile."""
    store = MemoryStore()
    old = bet(conn, home="Wrexham")
    remote.backup_bets(conn, store, None)
    new = bet(fresh, home="Brann")
    assert remote.restore_bets(fresh, store) == 1  # the stored bet is added, the new one kept
    assert {b["id"] for b in bets.all_bets(fresh)} == {old, new}
    remote.backup_bets(fresh, store, None)
    assert "Wrexham" in store.values[remote.BETS] and "Brann" in store.values[remote.BETS]


def test_nothing_stored_reads_nothing(conn):
    assert remote.restore_bets(conn, MemoryStore()) == 0


def test_without_database_url_there_is_no_store(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert remote.store_from_env() is None
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.invalid/db")
    assert isinstance(remote.store_from_env(), remote.PostgresStore)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs a Postgres in TEST_DATABASE_URL")
def test_postgres_store_round_trip(conn, fresh):
    store = remote.PostgresStore(os.environ["TEST_DATABASE_URL"])
    for key in (remote.BETS, remote.PREVIOUS):
        store.put(key, "")
    assert store.get("missing-key") is None
    first = bet(conn)
    digest = remote.backup_bets(conn, store, None)
    assert remote.restore_bets(fresh, store) == 1 and bets.all_bets(fresh)[0]["id"] == first
    bets.update(fresh, first, odds=4.2, stake=300.0, note="økt")
    remote.backup_bets(fresh, store, digest)
    assert "300.0" in store.get(remote.BETS) and "250.0" in store.get(remote.PREVIOUS)
    assert remote.backup_bets(fresh, store, None)  # writing the same log again is harmless


def test_kickoff_is_kept_as_utc(conn, fresh):
    store = MemoryStore()
    bet(conn)
    remote.backup_bets(conn, store, None)
    remote.restore_bets(fresh, store)
    assert db.parse_iso(bets.all_bets(fresh)[0]["kickoff_utc"]) == KICKOFF


def test_errors_never_show_the_address_or_password():
    url = "postgressql://neondb_owner:npg_secret123@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    error = Exception(f'invalid connection option "{url[:-8]}"')  # as psycopg said it, cut at «=»
    text = remote.safe_error(error, url)
    assert "npg_secret123" not in text and "neondb_owner" not in text and "postgressql://" not in text
    assert text.startswith("Exception: invalid connection option")
    assert "secret" not in remote.safe_error(Exception("host=x password=secret user=u"))


def test_an_address_that_is_not_postgres_is_refused_without_being_shown():
    store = remote.PostgresStore("postgressql://user:npg_secret123@host/db")  # a typo: two s
    with pytest.raises(ValueError, match="postgresql://") as raised:
        store.get(remote.BETS)
    assert "npg_secret123" not in str(raised.value)
