from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as datetime_time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.common.config import ROOT
from app.pieces.config import settings
from app.pieces.models import CatalogSyncStatus, CatalogSyncSupplierStatus
from app.pieces.scrapers.sites import SITES
from app.pieces.services.history import archive_catalog, ensure_catalog_archived
from app.pieces.services.text import extract_price, normalize_text

SCRAPER_ROOT = ROOT / "scrapers"
PARIS_TZ = ZoneInfo("Europe/Paris")
CATALOG_DIR = settings.data_dir / "catalogues"
SYNC_STATUS_PATH = CATALOG_DIR / "sync_status.json"
OPEL_GT_SOURCE_SITE_ID = "opel_gt_source"

MODULE_BY_SITE_ID: dict[str, str] = {
    "opelix_parts": "opelixparts",
    "splendid_parts": "splendidparts",
    "edelschmiede": "edelschmiede",
    "pro_gt": "gtteile",
    "atz_online": "atz",
    "opel_gt_source": "opelgtsource",
    "oldtimer_motorenteile": "oldtimermotorenteile",
    "tw_oldtimerteile": "twoldtimerteile",
}

_LOCK = threading.RLock()
_RUNNING_THREAD: threading.Thread | None = None
_STATUS: CatalogSyncStatus | None = None


@dataclass(frozen=True)
class CatalogStartupCheck:
    update_required: bool
    reasons: tuple[str, ...]
    missing_site_ids: tuple[str, ...]
    latest_scheduled_update: datetime


@dataclass(frozen=True)
class CatalogMetrics:
    item_count: int
    known_prices: int
    known_availability: int
    unique_titles: int


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(PARIS_TZ)


def latest_scheduled_catalog_update(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(PARIS_TZ)
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    target_weekday = days.index(settings.weekly_catalog_update_day.lower())
    hour, minute = (int(part) for part in settings.daily_restart_time.split(":", 1))
    candidate_date = local_now.date() - timedelta(days=(local_now.weekday() - target_weekday) % 7)
    candidate = datetime.combine(candidate_date, datetime_time(hour, minute), tzinfo=PARIS_TZ)
    if candidate > local_now:
        candidate -= timedelta(days=7)
    return candidate


def catalog_startup_check(now: datetime | None = None) -> CatalogStartupCheck:
    status = _read_persisted_status()
    missing = tuple(
        site_id for site_id in MODULE_BY_SITE_ID if site_id in SITES and not _catalog_is_usable(site_id)
    )
    latest_due = latest_scheduled_catalog_update(now)
    last_completed = _parse_timestamp(status.last_completed_at)
    reasons: list[str] = []
    if missing:
        names = ", ".join(SITES[site_id].name for site_id in missing)
        reasons.append(f"catalogues absents ou invalides : {names}")
    if last_completed is None:
        reasons.append("aucune synchronisation complète enregistrée")
    elif last_completed < latest_due:
        reasons.append(
            "dernière synchronisation antérieure à l'échéance planifiée "
            f"du {latest_due.strftime('%d/%m/%Y à %H:%M')}"
        )
    return CatalogStartupCheck(
        update_required=bool(reasons),
        reasons=tuple(reasons),
        missing_site_ids=missing,
        latest_scheduled_update=latest_due,
    )


def catalog_status_is_current(status: CatalogSyncStatus, now: datetime | None = None) -> bool:
    last_completed = _parse_timestamp(status.last_completed_at)
    return last_completed is not None and last_completed >= latest_scheduled_catalog_update(now)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _catalog_path(site_id: str) -> Path:
    return CATALOG_DIR / f"{MODULE_BY_SITE_ID[site_id]}.json"


def _status_path(site_id: str) -> Path:
    return CATALOG_DIR / f"{MODULE_BY_SITE_ID[site_id]}.status.json"


def _standalone_opelgtsource_cache_dir() -> Path:
    """Return the cache location used by opelgtsource.py when run standalone.

    The standalone script defaults to ~/.cache/entraide-opel-gt/opelgtsource
    unless XDG_CACHE_HOME is set. The bundle stores its runtime cache in
    data/catalogues/_cache/opelgtsource for portability; seeding that directory
    from the standalone cache avoids re-downloading and re-translating the full
    Opel GT Source catalogue after the user has already run the scraper directly.
    """
    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    root = Path(xdg_cache_home) if xdg_cache_home else Path.home() / ".cache"
    return root / "entraide-opel-gt" / "opelgtsource"


def _seed_opelgtsource_cache(bundle_cache_dir: Path) -> None:
    source = _standalone_opelgtsource_cache_dir()
    if not source.is_dir():
        return
    try:
        if source.resolve() == bundle_cache_dir.resolve():
            return
    except OSError:
        return
    bundle_cache_dir.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = bundle_cache_dir / entry.name
        if target.exists():
            continue
        try:
            if entry.is_dir():
                shutil.copytree(entry, target)
            elif entry.is_file():
                shutil.copy2(entry, target)
        except OSError:
            # Cache seeding is an optimization only; a copy failure must never
            # prevent the catalogue synchronization from running normally.
            continue


def _supplier_defaults() -> list[CatalogSyncSupplierStatus]:
    return [
        CatalogSyncSupplierStatus(
            site_id=site_id,
            site_name=SITES[site_id].name,
            status="missing",
            ok=False,
            item_count=_catalog_item_count(_catalog_path(site_id)),
            message="Catalogue non synchronisé.",
            progress_percent=0,
        )
        for site_id in MODULE_BY_SITE_ID
        if site_id in SITES
    ]


def _catalog_item_count(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return len(data) if isinstance(data, list) else 0


def _availability_is_known(value: Any) -> bool:
    normalized = normalize_text(str(value or ""))
    return bool(normalized and normalized not in {"inconnu", "unknown", "a confirmer", "prix inconnu"})


def _catalog_metrics(site_id: str, path: Path | None = None) -> CatalogMetrics:
    catalog_path = path or _catalog_path(site_id)
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return CatalogMetrics(0, 0, 0, 0)
    if not isinstance(data, list):
        return CatalogMetrics(0, 0, 0, 0)
    known_prices = 0
    known_availability = 0
    titles: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        price, _currency = extract_price(str(item.get("prix") or ""), SITES[site_id].currency_hint)
        if price is not None:
            known_prices += 1
        if _availability_is_known(item.get("disponibilite")):
            known_availability += 1
        title = normalize_text(str(item.get("nom") or ""))
        if title:
            titles.add(title)
    return CatalogMetrics(len(data), known_prices, known_availability, len(titles))


def _catalog_suspicion_reasons(site_id: str, candidate_path: Path) -> tuple[str, ...]:
    current_path = _catalog_path(site_id)
    if not current_path.is_file():
        return ()
    baseline = _catalog_metrics(site_id, current_path)
    candidate = _catalog_metrics(site_id, candidate_path)
    if baseline.item_count < settings.catalog_min_baseline_items:
        return ()
    reasons: list[str] = []
    minimum_items = max(1, int(baseline.item_count * settings.catalog_min_item_ratio))
    if candidate.item_count < minimum_items:
        reasons.append(
            f"nombre de pièces anormalement faible ({candidate.item_count} contre {baseline.item_count})"
        )
    if baseline.known_prices >= 5:
        minimum_prices = max(1, int(baseline.known_prices * settings.catalog_min_known_price_ratio))
        if candidate.known_prices < minimum_prices:
            reasons.append(
                f"forte disparition des prix ({candidate.known_prices} contre {baseline.known_prices})"
            )
    if (
        settings.catalog_reject_zero_availability
        and baseline.known_availability > 0
        and candidate.known_availability == 0
    ):
        reasons.append(
            "aucune disponibilité reconnue alors que le catalogue précédent en contenait "
            f"{baseline.known_availability}"
        )
    return tuple(reasons)


def initialize_catalog_history() -> int:
    archived = 0
    for site_id in MODULE_BY_SITE_ID:
        if site_id not in SITES:
            continue
        if ensure_catalog_archived(
            site_id,
            _catalog_path(site_id),
            currency_hint=SITES[site_id].currency_hint,
        ):
            archived += 1
    return archived


def _catalog_quality(site_id: str, path: Path | None = None) -> tuple[bool, str, int, int]:
    """Validate catalogue structure and ensure prices were actually extracted."""

    catalog_path = path or _catalog_path(site_id)
    if not catalog_path.is_file():
        return False, "catalogue absent", 0, 0
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"JSON illisible : {exc}", 0, 0
    if not isinstance(data, list) or not data:
        return False, "catalogue vide", 0, 0

    required = {"nom", "nom_traduit", "prix", "disponibilite", "url_photo", "url_fiche"}
    known_prices = 0
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict) or not required <= set(item):
            return False, f"élément {index}: schéma incomplet", len(data), known_prices
        if not str(item.get("nom") or "").strip():
            return False, f"élément {index}: titre source vide", len(data), known_prices
        price, _currency = extract_price(str(item.get("prix") or ""), SITES[site_id].currency_hint)
        if price is not None:
            known_prices += 1

    if known_prices == 0:
        return (
            False,
            "aucun prix numérique extrait : catalogue refusé pour éviter de remplacer des données valides",
            len(data),
            0,
        )
    return True, "", len(data), known_prices


def _catalog_is_usable(site_id: str) -> bool:
    ok, _message, _item_count, _known_prices = _catalog_quality(site_id)
    return ok


def _recompute_ready(status: CatalogSyncStatus) -> CatalogSyncStatus:
    usable = {site_id: _catalog_is_usable(site_id) for site_id in MODULE_BY_SITE_ID if site_id in SITES}
    usable_count = sum(1 for ok in usable.values() if ok)
    any_usable = usable_count > 0
    suppliers = []
    by_id = {supplier.site_id: supplier for supplier in status.suppliers}
    for default in _supplier_defaults():
        current = by_id.get(default.site_id, default)
        item_count = _catalog_item_count(_catalog_path(default.site_id))
        is_usable = usable.get(default.site_id, False)
        if not status.running and current.status in {"pending", "running"}:
            current = current.model_copy(
                update={
                    "status": "ok" if is_usable else "failed",
                    "ok": is_usable,
                    "item_count": item_count,
                    "message": (
                        "Synchronisation interrompue ; catalogue local valide conservé."
                        if is_usable
                        else "Synchronisation interrompue avant la fin ; aucun catalogue local valide."
                    ),
                    "finished_at": current.finished_at or status.finished_at,
                    "progress_percent": 100,
                }
            )
        if not status.running and is_usable and current.status == "missing":
            current = current.model_copy(
                update={
                    "status": "ok",
                    "ok": True,
                    "item_count": item_count,
                    "message": "Catalogue local disponible.",
                    "progress_percent": 100,
                }
            )
        elif not status.running and is_usable and not current.ok and current.status != "running":
            # Preserve the last catalogue that passed validation when a later
            # retrieval fails; it becomes available again when the task ends.
            failure_message = current.message.strip()
            current = current.model_copy(
                update={
                    "status": "ok",
                    "ok": True,
                    "item_count": item_count,
                    "message": (
                        "Dernière récupération refusée ; catalogue local valide conservé."
                        + (f" Détail : {failure_message}" if failure_message else "")
                    ),
                    "progress_percent": 100,
                }
            )
        elif not status.running and is_usable and current.ok and current.progress_percent < 100 and current.status != "running":
            current = current.model_copy(update={"item_count": item_count, "progress_percent": 100})
        elif not is_usable and current.ok:
            current = current.model_copy(
                update={
                    "ok": False,
                    "item_count": item_count,
                    "message": current.message or "Catalogue local absent ou illisible.",
                    "progress_percent": 0
                    if current.status in {"missing", "pending"}
                    else current.progress_percent,
                }
            )
        elif item_count != current.item_count:
            current = current.model_copy(update={"item_count": item_count})
        suppliers.append(current)
    current = catalog_status_is_current(status)
    unavailable = [
        supplier.site_name for supplier in suppliers if not (supplier.ok and supplier.item_count > 0)
    ]
    detail = status.detail
    if status.running:
        detail = "Synchronisation des catalogues fournisseurs en cours."
    elif any_usable and unavailable:
        freshness = (
            " Le contrôle automatique périodique reste à effectuer ; "
            "les catalogues valides restent utilisables."
            if not current
            else ""
        )
        detail = (
            f"{usable_count}/{len(suppliers)} catalogue(s) prêt(s). "
            "Fournisseurs désactivés car catalogue indisponible : "
            + ", ".join(unavailable)
            + freshness
        )
    elif any_usable and not current:
        detail = (
            "Tous les catalogues locaux sont utilisables. "
            "Le contrôle automatique périodique reste à effectuer sans bloquer la recherche."
        )
    elif any_usable:
        detail = "Tous les catalogues fournisseurs sont prêts pour la recherche."
    elif not status.finished_at and not status.last_completed_at:
        detail = "Aucune synchronisation complète n'a encore été effectuée."
    else:
        detail = "Aucun catalogue fournisseur utilisable après la dernière tentative de synchronisation."
    return status.model_copy(
        update={
            "ready": any_usable,
            "detail": detail,
            "suppliers": suppliers,
        }
    )


def _read_persisted_status() -> CatalogSyncStatus:
    if not SYNC_STATUS_PATH.is_file():
        return _recompute_ready(CatalogSyncStatus(suppliers=_supplier_defaults()))
    try:
        payload = json.loads(SYNC_STATUS_PATH.read_text(encoding="utf-8"))
        status = CatalogSyncStatus.model_validate(payload)
        if status.running:
            status = status.model_copy(
                update={"running": False, "detail": "Synchronisation interrompue avant la fin."}
            )
    except Exception:
        return _recompute_ready(
            CatalogSyncStatus(
                detail="Fichier de statut de synchronisation illisible.", suppliers=_supplier_defaults()
            )
        )
    return _recompute_ready(status)


def read_sync_status_snapshot() -> CatalogSyncStatus:
    if not SYNC_STATUS_PATH.is_file():
        return _recompute_ready(CatalogSyncStatus(suppliers=_supplier_defaults()))
    try:
        payload = json.loads(SYNC_STATUS_PATH.read_text(encoding="utf-8"))
        status = CatalogSyncStatus.model_validate(payload)
    except Exception:
        return _recompute_ready(
            CatalogSyncStatus(
                detail="Fichier de statut de synchronisation illisible.", suppliers=_supplier_defaults()
            )
        )
    return _recompute_ready(status)


def _write_status(status: CatalogSyncStatus) -> None:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SYNC_STATUS_PATH.with_suffix(SYNC_STATUS_PATH.suffix + ".tmp")
    tmp.write_text(status.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(SYNC_STATUS_PATH)


def get_sync_status() -> CatalogSyncStatus:
    global _STATUS
    with _LOCK:
        if _STATUS is None:
            _STATUS = _read_persisted_status()
        return _recompute_ready(_STATUS)


def reset_unscheduled_catalog_state() -> int:
    global _RUNNING_THREAD, _STATUS
    with _LOCK:
        previous = _read_persisted_status()
        changed = int(
            SYNC_STATUS_PATH.is_file()
            and (previous.running or any(item.status in {"pending", "running"} for item in previous.suppliers))
        )
        normalized = previous.model_copy(
            update={
                "running": False,
                "queued": False,
                "current_supplier": None,
                "detail": "Aucune récupération de catalogues en cours ; prochaine exécution planifiée le dimanche à minuit.",
            }
        )
        _STATUS = _recompute_ready(normalized)
        _RUNNING_THREAD = None
        _write_status(_STATUS)
        with contextlib.suppress(FileNotFoundError):
            (CATALOG_DIR / ".force-update").unlink()
        return changed


def start_catalog_sync() -> CatalogSyncStatus:
    global _RUNNING_THREAD, _STATUS
    with _LOCK:
        if _RUNNING_THREAD is not None and _RUNNING_THREAD.is_alive():
            return _recompute_ready(_STATUS or _read_persisted_status())
        started = utc_now()
        previous = _read_persisted_status()
        _STATUS = CatalogSyncStatus(
            running=True,
            ready=False,
            started_at=started,
            finished_at=None,
            last_completed_at=previous.last_completed_at,
            last_success_at=previous.last_success_at,
            detail="Synchronisation des catalogues fournisseurs en cours.",
            suppliers=[
                CatalogSyncSupplierStatus(
                    site_id=site_id,
                    site_name=SITES[site_id].name,
                    status="pending",
                    ok=False,
                    item_count=_catalog_item_count(_catalog_path(site_id)),
                    message="En attente de synchronisation.",
                    progress_percent=0,
                )
                for site_id in MODULE_BY_SITE_ID
                if site_id in SITES
            ],
        )
        _write_status(_STATUS)
        _RUNNING_THREAD = threading.Thread(target=_sync_worker, name="catalog-sync", daemon=True)
        _RUNNING_THREAD.start()
        return _STATUS


def synchronize_catalogs_blocking(
    progress_callback: Callable[[CatalogSyncStatus], None] | None = None,
    *,
    timeout_seconds: int | None = None,
    poll_interval_seconds: float = 0.5,
) -> CatalogSyncStatus:
    status = start_catalog_sync()
    deadline = None if timeout_seconds is None else time.monotonic() + float(timeout_seconds)
    last_payload = ""
    last_callback_at = 0.0
    while True:
        payload = status.model_dump_json()
        now = time.monotonic()
        if progress_callback is not None and (payload != last_payload or now - last_callback_at >= 15.0):
            progress_callback(status)
            last_payload = payload
            last_callback_at = now
        if not status.running:
            return status
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(f"La synchronisation a dépassé {timeout_seconds} secondes.")
        time.sleep(max(0.05, poll_interval_seconds))
        status = get_sync_status()


def _set_supplier_status(site_id: str, update: dict[str, Any]) -> None:
    global _STATUS
    with _LOCK:
        assert _STATUS is not None
        suppliers = []
        for supplier in _STATUS.suppliers:
            if supplier.site_id == site_id:
                supplier = supplier.model_copy(update=update)
            suppliers.append(supplier)
        _STATUS = _STATUS.model_copy(update={"suppliers": suppliers})
        _write_status(_STATUS)


def _supplier_jobs() -> list[tuple[str, str]]:
    return [(site_id, module_name) for site_id, module_name in MODULE_BY_SITE_ID.items() if site_id in SITES]


def _mark_supplier_running(site_id: str) -> None:
    _set_supplier_status(
        site_id,
        {
            "status": "running",
            "started_at": utc_now(),
            "finished_at": None,
            "duration_seconds": None,
            "ok": _catalog_is_usable(site_id),
            "item_count": _catalog_item_count(_catalog_path(site_id)),
            "message": "Synchronisation en cours ; le dernier catalogue valide est conservé jusqu’à la fin du traitement.",
            "progress_percent": 5,
        },
    )


def _sync_one_supplier(site_id: str, module_name: str) -> None:
    _mark_supplier_running(site_id)
    try:
        result = _run_supplier_scraper(site_id, module_name)
        status_value = "ok" if result.get("ok") else result.get("status", "failed")
        if status_value not in {"ok", "unavailable", "failed"}:
            status_value = "failed"
        _set_supplier_status(
            site_id,
            {
                "status": status_value,
                "ok": bool(result.get("ok")),
                "item_count": int(result.get("item_count") or _catalog_item_count(_catalog_path(site_id))),
                "message": str(result.get("message") or "Synchronisation terminée."),
                "finished_at": utc_now(),
                "duration_seconds": float(result.get("duration_seconds") or 0.0),
                "progress_percent": 100,
            },
        )
    except Exception as exc:
        _set_supplier_status(
            site_id,
            {
                "status": "failed",
                "ok": False,
                "item_count": _catalog_item_count(_catalog_path(site_id)),
                "message": f"Échec contrôlé : {type(exc).__name__}",
                "finished_at": utc_now(),
                "duration_seconds": None,
                "progress_percent": 100,
            },
        )


def _finish_sync_status() -> None:
    global _STATUS
    with _LOCK:
        assert _STATUS is not None
        finished = utc_now()
        ready = any(_catalog_is_usable(site_id) for site_id in MODULE_BY_SITE_ID if site_id in SITES)
        _STATUS = _STATUS.model_copy(
            update={
                "running": False,
                "finished_at": finished,
                "last_completed_at": finished,
                "last_success_at": finished if ready else _STATUS.last_success_at,
            }
        )
        _STATUS = _recompute_ready(_STATUS)
        _write_status(_STATUS)


def _sync_worker() -> None:
    try:
        jobs = _supplier_jobs()
        if not jobs:
            return
        max_workers = max(1, min(len(jobs), settings.max_concurrent_sites or len(jobs)))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="catalog-supplier") as executor:
            futures = [executor.submit(_sync_one_supplier, site_id, module_name) for site_id, module_name in jobs]
            for future in as_completed(futures):
                with contextlib.suppress(Exception):
                    future.result()
    finally:
        _finish_sync_status()


def _python_executable_for_scraper_subprocess() -> str:
    return sys.executable


def _read_scraper_status(status_file: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(status_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_scraper_attempt_status(status_file: Path, result: dict[str, Any]) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_file.with_suffix(status_file.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(status_file)


def _run_supplier_scraper_subprocess(site_id: str, module_name: str) -> dict[str, Any]:
    python_exe = _python_executable_for_scraper_subprocess()
    script = SCRAPER_ROOT / f"{module_name}.py"
    if not script.is_file():
        raise RuntimeError(f"Script scraper absent : {script}")

    output = _catalog_path(site_id)
    status_file = _status_path(site_id)
    staging_output = output.with_name(output.stem + ".staging.json")
    staging_status = status_file.with_name(status_file.stem + ".staging.json")

    # A scraper must never write over the last valid catalogue before its new
    # output has passed both schema and price-quality checks.
    for path in (status_file, staging_output, staging_status):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    env = os.environ.copy()
    pythonpath_parts = [str(ROOT), str(SCRAPER_ROOT)]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(pythonpath_parts))
    env.setdefault("PYTHONUNBUFFERED", "1")

    if site_id == OPEL_GT_SOURCE_SITE_ID:
        ogs_cache_dir = CATALOG_DIR / "_cache" / "opelgtsource"
        _seed_opelgtsource_cache(ogs_cache_dir)
        env["OGS_CACHE_DIR"] = str(ogs_cache_dir)
        env.setdefault("OGS_CACHE_MODE", "prefer")
        env.setdefault("OGS_PAGE_WORKERS", str(max(1, settings.max_concurrent_pages_per_site)))
        env.setdefault("OGS_PAGE_BATCH_SIZE", "9999")
        env.setdefault("OGS_PAGE_BATCH_PAUSE", "0")
        env.setdefault("OGS_REQUEST_GAP", "0")
        env.setdefault("OGS_TRANSLATION_WORKERS", str(max(1, settings.max_concurrent_details)))

    try:
        completed = subprocess.run(
            [
                python_exe,
                str(script),
                "--output",
                str(staging_output),
                "--status-file",
                str(staging_status),
                "--quiet",
                "--strict",
            ],
            cwd=str(SCRAPER_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=settings.catalog_update_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        for path in (staging_output, staging_status):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        result = {
            "supplier": SITES[site_id].name,
            "status": "failed",
            "ok": False,
            "output_path": str(output),
            "status_path": str(status_file),
            "item_count": _catalog_item_count(output),
            "duration_seconds": float(settings.catalog_update_timeout_seconds),
            "message": f"Délai maximal dépassé ({settings.catalog_update_timeout_seconds} s).",
            "details": str(exc),
        }
        _write_scraper_attempt_status(status_file, result)
        return result

    result = _read_scraper_status(staging_status)
    tail = ((completed.stdout or "") + "\n" + (completed.stderr or ""))[-6000:]
    if result is None:
        result = {
            "supplier": SITES[site_id].name,
            "status": "failed",
            "ok": False,
            "item_count": _catalog_item_count(output),
            "duration_seconds": 0.0,
            "message": f"Le scraper n'a pas écrit de statut exploitable (code {completed.returncode}).",
            "details": tail,
        }
    elif completed.returncode != 0 and result.get("status") == "ok":
        result = {
            **result,
            "status": "failed",
            "ok": False,
            "message": "Code retour scraper non nul malgré un statut OK.",
        }

    if result.get("ok"):
        quality_ok, quality_message, item_count, known_prices = _catalog_quality(site_id, staging_output)
        if quality_ok:
            suspicion_reasons = _catalog_suspicion_reasons(site_id, staging_output)
            if suspicion_reasons:
                result = {
                    **result,
                    "status": "failed",
                    "ok": False,
                    "output_path": str(output),
                    "status_path": str(status_file),
                    "item_count": _catalog_item_count(output),
                    "message": (
                        "Catalogue nouvellement récupéré refusé comme statistiquement suspect : "
                        + "; ".join(suspicion_reasons)
                        + ". Dernier catalogue valide conservé."
                    ),
                    "details": tail,
                }
            else:
                archive_catalog(
                    site_id,
                    staging_output,
                    source="synchronization",
                    currency_hint=SITES[site_id].currency_hint,
                )
                staging_output.replace(output)
                result = {
                    **result,
                    "output_path": str(output),
                    "status_path": str(status_file),
                    "item_count": item_count,
                    "message": (
                        f"Scraping terminé : {item_count} pièce(s), {known_prices} prix numérique(s). "
                        "Instantané historique archivé."
                    ),
                }
        else:
            result = {
                **result,
                "status": "failed",
                "ok": False,
                "output_path": str(output),
                "status_path": str(status_file),
                "item_count": _catalog_item_count(output),
                "message": f"Catalogue nouvellement récupéré refusé : {quality_message}.",
                "details": tail,
            }
    else:
        result = {
            **result,
            "output_path": str(output),
            "status_path": str(status_file),
            "item_count": _catalog_item_count(output),
        }

    for path in (staging_output, staging_status):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    _write_scraper_attempt_status(status_file, result)
    return result


def _run_supplier_scraper(site_id: str, module_name: str) -> dict[str, Any]:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    if not SCRAPER_ROOT.is_dir():
        raise RuntimeError(f"Répertoire scrapers absent : {SCRAPER_ROOT}")

    # Le sous-processus reproduit le comportement CLI autonome des scrapers et
    # permet de récupérer les catalogues en parallèle sans état mutable partagé.
    return _run_supplier_scraper_subprocess(site_id, module_name)


def load_catalog(site_id: str) -> list[dict[str, Any]]:
    if site_id not in MODULE_BY_SITE_ID:
        raise KeyError(site_id)
    path = _catalog_path(site_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []
