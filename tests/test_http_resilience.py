from dataclasses import replace

import httpx
import pytest

from app.pieces.scrapers.adapters import scraper_for
from app.pieces.scrapers.sites import SITES
from app.pieces.services import http_utils
from app.pieces.services.cache import cache


class ScopeAwareClient:
    def __init__(self, title: str, description: str, product_url: str) -> None:
        self.title = title
        self.description = description
        self.product_url = product_url
        self.calls: list[str] = []
        self.failures_left = 2

    async def get(self, url: str, **kwargs) -> httpx.Response:
        self.calls.append(url)
        request = httpx.Request("GET", url)
        if self.failures_left:
            self.failures_left -= 1
            raise httpx.ConnectError("temporary supplier probe failure", request=request)

        if url == SITES["splendid_parts"].home_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><article class="product-miniature">
                  <h2 class="product-title"><a href="{self.product_url}">{self.title}</a></h2>
                  <span class="price">25,90 €</span>
                </article></body></html>''',
            )
        if url == self.product_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><head><link rel="canonical" href="{self.product_url}"></head>
                <body id="product"><main><div class="product-container">
                  <h1 itemprop="name">{self.title}</h1>
                  <div class="current-price"><span itemprop="price" content="25.90">€25.90</span></div>
                  <div class="product-description">{self.description}</div>
                </div></main></body></html>''',
            )
        return httpx.Response(404, request=request, text="Not found")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keywords,title,description,product_url",
    [
        (
            "câble embrayage",
            "Clutch Cable Opel GT",
            "Reinforced clutch cable for the Opel GT.",
            "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt.html",
        ),
        (
            "essuie glace",
            "Wiper Arm Set Opel GT",
            "Set of new black Opel GT wiper arms.",
            "https://splenditparts.de/shop/en/body/39-wiper-arm-set-opel-gt-black.html",
        ),
    ],
)
async def test_status_circuit_cannot_block_file_driven_catalog_search(
    monkeypatch, keywords, title, description, product_url
):
    async def no_robots_check(client, url, site_id):
        return None

    async def no_throttle(site_id):
        return None

    monkeypatch.setattr(http_utils, "_ensure_allowed", no_robots_check)
    monkeypatch.setattr(http_utils, "_throttle", no_throttle)
    monkeypatch.setattr(
        http_utils,
        "settings",
        replace(
            http_utils.settings,
            http_retries=0,
            circuit_breaker_failures=2,
            circuit_breaker_seconds=120,
        ),
    )
    http_utils._CIRCUITS.clear()
    cache.delete_namespace("product_detail")

    client = ScopeAwareClient(title, description, product_url)
    site = SITES["splendid_parts"]

    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            await http_utils.resilient_get(
                client,
                site.home_url,
                site.id,
                circuit_scope="status",
            )

    with pytest.raises(http_utils.CircuitOpenError):
        await http_utils.resilient_get(
            client,
            site.home_url,
            site.id,
            circuit_scope="status",
        )

    result = await scraper_for(site, client).search(keywords, ["1900"])

    assert [offer.title for offer in result.offers] == [title]
    assert client.calls.count(site.home_url) == 3
    assert product_url in client.calls
