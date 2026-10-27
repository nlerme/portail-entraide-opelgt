"""Initial and weekly incremental bulletin downloads, independent of web sessions."""
from __future__ import annotations

import fcntl
import logging
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.bulletins.config import settings
from app.bulletins.crawler import EntraideCrawler
from app.bulletins.database import connect, init_db
from app.bulletins.sync import SyncManager
from app.common.bulletin_setup import validate
from app.common.config import SECRETS_PATH
from app.common.jobs import init_jobs
from app.common.ntfy_setup import read

LOGGER = logging.getLogger("portail.bulletins")
PARIS = ZoneInfo("Europe/Paris")


def latest_weekly_update(now: datetime) -> datetime:
    local = now.astimezone(PARIS)
    day = local.date() - timedelta(days=(local.weekday() - 6) % 7)
    scheduled = datetime.combine(day, time(2), tzinfo=PARIS)
    return scheduled - timedelta(days=7) if scheduled > local else scheduled


def update_required(now: datetime) -> bool:
    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT finished_at FROM sync_runs WHERE status='finished' AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return True
    try:
        finished = datetime.fromisoformat(row["finished_at"])
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return finished.astimezone(timezone.utc) < latest_weekly_update(now).astimezone(timezone.utc)


def synchronize(now: datetime | None = None) -> int:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(settings.data_dir / "automatic.lock", os.O_CREAT | os.O_RDWR, 0o640)
    with os.fdopen(descriptor, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOGGER.info("Une collecte automatique des bulletins est déjà en cours.")
            return 0
        init_db(settings.db_path)
        init_jobs()
        if not update_required(now or datetime.now(timezone.utc)):
            LOGGER.info("Bulletins déjà synchronisés depuis l’échéance hebdomadaire ; aucune nouvelle collecte.")
            return 0
        try:
            credentials = validate(read(SECRETS_PATH).get("bulletins", {}))
        except (ValueError, OSError):
            LOGGER.error("Identifiants des bulletins absents ou invalides. Relancez run_server.sh install pour les renseigner.")
            return 1
        manager = SyncManager(settings, settings.db_path)
        state = manager.run(EntraideCrawler(settings), credentials=credentials)
        LOGGER.info("%s", state["message"])
        return 0 if state["phase"] == "finished" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(synchronize())
