from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.bulletins.config import Settings
from app.bulletins.crawler import BulletinLink, EntraideCrawler
from app.bulletins.maintenance import (
    acquire_sync_lock,
    cleanup_stale_sync_state,
    release_sync_lock,
    sync_lock_is_active,
)
from app.bulletins.signatures import ocr_index_signature
from app.common.jobs import enqueue


@dataclass
class SyncState:
    running: bool = False
    phase: str = "idle"
    message: str = "Aucune synchronisation en cours."
    discovered: int = 0
    downloaded: int = 0
    indexed: int = 0
    ocr_completed: int = 0
    ocr_total: int = 0
    unchanged: int = 0
    failed: int = 0
    completed_steps: int = 0
    total_steps: int = 0
    current: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "phase": self.phase,
            "message": self.message,
            "discovered": self.discovered,
            "downloaded": self.downloaded,
            "indexed": self.indexed,
            "ocrCompleted": self.ocr_completed,
            "ocrTotal": self.ocr_total,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "completedSteps": self.completed_steps,
            "totalSteps": self.total_steps,
            "current": self.current,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "errors": self.errors[-20:],
        }


class SyncManager:
    def __init__(self, settings: Settings, db_path: Path):
        self.settings = settings
        self.db_path = db_path
        self._lock = threading.Lock()
        self._state = SyncState()
        self._thread: threading.Thread | None = None

    def start(self, crawler: EntraideCrawler, force_reindex: bool = False) -> bool:
        # Source unique de vérité pour les autres processus: un verrou sur disque.
        # Sans ce verrou, la commande run_server.sh status ne peut pas savoir
        # qu'une synchronisation lancée depuis l'interface web est réellement en
        # cours, car elle s'exécute dans un autre processus Python.
        cleanup_stale_sync_state(self.settings)
        if sync_lock_is_active(self.settings):
            return False
        with self._lock:
            if self._state.running:
                return False
            self._state = SyncState(
                running=True,
                phase="starting",
                message="Démarrage de la synchronisation...",
                started_at=time.time(),
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(crawler, force_reindex),
                daemon=True,
            )
            self._thread.start()
            return True

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state.as_dict()

    def _update(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._state, key, value)

    def _increment(self, field_name: str, amount: int = 1) -> None:
        with self._lock:
            setattr(self._state, field_name, getattr(self._state, field_name) + amount)

    def _add_error(self, message: str) -> None:
        with self._lock:
            self._state.errors.append(message)
            self._state.failed += 1

    def _run(self, crawler: EntraideCrawler, force_reindex: bool) -> None:
        lock_path = None
        try:
            lock_path = acquire_sync_lock(self.settings, reason="synchronisation après connexion membre")
        except Exception as exc:  # noqa: BLE001
            self._update(
                running=False,
                phase="locked",
                message=f"Synchronisation déjà en cours ou verrou impossible à créer : {exc}",
                current=None,
                finished_at=time.time(),
            )
            try:
                crawler.session.close()
            except Exception:
                pass
            return

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        run_id: int | None = None
        try:
            run_id = conn.execute(
                "INSERT INTO sync_runs(status, message) VALUES (?, ?)",
                ("running", "Synchronisation en cours"),
            ).lastrowid
            conn.commit()
            self._update(phase="discover", message="Recuperation et validation de la liste des PDF...")
            links = crawler.discover_bulletins()
            self._update(
                discovered=len(links),
                total_steps=max(len(links) * 2, 1),
                message=f"{len(links)} PDF distant(s) trouve(s). Comparaison avec le cache local...",
            )

            pairs: list[tuple[BulletinLink, sqlite3.Row]] = []
            for link in links:
                row = upsert_bulletin(conn, link, self.settings.pdf_dir)
                pairs.append((link, row))
            conn.commit()

            expected_signature = ocr_index_signature(self.settings)
            bulletins_to_index: list[dict[str, Any]] = []

            for link, bulletin in pairs:
                filename = bulletin["filename"]

                if not link.verified:
                    conn.execute("UPDATE bulletins SET status = 'missing-remote' WHERE id = ?", (bulletin["id"],))
                    conn.commit()
                    self._add_error(
                        f"Fichier distant introuvable pour {filename}. URL source: {link.original_url or link.url}. Detail: {link.validation_error or 'non disponible'}"
                    )
                    self._increment("completed_steps", 2)
                    continue

                self._update(phase="download", current=filename, message=f"Comparaison distante/locale : {filename}")
                changed = False
                try:
                    changed = should_download(bulletin, link, force_reindex)
                    if changed:
                        target_path = self.settings.pdf_dir / filename
                        self._update(phase="download", current=filename, message=f"Telechargement : {filename}")
                        sha, length, etag, last_modified = crawler.download_pdf(bulletin["url"], target_path)
                        conn.execute(
                            """
                            UPDATE bulletins
                            SET local_path = ?, sha256 = ?, content_length = ?, etag = ?, last_modified = ?,
                                downloaded_at = CURRENT_TIMESTAMP, status = 'downloaded'
                            WHERE id = ?
                            """,
                            (str(target_path), sha, length, etag, last_modified, bulletin["id"]),
                        )
                        conn.commit()
                        self._increment("downloaded")
                    else:
                        self._increment("unchanged")
                    self._increment("completed_steps")
                except Exception as exc:  # noqa: BLE001 - sync should continue per file
                    conn.execute("UPDATE bulletins SET status = 'download-error' WHERE id = ?", (bulletin["id"],))
                    conn.commit()
                    self._add_error(f"Telechargement impossible pour {filename}: {exc}")
                    self._increment("completed_steps", 2)
                    continue

                try:
                    fresh_bulletin = conn.execute("SELECT * FROM bulletins WHERE id = ?", (bulletin["id"],)).fetchone()
                    stored_signature = fresh_bulletin["index_signature"] if "index_signature" in fresh_bulletin.keys() else None
                    needs_index = force_reindex or not fresh_bulletin["indexed_at"] or changed or stored_signature != expected_signature
                    if needs_index:
                        bulletins_to_index.append(dict(fresh_bulletin))
                    else:
                        self._increment("completed_steps")
                except Exception as exc:  # noqa: BLE001
                    conn.execute("UPDATE bulletins SET status = 'index-error' WHERE id = ?", (bulletin["id"],))
                    conn.commit()
                    self._add_error(f"Preparation indexation impossible pour {filename}: {exc}")
                    self._increment("completed_steps")
                    continue

            if bulletins_to_index:
                self._index_bulletins_parallel(conn, bulletins_to_index)

            errors = self.state()["errors"]
            if errors:
                final_status = "finished-with-errors"
                final_message = "Téléchargement terminé avec certaines erreurs ; les OCR valides ont été planifiés."
                self._update(
                    running=False,
                    phase=final_status,
                    message=final_message,
                    current=None,
                    finished_at=time.time(),
                )
            else:
                final_status = "finished"
                final_message = "Téléchargement terminé ; les OCR nécessaires ont été planifiés."
                self._update(
                    running=False,
                    phase=final_status,
                    message=final_message,
                    current=None,
                    finished_at=time.time(),
                )
            if run_id is not None:
                conn.execute(
                    "UPDATE sync_runs SET finished_at = CURRENT_TIMESTAMP, status = ?, message = ? WHERE id = ?",
                    (final_status, final_message, run_id),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            final_message = f"Erreur de synchronisation : {exc}"
            self._update(
                running=False,
                phase="error",
                message=final_message,
                current=None,
                finished_at=time.time(),
            )
            if run_id is not None:
                conn.execute(
                    "UPDATE sync_runs SET finished_at = CURRENT_TIMESTAMP, status = ?, message = ? WHERE id = ?",
                    ("error", final_message, run_id),
                )
                conn.commit()
        finally:
            try:
                crawler.session.close()
            except Exception:
                pass
            conn.close()
            release_sync_lock(self.settings, lock_path)

    def _index_bulletins_parallel(self, conn: sqlite3.Connection, bulletins: list[dict[str, Any]]) -> None:
        total = len(bulletins)
        self._update(
            phase="enqueue-index",
            current=None,
            ocr_total=total,
            message=f"Mise en file OCR/indexation de {total} PDF.",
        )
        for position, bulletin in enumerate(bulletins, start=1):
            filename = str(bulletin["filename"])
            try:
                enqueue(
                    "ocr",
                    "bulletin_index",
                    {"bulletin_id": int(bulletin["id"])},
                    deduplication_key=f"bulletin-index:{int(bulletin['id'])}:{ocr_index_signature(self.settings)}",
                    items=[filename],
                )
                conn.execute("UPDATE bulletins SET status = 'index-pending' WHERE id = ?", (bulletin["id"],))
                conn.commit()
                self._increment("completed_steps")
                self._update(
                    phase="enqueue-index",
                    current=filename,
                    message=f"OCR planifié {position}/{total} : {filename}",
                )
            except Exception as exc:
                conn.execute("UPDATE bulletins SET status = 'index-error' WHERE id = ?", (bulletin["id"],))
                conn.commit()
                self._increment("completed_steps")
                self._add_error(f"Planification OCR impossible pour {filename}: {exc}")


def upsert_bulletin(conn: sqlite3.Connection, link: BulletinLink, pdf_dir: Path) -> sqlite3.Row:
    local_path = pdf_dir / link.filename
    existing = conn.execute("SELECT * FROM bulletins WHERE url = ?", (link.url,)).fetchone()
    if not existing and link.number is not None:
        existing = conn.execute("SELECT * FROM bulletins WHERE number = ?", (link.number,)).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE bulletins
            SET url = ?, title = ?, filename = ?, number = ?, year = ?, month = ?, local_path = ?,
                remote_content_length = ?, remote_etag = ?, remote_last_modified = ?, remote_checked_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                link.url,
                link.title,
                link.filename,
                link.number,
                link.year,
                link.month,
                str(local_path),
                link.remote_content_length,
                link.remote_etag,
                link.remote_last_modified,
                existing["id"],
            ),
        )
        return conn.execute("SELECT * FROM bulletins WHERE id = ?", (existing["id"],)).fetchone()

    conn.execute(
        """
        INSERT INTO bulletins (
            url, title, filename, number, year, month, local_path, status,
            remote_content_length, remote_etag, remote_last_modified, remote_checked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'discovered', ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            link.url,
            link.title,
            link.filename,
            link.number,
            link.year,
            link.month,
            str(local_path),
            link.remote_content_length,
            link.remote_etag,
            link.remote_last_modified,
        ),
    )
    return conn.execute("SELECT * FROM bulletins WHERE url = ?", (link.url,)).fetchone()


def should_download(bulletin: sqlite3.Row, link: BulletinLink, force: bool) -> bool:
    if force:
        return True

    local_path = bulletin["local_path"]
    if not local_path or not Path(local_path).exists():
        return True

    # Prefer strong validators when the server exposes them. They let us avoid a
    # full download while still detecting changed PDFs.
    if link.remote_etag and bulletin["etag"] and normalize_etag(link.remote_etag) != normalize_etag(bulletin["etag"]):
        return True

    if link.remote_last_modified and bulletin["last_modified"] and link.remote_last_modified != bulletin["last_modified"]:
        return True

    if (
        link.remote_content_length is not None
        and bulletin["content_length"] is not None
        and int(link.remote_content_length) != int(bulletin["content_length"])
    ):
        return True

    # If the server gives no comparable metadata, we trust the existing local PDF.
    # A future terminal maintenance command can force a complete reindex/download if needed.
    return False


def normalize_etag(value: str) -> str:
    return value.strip().removeprefix("W/").strip('"')
