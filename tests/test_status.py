import httpx
import pytest

from app.pieces.models import SiteState
from app.pieces.scrapers.sites import SITES
from app.pieces.services import status as status_service
from app.pieces.services.http_utils import RobotsDeniedError


@pytest.mark.asyncio
async def test_splendidparts_status_uses_configured_root(monkeypatch):
    site = SITES["splendid_parts"]
    calls: list[str] = []

    async def fake_get(client, url, site_id, **kwargs):
        assert kwargs.get("circuit_scope") == "status"
        calls.append(url)
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text="""<html><title>Opel GT</title><body>
                <article class="product-miniature"><h2>Wiper Arm</h2><span class="price">25,90 €</span></article>
                <a href="/shop/en/body">Body</a><a href="/shop/en/engine">Engine</a>
                </body></html>""",
        )

    monkeypatch.setattr(status_service, "resilient_get", fake_get)
    async with httpx.AsyncClient() as client:
        result = await status_service.check_site(client, site, force=True)

    assert calls == [site.home_url]
    assert result.state == SiteState.online
    assert result.online is True
    assert result.selectable is True
    assert result.badge == "en ligne"


@pytest.mark.asyncio
async def test_splendidparts_robots_limit_is_reported_offline(monkeypatch):
    site = SITES["splendid_parts"]

    async def fake_get(client, url, site_id, **kwargs):
        assert kwargs.get("circuit_scope") == "status"
        raise RobotsDeniedError("blocked for automated access")

    monkeypatch.setattr(status_service, "resilient_get", fake_get)
    async with httpx.AsyncClient() as client:
        result = await status_service.check_site(client, site, force=True)

    assert result.state == SiteState.offline
    assert result.online is False
    assert result.selectable is False
    assert result.badge == "hors ligne"
    assert "accès automatisé refusé" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("dns failure"),
        httpx.ReadTimeout("read timeout"),
        httpx.RemoteProtocolError("remote protocol error"),
    ],
)
async def test_splendidparts_inconclusive_probe_is_reported_offline_on_every_platform(monkeypatch, error):
    site = SITES["splendid_parts"]
    calls: list[str] = []

    async def fake_get(client, url, site_id, **kwargs):
        assert kwargs.get("circuit_scope") == "status"
        calls.append(url)
        raise error

    monkeypatch.setattr(status_service, "resilient_get", fake_get)
    async with httpx.AsyncClient() as client:
        result = await status_service.check_site(client, site, force=True)

    assert calls == list(site.status_urls)
    assert result.state == SiteState.offline
    assert result.online is False
    assert result.selectable is False
    assert result.badge == "hors ligne"
    assert "Site injoignable" in result.detail


@pytest.mark.asyncio
async def test_splendidparts_real_server_error_is_still_reported_offline(monkeypatch):
    site = SITES["splendid_parts"]

    async def fake_get(client, url, site_id, **kwargs):
        assert kwargs.get("circuit_scope") == "status"
        return httpx.Response(
            503,
            request=httpx.Request("GET", url),
            text="<html><title>Service unavailable</title></html>",
        )

    monkeypatch.setattr(status_service, "resilient_get", fake_get)
    async with httpx.AsyncClient() as client:
        result = await status_service.check_site(client, site, force=True)

    assert result.state == SiteState.offline
    assert result.online is False
    assert result.selectable is False
    assert result.badge == "hors ligne"


@pytest.mark.asyncio
async def test_all_site_checks_have_a_strict_global_deadline(monkeypatch):
    import asyncio
    from dataclasses import replace

    async def never_finishes(client, site, force=False):
        await asyncio.sleep(10)

    fast_settings = replace(
        status_service.settings,
        status_site_timeout_seconds=0.02,
        status_all_timeout_seconds=0.05,
    )
    monkeypatch.setattr(status_service, "settings", fast_settings)
    monkeypatch.setattr(status_service, "check_site", never_finishes)

    started = asyncio.get_running_loop().time()
    results = await status_service.check_all_sites(force=True)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.5
    assert len(results) == len(SITES)
    by_id = {result.id: result for result in results}
    assert by_id["splendid_parts"].selectable is False
    assert by_id["splendid_parts"].badge == "hors ligne"
    assert all(result.selectable is False for result in results)
    assert all("délai" in result.detail for result in results)


@pytest.mark.asyncio
async def test_single_line_supplier_page_is_reported_offline(monkeypatch):
    site = SITES["splendid_parts"]

    async def fake_get(client, url, site_id, **kwargs):
        assert kwargs.get("circuit_scope") == "status"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text="<html><title>Opel GT</title><body>Opel GT</body></html>",
        )

    monkeypatch.setattr(status_service, "resilient_get", fake_get)
    async with httpx.AsyncClient() as client:
        result = await status_service.check_site(client, site, force=True)

    assert result.state == SiteState.offline
    assert result.online is False
    assert result.selectable is False
    assert result.badge == "hors ligne"
    assert "Contenu anormalement court" in result.detail
