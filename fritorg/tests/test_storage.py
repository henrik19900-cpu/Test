"""What the database files keep: deleted text must really be gone from them, not just hidden."""

from __future__ import annotations

from fritorg import listings, maintenance, users
from fritorg.config import Settings
from fritorg.db import Database
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
