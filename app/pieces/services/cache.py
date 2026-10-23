from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.pieces.config import settings


class PersistentCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "cache.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY(namespace, cache_key)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache_entries(expires_at)")

    def get(self, namespace: str, key: str) -> Any | None:
        now = time.time()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json, expires_at FROM cache_entries WHERE namespace=? AND cache_key=?",
                (namespace, key),
            ).fetchone()
            if not row:
                return None
            if float(row[1]) <= now:
                connection.execute(
                    "DELETE FROM cache_entries WHERE namespace=? AND cache_key=?",
                    (namespace, key),
                )
                return None
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
        now = time.time()
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries(namespace, cache_key, value_json, created_at, expires_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    value_json=excluded.value_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (namespace, key, payload, now, now + max(1, ttl_seconds)),
            )
            connection.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (now,))

    def delete_namespace(self, namespace: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM cache_entries WHERE namespace=?", (namespace,))


cache = PersistentCache()
