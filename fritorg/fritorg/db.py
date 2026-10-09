"""SQLite storage: connection handling and schema migrations.

One connection per request; WAL mode lets readers and a writer work concurrently.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

MMAP_BYTES = 1 << 30  # address space only: memory is used as pages are read, and shared between connections

SCHEMA_V1 = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_via TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL,
    banned_at TEXT,
    ban_reason TEXT,
    -- BankID: a keyed hash of the person's identifier (one person, one account). The
    -- identifier itself (e.g. the national identity number) is never stored.
    identity_hash TEXT UNIQUE,
    verified_name TEXT,
    verified_at TEXT,
    verified_via TEXT,
    email_verified_at TEXT,
    -- Verified Norwegian mobile number: only a keyed hash (one account per number) and a hint.
    phone_hash TEXT UNIQUE,
    phone_hint TEXT,
    phone_verified_at TEXT
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE api_tokens (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    token_hint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX idx_api_tokens_user ON api_tokens(user_id);

-- AUTOINCREMENT: ids of deleted listings are never reused, so permalinks stay unambiguous.
CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price INTEGER,
    price_unit TEXT NOT NULL DEFAULT 'total',
    county TEXT,
    location TEXT,
    postal_code TEXT,
    attributes TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    created_via TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- Fraud protection: signals found when the listing was last assessed (see fraud.py).
    risk_score INTEGER NOT NULL DEFAULT 0,
    risk_flags TEXT NOT NULL DEFAULT '[]',
    text_hash TEXT,
    reviewed_at TEXT,
    moderation_note TEXT,
    -- Listings imported from an open source (e.g. "nav": job ads from arbeidsplassen.no).
    source TEXT,
    source_id TEXT,
    source_url TEXT,
    apply_url TEXT,
    source_updated_at TEXT,
    expires_at TEXT,
    -- Listings a business keeps in sync from its own system (inventory.py): its feed name and item id.
    feed TEXT,
    external_id TEXT,
    sync_hash TEXT
);
CREATE INDEX idx_listings_status_created ON listings(status, created_at);
CREATE UNIQUE INDEX idx_listings_source ON listings(source, source_id) WHERE source IS NOT NULL;
CREATE INDEX idx_listings_expires ON listings(expires_at) WHERE expires_at IS NOT NULL;
CREATE UNIQUE INDEX idx_listings_feed ON listings(user_id, feed, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX idx_listings_category ON listings(category);
CREATE INDEX idx_listings_status_category ON listings(status, category, user_id);
CREATE INDEX idx_listings_user ON listings(user_id);
CREATE INDEX idx_listings_county ON listings(county);
CREATE INDEX idx_listings_updated ON listings(updated_at);
CREATE INDEX idx_listings_text_hash ON listings(text_hash);
-- Listing ids start at 100001 (six digits, easy to read aloud and to type).
INSERT INTO sqlite_sequence(name, seq) VALUES ('listings', 100000);

-- Trigram index: substring matching, so "sofa" also finds "hjørnesofa" (Norwegian compounds).
CREATE VIRTUAL TABLE listings_fts USING fts5(title, body, meta, tokenize = 'trigram');

CREATE TABLE listing_images (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    alt_text TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    dhash TEXT,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_images_listing ON listing_images(listing_id, position);
CREATE INDEX idx_images_sha256 ON listing_images(sha256);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    listing_title TEXT NOT NULL,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_conversations_listing_buyer ON conversations(listing_id, buyer_id);
CREATE INDEX idx_conversations_buyer ON conversations(buyer_id);
CREATE INDEX idx_conversations_seller ON conversations(seller_id);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_via TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL,
    read_at TEXT,
    risk_score INTEGER NOT NULL DEFAULT 0,
    risk_flags TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, id);
CREATE INDEX idx_messages_sender_created ON messages(sender_id, created_at);

CREATE TABLE reports (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER REFERENCES listings(id) ON DELETE CASCADE,
    reported_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    reporter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    comment TEXT,
    created_via TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_reports_open ON reports(resolved_at, created_at);
CREATE INDEX idx_reports_listing ON reports(listing_id);

-- OpenID Connect login in progress (state, nonce and PKCE verifier), kept for minutes.
CREATE TABLE login_states (
    state_hash TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    return_to TEXT,
    created_at TEXT NOT NULL
);

-- A person who has logged in with BankID but not finished creating an account yet.
CREATE TABLE pending_identities (
    token_hash TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL,
    verified_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    verified_via TEXT NOT NULL,
    return_to TEXT,
    created_at TEXT NOT NULL
);

-- SMS codes for verifying a mobile number. The number itself is never stored.
CREATE TABLE phone_codes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    phone_hash TEXT NOT NULL,
    phone_hint TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'verify',  -- 'verify' a number, or 'reset' a forgotten password
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX idx_phone_codes_user ON phone_codes(user_id, created_at);
CREATE INDEX idx_phone_codes_phone ON phone_codes(phone_hash, created_at);

-- Device authorization for agents: the agent shows a code, a logged-in person approves it.
CREATE TABLE device_grants (
    id INTEGER PRIMARY KEY,
    device_code_hash TEXT NOT NULL UNIQUE,
    user_code TEXT NOT NULL UNIQUE,
    client_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    polled_at TEXT
);

-- Imports from open sources: where the importer is in the source's feed, and changes waiting
-- to be applied (the latest state per item; see navjobs.py).
CREATE TABLE import_state (
    source TEXT PRIMARY KEY,
    page_id TEXT,
    etag TEXT,
    last_modified TEXT,
    token TEXT,
    lease_until TEXT,
    last_run_at TEXT,
    last_error TEXT
);

CREATE TABLE import_queue (
    source TEXT NOT NULL,
    item_id TEXT NOT NULL,
    status TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    PRIMARY KEY (source, item_id)
);

-- Every moderator decision, kept for accountability.
CREATE TABLE moderation_log (
    id INTEGER PRIMARY KEY,
    moderator_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    listing_id INTEGER,
    user_id INTEGER,
    action TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
"""

# Favourites, saved searches and price-drop alerts. Written so it also applies to a database that
# already has the first version of the two tables (they were briefly part of SCHEMA_V1).
SCHEMA_V2 = """
-- Listings a person has saved to look at again ("favoritter").
CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, listing_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_favorites_listing ON favorites(listing_id);
-- The price when saved (shown as "satt ned fra ..."), and the price the person last heard about.
ALTER TABLE favorites ADD COLUMN price INTEGER;
ALTER TABLE favorites ADD COLUMN notified_price INTEGER;

-- Saved searches, as /sok query parameters. Listing ids only grow, so the new matches are those with
-- a higher id than the newest listing when the person last looked (seen_id) or was e-mailed (alerted_id).
CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    query TEXT NOT NULL,
    notify INTEGER NOT NULL DEFAULT 1,
    seen_id INTEGER NOT NULL DEFAULT 0,
    alerted_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    alerted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_searches_user_query ON saved_searches(user_id, query);
CREATE INDEX IF NOT EXISTS idx_saved_searches_notify ON saved_searches(notify, alerted_id);

-- E-mail when the price of a favourite is lowered (on unless turned off), at most twice a day.
ALTER TABLE users ADD COLUMN price_alerts INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN price_alerted_at TEXT;
"""

# Blocking in messages, and view counts for sellers.
SCHEMA_V3 = """
-- People someone does not want messages from (in either direction).
CREATE TABLE blocks (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, blocked_id)
) WITHOUT ROWID;
CREATE INDEX idx_blocks_blocked ON blocks(blocked_id);

-- How many times people have looked at a listing (counted in memory, written every few minutes).
ALTER TABLE listings ADD COLUMN views INTEGER NOT NULL DEFAULT 0;
"""

# The order in which listings were published, for "new since you last looked" in saved searches:
# a draft or a listing that waited for review is new when it becomes active, not when it was written.
# Triggers number a listing the first time it becomes active, always above every listing id and every
# number handed out before, so watermarks from earlier versions (listing ids) stay valid.
_NEXT_SEQ = (
    "(SELECT MAX(COALESCE((SELECT MAX(public_seq) FROM listings), 0), "
    "COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'listings'), 0)) + 1)"
)
SCHEMA_V4 = f"""
ALTER TABLE listings ADD COLUMN public_seq INTEGER;
UPDATE listings SET public_seq = id WHERE status IN ('active', 'sold');
CREATE INDEX idx_listings_public_seq ON listings(public_seq);

CREATE TRIGGER listings_published_on_insert AFTER INSERT ON listings
WHEN NEW.status = 'active' AND NEW.public_seq IS NULL
BEGIN
    UPDATE listings SET public_seq = {_NEXT_SEQ} WHERE id = NEW.id;
END;

CREATE TRIGGER listings_published_on_update AFTER UPDATE OF status ON listings
WHEN NEW.status = 'active' AND NEW.public_seq IS NULL
BEGIN
    UPDATE listings SET public_seq = {_NEXT_SEQ} WHERE id = NEW.id;
END;
"""

# Search that stays fast with a million listings (see listings.search).
#
# * The full-text index reads its text from the listings table instead of keeping its own copy. Triggers keep
#   it up to date, so nothing else writes to listings_fts. Each column is indexed with a space on both sides,
#   so one- and two-letter words can be found as words ("tv" = a word that starts or ends with "tv").
# * Covering indexes hold every column that searches filter and sort on, so finding the 20 listings on a page
#   (and counting the rest) never reads the listing rows with their long descriptions. listings.search picks
#   one of them by how it sorts: by date, by category, by county, by price, or by id for full-text hits.
# * A partial index finds closed accounts, whose listings are hidden.
IMPORTED_INDEXED_CHARS = 2500  # how much of an imported ad's text is searchable (long ads stay fast)


def _indexed(row: str) -> str:
    """The title, body and meta values indexed for a listings row (NEW, OLD or the table itself)."""
    body = (
        f"CASE WHEN {row}.source IS NULL THEN {row}.description "
        f"ELSE substr({row}.description, 1, {IMPORTED_INDEXED_CHARS}) END"
    )
    return f"' ' || {row}.title || ' ', ' ' || {body} || ' ', ' ' || {row}.search_meta || ' '"


SCHEMA_V5 = [
    "DROP TABLE listings_fts",
    f"CREATE VIEW listings_search (id, title, body, meta) AS SELECT l.id, {_indexed('l')} FROM listings l",
    "CREATE VIRTUAL TABLE listings_fts USING fts5(title, body, meta, content = 'listings_search', "
    "content_rowid = 'id', tokenize = 'trigram', columnsize = 0)",
    f"""CREATE TRIGGER listings_fts_insert AFTER INSERT ON listings BEGIN
        INSERT INTO listings_fts (rowid, title, body, meta) VALUES (NEW.id, {_indexed("NEW")});
    END""",
    f"""CREATE TRIGGER listings_fts_delete AFTER DELETE ON listings BEGIN
        INSERT INTO listings_fts (listings_fts, rowid, title, body, meta) VALUES ('delete', OLD.id, {_indexed("OLD")});
    END""",
    f"""CREATE TRIGGER listings_fts_update AFTER UPDATE OF title, description, source, search_meta ON listings
    BEGIN
        INSERT INTO listings_fts (listings_fts, rowid, title, body, meta) VALUES ('delete', OLD.id, {_indexed("OLD")});
        INSERT INTO listings_fts (rowid, title, body, meta) VALUES (NEW.id, {_indexed("NEW")});
    END""",
    "INSERT INTO listings_fts (listings_fts) VALUES ('rebuild')",
    "DROP INDEX idx_listings_status_created",
    "DROP INDEX idx_listings_status_category",
    "DROP INDEX idx_listings_county",
    "DROP INDEX idx_listings_user",
    "CREATE INDEX idx_listings_by_date ON listings(status, created_at, id, user_id, category, type, county, price, "
    "source)",
    "CREATE INDEX idx_listings_by_category ON listings(status, category, created_at, id, user_id, type, county, "
    "price, source, attributes)",
    "CREATE INDEX idx_listings_by_county ON listings(status, county, created_at, id, user_id, category, type, price, "
    "source)",
    "CREATE INDEX idx_listings_by_price ON listings(status, price, id DESC, user_id, category, type, county, "
    "source)",
    "CREATE INDEX idx_listings_by_id ON listings(id, status, user_id, category, type, county, price, source, "
    "created_at, public_seq, location)",
    "CREATE INDEX idx_listings_by_user ON listings(user_id, status, created_at, id)",
    "CREATE INDEX idx_users_banned ON users(id) WHERE banned_at IS NOT NULL",
    # Reused photos (images.py): the quarters of each perceptual hash, and the start of the file hash.
    "DROP INDEX idx_images_sha256",
    "CREATE INDEX idx_images_sha256_start ON listing_images(substr(sha256, 1, 16))",
    "CREATE INDEX idx_images_hash_a ON listing_images(hash_a) WHERE hash_a IS NOT NULL",
    "CREATE INDEX idx_images_hash_b ON listing_images(hash_b) WHERE hash_b IS NOT NULL",
    "CREATE INDEX idx_images_hash_c ON listing_images(hash_c) WHERE hash_c IS NOT NULL",
    "CREATE INDEX idx_images_hash_d ON listing_images(hash_d) WHERE hash_d IS NOT NULL",
]


def _migrate_v5(conn: sqlite3.Connection) -> None:
    from .images import hash_quarters
    from .listings import refresh_search_meta  # the extra searchable text comes from the taxonomy

    conn.execute("ALTER TABLE listings ADD COLUMN search_meta TEXT NOT NULL DEFAULT ''")
    refresh_search_meta(conn)
    for column in ("hash_a", "hash_b", "hash_c", "hash_d"):
        conn.execute(f"ALTER TABLE listing_images ADD COLUMN {column} INTEGER")
    conn.executemany(
        "UPDATE listing_images SET hash_a = ?, hash_b = ?, hash_c = ?, hash_d = ? WHERE id = ?",
        (
            (*hash_quarters(row[1]), row[0])
            for row in conn.execute("SELECT id, dhash FROM listing_images WHERE dhash IS NOT NULL").fetchall()
        ),
    )
    for statement in SCHEMA_V5:
        conn.execute(statement)
    analyze(conn)


def analyze(conn: sqlite3.Connection) -> None:
    """Refresh the statistics the query planner uses to pick an index (sampled, so it stays quick)."""
    conn.execute("PRAGMA analysis_limit = 1000")
    conn.execute("ANALYZE")


# Append new migrations to the end; never edit one that has shipped. A migration is SQL run as one script,
# or a function that gets the connection inside the migration's transaction.
MIGRATIONS: list[str | Callable[[sqlite3.Connection], None]] = [
    SCHEMA_V1,
    SCHEMA_V2,
    SCHEMA_V3,
    SCHEMA_V4,
    _migrate_v5,
]


def _casefold(value: object) -> object:
    return value.casefold() if isinstance(value, str) else value


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        # isolation_level=None: autocommit, explicit transactions via `transaction()`.
        # check_same_thread=False: FastAPI may run a request's dependency and endpoint
        # in different worker threads; a connection is still only used by one request.
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # SQLite's lower()/LIKE only fold ASCII; casefold() also handles æ, ø and å.
        conn.create_function("casefold", 1, _casefold, deterministic=True)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        # Read the file through the operating system's cache directly (each request has a fresh connection,
        # so SQLite's own per-connection cache starts empty), and sort in memory.
        conn.execute(f"PRAGMA mmap_size = {MMAP_BYTES}")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
                if isinstance(migration, str):
                    conn.executescript(f"BEGIN;\n{migration}\nPRAGMA user_version = {number};\nCOMMIT;")
                    continue
                conn.execute("BEGIN IMMEDIATE")
                try:
                    migration(conn)
                    conn.execute(f"PRAGMA user_version = {number}")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in one write transaction (BEGIN IMMEDIATE avoids lock upgrades)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
