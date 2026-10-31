from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from app.bulletins.database import connect as bulletin_connect
from app.bulletins.database import init_db
from app.common import jobs
from app.manage import migrate


def reset_jobs() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(jobs.DB_PATH) + suffix).unlink(missing_ok=True)
    jobs.init_jobs()


def test_job_deduplication_claim_and_finish():
    reset_jobs()
    first = jobs.enqueue("ocr", "bulletin_index", {"bulletin_id": 1}, deduplication_key="same", items=["a.pdf"])
    second = jobs.enqueue("ocr", "bulletin_index", {"bulletin_id": 1}, deduplication_key="same", items=["a.pdf"])
    assert second == first
    job = jobs.claim("ocr", "worker")
    assert job and job.id == first
    jobs.set_item(first, "a.pdf", "succeeded", "ok")
    jobs.finish(first)
    record = jobs.list_jobs(1)[0]
    assert record["state"] == "succeeded"
    assert record["progress_percent"] == 100


def test_failed_item_can_complete_job_with_warnings_at_100_percent():
    reset_jobs()
    job_id = jobs.enqueue("ocr", "batch", {}, items=["ok.pdf", "bad.pdf"])
    job = jobs.claim("ocr", "worker")
    assert job
    jobs.set_item(job_id, "ok.pdf", "succeeded")
    jobs.set_item(job_id, "bad.pdf", "failed", "OCR impossible")
    jobs.finish(job_id, warnings=1, message="Terminé avec avertissement")
    record = jobs.list_jobs(1)[0]
    assert record["state"] == "completed_with_warnings"
    assert record["progress_current"] == 2
    assert record["progress_percent"] == 100


def test_expired_lease_is_recovered():
    reset_jobs()
    job_id = jobs.enqueue("ocr", "bulletin_index", {})
    first = jobs.claim("ocr", "dead-worker", lease_seconds=1)
    assert first
    with jobs.connect() as conn:
        conn.execute("UPDATE jobs SET lease_expires_at=? WHERE id=?", (time.time() - 10, job_id))
    recovered = jobs.claim("ocr", "new-worker")
    assert recovered and recovered.id == job_id


def test_worker_restart_requeues_running_job_immediately():
    reset_jobs()
    job_id = jobs.enqueue("catalogs", "catalog_sync", {}, items=["supplier-a", "supplier-b"])
    claimed = jobs.claim("catalogs", "old-worker", lease_seconds=21600)
    assert claimed and claimed.id == job_id

    assert jobs.recover_running_jobs("catalogs") == 1

    recovered = jobs.claim("catalogs", "new-worker")
    assert recovered and recovered.id == job_id
    record = jobs.list_jobs(1)[0]
    assert record["state"] == "running"
    assert record["message"] == "Traitement en cours."


def test_worker_restart_does_not_steal_job_from_live_worker():
    reset_jobs()
    job_id = jobs.enqueue("catalogs", "catalog_sync", {})
    owner = f"{socket.gethostname()}:{os.getpid()}:catalogs"
    claimed = jobs.claim("catalogs", owner, lease_seconds=21600)
    assert claimed and claimed.id == job_id

    assert jobs.recover_running_jobs("catalogs") == 0
    assert jobs.list_jobs(1)[0]["state"] == "running"


def test_pending_job_can_be_cancelled():
    reset_jobs()
    job_id = jobs.enqueue("catalogs", "catalog_sync", {})
    assert jobs.cancel(job_id) is True
    record = jobs.list_jobs(1)[0]
    assert record["state"] == "cancelled"
    assert record["progress_percent"] == 100


def test_migration_copies_old_bulletins_and_catalogs(tmp_path, monkeypatch):
    from app import manage
    old_bulletins = tmp_path / "old-bulletins"
    old_pieces = tmp_path / "old-pieces"
    old_bulletins.mkdir()
    old_pieces.mkdir()
    old_pdf_dir = old_bulletins / "pdfs"
    old_pdf_dir.mkdir()
    (old_pdf_dir / "bulletin.pdf").write_bytes(b"%PDF")
    old_db = old_bulletins / "search.db"
    init_db(old_db)
    with bulletin_connect(old_db) as conn:
        conn.execute("INSERT INTO bulletins(url,title,filename,status) VALUES (?,?,?,?)", ("https://example/1", "B", "bulletin.pdf", "downloaded"))
        conn.commit()
    catalogs = old_pieces / "catalogues"
    catalogs.mkdir()
    (catalogs / "splendidparts.json").write_text('[{"nom":"Pièce"}]', encoding="utf-8")
    marker = manage.data_root() / "portal" / "migration-v1.json"
    marker.unlink(missing_ok=True)
    assert migrate(old_bulletins, old_pieces) == 0
    assert (manage.bulletin_settings.pdf_dir / "bulletin.pdf").exists()
    assert (manage.pieces_settings.data_dir / "catalogues" / "splendidparts.json").exists()
    assert marker.exists()
    report = json.loads(marker.read_text())
    assert report["sources"]["bulletins"] == str(old_bulletins)


def test_admin_password_reprompts_until_policy_and_confirmation_match(tmp_path, monkeypatch):
    from app import manage

    secrets_path = tmp_path / "secrets.json"
    config_path = tmp_path / "config.json"
    config_path.write_text('{"admin":{"username":"admin"}}', encoding="utf-8")
    answers = iter(["court", "ValideAdmin!123456", "different", "ValideAdmin!123456", "ValideAdmin!123456"])
    monkeypatch.setattr(manage, "SECRETS_PATH", secrets_path)
    monkeypatch.setattr(manage, "CONFIG_PATH", config_path)
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt: next(answers))
    assert manage.set_admin_password(no_restart_hint=True) == 0
    payload = json.loads(secrets_path.read_text())
    assert payload["admin_password_hash"].startswith("$argon2")
    assert payload["app_secret"]


def test_upgrade_cancels_old_catalog_jobs_and_normalizes_progress(tmp_path, monkeypatch):
    from app import manage
    from app.pieces.models import CatalogSyncStatus, CatalogSyncSupplierStatus
    from app.pieces.services import catalogs

    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / "jobs.sqlite3")
    reset_jobs()
    pending = jobs.enqueue("catalogs", "catalog_sync", {}, deduplication_key="pending-catalogs")
    running = jobs.enqueue("catalogs", "catalog_sync", {}, deduplication_key="running-catalogs")
    assert jobs.claim("catalogs", "missing-host:999999:catalogs").id == pending

    monkeypatch.setattr(catalogs, "CATALOG_DIR", tmp_path / "catalogues")
    monkeypatch.setattr(catalogs, "SYNC_STATUS_PATH", tmp_path / "catalogues/sync_status.json")
    monkeypatch.setattr(catalogs, "_STATUS", CatalogSyncStatus(
        running=True,
        queued=True,
        current_supplier="Fournisseur A",
        suppliers=[CatalogSyncSupplierStatus(
            site_id="supplier-a",
            site_name="Fournisseur A",
            status="running",
            progress_percent=73,
        )],
    ))
    monkeypatch.setattr(catalogs, "_RUNNING_THREAD", None)

    assert manage.reset_catalog_schedule_state() == 0
    records = {record["id"]: record for record in jobs.list_jobs(10)}
    assert records[pending]["state"] == "cancelled"
    assert records[running]["state"] == "cancelled"
    status = catalogs.get_sync_status()
    assert status.running is False
    assert status.queued is False
    assert status.current_supplier is None
    assert "synchronisation" in status.detail.lower()


def test_initial_catalog_retrieval_is_enqueued_only_when_portal_has_no_catalogue(tmp_path, monkeypatch):
    from app import manage
    from app.pieces.models import CatalogSyncStatus, CatalogSyncSupplierStatus
    from app.pieces.services import catalogs

    reset_jobs()
    monkeypatch.setattr(
        catalogs,
        "get_sync_status",
        lambda: CatalogSyncStatus(
            running=False,
            ready=False,
            suppliers=[
                CatalogSyncSupplierStatus(
                    site_id="supplier-a",
                    site_name="Fournisseur A",
                    status="missing",
                    ok=False,
                    item_count=0,
                    progress_percent=0,
                )
            ],
        ),
    )

    assert manage.enqueue_initial_catalogs() == 0
    pending = [record for record in jobs.list_jobs(10) if record["queue"] == "catalogs"]
    assert len(pending) == 1
    assert pending[0]["state"] == "pending"

    reset_jobs()
    monkeypatch.setattr(
        catalogs,
        "get_sync_status",
        lambda: CatalogSyncStatus(
            running=False,
            ready=True,
            suppliers=[
                CatalogSyncSupplierStatus(
                    site_id="supplier-a",
                    site_name="Fournisseur A",
                    status="ok",
                    ok=True,
                    item_count=100,
                    progress_percent=100,
                )
            ],
        ),
    )

    assert manage.enqueue_initial_catalogs() == 0
    assert [record for record in jobs.list_jobs(10) if record["queue"] == "catalogs"] == []
