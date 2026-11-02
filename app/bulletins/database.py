from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS bulletins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    number INTEGER,
    year INTEGER,
    month INTEGER,
    local_path TEXT,
    content_length INTEGER,
    etag TEXT,
    last_modified TEXT,
    sha256 TEXT,
    remote_content_length INTEGER,
    remote_etag TEXT,
    remote_last_modified TEXT,
    remote_checked_at TEXT,
    pages INTEGER DEFAULT 0,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    downloaded_at TEXT,
    indexed_at TEXT,
    index_signature TEXT,
    status TEXT NOT NULL DEFAULT 'discovered'
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bulletin_id INTEGER NOT NULL,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_source TEXT NOT NULL,
    ocr_confidence REAL,
    indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bulletin_id, page_no),
    FOREIGN KEY(bulletin_id) REFERENCES bulletins(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text,
    title UNINDEXED,
    filename UNINDEXED,
    bulletin_id UNINDEXED,
    page_no UNINDEXED,
    number UNINDEXED,
    year UNINDEXED,
    text_source UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_bulletins_number ON bulletins(number);
CREATE INDEX IF NOT EXISTS idx_bulletins_year ON bulletins(year);
CREATE INDEX IF NOT EXISTS idx_pages_bulletin_id ON pages(bulletin_id);

CREATE TABLE IF NOT EXISTS admin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    details TEXT
);

CREATE TABLE IF NOT EXISTS bulletin_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bulletin_id INTEGER,
    bulletin_filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_events_type_date ON admin_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_bulletin_views_filename ON bulletin_views(bulletin_filename);
CREATE INDEX IF NOT EXISTS idx_search_queries_created ON search_queries(created_at);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        ensure_migrations(conn)
        conn.commit()


def ensure_migrations(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first local DB schema.

    Existing users keep their search.db between bundle updates. SQLite has no
    IF NOT EXISTS for ADD COLUMN on older versions, so we inspect the table.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(bulletins)").fetchall()}
    additions = {
        "remote_content_length": "INTEGER",
        "remote_etag": "TEXT",
        "remote_last_modified": "TEXT",
        "remote_checked_at": "TEXT",
        "index_signature": "TEXT",
    }
    for name, decl in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE bulletins ADD COLUMN {name} {decl}")


def dict_rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
