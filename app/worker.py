from __future__ import annotations

import argparse
import logging
import os
import socket
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.bulletins.config import settings as bulletin_settings
from app.bulletins.database import connect as bulletin_connect
from app.bulletins.database import init_db
from app.common.config import data_root, section
from app.common.jobs import Job, cancelled, claim, fail, finish, heartbeat, init_jobs, recover_running_jobs, set_item

LOGGER = logging.getLogger("portail.worker")


def process_ocr(job: Job, worker_id: str) -> None:
    from app.bulletins.indexer import extract_pdf_pages, store_pdf_index
    bulletin_id = int(job.payload["bulletin_id"])
    init_db(bulletin_settings.db_path)
    with bulletin_connect(bulletin_settings.db_path) as conn:
        row = conn.execute("SELECT * FROM bulletins WHERE id=?", (bulletin_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"Bulletin {bulletin_id} introuvable.")
        bulletin = dict(row)
        filename = str(bulletin.get("filename") or bulletin_id)
        if cancelled(job.id):
            set_item(job.id, filename, "cancelled", "Annulation demandée avant l'OCR.")
            finish(job.id, warnings=1, message="OCR annulé.")
            return
        local_path = Path(str(bulletin.get("local_path") or ""))
        if not local_path.is_file():
            conn.execute("UPDATE bulletins SET status='index-error' WHERE id=?", (bulletin_id,))
            conn.commit()
            set_item(job.id, filename, "failed", "PDF local absent.")
            raise RuntimeError(f"PDF local absent : {local_path}")
        heartbeat(job.id, worker_id, message=f"OCR de {filename}", current=0, total=1)
        try:
            pages = extract_pdf_pages(bulletin_settings, bulletin)
            store_pdf_index(conn, bulletin_settings, bulletin, pages)
            conn.commit()
        except Exception:
            conn.execute("UPDATE bulletins SET status='index-error' WHERE id=?", (bulletin_id,))
            conn.commit()
            set_item(job.id, filename, "failed", "Échec OCR/indexation.")
            raise
        set_item(job.id, filename, "succeeded", f"{len(pages)} page(s) indexée(s).")
        finish(job.id, message=f"OCR/indexation terminée pour {filename}.")


def process_catalogs(job: Job, worker_id: str) -> None:
    from app.pieces.services.catalogs import synchronize_catalogs_blocking
    def progress(status):
        terminal = {"ok", "failed", "unavailable"}
        done = sum(1 for supplier in status.suppliers if supplier.status in terminal)
        heartbeat(
            job.id,
            worker_id,
            message=status.detail or "Synchronisation des catalogues.",
            current=done,
            total=len(status.suppliers),
            lease_seconds=int(section("maintenance").get("catalog_update_timeout_seconds", 21600)) + 300,
        )
        for supplier in status.suppliers:
            if supplier.status in terminal:
                item_state = "succeeded" if supplier.ok else "failed"
                set_item(job.id, supplier.site_id, item_state, supplier.message)

    status = synchronize_catalogs_blocking(
        progress_callback=progress,
        timeout_seconds=int(section("maintenance").get("catalog_update_timeout_seconds", 21600)) + 60,
    )
    failed_count = sum(1 for supplier in status.suppliers if not supplier.ok)
    finish(
        job.id,
        warnings=failed_count,
        message=(
            "Synchronisation terminée avec avertissements ; les derniers catalogues valides restent disponibles."
            if failed_count
            else "Synchronisation de tous les catalogues terminée."
        ),
    )


def process(job: Job, worker_id: str) -> None:
    if job.job_type == "bulletin_index":
        process_ocr(job, worker_id)
        return
    if job.job_type == "catalog_sync":
        process_catalogs(job, worker_id)
        return
    raise RuntimeError(f"Type de tâche non pris en charge : {job.job_type}")


def run(queue: str, *, once: bool = False) -> int:
    init_jobs()
    recovered = recover_running_jobs(queue)
    if recovered:
        LOGGER.warning("%s tâche(s) %s reprise(s) après redémarrage du worker.", recovered, queue)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{queue}"
    poll = max(0.2, float(section("jobs").get("poll_seconds", 2)))
    while True:
        job = claim(queue, worker_id)
        if job is None:
            if once:
                return 0
            time.sleep(poll)
            continue
        try:
            process(job, worker_id)
        except Exception as exc:
            LOGGER.exception("Échec de la tâche %s", job.id)
            fail(job, f"{type(exc).__name__}: {exc}")
        if once:
            return 0


def configure_logging(queue: str) -> None:
    log_dir = data_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / f"{queue}-worker.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker du portail Entraide Opel GT")
    parser.add_argument("--queue", required=True, choices=("ocr", "catalogs"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    configure_logging(args.queue)
    return run(args.queue, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
