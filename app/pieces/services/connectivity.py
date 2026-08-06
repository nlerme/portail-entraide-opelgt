from __future__ import annotations

import asyncio
import shutil
import socket
import threading
import time
from datetime import datetime, timezone

import httpx

from app.pieces.config import settings
from app.pieces.models import ConnectivityStatus
from app.pieces.services.cache import cache

_CACHE_KEY = "internet"
_TCP_TARGETS = (
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
    ("9.9.9.9", 53),
    ("www.python.org", 443),
)
_DNS_TARGETS = ("www.cloudflare.com", "www.python.org", "www.debian.org")
_HTTP_TARGETS = (
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://www.python.org/",
    "https://www.debian.org/",
)
_PING_TARGETS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")
_FAILURES_BEFORE_OFFLINE = 3
_ONLINE_GRACE_SECONDS = 120
_failure_streak = 0
_last_online_monotonic: float | None = None
_last_online_status: ConnectivityStatus | None = None
_state_lock = threading.Lock()


async def _tcp_probe(host: str, port: int) -> bool:
    writer = None
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=settings.connectivity_timeout_seconds,
        )
        return True
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def _tcp_probes() -> bool:
    results = await asyncio.gather(
        *(_tcp_probe(host, port) for host, port in _TCP_TARGETS),
        return_exceptions=True,
    )
    return any(result is True for result in results)


async def _dns_probe(host: str) -> bool:
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM),
            timeout=settings.connectivity_timeout_seconds,
        )
        return bool(result)
    except (OSError, asyncio.TimeoutError, socket.gaierror):
        return False


async def _dns_probes() -> bool:
    results = await asyncio.gather(*(_dns_probe(host) for host in _DNS_TARGETS), return_exceptions=True)
    return any(result is True for result in results)


async def _http_probe(client: httpx.AsyncClient, url: str) -> bool:
    try:
        response = await client.get(
            url,
            headers={"User-Agent": settings.user_agent, "Range": "bytes=0-2048"},
            follow_redirects=True,
        )
        return 200 <= response.status_code < 500
    except httpx.HTTPError:
        return False


async def _http_probes() -> bool:
    timeout = httpx.Timeout(settings.connectivity_timeout_seconds)
    limits = httpx.Limits(max_connections=len(_HTTP_TARGETS), max_keepalive_connections=0)
    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            results = await asyncio.gather(
                *(_http_probe(client, url) for url in _HTTP_TARGETS),
                return_exceptions=True,
            )
            return any(result is True for result in results)
    except httpx.HTTPError:
        return False


async def _ping_probe(host: str) -> bool:
    executable = shutil.which("ping")
    if not executable:
        return False
    timeout = max(1, int(round(settings.connectivity_timeout_seconds)))
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            "-n",
            "-c",
            "1",
            "-W",
            str(timeout),
            host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(process.wait(), timeout=settings.connectivity_timeout_seconds + 1) == 0
    except (OSError, asyncio.TimeoutError):
        return False


async def _ping_probes() -> bool:
    results = await asyncio.gather(*(_ping_probe(host) for host in _PING_TARGETS), return_exceptions=True)
    return any(result is True for result in results)


async def _run_probes() -> list[str]:
    names = ("TCP", "DNS", "HTTPS", "ICMP")
    probes = (_tcp_probes(), _dns_probes(), _http_probes(), _ping_probes())
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*probes, return_exceptions=True),
            timeout=max(2.0, settings.connectivity_timeout_seconds * 2 + 2),
        )
    except asyncio.TimeoutError:
        return []
    return [name for name, result in zip(names, results, strict=True) if result is True]


async def check_internet(force: bool = False) -> ConnectivityStatus:
    global _failure_streak, _last_online_monotonic, _last_online_status

    if not force:
        cached = cache.get("connectivity", _CACHE_KEY)
        if cached:
            return ConnectivityStatus.model_validate(cached)

    started = time.perf_counter()
    successful_methods = await _run_probes()
    checked_at = datetime.now(timezone.utc).isoformat()

    with _state_lock:
        if successful_methods:
            _failure_streak = 0
            _last_online_monotonic = time.monotonic()
            status = ConnectivityStatus(
                online=True,
                conclusive=True,
                detail="Connexion Internet disponible (" + ", ".join(successful_methods) + ")",
                checked_at=checked_at,
                response_ms=int((time.perf_counter() - started) * 1000),
            )
            _last_online_status = status
            ttl = settings.connectivity_cache_seconds
        else:
            _failure_streak += 1
            recently_online = (
                _last_online_monotonic is not None
                and time.monotonic() - _last_online_monotonic <= _ONLINE_GRACE_SECONDS
            )
            if recently_online and _failure_streak < _FAILURES_BEFORE_OFFLINE and _last_online_status is not None:
                status = ConnectivityStatus(
                    online=True,
                    conclusive=False,
                    detail=(
                        "Connexion récemment confirmée ; contrôle momentanément inconclusif "
                        f"({_failure_streak}/{_FAILURES_BEFORE_OFFLINE})."
                    ),
                    checked_at=checked_at,
                    response_ms=int((time.perf_counter() - started) * 1000),
                )
            else:
                conclusive = _failure_streak >= _FAILURES_BEFORE_OFFLINE
                status = ConnectivityStatus(
                    online=False,
                    conclusive=conclusive,
                    detail=(
                        "Connexion Internet indisponible après plusieurs méthodes de contrôle"
                        if conclusive
                        else f"Contrôle Internet inconclusif ({_failure_streak}/{_FAILURES_BEFORE_OFFLINE}) ; nouvelle vérification imminente"
                    ),
                    checked_at=checked_at,
                    response_ms=int((time.perf_counter() - started) * 1000),
                )
            ttl = min(5, settings.connectivity_cache_seconds)

    cache.set("connectivity", _CACHE_KEY, status.model_dump(mode="json"), ttl)
    return status
