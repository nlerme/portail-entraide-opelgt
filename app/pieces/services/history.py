from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from app.pieces.config import settings
from app.pieces.services.text import extract_price, normalize_text

HISTORY_ROOT = settings.data_dir / "catalogues" / "history"
HISTORY_DB = HISTORY_ROOT / "catalog_history.sqlite3"


@dataclass(frozen=True)
class PriceHistory:
    current_price: float | None
    previous_price: float | None
    previous_at: str | None
    currency: str | None

    @property
    def trend(self) -> str | None:
        if self.current_price is None or self.previous_price is None:
            return None
        delta = self.current_price - self.previous_price
        if abs(delta) < 0.005:
            return "stable"
        return "up" if delta > 0 else "down"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize_history() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                source TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                known_price_count INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                archive_path TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_site_date
                ON catalog_snapshots(site_id, captured_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS catalog_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL REFERENCES catalog_snapshots(id) ON DELETE CASCADE,
                site_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                url TEXT,
                reference TEXT,
                title TEXT NOT NULL,
                translated_title TEXT,
                price REAL,
                currency TEXT,
                availability TEXT,
                item_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_items_site_key_snapshot
                ON catalog_items(site_id, item_key, snapshot_id DESC);
            CREATE INDEX IF NOT EXISTS idx_items_snapshot
                ON catalog_items(snapshot_id);
            """
        )


def _canonical_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.lower().rstrip("/")
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def item_history_key(site_id: str, item: dict[str, Any]) -> str:
    url = _canonical_url(str(item.get("url_fiche") or item.get("url") or ""))
    if url:
        basis = f"url:{url}"
    else:
        reference = normalize_text(str(item.get("reference") or item.get("ref") or ""))
        if reference:
            basis = f"ref:{reference}"
        else:
            title = normalize_text(str(item.get("nom") or item.get("title") or ""))
            translated = normalize_text(str(item.get("nom_traduit") or ""))
            basis = f"title:{title}|{translated}"
    return hashlib.sha256(f"{site_id}|{basis}".encode("utf-8")).hexdigest()


def _timestamp_for_filename(captured_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def archive_catalog(
    site_id: str,
    catalog_path: Path,
    *,
    captured_at: str | None = None,
    source: str = "synchronization",
    currency_hint: str | None = None,
) -> int:
    """Archive an accepted catalogue and index every item.

    The JSON snapshot is retained indefinitely. The SQLite index is only an
    accelerator for diagnostics and price-history lookup; the archived JSON is
    the complete source of truth for each synchronization.
    """

    initialize_history()
    payload_bytes = catalog_path.read_bytes()
    data = json.loads(payload_bytes.decode("utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Le catalogue à archiver doit être une liste JSON non vide.")

    captured = captured_at or datetime.now(timezone.utc).isoformat(timespec="microseconds")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    stamp = _timestamp_for_filename(captured)
    site_dir = HISTORY_ROOT / site_id / stamp[:4]
    site_dir.mkdir(parents=True, exist_ok=True)
    archive_path = site_dir / f"{stamp}-{digest[:12]}.json"
    counter = 1
    while archive_path.exists():
        archive_path = site_dir / f"{stamp}-{digest[:12]}-{counter}.json"
        counter += 1
    shutil.copy2(catalog_path, archive_path)

    rows: list[tuple[Any, ...]] = []
    known_prices = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        price, currency = extract_price(str(item.get("prix") or ""), currency_hint)
        if price is not None:
            known_prices += 1
        rows.append(
            (
                site_id,
                item_history_key(site_id, item),
                str(item.get("url_fiche") or item.get("url") or "") or None,
                str(item.get("reference") or item.get("ref") or "") or None,
                str(item.get("nom") or item.get("title") or "").strip(),
                str(item.get("nom_traduit") or "").strip() or None,
                price,
                currency,
                str(item.get("disponibilite") or "").strip() or None,
                json.dumps(item, ensure_ascii=False, sort_keys=True),
            )
        )

    try:
        with _connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO catalog_snapshots
                    (site_id, captured_at, source, item_count, known_price_count, sha256, archive_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (site_id, captured, source, len(data), known_prices, digest, str(archive_path)),
            )
            snapshot_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO catalog_items
                    (snapshot_id, site_id, item_key, url, reference, title, translated_title,
                     price, currency, availability, item_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ((snapshot_id, *row) for row in rows),
            )
        return snapshot_id
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def price_history_map(site_id: str) -> dict[str, PriceHistory]:
    initialize_history()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT i.item_key, i.price, i.currency, s.captured_at
            FROM catalog_items AS i
            JOIN catalog_snapshots AS s ON s.id = i.snapshot_id
            WHERE i.site_id = ?
            ORDER BY i.item_key, s.captured_at DESC, s.id DESC
            """,
            (site_id,),
        ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["item_key"]), []).append(row)

    result: dict[str, PriceHistory] = {}
    for key, values in grouped.items():
        current = values[0]
        previous = next((row for row in values[1:] if row["price"] is not None), None)
        result[key] = PriceHistory(
            current_price=float(current["price"]) if current["price"] is not None else None,
            previous_price=float(previous["price"]) if previous is not None else None,
            previous_at=str(previous["captured_at"]) if previous is not None else None,
            currency=str(current["currency"] or previous["currency"] or "")
            if previous is not None
            else str(current["currency"] or "") or None,
        )
    return result


def history_summary(site_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    initialize_history()
    result: dict[str, dict[str, Any]] = {}
    with _connect() as conn:
        for site_id in site_ids:
            row = conn.execute(
                """
                SELECT COUNT(*) AS snapshots, MIN(captured_at) AS first_at,
                       MAX(captured_at) AS last_at, COALESCE(SUM(item_count), 0) AS observations
                FROM catalog_snapshots WHERE site_id = ?
                """,
                (site_id,),
            ).fetchone()
            distinct_items = conn.execute(
                "SELECT COUNT(DISTINCT item_key) FROM catalog_items WHERE site_id = ?", (site_id,)
            ).fetchone()[0]
            result[site_id] = {
                "snapshots": int(row["snapshots"] or 0),
                "first_at": row["first_at"],
                "last_at": row["last_at"],
                "observations": int(row["observations"] or 0),
                "distinct_items": int(distinct_items or 0),
            }
    return result


def restore_previous_snapshot(
    site_id: str,
    target_path: Path,
    *,
    currency_hint: str | None = None,
) -> str:
    """Restore the snapshot preceding the latest observation and archive the rollback."""

    initialize_history()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT captured_at, archive_path
            FROM catalog_snapshots
            WHERE site_id = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 2
            """,
            (site_id,),
        ).fetchall()
    if len(rows) < 2:
        raise RuntimeError(f"Historique insuffisant pour restaurer {site_id}.")
    source = Path(str(rows[1]["archive_path"]))
    if not source.is_file():
        raise RuntimeError(f"Instantané historique introuvable : {source}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging = target_path.with_suffix(target_path.suffix + ".rollback")
    shutil.copy2(source, staging)
    archive_catalog(
        site_id,
        staging,
        source=f"rollback-from-{rows[1]['captured_at']}",
        currency_hint=currency_hint,
    )
    staging.replace(target_path)
    return str(rows[1]["captured_at"])
