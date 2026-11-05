"""What the database files keep: deleted text must really be gone from them, not just hidden."""

from __future__ import annotations

import os
import stat
from contextlib import closing
from pathlib import Path

from fritorg import identity, listings, maintenance, users
from fritorg.config import Settings
from fritorg.db import Database, transaction
from fritorg.listings import SearchParams


def _varint(data: bytes, at: int) -> tuple[int, int]:
    value = 0
    for i in range(8):
        byte = data[at + i]
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, at + i + 1
    return (value << 8) | data[at + 8], at + 9


def index_terms(conn) -> set[str]:
    """Every word (trigram) on the pages of the full-text index, also those of deleted text that no search finds.

    Read the way someone with a copy of the file could: FTS5 leaf pages have a 4-byte header, prefix-compressed
    terms, and a footer with the offset of each term (rowids of segment leaves have no height or doclist-index bits).
    """
    terms = set()
    leaves = "SELECT block FROM listings_fts_data WHERE id >= 1 << 37 AND (id >> 31) & 63 = 0"
    for (page,) in conn.execute(leaves):
        at, offset, term = int.from_bytes(page[2:4], "big"), 0, b""
        first = True
        while at < len(page):
            delta, at = _varint(page, at)
            offset += delta
            if first:  # the first term on a page is stored whole
                size, start = _varint(page, offset)
                term = page[start : start + size]
            else:
                prefix, start = _varint(page, offset)
                size, start = _varint(page, start)
                term = term[:prefix] + page[start : start + size]
            first = False
            terms.add(term[1:].decode())  # the first byte says which index (the main one or a prefix index)
    return terms


def add(conn, seller, title: str, description: str) -> int:
    return listings.create_listing(
        conn, seller.id, {"category": "mobler", "title": title, "description": description}
    )


def test_text_of_deleted_and_changed_listings_leaves_the_search_index(tmp_path):
    """FTS5 deletes by adding markers, and keeps the old words with their positions in its older segments until
    they are merged into the oldest one. The daily maintenance merges them, so the text is gone from the file."""
    settings = Settings(data_dir=tmp_path, verification="none", bankid_mode="off", business_registry="off")
    db = Database(settings.db_path)
    db.init()
    with db.session() as conn:
        seller = users.create_user(conn, "selger@example.no", "Selger", "hemmelig123")
        kept = add(conn, seller, "Spisebord", "Et pent bord i eik.")
        edited = add(conn, seller, "Stol", "Ring Qzxvwk på 912 34 567.")
        gone = add(conn, seller, "Sofa", "Hentes hos Jyqvbx i Storgata 1.")
        listings.update_listing(conn, seller.id, edited, {"description": "Send en melding her på siden."})
        listings.delete_listing(conn, seller.id, gone)
        names = {"qzx", "zxv", "xvw", "vwk", "jyq", "yqv", "qvb", "vbx"}  # in the old texts only
        assert names <= index_terms(conn)  # no search finds them, but the file still has them

    maintenance.run(db, settings)
    with db.session() as conn:
        assert not names & index_terms(conn)
        assert [item.id for item in listings.search(conn, SearchParams(q="eik")).items] == [kept]
        conn.execute("INSERT INTO listings_fts (listings_fts, rank) VALUES ('integrity-check', 1)")


def test_deleted_messages_do_not_stay_in_the_write_ahead_log(tmp_path):
    """After a checkpoint SQLite writes the -wal file from the start again, but keeps the rest of it, with pages as
    they were before a delete, until something overwrites them. A busy server always has a connection open, so the
    file is never removed either."""
    db = Database(tmp_path / "fritorg.sqlite3")
    db.init()
    secret = "Ring meg på 912 34 567, jeg bor i Storgata 1"
    with closing(db.connect()) as conn:
        conn.execute(
            "INSERT INTO users (email, name, password_hash, created_at) VALUES ('kari@example.no', 'Kari', '!', '2026')"
        )
        conn.execute(
            "INSERT INTO conversations (listing_title, buyer_id, seller_id, created_at, last_message_at) "
            "VALUES ('Sofa', 1, 1, '2026', '2026')"
        )
        with transaction(conn):
            conn.executemany(
                "INSERT INTO messages (conversation_id, sender_id, body, created_at) VALUES (1, 1, ?, '2026')",
                [(f"{secret}. {n}" + "." * 400,) for n in range(500)],
            )
        conn.execute("DELETE FROM conversations")  # both people deleted it: the messages go with it
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.execute("UPDATE users SET name = 'Kari N.'")  # the next write starts the -wal file over
        files = [db.path, db.path.with_name(db.path.name + "-wal")]
        assert [file.name for file in files if secret.encode() in file.read_bytes()] == []


def test_the_secret_key_file_is_never_readable_by_others(tmp_path, monkeypatch):
    """The key made on first start is created for the app's user only. Narrowing the permissions afterwards would
    leave a moment in which another user on the machine could open it (and keep it open)."""
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)  # as if that moment had not passed yet
    umask = os.umask(0o022)
    try:
        key = identity.load_secret_key(Settings(data_dir=tmp_path / "data"))
    finally:
        os.umask(umask)
    path = tmp_path / "data" / "secret_key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert identity.load_secret_key(Settings(data_dir=tmp_path / "data")) == key == path.read_text()
