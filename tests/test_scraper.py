from pathlib import Path

import pytest

from app.pieces.models import Offer
from app.pieces.scrapers.adapters import scraper_for
from app.pieces.scrapers.base import GenericScraper, availability_from_text
from app.pieces.scrapers.sites import SITES
from app.pieces.services.compatibility import assess_compatibility


class DummyClient:
    pass


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "site_id,filename,price,availability",
    [
        ("splendid_parts", "splendid_parts.html", 25.90, "in_stock"),
        ("opelix_parts", "opelix_parts.html", 37.95, "out_of_stock"),
        ("oldtimer_motorenteile", "oldtimer_motorenteile.html", 39.90, "out_of_stock"),
        ("opel_gt_source", "opel_gt_source.html", 60.00, "out_of_stock"),
        ("pro_gt", "pro_gt.html", 44.00, "restocking"),
        ("atz_online", "atz_online.html", 35.70, "out_of_stock"),
        ("edelschmiede", "edelschmiede.html", 44.90, "in_stock"),
    ],
)
def test_supplier_detail_snapshots(site_id, filename, price, availability):
    site = SITES[site_id]
    scraper = scraper_for(site, DummyClient())
    html = (FIXTURES / filename).read_text(encoding="utf-8")
    offer = scraper._offer_from_detail_page(html, site.home_url)
    assert offer is not None
    assert offer.price == price
    assert offer.availability == availability
    assert offer.price_source.startswith("fiche:")
    assert offer.availability_source.startswith("fiche:")


def test_stock_precedence_and_labels():
    assert availability_from_text("Out-of-Stock") == ("out_of_stock", "Pas de stock")
    assert availability_from_text("Rupture de stock") == ("out_of_stock", "Pas de stock")
    assert availability_from_text("Rupture de stock, délai de réapprovisionnement 2 semaines") == (
        "restocking",
        "Réapprovisionnement",
    )
    assert availability_from_text("Sur commande") == ("restocking", "Réapprovisionnement")


def test_query_confidence_is_discriminating():
    scraper = GenericScraper(SITES["splendid_parts"], DummyClient())
    exact = Offer(
        id="1",
        site_id="x",
        site_name="x",
        title="Clutch Cable Opel GT",
        url="https://x.test/1",
        raw_description="",
    )
    mixed = exact.model_copy(
        update={"id": "2", "title": "Clutch control", "raw_description": "cable for the clutch"}
    )
    description = exact.model_copy(
        update={"id": "3", "title": "Transmission part", "raw_description": "clutch cable replacement"}
    )
    assert scraper._query_match_score(exact, "câble embrayage") >= 0.92
    assert scraper._query_match_score(mixed, "câble embrayage") is None
    assert scraper._query_match_score(description, "câble embrayage") is None


def test_model_filter_excludes_explicitly_incompatible_part():
    offer_1100 = Offer(
        id="1",
        site_id="x",
        site_name="x",
        title="Clutch Cable Opel GT 1100",
        url="https://x.test",
        models=["1100"],
    )
    generic = offer_1100.model_copy(update={"id": "2", "title": "Clutch Cable Opel GT", "models": []})
    assert assess_compatibility(offer_1100, "1900") == "incompatible"
    assert assess_compatibility(generic, "1900") == "uncertain"


def test_prestashop_json_payload_does_not_become_raw_text_title():
    payload = """{"rendered_products":"<article class=\\"product-miniature\\"><h2><a href=\\"/p/1\\">Câble embrayage GT 1900</a></h2><span class=\\"price\\">37,95 €</span></article>","products":[{"name":"Câble embrayage GT 1900","url":"https://www.opelixparts.com/p/1","price":{"amount":37.95},"quantity":0,"available_for_order":false}]}"""
    scraper = scraper_for(SITES["opelix_parts"], DummyClient())
    offers, _ = scraper.parse_page(payload, "https://www.opelixparts.com/recherche")
    assert len(offers) == 1
    assert offers[0].title == "Câble embrayage GT 1900"
    assert offers[0].availability == "out_of_stock"


def test_opel_gt_source_rejects_select_option_and_reads_explicit_listing_price():
    html = """
    <html><body><main>
      <section><h4>SELECT YOUR OPTION</h4>
        <ul><li><a href="/search?car_id=4">OPEL GT</a></li></ul>
      </section>
      <ul class="results">
        <li class="product-row">
          <span class="amount">$60.00</span>
          <div>Clutch Cable, Opel GT 1.9L</div>
          <div>Part: 8001</div>
          <a href="/search/2857/details">Details</a>
          <button>Add to Cart</button>
        </li>
      </ul>
    </main></body></html>
    """
    scraper = scraper_for(SITES["opel_gt_source"], DummyClient())
    offers, _ = scraper.parse_page(html, "https://www.opelgtsource.com/search?search=clutch+cable")

    assert len(offers) == 1
    assert offers[0].title == "Clutch Cable, Opel GT 1.9L"
    assert offers[0].price == 60.00
    assert offers[0].currency == "USD"
    assert all(offer.title.upper() != "SELECT YOUR OPTION" for offer in offers)


def test_opel_gt_source_detail_price_ignores_engine_displacement():
    html = """
    <html><body><main>
      <h1>Clutch Cable, Opel GT 1.9L</h1>
      <div>Part: 8001</div>
      <div>Price:</div><div>$60.00</div>
      <div>Description:</div><p>New reproduction clutch cable for the Opel GT.</p>
      <button>Add to Cart</button>
    </main></body></html>
    """
    scraper = scraper_for(SITES["opel_gt_source"], DummyClient())
    offer = scraper._offer_from_detail_page(html, "https://www.opelgtsource.com/search/2857/details")

    assert offer is not None
    assert offer.title == "Clutch Cable, Opel GT 1.9L"
    assert offer.price == 60.00
    assert offer.currency == "USD"
    assert offer.price_source == "fiche:opelgtsource"


def test_wiper_blades_match_french_query_after_canonicalization():
    scraper = GenericScraper(SITES["splendid_parts"], DummyClient())
    offer = Offer(
        id="splendid-wiper-blades",
        site_id="splendid_parts",
        site_name="SplendidParts",
        title="Set Wiper Blades Opel GT Kadett B",
        url="https://splenditparts.de/shop/en/other-rubberparts/327-set-wiper-blades-opel-gt-kadett-b.html",
        price=15.90,
        currency="EUR",
        raw_description="Here you can get a set of new wiper blades suitable for the Opel GT.",
    )
    score = scraper._query_match_score(offer, "essuie glace")
    assert score is not None
    assert score >= 0.9


def test_wiper_arms_match_french_query_after_canonicalization():
    scraper = GenericScraper(SITES["splendid_parts"], DummyClient())
    offers = [
        Offer(
            id="splendid-wiper-arm-black",
            site_id="splendid_parts",
            site_name="SplendidParts",
            title="Wiper Arm Set Opel GT, black",
            url="https://splenditparts.de/shop/en/body/39-wiper-arm-set-opel-gt-black.html",
            price=99.90,
            currency="EUR",
            raw_description="Set of new black Opel GT Wiper Arms.",
        ),
        Offer(
            id="splendid-wiper-arm-chrome",
            site_id="splendid_parts",
            site_name="SplendidParts",
            title="Opel GT Wiper Arm Set, chrome",
            url="https://splenditparts.de/shop/en/body/40-opel-gt-wiper-arm-set-chrome.html",
            price=109.00,
            currency="EUR",
            raw_description="Set of new chrome Opel GT Wiper Arms.",
        ),
    ]
    scores = [scraper._query_match_score(offer, "essuie glace") for offer in offers]
    assert all(score is not None and score >= 0.9 for score in scores)


@pytest.mark.asyncio
async def test_catalog_strategy_translates_and_crawls_every_splendidparts_page(monkeypatch):
    import httpx

    from app.pieces.scrapers import base as base_module

    site = SITES["splendid_parts"]
    page2 = f"{site.home_url}?page=2"
    page3 = f"{site.home_url}?page=3"
    product_url = "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt.html"
    calls: list[str] = []
    translated_languages: list[str] = []

    async def fake_queries(keywords, language, models, client):
        translated_languages.append(language)
        assert keywords == "câble embrayage"
        assert models == ["1900"]
        return ["clutch cable"]

    async def fake_get(client, url, site_id, **kwargs):
        calls.append(url)
        request = httpx.Request("GET", url)
        if url == site.home_url:
            return httpx.Response(
                200,
                request=request,
                text="""<html><body>
                  <article class="product-miniature"><h2 class="product-title">
                    <a href="/shop/en/body/1-badge.html">Opel GT badge</a>
                  </h2></article>
                  <nav class="pagination"><a href="?page=2">2</a><a href="?page=3">3</a></nav>
                </body></html>""",
            )
        if url == page2:
            return httpx.Response(
                200,
                request=request,
                text='<html><body><article class="product-miniature"><h2 class="product-title"><a href="/shop/en/brake/2-disc.html">Brake disc Opel GT</a></h2></article></body></html>',
            )
        if url == page3:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><article class="product-miniature">
                  <h2 class="product-title"><a href="{product_url}">Clutch Cable Opel GT</a></h2>
                  <span class="price">25,90 €</span>
                </article></body></html>''',
            )
        if url == product_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><head><link rel="canonical" href="{product_url}"></head>
                <body id="product"><main><div class="product-container">
                  <h1 itemprop="name">Clutch Cable Opel GT</h1>
                  <div class="current-price"><span itemprop="price" content="25.90">€25.90</span></div>
                  <div class="product-description">Reinforced clutch cable for the Opel GT.</div>
                </div></main></body></html>''',
            )
        return httpx.Response(404, request=request, text="Not found")

    monkeypatch.setattr(base_module, "verified_query_candidates_for_language", fake_queries)
    monkeypatch.setattr(base_module, "resilient_get", fake_get)

    result = await scraper_for(site, DummyClient()).search("câble embrayage", ["1900"])

    assert translated_languages == ["en"]
    assert {site.home_url, page2, page3}.issubset(calls)
    assert [offer.title for offer in result.offers] == ["Clutch Cable Opel GT"]
    assert result.pages_read == 3


@pytest.mark.asyncio
async def test_website_engine_strategy_discovers_form_and_crawls_all_results(monkeypatch):
    import httpx

    from app.pieces.scrapers import base as base_module

    site = SITES["pro_gt"]
    product_url = "https://www.pro-gt.de/en/clutch-cable-opel-gt-p-42.html"
    calls: list[str] = []

    async def fake_queries(keywords, language, models, client):
        assert language == "en"
        return ["clutch cable"]

    async def fake_get(client, url, site_id, **kwargs):
        calls.append(url)
        request = httpx.Request("GET", url)
        if url == site.home_url:
            return httpx.Response(
                200,
                request=request,
                text="""<html><body><form action="/en/advanced_search_result.php" method="get">
                  <input type="hidden" name="search_in_description" value="1">
                  <input type="search" name="keywords">
                </form></body></html>""",
            )
        parsed = httpx.URL(url)
        if parsed.path == "/en/advanced_search_result.php" and parsed.params.get("page") is None:
            assert parsed.params.get("keywords") == "clutch cable"
            return httpx.Response(
                200,
                request=request,
                text='<html><body><nav class="pagination"><a href="?keywords=clutch+cable&page=2">2</a></nav></body></html>',
            )
        if parsed.path == "/en/advanced_search_result.php" and parsed.params.get("page") == "2":
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><article class="product">
                  <h2><a href="{product_url}">Clutch Cable Opel GT 1900</a></h2>
                  <span class="price">44,00 €</span>
                </article></body></html>''',
            )
        if url == product_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><head><link rel="canonical" href="{product_url}"></head><body><main>
                  <h1>Clutch Cable Opel GT 1900</h1><div class="price">44,00 €</div>
                  <div class="description">Clutch cable for Opel GT 1900.</div>
                </main></body></html>''',
            )
        return httpx.Response(404, request=request, text="Not found")

    monkeypatch.setattr(base_module, "verified_query_candidates_for_language", fake_queries)
    monkeypatch.setattr(base_module, "resilient_get", fake_get)

    result = await scraper_for(site, DummyClient()).search("câble embrayage", ["1900"])

    assert any("keywords=clutch+cable" in url for url in calls)
    assert any("page=2" in url for url in calls)
    assert [offer.title for offer in result.offers] == ["Clutch Cable Opel GT 1900"]
    assert result.pages_read == 3


def test_website_engine_fallback_preserves_language_path():
    scraper = scraper_for(SITES["pro_gt"], DummyClient())
    urls = scraper._website_search_urls(
        "<html><body><div>Search form rendered by JavaScript</div></body></html>",
        SITES["pro_gt"].home_url,
        ["clutch cable"],
    )

    assert urls == [
        "https://www.pro-gt.de/en/advanced_search_result.php?search_in_description=1&categories_id=0&inc_subcat=1&keywords=clutch+cable"
    ]


@pytest.mark.asyncio
async def test_oldtimer_selects_exact_model_then_crawls_its_pagination(monkeypatch):
    import httpx

    from app.pieces.scrapers import base as base_module

    site = SITES["oldtimer_motorenteile"]
    gt1100 = "https://www.oldtimer-motorenteile.com/?cat=c899_Opel-GT-1100.html"
    gt1900 = "https://www.oldtimer-motorenteile.com/?cat=c900_Opel-GT-1900.html"
    gtj = "https://www.oldtimer-motorenteile.com/?cat=c901_Opel-GT-J-1900.html"
    gtj_page2 = gtj + "&page=2"
    product_url = "https://www.oldtimer-motorenteile.com/product_info.php?products_id=77"
    calls: list[str] = []

    async def fake_queries(keywords, language, models, client):
        assert language == "en"
        return ["clutch cable"]

    async def fake_get(client, url, site_id, **kwargs):
        calls.append(url)
        request = httpx.Request("GET", url)
        if url == site.home_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body>
                  <a href="{gt1100}">Opel GT 1100</a>
                  <a href="{gt1900}">Opel GT 1900</a>
                  <a href="{gtj}">Opel GT/J 1900</a>
                </body></html>''',
            )
        if url == gtj:
            return httpx.Response(
                200,
                request=request,
                text=f'<html><body><nav class="pagination"><a href="{gtj_page2}">2</a></nav></body></html>',
            )
        if url == gtj_page2:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><div class="productlist-item">
                  <h2><a href="{product_url}">Kupplungszug Opel GT/J 1900</a></h2>
                  <span class="price">39,90 €</span>
                </div></body></html>''',
            )
        if url == product_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><head><link rel="canonical" href="{product_url}"></head><body><main>
                  <h1>Kupplungszug Opel GT/J 1900</h1><div class="price">39,90 €</div>
                  <div class="description">Kupplungszug für Opel GT/J 1900.</div>
                </main></body></html>''',
            )
        return httpx.Response(404, request=request, text="Not found")

    monkeypatch.setattr(base_module, "verified_query_candidates_for_language", fake_queries)
    monkeypatch.setattr(base_module, "resilient_get", fake_get)

    result = await scraper_for(site, DummyClient()).search("câble embrayage", ["gtj"])

    assert gtj in calls and gtj_page2 in calls
    assert gt1100 not in calls and gt1900 not in calls
    assert [offer.title for offer in result.offers] == ["Kupplungszug Opel GT/J 1900"]
    assert result.pages_read == 3


def test_product_detail_page_keeps_main_product_when_related_cards_are_present():
    scraper = scraper_for(SITES["splendid_parts"], DummyClient())
    url = "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt-splendid-parts.html"
    html = f"""
    <html><head><link rel="canonical" href="{url}"></head><body id="product"><main>
      <div class="product-container">
        <h1 itemprop="name">Clutch Cable Opel GT, Splendid Parts</h1>
        <div class="current-price"><span itemprop="price" content="25.90">€25.90</span></div>
        <div id="product-availability">1-8 Work Days</div>
        <div class="product-description">Reinforced clutch cable for the Opel GT.</div>
      </div>
      <section class="product-accessories">
        <article class="product-miniature">
          <h2 class="product-title">
            <a href="/shop/en/gearbox-clutch/999-clutch-kit-manta.html">
              Clutch Kit Manta A
            </a>
          </h2>
          <span class="price">€199.00</span>
        </article>
      </section>
    </main></body></html>
    """

    offers, _ = scraper.parse_page(html, url)

    assert any(offer.url == url and offer.title == "Clutch Cable Opel GT, Splendid Parts" for offer in offers)


def test_vehicle_filter_rejects_non_gt_models_even_when_engine_matches():
    manta = Offer(
        id="manta",
        site_id="splendid_parts",
        site_name="SplendidParts",
        title="Clutch Cable Opel Manta A 1900",
        url="https://example.test/manta",
        models=["1900"],
    )
    rekord = manta.model_copy(
        update={
            "id": "rekord",
            "title": "Kupplungszug Rekord C 1.9 CIH",
            "url": "https://example.test/rekord",
        }
    )
    cross_model_gt = manta.model_copy(
        update={
            "id": "cross",
            "title": "Clutch Cable Opel GT / Manta A 1900",
            "url": "https://example.test/cross",
        }
    )

    assert assess_compatibility(manta, "1900") == "incompatible"
    assert assess_compatibility(rekord, "1900") == "incompatible"
    assert assess_compatibility(cross_model_gt, "1900") == "compatible"


def test_vehicle_filter_preserves_generic_gt_catalogue_parts():
    generic = Offer(
        id="generic",
        site_id="splendid_parts",
        site_name="SplendidParts",
        title="Clutch Cable",
        url="https://splenditparts.de/shop/en/clutch-cable.html",
        models=[],
    )
    assert assess_compatibility(generic, "1900") == "uncertain"


def test_vehicle_filter_uses_product_url_when_title_is_ambiguous():
    rekord = Offer(
        id="rekord-url",
        site_id="other_supplier",
        site_name="Other Supplier",
        title="Clutch Cable 1.9 CIH",
        url="https://example.test/kupplungszug-opel-rekord-c",
        models=["1900"],
    )
    gt = rekord.model_copy(
        update={
            "id": "gt-url",
            "url": "https://example.test/clutch-cable-opel-gt-1900",
        }
    )

    assert assess_compatibility(rekord, "1900") == "incompatible"
    assert assess_compatibility(gt, "1900") == "compatible"


def test_numeric_and_jtl_pagination_links_are_all_detected():
    scraper = scraper_for(SITES["edelschmiede"], DummyClient())
    html = """<html><body>
      <a href="/GT_1">Page 1</a>
      <a href="/GT_1_s2">Page 2</a>
      <a href="/GT_1_s3">Page 3</a>
      <a href="/some-product_123">123</a>
    </body></html>"""
    assert scraper._pagination_urls(html, "https://www.edelschmiede.com/GT_1") == [
        "https://www.edelschmiede.com/GT_1_s2",
        "https://www.edelschmiede.com/GT_1_s3",
    ]


def test_opel_gt_source_uses_configured_car_catalog_and_paginate_endpoint():
    scraper = scraper_for(SITES["opel_gt_source"], DummyClient())
    urls = scraper._opel_gt_source_catalog_urls(["clutch cable", "clutch"])
    assert "https://www.opelgtsource.com/search?car_id=4&search=clutch+cable" in urls
    assert (
        "https://www.opelgtsource.com/search/paginate?car_id=4&search=clutch+cable&order_by=featured&page=1"
        in urls
    )
    assert len(urls) == 4


@pytest.mark.asyncio
async def test_splendidparts_enumerates_all_pages_from_catalogue_summary(monkeypatch):
    """SP must schedule page=2..25 directly, not depend on intermediate links."""
    from dataclasses import replace
    from urllib.parse import parse_qs, urlparse

    import httpx

    from app.pieces.scrapers import base as base_module

    site = SITES["splendid_parts"]
    requested_pages: set[int] = set()
    seen_headers: list[dict[str, str] | None] = []
    product_titles = [
        "Clutch Cable Opel GT, Splendid Parts",
        "Clutch Cable Advantage Set Opel GT",
        "Maxi- Locking Ring Clutch Cable Opel GT",
        "Mounting Sleeve Clutch Cable, Opel GT",
        "Professional Clutch Kabel Mounting Set Opel GT",
    ]

    def listing(cards: list[str], *, summary: str = "") -> str:
        rendered = "".join(
            f'''<article class="product-miniature js-product-miniature">
              <h2 class="product-title"><a href="{site.base_url}/shop/en/gearbox-clutch/{index}-{title.lower().replace(" ", "-")}.html">{title}</a></h2>
              <div class="product-description">Opel GT clutch cable component</div>
              <span class="price">25,90 €</span>
            </article>'''
            for index, title in enumerate(cards, 966)
        )
        return f"""<html><body><main><p>{summary}</p>{rendered}
          <nav class="pagination"><a href="?page=2">2</a><a href="?page=3">3</a><a href="?page=25">25</a></nav>
        </main></body></html>"""

    async def fake_get(client, url, site_id, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        page = int(parse_qs(urlparse(url).query).get("page", ["1"])[0])
        requested_pages.add(page)
        cards = product_titles if page == 14 else []
        summary = (
            "Showing 1-36 of 887 item(s)"
            if page == 1
            else f"Showing {(page - 1) * 36 + 1}-{min(page * 36, 887)} of 887 item(s)"
        )
        return httpx.Response(200, request=httpx.Request("GET", url), text=listing(cards, summary=summary))

    async def fake_queries(keywords, language, models, client):
        assert keywords == "câble embrayage"
        assert language == "en"
        return ["clutch cable", "clutch", "cable"]

    monkeypatch.setattr(base_module, "resilient_get", fake_get)
    monkeypatch.setattr(base_module, "verified_query_candidates_for_language", fake_queries)
    monkeypatch.setattr(
        base_module,
        "settings",
        replace(
            base_module.settings,
            max_detail_pages_per_site=0,
            search_site_timeout_seconds=30,
            max_concurrent_pages_per_site=8,
        ),
    )

    result = await scraper_for(site, DummyClient()).search("câble embrayage", ["1900"])

    assert requested_pages == set(range(1, 26))
    assert {offer.title for offer in result.offers} == set(product_titles)
    assert result.pages_read == 25
    assert all(headers and headers["Accept-Language"].startswith("en") for headers in seen_headers)


def test_listing_parser_continues_after_a_matching_but_invalid_selector():
    """A wrapper matched by the first selector must not hide real product cards."""
    site = SITES["splendid_parts"]
    scraper = scraper_for(site, DummyClient())
    product_url = (
        "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt-splendid-parts.html"
    )
    html = f"""
    <html><body>
      <div class="product-miniature"><a href="/shop/en/70-opel-gt">Opel GT catalogue</a></div>
      <article class="js-product-miniature">
        <h2 class="product-title"><a href="{product_url}">Clutch Cable Opel GT</a></h2>
        <span class="price">25,90 €</span>
      </article>
    </body></html>
    """

    offers, _ = scraper.parse_page(html, site.home_url)

    assert [offer.title for offer in offers] == ["Clutch Cable Opel GT"]
    assert offers[0].url == product_url


@pytest.mark.asyncio
async def test_catalog_search_prioritizes_query_relevant_subcategory(monkeypatch):
    """SP-only + câble embrayage must open Gearbox & Clutch from the configured root."""
    import httpx

    from app.pieces.scrapers import base as base_module

    site = SITES["splendid_parts"]
    category_url = "https://splenditparts.de/shop/en/85-gearbox-clutch"
    product_url = (
        "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt-splendid-parts.html"
    )
    calls: list[str] = []

    async def fake_queries(keywords, language, models, client):
        assert (keywords, language, models) == ("câble embrayage", "en", ["1900"])
        return ["clutch cable", "clutch", "cable"]

    async def fake_get(client, url, site_id, **kwargs):
        calls.append(url)
        request = httpx.Request("GET", url)
        if url == site.home_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><nav><a href="{category_url}">Gearbox &amp; Clutch</a></nav>
                <article class="product-miniature"><h2><a href="/shop/en/body/39-wiper-arm.html">Wiper Arm Opel GT</a></h2></article>
                </body></html>''',
            )
        if url == category_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><article class="product-miniature">
                <h2 class="product-title"><a href="{product_url}">Clutch Cable Opel GT, Splendid Parts</a></h2>
                <span class="price">25,90 €</span></article></body></html>''',
            )
        if url == product_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><head><link rel="canonical" href="{product_url}"></head>
                <body id="product"><main><div class="product-container">
                <h1 itemprop="name">Clutch Cable Opel GT, Splendid Parts</h1>
                <div class="current-price"><span itemprop="price" content="25.90">25,90 €</span></div>
                <div class="product-description">Clutch cable for Opel GT 1900.</div>
                </div></main></body></html>''',
            )
        return httpx.Response(404, request=request, text="Not found")

    monkeypatch.setattr(base_module, "verified_query_candidates_for_language", fake_queries)
    monkeypatch.setattr(base_module, "resilient_get", fake_get)

    result = await scraper_for(site, DummyClient()).search("câble embrayage", ["1900"])

    assert category_url in calls
    assert [offer.title for offer in result.offers] == ["Clutch Cable Opel GT, Splendid Parts"]


@pytest.mark.asyncio
async def test_opelix_catalog_search_opens_transmission_category(monkeypatch):
    import httpx

    from app.pieces.scrapers import base as base_module

    site = SITES["opelix_parts"]
    category_url = "https://www.opelixparts.com/263-transmission-opel"
    product_url = "https://www.opelixparts.com/accueil/6000-cable-embrayage-gt-1900.html"
    calls: list[str] = []

    async def fake_queries(keywords, language, models, client):
        assert language == "fr"
        return ["câble embrayage", "embrayage", "câble"]

    async def fake_get(client, url, site_id, **kwargs):
        calls.append(url)
        request = httpx.Request("GET", url)
        if url == site.home_url:
            return httpx.Response(
                200,
                request=request,
                text=f'<html><body><a href="{category_url}">Boîte de vitesses / Embrayage</a></body></html>',
            )
        if url == category_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><body><article class="product-miniature">
                <h2 class="product-title"><a href="{product_url}">Câble embrayage GT 1900</a></h2>
                <span class="price">37,95 €</span></article></body></html>''',
            )
        if url == product_url:
            return httpx.Response(
                200,
                request=request,
                text=f'''<html><head><link rel="canonical" href="{product_url}"></head><body><main>
                <div class="product-container"><h1 itemprop="name">Câble embrayage GT 1900</h1>
                <div class="current-price"><span itemprop="price" content="37.95">37,95 €</span></div>
                <div class="product-description">Câble d'embrayage pour Opel GT 1900.</div>
                </div></main></body></html>''',
            )
        return httpx.Response(404, request=request, text="Not found")

    monkeypatch.setattr(base_module, "verified_query_candidates_for_language", fake_queries)
    monkeypatch.setattr(base_module, "resilient_get", fake_get)

    result = await scraper_for(site, DummyClient()).search("câble embrayage", ["1900"])

    assert category_url in calls
    assert [offer.title for offer in result.offers] == ["Câble embrayage GT 1900"]


def test_opel_gt_source_catalog_sync_uses_standalone_subprocess(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.pieces.services import catalogs as catalog_module

    calls = []
    monkeypatch.setattr(catalog_module, "CATALOG_DIR", tmp_path)
    monkeypatch.setattr(
        catalog_module, "_python_executable_for_scraper_subprocess", lambda: "/usr/bin/python3"
    )

    def fake_run(cmd, *, site_id, env, progress_file, timeout):
        calls.append(
            {
                "cmd": cmd,
                "site_id": site_id,
                "env": env,
                "progress_file": progress_file,
                "timeout": timeout,
            }
        )
        output_path = Path(cmd[cmd.index("--output") + 1])
        status_path = Path(cmd[cmd.index("--status-file") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            """[
  {
    "nom": "Clutch Cable, Opel GT 1.9L",
    "nom_traduit": "Câble d'embrayage, Opel GT 1.9L",
    "prix": "55,20€",
    "disponibilite": "en stock",
    "url_photo": "inconnu",
    "url_fiche": "https://www.opelgtsource.com/search/2857/details"
  }
]
""",
            encoding="utf-8",
        )
        status_path.write_text(
            """{
  "supplier": "Opel GT Source",
  "status": "ok",
  "ok": true,
  "output_path": "unused",
  "status_path": "unused",
  "item_count": 1,
  "duration_seconds": 12.5,
  "message": "scraping terminé"
}
""",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(catalog_module, "_run_catalog_process", fake_run)

    result = catalog_module._run_supplier_scraper("opel_gt_source", "opelgtsource")

    assert result["ok"] is True
    assert result["item_count"] == 1
    assert len(calls) == 1
    command = calls[0]["cmd"]
    assert command[0] == "/usr/bin/python3"
    assert command[1].endswith("scrapers/opelgtsource.py")
    assert "--quiet" in command and "--strict" in command
    assert calls[0]["site_id"] == "opel_gt_source"
    assert calls[0]["env"]["CATALOG_PROGRESS_FILE"] == str(calls[0]["progress_file"])
    assert calls[0]["env"]["OGS_CACHE_DIR"] == str(tmp_path / "_cache" / "opelgtsource")
    assert calls[0]["env"]["OGS_CACHE_MODE"] == "refresh"
    assert calls[0]["env"]["CATALOG_PREVIOUS_OUTPUT"] == str(tmp_path / "opelgtsource.json")
    assert calls[0]["env"]["OGS_PAGE_WORKERS"] == str(catalog_module.settings.max_concurrent_pages_per_site)
    assert calls[0]["env"]["OGS_REQUEST_GAP"] == "0"


def test_catalog_sync_runs_all_supplier_jobs_in_parallel(monkeypatch, tmp_path):
    import threading

    from app.pieces.models import CatalogSyncStatus
    from app.pieces.services import catalogs as catalog_module

    jobs = {
        "opelix_parts": "opelixparts",
        "splendid_parts": "splendidparts",
        "opel_gt_source": "opelgtsource",
    }
    barrier = threading.Barrier(len(jobs))
    calls: list[str] = []
    calls_lock = threading.Lock()

    def fake_scraper(site_id, module_name):
        with calls_lock:
            calls.append(site_id)
        barrier.wait(timeout=2)
        return {
            "ok": True,
            "status": "ok",
            "item_count": 1,
            "message": "Synchronisation terminée.",
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(catalog_module, "MODULE_BY_SITE_ID", jobs)
    monkeypatch.setattr(catalog_module, "CATALOG_DIR", tmp_path)
    monkeypatch.setattr(catalog_module, "SYNC_STATUS_PATH", tmp_path / "sync_status.json")
    monkeypatch.setattr(
        catalog_module, "_python_executable_for_scraper_subprocess", lambda: "/usr/bin/python3"
    )
    monkeypatch.setattr(catalog_module, "_run_supplier_scraper", fake_scraper)
    monkeypatch.setattr(catalog_module, "_catalog_is_usable", lambda site_id: site_id in jobs)
    monkeypatch.setattr(catalog_module, "_catalog_item_count", lambda path: 1)
    monkeypatch.setattr(
        catalog_module,
        "_STATUS",
        CatalogSyncStatus(running=True, suppliers=catalog_module._supplier_defaults()),
    )

    catalog_module._sync_worker()

    status = catalog_module.get_sync_status()
    assert set(calls) == set(jobs)
    assert status.running is False
    assert status.ready is True
    assert all(supplier.status == "ok" and supplier.progress_percent == 100 for supplier in status.suppliers)


def test_live_scraper_matching_never_uses_description_or_category_url():
    scraper = GenericScraper(SITES["splendid_parts"], DummyClient())
    irrelevant = Offer(
        id="irrelevant-distributor",
        site_id="splendid_parts",
        site_name="SplendidParts",
        title="Delco Distributor Opel GT",
        url="https://splenditparts.de/shop/en/gearbox-clutch/distributor.html",
        raw_description="Gearbox and clutch category. Cable accessories and related products.",
    )
    relevant = irrelevant.model_copy(
        update={
            "id": "relevant-cable",
            "title": "Clutch Cable Opel GT",
            "url": "https://splenditparts.de/shop/en/gearbox-clutch/clutch-cable.html",
        }
    )

    assert scraper._query_match_score(irrelevant, "câble embrayage", ["clutch cable"]) is None
    assert scraper._query_match_score(relevant, "câble embrayage", ["clutch cable"]) is not None
