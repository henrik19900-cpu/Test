"""SQLite storage: connection handling and schema migrations.

One connection per request; WAL mode lets readers and a writer work concurrently.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
    expires_at TEXT
);
CREATE INDEX idx_listings_status_created ON listings(status, created_at);
CREATE UNIQUE INDEX idx_listings_source ON listings(source, source_id) WHERE source IS NOT NULL;
CREATE INDEX idx_listings_expires ON listings(expires_at) WHERE expires_at IS NOT NULL;
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

# Append new migrations to the end; never edit one that has shipped.
MIGRATIONS: list[str] = [SCHEMA_V1]


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
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
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
