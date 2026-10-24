from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.annonces.collectors import COLLECTORS, SOURCES, AccessRestricted, PartialCollection, PublicClient
from app.common.config import data_root

LOGGER = logging.getLogger("portail.annonces")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def directory() -> Path:
    return data_root() / "annonces"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
        os.chmod(temporary, 0o640)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def read_lock():
    """Hold a shared lock while reading, or report a live update immediately."""
    directory().mkdir(parents=True, exist_ok=True)
    stream = (directory() / "update.lock").open("a+")
    with stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            yield True
        else:
            yield False


def snapshot(*, include_items: bool = True) -> dict:
    root = directory()
    statuses = []
    items = []
    with read_lock() as running:
        for source in SOURCES:
            payload = read_json(root / f"{source.id}.json")
            rows = payload.get("items") if isinstance(payload.get("items"), list) else []
            statuses.append({
                "id": source.id, "name": source.name, "url": source.url,
                "status": payload.get("status", "missing"), "message": payload.get("message", "Première collecte en attente."),
                "last_attempt_at": payload.get("last_attempt_at"), "last_success_at": payload.get("last_success_at"), "count": len(rows),
            })
            if include_items and not running:
                items.extend(rows)
        return {
            "running": running, "items": items, "sources": statuses,
            "count": sum(source["count"] for source in statuses),
            "automaticFrequency": "Mise à jour automatique tous les jours à 02:00 (Europe/Paris).",
            "last_completed_at": read_json(root / "sync.json").get("finished_at"),
        }


def synchronize() -> int:
    root = directory()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "update.lock").open("a") as lock:
        # A page reading its snapshot holds a very short shared lock. Wait for
        # that read instead of mistaking it for an updater and skipping a day.
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    LOGGER.info("Une collecte ou lecture des annonces est déjà en cours.")
                    return 0
                time.sleep(0.05)
        started = utc_now()
        write_json(root / "sync.json", {"started_at": started, "finished_at": None})
        failures = 0
        try:
            for source in SOURCES:
                path = root / f"{source.id}.json"
                previous = read_json(path)
                attempt = utc_now()
                client = PublicClient(source)
                try:
                    items = COLLECTORS[source.id](client)
                    prior_items = previous.get("items", [])
                    if len(prior_items) >= 5 and len(items) < len(prior_items) * 0.5:
                        raise RuntimeError("Baisse inhabituelle du nombre d'annonces ; vérification nécessaire.")
                    missing = sum(item["seller_type"] == "inconnu" for item in items)
                    payload = {
                        "items": items, "last_attempt_at": attempt, "last_success_at": utc_now(), "status": "ok",
                        "message": f"{len(items)} annonce(s) récupérée(s)." + (f" Type de vendeur non fourni pour {missing} annonce(s)." if missing else ""),
                    }
                except PartialCollection as exc:
                    failures += 1
                    fresh = {item["id"]: item for item in exc.items}
                    prior_rows = previous.get("items", [])
                    prior_rows = prior_rows if isinstance(prior_rows, list) else []
                    completed = set(exc.completed_sellers)
                    for seller in tuple(completed):
                        old_count = sum(isinstance(item, dict) and item.get("seller_type") == seller for item in prior_rows)
                        new_count = sum(item.get("seller_type") == seller for item in fresh.values())
                        if old_count >= 5 and new_count < old_count * 0.5:
                            completed.remove(seller)
                    retained = {
                        item["id"]: item for item in prior_rows
                        if isinstance(item, dict) and item.get("id") and
                        item.get("seller_type") not in completed and item["id"] not in fresh
                    }
                    payload = {
                        "items": [*retained.values(), *fresh.values()],
                        "last_success_at": previous.get("last_success_at"),
                        "last_attempt_at": attempt, "last_partial_at": utc_now(),
                        "status": "restricted" if exc.restricted else "failed",
                        "message": str(exc)[:250] + f" Collecte incomplète : {len(fresh)} annonce(s) récupérée(s), "
                                   f"{len(retained)} annonce(s) antérieure(s) conservée(s).",
                    }
                    LOGGER.warning("%s : %s", source.name, payload["message"])
                except Exception as exc:
                    failures += 1
                    LOGGER.warning("%s : %s", source.name, exc)
                    payload = {
                        "items": previous.get("items", []), "last_success_at": previous.get("last_success_at"),
                        "last_attempt_at": attempt, "status": "restricted" if isinstance(exc, AccessRestricted) else "failed",
                        "message": str(exc)[:500] + (" Dernières annonces conservées." if previous.get("items") else " Aucune annonce récupérée pour cette source."),
                    }
                finally:
                    client.close()
                write_json(path, payload)
                LOGGER.info("%s : %s", source.name, payload["message"])
        finally:
            write_json(root / "sync.json", {"started_at": started, "finished_at": utc_now(), "failures": failures})
        return 0 if failures < len(SOURCES) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(synchronize())
