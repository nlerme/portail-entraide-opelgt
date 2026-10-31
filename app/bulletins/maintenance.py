from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.bulletins.config import Settings
from app.bulletins.crawler import is_index_bulletins_filename
from app.bulletins.database import connect

MAX_SYNC_LOCK_AGE_SECONDS = 24 * 60 * 60
AUTOMATIC_FREQUENCY = "Première récupération à l’installation, puis mise à jour incrémentale chaque dimanche à 02:00 (Europe/Paris)."


def sync_lock_path(settings: Settings) -> Path:
    return settings.data_dir / "sync.lock"


def _pid_is_active(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_cmdline(pid: int) -> str:
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        raw = proc_cmdline.read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")


def _lock_pid_matches_bundle(pid: int) -> bool:
    # Check both the web process and the unattended bulletin service.
    # Checking the command line prevents an old PID reused by an unrelated
    # process from keeping the web UI locked forever.
    cmdline = _pid_cmdline(pid)
    if not cmdline:
        return True  # No /proc details available but the PID exists.
    return any(name in cmdline for name in (
        "server_admin.py", "server_entry.py", "bulletins-entraide-opel-gt", "app.bulletins.service",
    ))


def read_sync_lock(settings: Settings) -> dict[str, Any] | None:
    path = sync_lock_path(settings)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sync_lock_is_active(settings: Settings) -> bool:
    data = read_sync_lock(settings)
    if not data:
        return False
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    try:
        started_ts = float(data.get("started_ts") or 0.0)
    except (TypeError, ValueError):
        started_ts = 0.0
    if started_ts and time.time() - started_ts > MAX_SYNC_LOCK_AGE_SECONDS:
        return False
    if not _pid_is_active(pid):
        return False
    return _lock_pid_matches_bundle(pid)


def mark_running_syncs_interrupted(settings: Settings, message: str) -> int:
    if not settings.db_path.exists():
        return 0
    with connect(settings.db_path) as conn:
        cur = conn.execute(
            """
            UPDATE sync_runs
            SET finished_at = CURRENT_TIMESTAMP, status = 'interrupted', message = ?
            WHERE status = 'running' AND finished_at IS NULL
            """,
            (message,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def cleanup_stale_sync_state(settings: Settings) -> int:
    """Remove stale synchronization state left by killed or crashed processes.

    Older versions could leave a row in sync_runs with status='running' and no
    finished_at. The web page then displayed "synchronisation en cours"
    forever, even though no synchronization process was alive. The source of
    truth is now the lock file plus the live PID. If there is no active lock,
    any unfinished DB run is closed as interrupted.
    """
    path = sync_lock_path(settings)
    active = sync_lock_is_active(settings)
    if not active and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    if active:
        return 0
    return mark_running_syncs_interrupted(
        settings,
        "Synchronisation interrompue ou état ancien nettoyé automatiquement.",
    )


def acquire_sync_lock(settings: Settings, *, reason: str) -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_sync_state(settings)
    path = sync_lock_path(settings)
    if sync_lock_is_active(settings):
        data = read_sync_lock(settings) or {}
        raise RuntimeError(
            f"Une synchronisation est déjà en cours (PID {data.get('pid', 'inconnu')}, raison : {data.get('reason', 'inconnue')})."
        )
    payload = {
        "pid": os.getpid(),
        "reason": reason,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "started_ts": time.time(),
    }
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    except FileExistsError:
        # Possible race: clean again and retry once.
        cleanup_stale_sync_state(settings)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def release_sync_lock(settings: Settings, lock_path: Path | None) -> None:
    if lock_path is None:
        return
    current = read_sync_lock(settings)
    if current:
        try:
            if int(current.get("pid") or 0) != os.getpid():
                return
        except (TypeError, ValueError):
            pass
    try:
        lock_path.unlink()
    except OSError:
        pass


def storage_counts(settings: Settings) -> dict[str, int]:
    """Return durable PDF/index counters used by both CLI and web UI.

    Runtime counters such as "downloaded this session" are not enough for a
    server application: after a restart or an interrupted OCR run the disk can
    legitimately contain 99 PDFs while the current in-memory counter is 0.  The
    UI therefore displays these durable counters as the source of truth for
    "PDF en cache" and "Indexés".
    """
    pdf_count = 0
    if settings.pdf_dir.exists():
        try:
            pdf_count = sum(
                1
                for path in settings.pdf_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".pdf" and not is_index_bulletins_filename(path.name)
            )
        except OSError:
            pdf_count = 0

    counts = {
        "knownBulletins": 0,
        "localPdfCount": pdf_count,
        "indexedBulletins": 0,
        "indexedPages": 0,
        "downloadedRows": 0,
    }
    if not settings.db_path.exists():
        return counts
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS known,
              SUM(CASE WHEN local_path IS NOT NULL AND local_path <> '' THEN 1 ELSE 0 END) AS local_rows,
              SUM(CASE WHEN indexed_at IS NOT NULL AND COALESCE(pages, 0) > 0 THEN 1 ELSE 0 END) AS indexed,
              COALESCE(SUM(CASE WHEN indexed_at IS NOT NULL THEN COALESCE(pages, 0) ELSE 0 END), 0) AS pages
            FROM bulletins
            """
        ).fetchone()
        counts["knownBulletins"] = int(row["known"] or 0)
        counts["downloadedRows"] = int(row["local_rows"] or 0)
        counts["indexedBulletins"] = int(row["indexed"] or 0)
        counts["indexedPages"] = int(row["pages"] or 0)
    return counts


def augment_sync_state(settings: Settings, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge volatile sync progress with durable disk/SQLite counters.

    This prevents misleading displays such as "Téléchargés : 0" when the PDFs
    are already present on disk but no new file was downloaded during the
    current session.
    """
    payload: dict[str, Any] = dict(state or {})
    if not payload.get("running"):
        active = sync_lock_is_active(settings)
        try:
            saved = json.loads((settings.data_dir / "sync_state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if isinstance(saved, dict) and (not saved.get("running") or active):
            payload.update(saved)
        if active:
            payload["running"] = True
    counts = storage_counts(settings)
    payload.setdefault("running", False)
    payload.setdefault("phase", "idle")
    payload.setdefault("message", "Aucune synchronisation en cours.")
    payload.setdefault("discovered", counts["knownBulletins"])

    downloaded_this_run = int(payload.get("downloadedThisRun", payload.get("downloaded", 0)) or 0)
    indexed_this_run = int(payload.get("indexedThisRun", payload.get("indexed", 0)) or 0)
    payload["downloadedThisRun"] = downloaded_this_run
    payload["indexedThisRun"] = indexed_this_run

    # Backward compatible field names consumed by older JS/tests, but now they
    # represent durable totals, not only current-run increments.
    payload["downloaded"] = counts["localPdfCount"]
    payload["indexed"] = counts["indexedBulletins"]
    payload["localPdfCount"] = counts["localPdfCount"]
    payload["knownBulletins"] = counts["knownBulletins"]
    payload["indexedBulletins"] = counts["indexedBulletins"]
    payload["indexedPages"] = counts["indexedPages"]
    payload["downloadedRows"] = counts["downloadedRows"]
    return payload


def last_sync_run(settings: Settings) -> dict[str, Any] | None:
    if not settings.db_path.exists():
        return None
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT id, started_at, finished_at, status, message
            FROM sync_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def readiness(settings: Settings, sync_state: dict[str, Any] | None = None) -> dict[str, Any]:
    counts = storage_counts(settings)
    indexed = counts["indexedBulletins"]
    # Never trust an old DB flag alone. A synchronization is considered active
    # only if it is running in the current process or if the lock file points to
    # a live synchronization process. Stale rows from interrupted runs are closed
    # automatically so the page cannot stay blocked for hours.
    if not (sync_state and sync_state.get("running")):
        cleanup_stale_sync_state(settings)
    last = last_sync_run(settings)
    external_running = sync_lock_is_active(settings)
    running = bool(sync_state and sync_state.get("running")) or external_running
    ready = indexed > 0
    if running and ready:
        message = f"Récupération ou indexation en cours. Les {indexed} bulletin(s) déjà indexé(s) seront de nouveau consultables à la fin du traitement."
    elif running:
        message = "Première synchronisation en cours. La recherche sera disponible dès qu’un premier bulletin aura été indexé."
    elif indexed <= 0:
        message = "Aucun bulletin n’est encore indexé. La première récupération est lancée à l’installation et se poursuit en arrière-plan."
    else:
        message = "Bulletins prêts. Mise à jour incrémentale chaque dimanche à 02:00 (Europe/Paris)."
    return {
        "ready": ready,
        "indexedBulletins": indexed,
        "localPdfCount": counts["localPdfCount"],
        "knownBulletins": counts["knownBulletins"],
        "indexedPages": counts["indexedPages"],
        "syncRunning": running,
        "message": message,
        "lastSync": last,
    }
