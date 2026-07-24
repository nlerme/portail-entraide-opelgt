from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.pieces.config import settings
from app.pieces.models import SiteState, SiteStatus
from app.pieces.scrapers.sites import SITES, SiteConfig
from app.pieces.services.cache import cache
from app.pieces.services.http_utils import CircuitOpenError, RobotsDeniedError, resilient_get

MAINTENANCE_MARKERS = (
    "site maintenance",
    "maintenance mode",
    "under maintenance",
    "wartungsarbeiten",
    "wegen wartungsarbeiten",
    "onderhoud",
    "en maintenance",
    "site en maintenance",
    "boutique en maintenance",
    "maintenance en cours",
)
VACATION_MARKERS = (
    "shop closed for holiday",
    "closed for vacation",
    "annual leave",
    "betriebsferien",
    "urlaub geschlossen",
    "vakantie gesloten",
    "ferme pour conges",
    "fermé pour congés",
    "ferme pour vacances",
    "fermé pour vacances",
    "boutique fermee",
    "boutique fermée",
)
DOWN_MARKERS = (
    "service unavailable",
    "temporarily unavailable",
    "currently unavailable",
    "bad gateway",
    "gateway timeout",
    "access denied",
    "zugriff verweigert",
    "nicht verfügbar",
    "vorübergehend nicht verfügbar",
    "site indisponible",
    "service indisponible",
)
PRICE_OR_SHOP_MARKER_RE = re.compile(
    r"(?:€|\bEUR\b|\$|\bUSD\b|add\s+to\s+cart|in\s+stock|product|products|artikel|warenkorb|panier)",
    re.IGNORECASE,
)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup((html or "")[:400_000], "html.parser")


def _focused_text(html: str) -> str:
    soup = _soup(html)
    parts: list[str] = []
    if soup.title:
        parts.append(soup.title.get_text(" ", strip=True))
    for selector in ("h1", "h2", ".maintenance", ".alert", ".notice", ".announcement", ".banner"):
        for node in soup.select(selector)[:12]:
            parts.append(node.get_text(" ", strip=True))
    parts.append(soup.get_text(" ", strip=True)[:3000])
    return _normalized_text(" ".join(parts))


def _visible_text_and_metrics(site: SiteConfig, html: str) -> tuple[str, int, int]:
    soup = _soup(html)
    for node in soup.select("script, style, noscript, svg"):
        node.decompose()
    text = _normalized_text(soup.get_text(" ", strip=True))
    product_count = 0
    for selector in site.product_selectors:
        try:
            product_count += len(soup.select(selector))
        except Exception:
            continue
    links = {link.get("href") for link in soup.select("a[href]") if link.get("href")}
    return text, product_count, len(links)


def _content_issue(site: SiteConfig, html: str) -> str | None:
    text, product_count, link_count = _visible_text_and_metrics(site, html)
    if product_count > 0:
        return None
    if len(text) < 80:
        return "Contenu anormalement court : la page fournisseur semble vide ou remplacée."
    if len(text) < 240 and link_count <= 2:
        return "Contenu insuffisant : la page fournisseur ne ressemble pas à une boutique exploitable."
    if (
        site.product_selectors
        and len(text) < 700
        and link_count < 6
        and not PRICE_OR_SHOP_MARKER_RE.search(text)
    ):
        return "Catalogue non détecté : aucun contenu boutique exploitable n'a été trouvé."
    return None


def _unavailable_status(site: SiteConfig, detail: str, *, response_ms: int | None = None) -> SiteStatus:
    return SiteStatus(
        id=site.id,
        name=site.name,
        url=site.home_url,
        state=SiteState.offline,
        online=False,
        selectable=False,
        badge="hors ligne",
        detail=detail,
        checked_at=datetime.now(timezone.utc).isoformat(),
        response_ms=response_ms,
    )


async def _bounded_status_get(
    client: httpx.AsyncClient,
    url: str,
    site_id: str,
) -> httpx.Response:
    """Bound one availability probe independently from DNS/client edge cases."""
    return await asyncio.wait_for(
        resilient_get(client, url, site_id, circuit_scope="status"),
        timeout=settings.status_probe_timeout_seconds,
    )


async def check_site(client: httpx.AsyncClient, site: SiteConfig, force: bool = False) -> SiteStatus:
    if not site.enabled or site.id in settings.disabled_sites:
        return _unavailable_status(site, "Fournisseur désactivé par la configuration locale")
    if not force:
        cached = cache.get("site_status", site.id)
        if cached:
            return SiteStatus.model_validate(cached)

    started = time.perf_counter()
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        response: httpx.Response | None = None
        last_network_error: Exception | None = None
        for status_url in site.status_urls or (site.home_url,):
            try:
                candidate = await _bounded_status_get(client, status_url, site.id)
                response = candidate
                if candidate.status_code < 500:
                    break
            except (asyncio.TimeoutError, httpx.RequestError) as exc:
                last_network_error = exc
                continue
        if response is None:
            if last_network_error is not None:
                raise last_network_error
            raise httpx.NetworkError("Aucune URL de contrôle n'a répondu")

        elapsed = int((time.perf_counter() - started) * 1000)
        text = _focused_text(response.text) if response.text else ""
        if response.status_code >= 500:
            status = _unavailable_status(site, f"Erreur HTTP {response.status_code}", response_ms=elapsed)
            status.checked_at = checked_at
        elif any(marker in text for marker in MAINTENANCE_MARKERS):
            status = SiteStatus(
                id=site.id,
                name=site.name,
                url=site.home_url,
                state=SiteState.maintenance,
                online=False,
                selectable=False,
                badge="hors ligne",
                detail="Maintenance annoncée par le site",
                checked_at=checked_at,
                response_ms=elapsed,
            )
        elif any(marker in text for marker in VACATION_MARKERS):
            status = SiteStatus(
                id=site.id,
                name=site.name,
                url=site.home_url,
                state=SiteState.vacation,
                online=False,
                selectable=False,
                badge="hors ligne",
                detail="Fermeture temporaire / congés annoncés",
                checked_at=checked_at,
                response_ms=elapsed,
            )
        elif any(marker in text for marker in DOWN_MARKERS):
            status = _unavailable_status(
                site, "Message d'indisponibilité détecté sur le site", response_ms=elapsed
            )
            status.checked_at = checked_at
        elif response.status_code in {401, 403, 408, 425, 429}:
            status = _unavailable_status(
                site,
                f"Site inaccessible au contrôle automatique (HTTP {response.status_code})",
                response_ms=elapsed,
            )
            status.checked_at = checked_at
        elif 400 <= response.status_code < 500:
            status = _unavailable_status(site, f"Réponse HTTP {response.status_code}", response_ms=elapsed)
            status.checked_at = checked_at
        elif 200 <= response.status_code < 400:
            issue = _content_issue(site, response.text or "")
            if issue:
                status = _unavailable_status(site, issue, response_ms=elapsed)
                status.checked_at = checked_at
            else:
                status = SiteStatus(
                    id=site.id,
                    name=site.name,
                    url=site.home_url,
                    state=SiteState.online,
                    online=True,
                    selectable=True,
                    badge="en ligne",
                    detail="Site joignable et contenu boutique cohérent",
                    checked_at=checked_at,
                    response_ms=elapsed,
                )
        else:
            status = _unavailable_status(site, f"Réponse HTTP {response.status_code}", response_ms=elapsed)
            status.checked_at = checked_at
    except (RobotsDeniedError, CircuitOpenError) as exc:
        detail = (
            "Contrôle impossible : accès automatisé refusé"
            if isinstance(exc, RobotsDeniedError)
            else "Contrôle impossible : circuit de protection temporairement ouvert"
        )
        status = _unavailable_status(site, detail)
        status.checked_at = checked_at
    except (asyncio.TimeoutError, httpx.RequestError) as exc:
        label = "délai dépassé" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
        status = _unavailable_status(site, f"Site injoignable ({label})")
        status.checked_at = checked_at
    except Exception as exc:
        status = _unavailable_status(site, f"Contrôle impossible ({type(exc).__name__})")
        status.checked_at = checked_at

    ttl = settings.status_cache_seconds if status.selectable else min(settings.status_cache_seconds, 30)
    cache.set("site_status", site.id, status.model_dump(mode="json"), ttl)
    return status


async def _check_site_with_deadline(
    client: httpx.AsyncClient,
    site: SiteConfig,
    force: bool,
) -> SiteStatus:
    try:
        return await asyncio.wait_for(
            check_site(client, site, force=force),
            timeout=settings.status_site_timeout_seconds,
        )
    except asyncio.TimeoutError:
        status = _unavailable_status(
            site,
            "Contrôle interrompu : délai maximal dépassé",
            response_ms=int(settings.status_site_timeout_seconds * 1000),
        )
        cache.set("site_status", site.id, status.model_dump(mode="json"), 30)
        return status


async def check_all_sites(force: bool = False) -> list[SiteStatus]:
    """Return every supplier status within a strict global deadline.

    A slow DNS resolver, TLS handshake or supplier can no longer keep `/api/sites`
    pending forever. Pending checks are cancelled and represented as unavailable.
    """
    limits = httpx.Limits(max_connections=len(SITES) + 2, max_keepalive_connections=len(SITES))
    timeout = httpx.Timeout(
        settings.status_probe_timeout_seconds,
        connect=settings.status_probe_timeout_seconds,
        read=settings.status_probe_timeout_seconds,
        write=settings.status_probe_timeout_seconds,
        pool=settings.status_probe_timeout_seconds,
    )
    headers = {"User-Agent": settings.user_agent, "Accept-Language": "fr,en;q=0.8,de;q=0.7,nl;q=0.6"}
    async with httpx.AsyncClient(timeout=timeout, limits=limits, headers=headers) as client:
        ordered_sites = list(SITES.values())
        tasks = {
            asyncio.create_task(_check_site_with_deadline(client, site, force)): site
            for site in ordered_sites
        }
        done, pending = await asyncio.wait(tasks, timeout=settings.status_all_timeout_seconds)

        results_by_id: dict[str, SiteStatus] = {}
        for task in done:
            site = tasks[task]
            try:
                results_by_id[site.id] = task.result()
            except Exception as exc:  # defensive: one supplier must not break the endpoint
                results_by_id[site.id] = _unavailable_status(
                    site,
                    f"Contrôle impossible ({type(exc).__name__})",
                )

        for task in pending:
            site = tasks[task]
            task.cancel()
            results_by_id[site.id] = _unavailable_status(
                site,
                "Contrôle interrompu : délai global dépassé",
                response_ms=int(settings.status_all_timeout_seconds * 1000),
            )
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        return [results_by_id[site.id] for site in ordered_sites]
