from __future__ import annotations

import fcntl
import logging
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.annonces.collectors import COLLECTORS, SOURCES, AccessRestricted, PartialCollection, PublicClient
from app.annonces.geography import GeoResolver, valid_geo
from app.annonces.tracking import archived_favorites, locked, read_json, record_observations, write_json
from app.common.config import data_root
from app.common.control_client import ControlChannelError, request_system_action

LOGGER = logging.getLogger("portail.annonces")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def directory() -> Path:
    return data_root() / "annonces"


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


def snapshot(*, include_items: bool = True, favorites: list[str] | None = None) -> dict:
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
                "last_attempt_at": payload.get("last_attempt_at"), "last_success_at": payload.get("last_success_at"),
                "last_partial_at": payload.get("last_partial_at"), "count": len(rows),
            })
            if include_items:
                items.extend(rows)
        if include_items and favorites:
            items.extend(archived_favorites(root, favorites, {item.get("id") for item in items}))
        sync = read_json(root / "sync.json")
        manual = read_json(root / "manual.json")
        requested = float(manual.get("requested_epoch", 0))
        queued = time.time() - requested < 30 and manual.get("requested_at", "") > (sync.get("started_at") or "")
        return {
            "running": running or queued, "items": items, "sources": statuses,
            "progress": sync.get("progress", {}) if running else {},
            "next_refresh_at": requested + 1800 if requested else 0,
            "count": sum(source["count"] for source in statuses),
            "automaticFrequency": "Mise à jour automatique tous les jours à 02:00 (Europe/Paris).",
            "last_completed_at": sync.get("finished_at"),
        }


def request_refresh() -> dict:
    root = directory()
    with locked(root / "manual.lock"):
        current = snapshot(include_items=False)
        if current["running"]:
            return {"ok": True, "running": True, "message": "Une collecte est déjà en cours."}
        if current["next_refresh_at"] > time.time():
            return {"ok": False, "retry_after": int(current["next_refresh_at"] - time.time()) + 1,
                    "message": "Une actualisation manuelle est autorisée toutes les 30 minutes."}
        timestamp = utc_now()
        try:
            result = request_system_action("refresh-annonces")
            if not result.get("ok"):
                raise ControlChannelError("Le service de collecte n’a pas pu démarrer.")
        except ControlChannelError:
            if Path("/run/systemd/system").exists():
                raise
            # Standalone development mode: collection still lives outside the
            # request, and the same file lock prevents overlapping workers.
            with (root / "update.log").open("ab") as stream:
                subprocess.Popen([sys.executable, "-m", "app.annonces.service"], stdin=subprocess.DEVNULL,
                                 stdout=stream, stderr=stream, start_new_session=True)
        write_json(root / "manual.json", {"requested_at": timestamp, "requested_epoch": time.time()})
    return {"ok": True, "running": True, "message": "Actualisation lancée. Les annonces restent consultables."}


def repair_geography(root: Path, resolver: GeoResolver) -> int:
    """Repair saved adverts before contacting their sources, under the update lock."""
    history = read_json(root / "history.json")
    entries = history.get("ads", {})
    history_changed = False
    count = 0
    for source in SOURCES:
        path = root / f"{source.id}.json"
        payload = read_json(path)
        changed = False
        rows = payload.get("items") if isinstance(payload.get("items"), list) else []
        for item in rows:
            if not isinstance(item, dict) or valid_geo(item.get("geo")):
                continue
            geo = resolver.resolve(item)
            if not geo:
                continue
            item["geo"] = geo
            changed = True
            count += 1
            entry = entries.get(item.get("id"), {})
            if isinstance(entry.get("latest"), dict) and all(item.get(field) == entry["latest"].get(field)
                                                            for field in ("location", "department", "postal_code")):
                entry["latest"]["geo"] = geo
                history_changed = True
        if changed:
            write_json(path, payload)
    if history_changed:
        write_json(root / "history.json", history)
    return count


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
        progress = {source.id: "pending" for source in SOURCES}
        write_json(root / "sync.json", {"started_at": started, "finished_at": None, "progress": progress})
        failures = 0
        resolver = GeoResolver(root)
        try:
            repaired = repair_geography(root, resolver)
            LOGGER.info("Géolocalisation des annonces enregistrées : %s repère(s) complété(s).", repaired)
            for source in SOURCES:
                path = root / f"{source.id}.json"
                previous = read_json(path)
                attempt = utc_now()
                client = PublicClient(source)
                observed = set()
                progress[source.id] = "running"
                write_json(root / "sync.json", {"started_at": started, "finished_at": None, "progress": progress})
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
                    observed = {item["id"] for item in items}
                except PartialCollection as exc:
                    failures += 1
                    fresh = {item["id"]: item for item in exc.items}
                    observed = set(fresh)
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
                record_observations(root, source.id, previous, payload, observed, utc_now(), resolver)
                write_json(path, payload)
                progress[source.id] = payload["status"]
                write_json(root / "sync.json", {"started_at": started, "finished_at": None, "progress": progress})
                LOGGER.info("%s : %s", source.name, payload["message"])
        finally:
            try:
                resolver.close()
            finally:
                write_json(root / "sync.json", {"started_at": started, "finished_at": utc_now(), "failures": failures, "progress": progress})
        return 0 if failures < len(SOURCES) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(synchronize())
