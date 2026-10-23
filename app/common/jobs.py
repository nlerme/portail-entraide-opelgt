from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.common.config import data_root, section

DB_PATH = data_root() / "portal" / "jobs.sqlite3"
TERMINAL_STATES = {"succeeded", "failed", "completed_with_warnings", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_jobs(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                queue TEXT NOT NULL,
                job_type TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 100,
                payload_json TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                progress_current INTEGER NOT NULL DEFAULT 0,
                progress_total INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 2,
                deduplication_key TEXT,
                lease_owner TEXT,
                lease_expires_at REAL,
                heartbeat_at REAL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_dedup
              ON jobs(deduplication_key)
              WHERE deduplication_key IS NOT NULL AND state IN ('pending','running');
            CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs(queue, state, priority, created_at);
            CREATE TABLE IF NOT EXISTS job_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(job_id, item_key)
            );
            """
        )


@dataclass(frozen=True)
class Job:
    id: str
    queue: str
    job_type: str
    state: str
    payload: dict[str, Any]
    retry_count: int
    max_retries: int


def enqueue(queue: str, job_type: str, payload: dict[str, Any] | None = None, *, priority: int = 100,
            deduplication_key: str | None = None, max_retries: int | None = None, items: Iterable[str] = ()) -> str:
    init_jobs()
    job_id = uuid.uuid4().hex
    max_retries = int(max_retries if max_retries is not None else section("jobs").get("max_retries", 2))
    item_keys = list(dict.fromkeys(str(item) for item in items))
    try:
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO jobs(id,queue,job_type,state,priority,payload_json,progress_total,max_retries,
                                     deduplication_key,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (job_id, queue, job_type, "pending", priority, json.dumps(payload or {}, ensure_ascii=False),
                 len(item_keys), max_retries, deduplication_key, utc_now()),
            )
            for key in item_keys:
                conn.execute("INSERT INTO job_items(job_id,item_key,created_at) VALUES (?,?,?)", (job_id, key, utc_now()))
            conn.commit()
    except sqlite3.IntegrityError:
        if not deduplication_key:
            raise
        with connect() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE deduplication_key=? AND state IN ('pending','running') ORDER BY created_at LIMIT 1",
                (deduplication_key,),
            ).fetchone()
        if row:
            return str(row["id"])
        raise
    return job_id



def _worker_owner_is_alive(owner: str | None, queue: str) -> bool:
    if not owner:
        return False
    try:
        host, pid_text, owner_queue = owner.rsplit(":", 2)
        pid = int(pid_text)
    except (TypeError, ValueError):
        return False
    if host != socket.gethostname() or owner_queue != queue:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def recover_running_jobs(queue: str) -> int:
    init_jobs()
    with connect() as conn:
        rows = conn.execute(
            "SELECT id,lease_owner FROM jobs WHERE queue=? AND state='running'",
            (queue,),
        ).fetchall()
        recovered = 0
        for row in rows:
            if _worker_owner_is_alive(row["lease_owner"], queue):
                continue
            recovered += conn.execute(
                """UPDATE jobs SET state='pending', lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL,
                           message='Reprise après redémarrage du worker.'
                   WHERE id=? AND state='running'""",
                (row["id"],),
            ).rowcount
    return int(recovered)


def claim(queue: str, worker_id: str, lease_seconds: int | None = None) -> Job | None:
    init_jobs()
    now = time.time()
    lease = int(lease_seconds or section("jobs").get("lease_seconds", 900))
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE jobs SET state='pending', lease_owner=NULL, lease_expires_at=NULL,
                       message='Reprise après expiration du bail.'
               WHERE state='running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?""",
            (now,),
        )
        row = conn.execute(
            "SELECT * FROM jobs WHERE queue=? AND state='pending' ORDER BY priority ASC, created_at ASC LIMIT 1",
            (queue,),
        ).fetchone()
        if not row:
            conn.commit()
            return None
        changed = conn.execute(
            """UPDATE jobs SET state='running', started_at=COALESCE(started_at,?), lease_owner=?,
                       lease_expires_at=?, heartbeat_at=?, message='Traitement en cours.'
               WHERE id=? AND state='pending'""",
            (utc_now(), worker_id, now + lease, now, row["id"]),
        ).rowcount
        conn.commit()
        if changed != 1:
            return None
        payload = json.loads(row["payload_json"] or "{}")
        return Job(str(row["id"]), str(row["queue"]), str(row["job_type"]), "running", payload,
                   int(row["retry_count"]), int(row["max_retries"]))


def heartbeat(job_id: str, worker_id: str, *, message: str | None = None, current: int | None = None,
              total: int | None = None, lease_seconds: int | None = None) -> None:
    now = time.time()
    lease = int(lease_seconds or section("jobs").get("lease_seconds", 900))
    fields = ["heartbeat_at=?", "lease_expires_at=?"]
    values: list[Any] = [now, now + lease]
    if message is not None:
        fields.append("message=?")
        values.append(message)
    if current is not None:
        fields.append("progress_current=?")
        values.append(max(0, current))
    if total is not None:
        fields.append("progress_total=?")
        values.append(max(0, total))
    values.extend([job_id, worker_id])
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=? AND lease_owner=? AND state='running'", values)


def finish(job_id: str, *, warnings: int = 0, message: str = "Traitement terminé.") -> None:
    state = "completed_with_warnings" if warnings else "succeeded"
    with connect() as conn:
        conn.execute(
            """UPDATE jobs SET state=?, warning_count=?, message=?, finished_at=?, lease_owner=NULL,
                       lease_expires_at=NULL, progress_current=CASE WHEN progress_total>0 THEN progress_total ELSE progress_current END
               WHERE id=?""",
            (state, warnings, message, utc_now(), job_id),
        )


def fail(job: Job, error: str) -> None:
    retry = job.retry_count + 1
    with connect() as conn:
        if retry <= job.max_retries:
            conn.execute(
                """UPDATE jobs SET state='pending', retry_count=?, error_summary=?, message=?, lease_owner=NULL,
                           lease_expires_at=NULL, heartbeat_at=NULL WHERE id=?""",
                (retry, error[:2000], f"Nouvelle tentative {retry}/{job.max_retries} planifiée.", job.id),
            )
        else:
            conn.execute(
                """UPDATE jobs SET state='failed', retry_count=?, error_summary=?, message=?, finished_at=?,
                           lease_owner=NULL, lease_expires_at=NULL WHERE id=?""",
                (retry, error[:2000], "Échec définitif après les tentatives autorisées.", utc_now(), job.id),
            )


def cancel(job_id: str) -> bool:
    with connect() as conn:
        changed = conn.execute(
            """UPDATE jobs SET cancel_requested=1,
                       state=CASE WHEN state='pending' THEN 'cancelled' ELSE state END,
                       finished_at=CASE WHEN state='pending' THEN ? ELSE finished_at END
               WHERE id=? AND state IN ('pending','running')""",
            (utc_now(), job_id),
        ).rowcount
    return bool(changed)



def cancel_active_queue(queue: str, message: str) -> int:
    init_jobs()
    with connect() as conn:
        changed = conn.execute(
            """UPDATE jobs
               SET state='cancelled', cancel_requested=1, message=?, finished_at=?,
                   lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL,
                   progress_current=CASE WHEN progress_total>0 THEN progress_total ELSE progress_current END
               WHERE queue=? AND state IN ('pending','running')""",
            (message, utc_now(), queue),
        ).rowcount
        conn.execute(
            """UPDATE job_items
               SET state='cancelled', message=?, finished_at=?
               WHERE job_id IN (SELECT id FROM jobs WHERE queue=? AND state='cancelled')
                 AND state IN ('pending','running')""",
            (message, utc_now(), queue),
        )
    return int(changed)

def cancelled(job_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row[0])


def set_item(job_id: str, item_key: str, state: str, message: str = "") -> None:
    terminal = state in {"succeeded", "failed", "skipped", "cancelled"}
    with connect() as conn:
        conn.execute(
            """INSERT INTO job_items(job_id,item_key,state,message,created_at,finished_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(job_id,item_key) DO UPDATE SET state=excluded.state,message=excluded.message,
                                                          finished_at=excluded.finished_at""",
            (job_id, item_key, state, message, utc_now(), utc_now() if terminal else None),
        )
        row = conn.execute(
            "SELECT COUNT(*) FROM job_items WHERE job_id=? AND state IN ('succeeded','failed','skipped','cancelled')",
            (job_id,),
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM job_items WHERE job_id=?", (job_id,)).fetchone()[0]
        conn.execute("UPDATE jobs SET progress_current=?, progress_total=? WHERE id=?", (int(row[0]), int(total), job_id))


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    init_jobs()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        total = int(item.get("progress_total") or 0)
        current = int(item.get("progress_current") or 0)
        item["progress_percent"] = 100 if item["state"] in TERMINAL_STATES else round(current / total * 100) if total else 0
        result.append(item)
    return result


def summary() -> dict[str, Any]:
    init_jobs()
    with connect() as conn:
        rows = conn.execute("SELECT state, COUNT(*) AS count FROM jobs GROUP BY state").fetchall()
        active = conn.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('pending','running')").fetchone()[0]
    return {"states": {str(row["state"]): int(row["count"]) for row in rows}, "active": int(active), "path": str(DB_PATH)}
