from __future__ import annotations

import ipaddress
import json
import logging
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.annonces.service import snapshot as annonces_snapshot
from app.bulletins.config import settings as bulletin_settings
from app.bulletins.crawler import (
    AuthenticationError,
    EntraideCrawler,
    is_index_bulletins_filename,
    parse_bulletin_metadata,
)
from app.bulletins.database import connect as bulletin_connect
from app.bulletins.database import dict_rows, init_db
from app.bulletins.maintenance import augment_sync_state, cleanup_stale_sync_state, readiness
from app.bulletins.preflight import run_preflight_checks
from app.bulletins.search import search_pages
from app.bulletins.sync import SyncManager
from app.common.access_stats import initialize as initialize_access_stats
from app.common.access_stats import record_login_attempt
from app.common.access_stats import statistics as login_statistics
from app.common.auth import (
    admin_session,
    cleanup_sessions,
    create_admin_session,
    create_member_session,
    enforce_rate_limit,
    keep_admin_alive,
    keep_member_alive,
    mark_admin_closing,
    mark_member_closing,
    member_session,
    require_admin,
    require_csrf,
    require_member,
    revoke_admin,
    revoke_member,
    session_duration_minutes,
    verify_admin_password,
)
from app.common.config import CONFIG_PATH, ROOT, SECRETS_PATH, data_root, section
from app.common.control_client import (
    ControlChannelError,
    request_config_write,
    request_ntfy_write,
    request_system_action,
)
from app.common.jobs import cancel as cancel_job
from app.common.jobs import init_jobs, list_jobs
from app.common.jobs import summary as jobs_summary
from app.common.ntfy_settings import public_settings, save_settings, updated_settings
from app.common.ntfy_setup import read as read_secrets
from app.common.version import VERSION
from app.pieces.config import settings as pieces_settings
from app.pieces.models import CatalogSyncStatus, ConnectivityStatus, SearchRequest, SearchResponse, SiteStatus
from app.pieces.scrapers.sites import SITES
from app.pieces.services.catalogs import read_sync_status_snapshot
from app.pieces.services.connectivity import check_internet
from app.pieces.services.search import run_search
from app.pieces.services.status import check_all_sites

STATIC = ROOT / "static"
RESOURCES = ROOT / "resources"
COUPLES_DATA_PATH = RESOURCES / "couples" / "couples_serrage.json"
FIXED_DOCUMENTS = {
    "fiche-intervention.pdf": RESOURCES / "documents" / "fiche-intervention.pdf",
    "inventaire-avant-deplacement.pdf": RESOURCES / "documents" / "inventaire-avant-deplacement.pdf",
    "liste-visserie-opel-gt.pdf": RESOURCES / "documents" / "liste-visserie-opel-gt.pdf",
    "couples-serrage-opel-gt.pdf": RESOURCES / "documents" / "couples-serrage-opel-gt.pdf",
    "couples-serrage-opel-gt.xlsx": RESOURCES / "couples" / "couples_serrage.xlsx",
}
LOGGER = logging.getLogger("portail.web")


_CPU_SAMPLE_LOCK = threading.Lock()
_CPU_SAMPLE: dict[int, tuple[int, int]] | None = None


@lru_cache(maxsize=1)
def _cpu_indices_from_cpuinfo() -> list[int]:
    indices: list[int] = []
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if not line.lower().startswith("processor") or ":" not in line:
                continue
            indices.append(int(line.split(":", 1)[1].strip()))
    except (OSError, ValueError):
        return []
    return sorted(set(indices))


def _read_proc_cpus() -> dict[int, tuple[int, int]]:
    samples: dict[int, tuple[int, int]] = {}
    try:
        lines = Path("/proc/stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return samples
    for line in lines:
        fields = line.split()
        if not fields or not fields[0].startswith("cpu") or fields[0] == "cpu":
            continue
        suffix = fields[0][3:]
        if not suffix.isdigit():
            continue
        try:
            values = [int(value) for value in fields[1:]]
        except ValueError:
            continue
        total = sum(values)
        idle = (values[3] if len(values) > 3 else 0) + (values[4] if len(values) > 4 else 0)
        samples[int(suffix)] = (total, idle)
    expected = _cpu_indices_from_cpuinfo()
    if expected:
        samples = {index: samples[index] for index in expected if index in samples}
    return samples


def _read_memory_metrics() -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return 0, 0
    total = max(0, values.get("MemTotal", 0))
    available = max(0, values.get("MemAvailable", values.get("MemFree", 0)))
    return total, max(0, total - available)


def _system_metrics() -> dict[str, Any]:
    global _CPU_SAMPLE
    sample = _read_proc_cpus()
    cpu_percents: list[float] = []
    labels = [f"CPU {index + 1}" for index in sample]
    with _CPU_SAMPLE_LOCK:
        previous = _CPU_SAMPLE
        _CPU_SAMPLE = sample
    for index, current in sample.items():
        percent = 0.0
        if previous and index in previous:
            total_delta = current[0] - previous[index][0]
            idle_delta = current[1] - previous[index][1]
            if total_delta > 0:
                percent = (1.0 - idle_delta / total_delta) * 100.0
        cpu_percents.append(round(max(0.0, min(100.0, percent)), 1))
    cpu_percent = round(sum(cpu_percents) / len(cpu_percents), 1) if cpu_percents else 0.0
    total_memory, used_memory = _read_memory_metrics()
    memory_percent = (used_memory / total_memory * 100.0) if total_memory else 0.0
    return {
        "timestamp": time_now(),
        "cpuPercent": cpu_percent,
        "cpuPercents": cpu_percents,
        "cpuLabels": labels,
        "memoryPercent": round(memory_percent, 1),
        "memoryUsedBytes": used_memory,
        "memoryTotalBytes": total_memory,
        "cpuCount": len(cpu_percents) or max(1, os.cpu_count() or 1),
    }


class LoginPayload(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class BulletinSearchPayload(BaseModel):
    keywords: str = Field(min_length=1, max_length=500)
    mode: str = "all"
    yearFrom: int | None = None
    yearTo: int | None = None
    bulletinFrom: int | None = None
    bulletinTo: int | None = None
    limit: int = 50
    offset: int = 0


class AdminLoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class AdminControlPayload(BaseModel):
    action: str = Field(min_length=1, max_length=80)


class AdminConfigPayload(BaseModel):
    content: str = Field(min_length=2, max_length=512 * 1024)


class SessionClosingPayload(BaseModel):
    csrfToken: str = Field(min_length=16, max_length=256)


def _refresh_preflight(application: FastAPI) -> None:
    try:
        application.state.preflight = run_preflight_checks(bulletin_settings)
    except Exception as exc:  # noqa: BLE001
        application.state.preflight = {
            "ok": False,
            "pending": False,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "durationMs": 0,
            "checks": [],
            "message": f"Contrôle réseau indisponible : {exc}",
        }


@asynccontextmanager
async def lifespan(application: FastAPI):
    root = data_root()
    for path in (
        root / "portal",
        root / "bulletins" / "pdf",
        root / "pieces" / "catalogues",
        root / "pieces" / "cache",
        root / "logs",
        root / "backups",
    ):
        path.mkdir(parents=True, exist_ok=True)
    init_jobs()
    init_db(bulletin_settings.db_path)
    initialize_access_stats()
    cleanup_stale_sync_state(bulletin_settings)
    application.state.sync_manager = SyncManager(bulletin_settings, bulletin_settings.db_path)
    application.state.preflight = {
        "ok": False,
        "pending": True,
        "checkedAt": None,
        "durationMs": 0,
        "checks": [],
        "message": "Contrôle réseau en cours.",
    }
    threading.Thread(target=_refresh_preflight, args=(application,), daemon=True, name="network-preflight").start()
    yield


app = FastAPI(
    title="Portail Entraide Opel GT",
    version=VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet, noimageindex"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    pdf_renderer = request.url.path == "/bulletins" or request.url.path.startswith("/static/vendor/pdfjs-")
    script_sources = "'self' 'wasm-unsafe-eval'" if pdf_renderer else "'self'"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
        f"script-src {script_sources}; worker-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; "
        "font-src 'self'; object-src 'none'"
    )
    if request.url.path.startswith(("/api/", "/admin", "/documents/")) or request.url.path in {"/", "/services", "/bulletins", "/pieces", "/couples", "/annonces"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "message": str(exc.detail)})


@app.get("/robots.txt", include_in_schema=False)
def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /\n", headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def login_page(request: Request) -> Response:
    if member_session(request):
        return RedirectResponse("/services", status_code=303)
    return FileResponse(STATIC / "common" / "login.html")


@app.get("/services", include_in_schema=False)
def services_page(request: Request) -> Response:
    if member_session(request) is None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "common" / "services.html")


@app.get("/bulletins", include_in_schema=False)
def bulletins_page(request: Request) -> Response:
    if member_session(request) is None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "bulletins" / "index.html")


@app.get("/pieces", include_in_schema=False)
def pieces_page(request: Request) -> Response:
    if member_session(request) is None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "pieces" / "index.html")


@app.get("/couples", include_in_schema=False)
def couples_page(request: Request) -> Response:
    if member_session(request) is None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "couples" / "index.html")


@app.get("/annonces", include_in_schema=False)
def annonces_page(request: Request) -> Response:
    if member_session(request) is None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "annonces" / "index.html")


@app.get("/api/annonces")
def annonces_data(request: Request) -> dict[str, Any]:
    require_member(request)
    return annonces_snapshot()


@lru_cache(maxsize=1)
def _bundled_documents() -> dict[str, Path]:
    documents = dict(FIXED_DOCUMENTS)
    payload = _couples_data()
    for view in payload.get("views", []):
        if not isinstance(view, dict):
            continue
        for key in ("pdf", "image"):
            raw_path = str(view.get(key, ""))
            if not raw_path.startswith("/documents/"):
                continue
            name = Path(raw_path).name
            if not name or name != raw_path.rsplit("/", 1)[-1]:
                continue
            documents[name] = RESOURCES / "documents" / name
    return documents


@app.get("/documents/{document_name}", include_in_schema=False)
def bundled_document(document_name: str, request: Request) -> Response:
    require_member(request)
    path = _bundled_documents().get(document_name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Document introuvable.")
    suffix = path.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    media_type = media_types.get(suffix)
    if media_type is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if suffix == ".xlsx":
        return FileResponse(path, media_type=media_type, filename=document_name)
    return FileResponse(path, media_type=media_type)


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(STATIC / "admin" / "index.html")


def _is_local_network_client(host: str) -> bool:
    normalized = host.strip().lower().split("%", 1)[0]
    if normalized in {"localhost", "testclient"}:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _remote_http_forbidden(request: Request) -> bool:
    authentication = section("authentication")
    if request.url.scheme == "https" or bool(authentication.get("allow_insecure_remote_http", False)):
        return False
    host = request.client.host if request.client else ""
    return not (
        bool(authentication.get("allow_insecure_lan_http", True))
        and _is_local_network_client(host)
    )


@app.post("/api/login")
def login(payload: LoginPayload, request: Request) -> JSONResponse:
    if _remote_http_forbidden(request):
        record_login_attempt(request, "member", "https-required")
        raise HTTPException(status_code=403, detail="La connexion membre en HTTP est autorisée uniquement depuis le réseau local. Utilisez HTTPS pour un accès depuis Internet.")
    authentication = section("authentication")
    limit = int(authentication.get("login_rate_limit_attempts", 5))
    window = int(authentication.get("login_rate_limit_window_seconds", 300))
    try:
        enforce_rate_limit(request, "member-login", limit, window)
    except HTTPException:
        record_login_attempt(request, "member", "rate-limited")
        raise
    crawler = EntraideCrawler(bulletin_settings)
    try:
        crawler.login(payload.login, payload.password)
    except AuthenticationError as exc:
        crawler.session.close()
        record_login_attempt(request, "member", "failed")
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        crawler.session.close()
        record_login_attempt(request, "member", "error")
        raise HTTPException(status_code=502, detail="Connexion au site membre momentanément impossible.") from exc
    record_login_attempt(request, "member", "success")
    response = JSONResponse({"ok": True, "user": payload.login})
    session = create_member_session(payload.login, response, request)
    sync_started = request.app.state.sync_manager.start(crawler, force_reindex=False)
    if not sync_started:
        crawler.session.close()
    response.body = json.dumps(
        {
            "ok": True,
            "user": payload.login,
            "csrfToken": session.csrf_token,
            "expiresAt": session.expires_at,
            "durationMinutes": session_duration_minutes(),
            "serverTime": time_now(),
            "bulletinSyncStarted": sync_started,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    response.headers["content-length"] = str(len(response.body))
    return response


@app.post("/api/logout")
def logout(request: Request) -> JSONResponse:
    require_csrf(request)
    response = JSONResponse({"ok": True})
    revoke_member(request, response)
    return response


def time_now() -> float:
    return datetime.now(timezone.utc).timestamp()


@app.get("/api/session")
def session_status(request: Request) -> dict[str, Any]:
    cleanup_sessions()
    current = member_session(request)
    return {
        "authenticated": current is not None,
        "user": current.subject if current else None,
        "csrfToken": current.csrf_token if current else None,
        "expiresAt": current.expires_at if current else None,
        "durationMinutes": session_duration_minutes(),
        "serverTime": time_now(),
    }


@app.post("/api/session/closing")
def member_session_closing(payload: SessionClosingPayload, request: Request) -> dict[str, bool]:
    return {"ok": mark_member_closing(request, payload.csrfToken)}


@app.post("/api/session/keepalive")
def member_session_keepalive(request: Request) -> dict[str, Any]:
    current = require_csrf(request)
    keep_member_alive(request)
    return {"ok": True, "expiresAt": current.expires_at, "serverTime": time_now()}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "portail-entraide-opel-gt", "version": VERSION, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/connectivity", response_model=ConnectivityStatus)
async def public_connectivity(force: bool = Query(False)) -> ConnectivityStatus:
    return await check_internet(force=force)


def _active_jobs(queue: str) -> list[dict[str, Any]]:
    return [job for job in list_jobs(500) if job["queue"] == queue and job["state"] in {"pending", "running"}]


def _catalog_status_for_api() -> CatalogSyncStatus:
    status = read_sync_status_snapshot()
    active = _active_jobs("catalogs")
    queued = any(job["state"] == "pending" for job in active)
    running = bool(status.running or active)
    suppliers = status.suppliers
    preparing = bool(active and not status.running)
    if preparing:
        suppliers = [
            item.model_copy(
                update={
                    "status": "pending",
                    "ok": False,
                    "progress_percent": 0,
                    "message": "En attente du démarrage de la récupération.",
                }
            )
            for item in suppliers
        ]
    progress = round(sum(int(item.progress_percent or 0) for item in suppliers) / len(suppliers)) if suppliers else 0
    current = next((item.site_name for item in suppliers if item.status == "running"), None)
    if not running and status.ready:
        progress = 100
    detail = status.detail
    if preparing:
        detail = (
            "Mise à jour des catalogues en attente de prise en charge par le worker."
            if queued
            else "Le worker prépare la récupération des catalogues fournisseurs."
        )
    return status.model_copy(update={
        "running": running,
        "queued": queued,
        "global_progress_percent": progress,
        "current_supplier": current,
        "detail": detail,
        "suppliers": suppliers,
    })


def _bulletin_processing_status(request: Request) -> dict[str, Any]:
    state = augment_sync_state(bulletin_settings, request.app.state.sync_manager.state())
    ocr_jobs = [job for job in list_jobs(500) if job["queue"] == "ocr"]
    active_jobs = [job for job in ocr_jobs if job["state"] in {"pending", "running"}]
    running_job = next((job for job in active_jobs if job["state"] == "running"), None)
    current_file = None
    if running_job:
        bulletin_id = running_job.get("payload", {}).get("bulletin_id")
        if bulletin_id is not None:
            with bulletin_connect(bulletin_settings.db_path) as conn:
                row = conn.execute("SELECT filename FROM bulletins WHERE id=?", (int(bulletin_id),)).fetchone()
            if row:
                current_file = str(row["filename"])
        current_file = current_file or str(running_job.get("message") or "") or None
    with bulletin_connect(bulletin_settings.db_path) as conn:
        counts = conn.execute(
            """SELECT
                   SUM(CASE WHEN indexed_at IS NOT NULL AND pages>0 THEN 1 ELSE 0 END) AS indexed,
                   SUM(CASE WHEN status='index-error' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status='index-pending' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN local_path IS NOT NULL AND local_path<>'' THEN 1 ELSE 0 END) AS local_count
               FROM bulletins"""
        ).fetchone()
    indexed = int(counts["indexed"] or 0)
    failed = int(counts["failed"] or 0)
    pending = int(counts["pending"] or 0)
    total = int(counts["local_count"] or 0)
    completed = min(total, indexed + failed)
    index_progress = round(completed / total * 100) if total else 0
    indexing = bool(active_jobs)
    state.update({
        "ocrJobs": ocr_jobs[:200],
        "indexingRunning": indexing,
        "processingRunning": bool(state.get("running") or indexing),
        "currentIndexFile": current_file,
        "indexProgressPercent": index_progress,
        "indexCompleted": completed,
        "indexTotal": total,
        "indexFailed": failed,
        "indexPending": pending,
    })
    state["readiness"] = readiness(bulletin_settings, state)
    return state


def _catalog_frequency_label() -> str:
    maintenance = section("maintenance")
    configured_days = str(maintenance.get("weekly_catalog_update_day", "Monday,Wednesday,Friday"))
    time_value = str(maintenance.get("weekly_catalog_update_time", "02:00"))
    days = {
        "Monday": "lundi", "Tuesday": "mardi", "Wednesday": "mercredi",
        "Thursday": "jeudi", "Friday": "vendredi", "Saturday": "samedi", "Sunday": "dimanche",
    }
    labels = [days.get(value.strip(), value.strip()) for value in configured_days.split(",") if value.strip()]
    if len(labels) > 1:
        day_label = ", ".join(labels[:-1]) + " et " + labels[-1]
    else:
        day_label = labels[0] if labels else configured_days
    return f"Mise à jour automatique les {day_label} à {time_value}."


@app.get("/api/services")
def service_status(request: Request) -> dict[str, Any]:
    require_member(request)
    bulletin_state = _bulletin_processing_status(request)
    bulletin_ready = bulletin_state["readiness"]
    catalog_state = _catalog_status_for_api()
    download_total = int(bulletin_state.get("totalSteps") or 0)
    download_done = int(bulletin_state.get("completedSteps") or 0)
    download_progress = round(download_done / download_total * 100) if download_total else (100 if not bulletin_state.get("running") else 0)
    bulletin_processing = bool(bulletin_state.get("processingRunning"))
    pieces_processing = bool(catalog_state.running)
    available_catalogs = sum(
        1 for supplier in catalog_state.suppliers if supplier.ok and supplier.item_count > 0
    )
    return {
        "bulletins": {
            "ready": bool(bulletin_ready.get("ready")),
            "available": not bulletin_processing,
            "indexedBulletins": int(bulletin_ready.get("indexedBulletins") or 0),
            "indexedPages": int(bulletin_ready.get("indexedPages") or 0),
            "localPdfCount": int(bulletin_ready.get("localPdfCount") or 0),
            "running": bulletin_processing,
            "downloadRunning": bool(bulletin_state.get("running")),
            "indexingRunning": bool(bulletin_state.get("indexingRunning")),
            "downloadProgressPercent": download_progress,
            "indexProgressPercent": int(bulletin_state.get("indexProgressPercent") or 0),
            "indexCompleted": int(bulletin_state.get("indexCompleted") or 0),
            "indexTotal": int(bulletin_state.get("indexTotal") or 0),
            "current": bulletin_state.get("currentIndexFile") or bulletin_state.get("current"),
            "phase": bulletin_state.get("phase"),
            "message": bulletin_state.get("message") or bulletin_ready.get("message"),
            "automaticFrequency": "Vérification automatique à chaque connexion membre ; téléchargement incrémental puis indexation en arrière-plan.",
        },
        "pieces": {
            "ready": available_catalogs > 0,
            "available": not pieces_processing,
            "running": pieces_processing,
            "queued": bool(catalog_state.queued),
            "availableCatalogs": available_catalogs,
            "globalProgressPercent": int(catalog_state.global_progress_percent),
            "currentSupplier": catalog_state.current_supplier,
            "lastCompletedAt": catalog_state.last_completed_at,
            "message": catalog_state.detail,
            "automaticFrequency": _catalog_frequency_label(),
            "suppliers": [supplier.model_dump(mode="json") for supplier in catalog_state.suppliers],
        },
        "annonces": annonces_snapshot(include_items=False),
        "jobs": jobs_summary(),
    }


# Couples de serrage --------------------------------------------------------

@lru_cache(maxsize=1)
def _couples_data() -> dict[str, Any]:
    try:
        payload = json.loads(COUPLES_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Référentiel des couples de serrage indisponible : {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise RuntimeError("Référentiel des couples de serrage invalide.")
    return payload


@app.get("/api/couples")
def couples_data(request: Request) -> dict[str, Any]:
    require_member(request)
    try:
        return _couples_data()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# Bulletins -----------------------------------------------------------------

@app.get("/api/bulletins/preflight")
def bulletins_preflight(request: Request) -> dict[str, Any]:
    require_member(request)
    return request.app.state.preflight


@app.get("/api/bulletins/sync/status")
def bulletin_sync_status(request: Request) -> dict[str, Any]:
    require_member(request)
    return _bulletin_processing_status(request)


@app.get("/api/bulletins/readiness")
def bulletin_readiness(request: Request) -> dict[str, Any]:
    require_member(request)
    state = augment_sync_state(bulletin_settings, request.app.state.sync_manager.state())
    return readiness(bulletin_settings, state)


@app.get("/api/bulletins/list")
def bulletin_list(request: Request) -> dict[str, Any]:
    require_member(request)
    with bulletin_connect(bulletin_settings.db_path) as conn:
        rows = conn.execute(
            """SELECT id,title,filename,number,year,month,pages,status,indexed_at,downloaded_at,local_path
               FROM bulletins WHERE local_path IS NOT NULL AND local_path<>''
               ORDER BY CASE WHEN number IS NULL THEN 1 ELSE 0 END, number, year, filename"""
        ).fetchall()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = dict(row)
        path = Path(str(row["local_path"] or ""))
        if not path.exists() or is_index_bulletins_filename(path.name):
            continue
        seen.add(path.name)
        if row["indexed_at"] and int(row["pages"] or 0) > 0:
            item["status"] = "indexed"
        elif item["status"] not in {"download-error", "index-error", "missing-remote"}:
            item["status"] = "downloaded"
        item["pdfUrl"] = f"/api/bulletins/pdf/{row['id']}"
        item.pop("local_path", None)
        items.append(item)
    if bulletin_settings.pdf_dir.exists():
        for path in sorted(bulletin_settings.pdf_dir.glob("*.pdf"), key=lambda candidate: candidate.name.lower()):
            if path.name in seen or is_index_bulletins_filename(path.name):
                continue
            _, number, year, month = parse_bulletin_metadata(path.name, path.stem)
            items.append({
                "id": None, "title": path.stem, "filename": path.name, "number": number, "year": year,
                "month": month, "pages": 0, "status": "downloaded", "indexed_at": None,
                "downloaded_at": None, "pdfUrl": f"/api/bulletins/pdf-file/{quote(path.name)}",
            })
    items.sort(key=lambda item: (item.get("number") is None, item.get("number") or 999999, item.get("year") or 999999, item.get("filename") or ""))
    return {"bulletins": items}


@app.post("/api/bulletins/search")
def bulletin_search(payload: BulletinSearchPayload, request: Request) -> dict[str, Any]:
    require_member(request)
    processing = _bulletin_processing_status(request)
    current = processing["readiness"]
    if processing.get("processingRunning") or processing.get("running") or processing.get("indexingRunning"):
        raise HTTPException(status_code=409, detail="La récupération ou l’indexation des bulletins est en cours. La recherche sera réactivée automatiquement à la fin du traitement.")
    if not current.get("ready"):
        raise HTTPException(status_code=503, detail=current.get("message") or "Aucun index exploitable.")
    with bulletin_connect(bulletin_settings.db_path) as conn:
        try:
            return search_pages(
                conn, keywords=payload.keywords, mode=payload.mode, year_from=payload.yearFrom,
                year_to=payload.yearTo, bulletin_from=payload.bulletinFrom, bulletin_to=payload.bulletinTo,
                limit=payload.limit, offset=payload.offset,
            )
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=400, detail=f"Syntaxe de recherche invalide : {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/bulletins/pdf/{bulletin_id}")
def bulletin_pdf(bulletin_id: int, request: Request) -> FileResponse:
    require_member(request)
    with bulletin_connect(bulletin_settings.db_path) as conn:
        row = conn.execute("SELECT local_path,filename FROM bulletins WHERE id=?", (bulletin_id,)).fetchone()
    if not row or not row["local_path"]:
        raise HTTPException(status_code=404, detail="PDF introuvable.")
    path = Path(row["local_path"])
    if not path.is_file() or is_index_bulletins_filename(path.name):
        raise HTTPException(status_code=404, detail="PDF absent du cache local.")
    return FileResponse(path, media_type="application/pdf", filename=row["filename"], content_disposition_type="inline")


@app.get("/api/bulletins/pdf-file/{filename:path}")
def bulletin_pdf_file(filename: str, request: Request) -> FileResponse:
    require_member(request)
    clean = unquote(filename).strip()
    if not clean or "/" in clean or "\\" in clean or is_index_bulletins_filename(clean):
        raise HTTPException(status_code=404, detail="PDF introuvable.")
    try:
        resolved = (bulletin_settings.pdf_dir / clean).resolve(strict=True)
        root = bulletin_settings.pdf_dir.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PDF introuvable.") from exc
    if resolved.parent != root or resolved.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF introuvable.")
    return FileResponse(resolved, media_type="application/pdf", filename=clean, content_disposition_type="inline")


@app.get("/api/bulletins/stats")
def bulletin_stats(request: Request) -> dict[str, Any]:
    require_member(request)
    with bulletin_connect(bulletin_settings.db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS bulletins, COALESCE(SUM(pages),0) AS pages FROM bulletins WHERE indexed_at IS NOT NULL AND pages>0").fetchone()
        sources = conn.execute("SELECT text_source AS source, COUNT(*) AS pages FROM pages GROUP BY text_source ORDER BY pages DESC").fetchall()
        bounds = conn.execute("SELECT MIN(year),MAX(year),MIN(number),MAX(number) FROM bulletins").fetchone()
    return {
        "summary": {"bulletins": int(row["bulletins"]), "pages": int(row["pages"]), "firstYear": bounds[0], "lastYear": bounds[1], "firstNumber": bounds[2], "lastNumber": bounds[3]},
        "sources": dict_rows(sources),
    }


# Pieces --------------------------------------------------------------------

@app.get("/api/pieces/connectivity", response_model=ConnectivityStatus)
async def pieces_connectivity(request: Request, force: bool = Query(False)) -> ConnectivityStatus:
    require_member(request)
    return await check_internet(force=force)


@app.get("/api/pieces/sites", response_model=list[SiteStatus])
async def pieces_sites(request: Request, force: bool = Query(False)) -> list[SiteStatus]:
    require_member(request)
    internet = await check_internet(force=False)
    if not internet.online and internet.conclusive:
        raise HTTPException(status_code=503, detail="Connexion Internet indisponible.")
    statuses = await check_all_sites(force=force)
    return [
        item.model_copy(update={"default_enabled": item.id in pieces_settings.default_enabled_sites})
        for item in statuses
    ]


@app.get("/api/pieces/catalog-sync", response_model=CatalogSyncStatus)
def pieces_catalog_status(request: Request) -> CatalogSyncStatus:
    require_member(request)
    return _catalog_status_for_api()


@app.post("/api/pieces/search", response_model=SearchResponse)
async def pieces_search(payload: SearchRequest, request: Request) -> SearchResponse:
    require_member(request)
    if _catalog_status_for_api().running:
        raise HTTPException(status_code=409, detail="La récupération des catalogues est en cours. La recherche sera réactivée automatiquement à la fin du traitement.")
    unknown = sorted(set(payload.sites) - set(SITES))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Sites inconnus : {', '.join(unknown)}")
    try:
        return await run_search(payload, connectivity=await check_internet(force=False))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Jobs ----------------------------------------------------------------------

@app.get("/api/jobs")
def jobs(request: Request, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    if member_session(request) is None and admin_session(request) is None:
        raise HTTPException(status_code=401, detail="Session requise.")
    return {"jobs": list_jobs(limit), "summary": jobs_summary()}


@app.post("/api/jobs/{job_id}/cancel")
def jobs_cancel(job_id: str, request: Request) -> dict[str, Any]:
    require_csrf(request)
    return {"ok": cancel_job(job_id)}


# Administration ------------------------------------------------------------

@app.post("/api/admin/login")
def admin_login(payload: AdminLoginPayload, request: Request) -> JSONResponse:
    if _remote_http_forbidden(request):
        record_login_attempt(request, "admin", "https-required")
        raise HTTPException(status_code=403, detail="La connexion administrateur en HTTP est autorisée uniquement depuis le réseau local. Utilisez HTTPS pour un accès depuis Internet.")
    admin_config = section("admin")
    limit = int(admin_config.get("login_rate_limit_attempts", 5))
    window = int(admin_config.get("login_rate_limit_window_seconds", 300))
    try:
        enforce_rate_limit(request, "admin-login", limit, window)
    except HTTPException:
        record_login_attempt(request, "admin", "rate-limited")
        raise
    expected_username = str(admin_config.get("username", "admin"))
    if payload.username != expected_username or not verify_admin_password(payload.password):
        record_login_attempt(request, "admin", "failed")
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe administrateur incorrect.")
    record_login_attempt(request, "admin", "success")
    response = JSONResponse({"ok": True, "user": payload.username})
    session = create_admin_session(payload.username, response, request)
    response.body = json.dumps(
        {
            "ok": True,
            "user": payload.username,
            "csrfToken": session.csrf_token,
            "expiresAt": session.expires_at,
            "durationMinutes": session_duration_minutes(),
            "serverTime": time_now(),
        },
        ensure_ascii=False,
    ).encode()
    response.headers["content-length"] = str(len(response.body))
    return response


@app.post("/api/admin/logout")
def admin_logout(request: Request) -> JSONResponse:
    require_csrf(request, admin=True)
    response = JSONResponse({"ok": True})
    revoke_admin(request, response)
    return response


@app.get("/api/admin/session")
def admin_session_status(request: Request) -> dict[str, Any]:
    current = admin_session(request)
    return {
        "authenticated": current is not None,
        "user": current.subject if current else None,
        "csrfToken": current.csrf_token if current else None,
        "expiresAt": current.expires_at if current else None,
        "durationMinutes": session_duration_minutes(),
        "serverTime": time_now(),
    }


@app.post("/api/admin/session/closing")
def admin_session_closing(payload: SessionClosingPayload, request: Request) -> dict[str, bool]:
    return {"ok": mark_admin_closing(request, payload.csrfToken)}


@app.post("/api/admin/session/keepalive")
def admin_session_keepalive(request: Request) -> dict[str, Any]:
    current = require_csrf(request, admin=True)
    keep_admin_alive(request)
    return {"ok": True, "expiresAt": current.expires_at, "serverTime": time_now()}


@app.get("/api/admin/config")
def admin_config(request: Request) -> dict[str, str]:
    require_admin(request)
    content = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else "{}\n"
    return {"content": content, "path": str(CONFIG_PATH)}


@app.put("/api/admin/config")
def admin_config_save(payload: AdminConfigPayload, request: Request) -> dict[str, Any]:
    require_csrf(request, admin=True)
    try:
        parsed = json.loads(payload.content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalide : {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="La configuration doit être un objet JSON.")
    formatted = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
    try:
        if os.access(CONFIG_PATH.parent, os.W_OK) and (not CONFIG_PATH.exists() or os.access(CONFIG_PATH, os.W_OK)):
            tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
            tmp.write_text(formatted, encoding="utf-8")
            tmp.replace(CONFIG_PATH)
            return {"ok": True, "message": "Configuration enregistrée. Utilisez « Appliquer et redémarrer » pour activer les nouveaux réglages."}
    except OSError:
        pass
    try:
        result = request_config_write(formatted)
    except ControlChannelError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or "Écriture refusée.")
    return result


@app.get("/api/admin/ntfy")
def admin_ntfy(request: Request) -> dict[str, Any]:
    require_admin(request)
    return public_settings(read_secrets(SECRETS_PATH).get("ntfy", {}))


@app.put("/api/admin/ntfy")
async def admin_ntfy_save(request: Request) -> dict[str, Any]:
    require_csrf(request, admin=True)
    # Parse this sensitive body explicitly: validation responses must never
    # echo token/password input, including malformed requests.
    raw = await request.body()
    if len(raw) > 16384:
        raise HTTPException(status_code=413, detail="Les réglages ntfy dépassent 16 Kio.")
    try:
        patch = json.loads(raw)
        updated_settings(read_secrets(SECRETS_PATH).get("ntfy", {}), patch)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Réglages ntfy invalides : vérifiez les champs et un intervalle d'au moins un jour.") from exc
    try:
        if os.access(SECRETS_PATH.parent, os.W_OK) and os.access(SECRETS_PATH, os.W_OK):
            return save_settings(SECRETS_PATH, patch)
        result = request_ntfy_write(patch)
    except ControlChannelError as exc:
        raise HTTPException(status_code=503, detail="Canal de contrôle ntfy indisponible.") from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Impossible d'enregistrer les réglages ntfy.") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="Enregistrement ntfy refusé ; vérifiez les réglages et les permissions.")
    return result


@app.get("/api/admin/status")
def admin_status(request: Request) -> dict[str, Any]:
    require_admin(request)
    disk = os.statvfs(data_root())
    return {
        "version": VERSION,
        "services": service_status_for_admin(request),
        "jobs": jobs_summary(),
        "storage": {"dataRoot": str(data_root()), "freeBytes": disk.f_bavail * disk.f_frsize, "totalBytes": disk.f_blocks * disk.f_frsize},
        "preflight": request.app.state.preflight,
    }


def service_status_for_admin(request: Request) -> dict[str, Any]:
    state = augment_sync_state(bulletin_settings, request.app.state.sync_manager.state())
    catalog = read_sync_status_snapshot()
    return {"web": {"ok": True}, "bulletins": state, "pieces": catalog.model_dump(mode="json")}


@app.get("/api/admin/metrics")
def admin_metrics(request: Request) -> dict[str, Any]:
    require_admin(request)
    return _system_metrics()


@app.get("/api/admin/statistics")
def admin_statistics(request: Request) -> dict[str, Any]:
    require_admin(request)
    with bulletin_connect(bulletin_settings.db_path) as conn:
        bulletins = int(conn.execute("SELECT COUNT(*) FROM bulletins").fetchone()[0])
        indexed = int(conn.execute("SELECT COUNT(*) FROM bulletins WHERE indexed_at IS NOT NULL AND pages>0").fetchone()[0])
        pages = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        failed = int(conn.execute("SELECT COUNT(*) FROM bulletins WHERE status IN ('download-error','index-error','missing-remote')").fetchone()[0])
    catalog = read_sync_status_snapshot()
    return {
        "bulletins": {"total": bulletins, "indexed": indexed, "pages": pages, "failed": failed, "coveragePercent": round(indexed / bulletins * 100, 1) if bulletins else 0},
        "pieces": {"suppliers": len(catalog.suppliers), "available": sum(1 for item in catalog.suppliers if item.item_count > 0), "items": sum(item.item_count for item in catalog.suppliers)},
        "jobs": jobs_summary(),
        "connections": login_statistics(limit=100),
    }


@app.get("/api/admin/logs")
def admin_logs(request: Request, lines: int = Query(300, ge=10, le=3000)) -> dict[str, Any]:
    require_admin(request)
    log_dir = data_root() / "logs"
    entries: list[dict[str, str]] = []
    for path in sorted(log_dir.glob("*.log")):
        try:
            content = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            continue
        entries.append({"source": path.name, "content": content or "Fichier vide."})
    if not entries:
        entries.append({"source": "application.log", "content": "Aucun log applicatif n'est encore disponible."})
    return {"logs": entries}


@app.post("/api/admin/control")
def admin_control(payload: AdminControlPayload, request: Request) -> dict[str, Any]:
    require_csrf(request, admin=True)
    action = payload.action.strip().lower()
    if action == "status":
        return {"ok": True, "message": "Portail en fonctionnement.", "status": service_status_for_admin(request)}
    if action in {"cleanup", "cleanup-locks"}:
        cleaned = cleanup_stale_sync_state(bulletin_settings)
        return {"ok": True, "message": f"Nettoyage terminé ({cleaned} état(s) clôturé(s))."}
    if action in {"restart", "stop", "apply-config"}:
        try:
            return request_system_action(action)
        except ControlChannelError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "terminalCommand": f"sudo /opt/portail-entraide-opel-gt/run_server.sh {action}",
            }
    raise HTTPException(status_code=400, detail="Action administrateur inconnue.")
