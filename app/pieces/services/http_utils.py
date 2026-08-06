from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.pieces.config import settings


class CircuitOpenError(RuntimeError):
    pass


class RobotsDeniedError(RuntimeError):
    pass


@dataclass
class _Circuit:
    failures: int = 0
    opened_until: float = 0.0


_CIRCUITS: dict[str, _Circuit] = {}
_RATE_LOCKS: dict[str, asyncio.Lock] = {}
_LAST_REQUEST_AT: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, tuple[float, RobotFileParser | None]] = {}
_ROBOTS_LOCKS: dict[str, asyncio.Lock] = {}


def _circuit(site_id: str, scope: str = "default") -> _Circuit:
    """Return the circuit for one supplier operation class.

    Availability probes, search pages, catalogue pages and product details do
    not have the same failure semantics. A slow status endpoint must therefore
    never disable a real user search, and a failing search endpoint must not
    disable direct product-page fallbacks.
    """
    return _CIRCUITS.setdefault(f"{site_id}:{scope}", _Circuit())


async def _throttle(site_id: str) -> None:
    from app.pieces.scrapers.sites import SITES

    site = SITES.get(site_id)
    requests_per_minute = site.requests_per_minute if site else settings.default_requests_per_minute
    requests_per_minute = max(1, requests_per_minute)
    minimum_interval = 60.0 / requests_per_minute
    lock = _RATE_LOCKS.setdefault(site_id, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        wait = minimum_interval - (now - _LAST_REQUEST_AT.get(site_id, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_REQUEST_AT[site_id] = time.monotonic()


async def _robots_parser(
    client: httpx.AsyncClient,
    url: str,
    site_id: str,
) -> RobotFileParser | None:
    now = time.time()
    cached = _ROBOTS_CACHE.get(site_id)
    if cached and cached[0] > now:
        return cached[1]

    lock = _ROBOTS_LOCKS.setdefault(site_id, asyncio.Lock())
    async with lock:
        cached = _ROBOTS_CACHE.get(site_id)
        if cached and cached[0] > time.time():
            return cached[1]
        parsed = urlparse(url)
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
        parser: RobotFileParser | None = None
        try:
            await _throttle(site_id)
            response = await client.get(robots_url, follow_redirects=True)
            if response.status_code == 200 and response.text.strip():
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
        except Exception:
            parser = None
        _ROBOTS_CACHE[site_id] = (time.time() + settings.robots_cache_seconds, parser)
        return parser


async def _ensure_allowed(client: httpx.AsyncClient, url: str, site_id: str) -> None:
    from app.pieces.scrapers.sites import SITES

    site = SITES.get(site_id)
    if not settings.respect_robots_txt or (site and not site.respect_robots_txt):
        return
    parser = await _robots_parser(client, url, site_id)
    if parser is not None and not parser.can_fetch(settings.user_agent, url):
        raise RobotsDeniedError(f"robots.txt interdit l'accès automatisé à {url}")


async def resilient_get(
    client: httpx.AsyncClient,
    url: str,
    site_id: str,
    *,
    follow_redirects: bool = True,
    circuit_scope: str = "default",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    circuit = _circuit(site_id, circuit_scope)
    now = time.time()
    if circuit.opened_until > now:
        raise CircuitOpenError(
            f"Protection temporaire active pour {site_id} pendant {int(circuit.opened_until - now)} s"
        )

    await _ensure_allowed(client, url, site_id)
    last_error: Exception | None = None
    for attempt in range(settings.http_retries + 1):
        try:
            await _throttle(site_id)
            response = await client.get(url, follow_redirects=follow_redirects, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < settings.http_retries:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = min(8.0, max(1.0, float(retry_after)))
                    except ValueError:
                        delay = min(8.0, 1.5 * (2**attempt))
                    await asyncio.sleep(delay)
                    continue
            circuit.failures = 0
            circuit.opened_until = 0.0
            return response
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt < settings.http_retries:
                await asyncio.sleep(min(4.0, 0.75 * (2**attempt)))
                continue
            break

    circuit.failures += 1
    if circuit.failures >= settings.circuit_breaker_failures:
        circuit.opened_until = time.time() + settings.circuit_breaker_seconds
        circuit.failures = 0
    if last_error:
        raise last_error
    raise RuntimeError(f"Échec HTTP pour {url}")
