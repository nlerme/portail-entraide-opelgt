from __future__ import annotations

import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from app.bulletins.config import Settings


def run_preflight_checks(settings: Settings) -> dict[str, object]:
    """Run non-blocking network checks at application startup.

    The application can still start when these checks fail: cached/local PDFs may
    remain searchable, but login/synchronization will require network access.
    """

    checks: list[dict[str, object]] = []
    started = time.monotonic()

    bulletins_url = settings.bulletins_url
    login_url = settings.login_url
    hosts = []
    for url in (bulletins_url, login_url):
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname not in hosts:
            hosts.append(parsed.hostname)

    for host in hosts:
        checks.append(_check_dns(host))

    checks.append(_check_http("bulletins_url", bulletins_url, settings.http_timeout_seconds))
    if login_url != bulletins_url:
        checks.append(_check_http("login_url", login_url, settings.http_timeout_seconds))

    ok = all(bool(item.get("ok")) for item in checks)
    return {
        "ok": ok,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "durationMs": round((time.monotonic() - started) * 1000),
        "checks": checks,
    }


def _check_dns(host: str) -> dict[str, object]:
    start = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        addresses = sorted({item[4][0] for item in infos})
        return {
            "name": f"dns:{host}",
            "ok": True,
            "message": f"DNS OK pour {host}",
            "addresses": addresses[:5],
            "durationMs": round((time.monotonic() - start) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": f"dns:{host}",
            "ok": False,
            "message": f"DNS impossible pour {host}: {exc}",
            "durationMs": round((time.monotonic() - start) * 1000),
        }


def _check_http(name: str, url: str, timeout_seconds: int) -> dict[str, object]:
    start = time.monotonic()
    timeout = min(max(timeout_seconds, 3), 12)
    try:
        # GET is more reliable than HEAD on CMS pages. We stream and close
        # immediately to avoid downloading a full page unnecessarily.
        response = requests.get(url, timeout=timeout, allow_redirects=True, stream=True)
        try:
            status = response.status_code
            ok = status < 500
            return {
                "name": f"http:{name}",
                "ok": ok,
                "status": status,
                "finalUrl": response.url,
                "message": f"HTTP {status} pour {url}",
                "durationMs": round((time.monotonic() - start) * 1000),
            }
        finally:
            response.close()
    except Exception as exc:  # noqa: BLE001
        return {
            "name": f"http:{name}",
            "ok": False,
            "message": f"Accès HTTP impossible pour {url}: {exc}",
            "durationMs": round((time.monotonic() - start) * 1000),
        }
