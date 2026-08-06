from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup

SCRAPER_DIR = Path(__file__).resolve().parents[1] / "scrapers"
if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))

import atz  # noqa: E402
import edelschmiede  # noqa: E402
import gtteile  # noqa: E402
import oldtimermotorenteile  # noqa: E402
import opelgtsource  # noqa: E402
import opelixparts  # noqa: E402
import splendidparts  # noqa: E402
import twoldtimerteile  # noqa: E402


def test_splendidparts_extracts_product_title_and_euro_price_from_card():
    soup = BeautifulSoup(
        """
        <html><meta itemprop="priceCurrency" content="EUR"><body>
          <article class="product-miniature">
            <h2 class="product-title"><a href="/shop/en/gearbox-clutch/966-clutch-cable.html">Clutch Cable Opel GT</a></h2>
            <div class="product-price-and-shipping"><span class="price">25,90 €</span></div>
            <button class="add-to-cart">Add to cart</button>
          </article>
        </body></html>
        """,
        "html.parser",
    )
    card = splendidparts.product_cards(soup)[0]
    amount, currency = splendidparts.extract_price(card, splendidparts.page_currency(soup))

    assert splendidparts.extract_name_and_url(card)[0] == "Clutch Cable Opel GT"
    assert amount == Decimal("25.90")
    assert currency == "EUR"
    assert splendidparts.extract_availability(card) == "en stock"


def test_opelixparts_extracts_product_title_and_price_from_card():
    card = BeautifulSoup(
        """
        <article class="product-miniature">
          <h2 class="product-title"><a href="/accueil/6000-cable-embrayage.html">câble embrayage GT 1900.</a></h2>
          <div class="product-price-and-shipping"><span class="price">37,95 €</span></div>
          <button class="add-to-cart">Ajouter au panier</button>
        </article>
        """,
        "html.parser",
    ).article

    item = opelixparts.listing_item(card, opelixparts.ROOT)

    assert item is not None
    assert item["nom"] == "câble embrayage GT 1900."
    assert item["prix"] == "37,95€"
    assert item["disponibilite"] == "en stock"


def test_edelschmiede_extracts_product_title_and_price_from_card():
    card = BeautifulSoup(
        """
        <div class="productbox">
          <a class="productbox-title" href="/Clutch-cable-control">Clutch cable control 'clutch cable', Opel GT</a>
          <div class="productbox-price"><span class="price">32,95 € *</span></div>
          <button name="inWarenkorb">In den Warenkorb</button>
        </div>
        """,
        "html.parser",
    ).div

    item = edelschmiede.listing_item(card, edelschmiede.ROOT_URL)

    assert item is not None
    assert item["nom"] == "Clutch cable control 'clutch cable', Opel GT"
    assert item["prix"] == "32,95€"


def test_gtteile_extracts_only_listing_title_and_numeric_price():
    products = gtteile.extract_listing_products(
        """
        <div class="productlist-viewmode-grid">
          <div class="product-container">
            <div class="title-description"><div class="title">
              <a href="/fr/kupplungszug-11l.html">Câble d'embrayage 1,1L</a>
            </div></div>
            <div class="price">30,00 EUR</div>
            <div>Temps de livraison: env. 2-3 jours Ajouter au panier</div>
          </div>
        </div>
        """,
        "https://www.pro-gt.de/fr/",
        None,
    )

    assert products == [
        {
            "nom": "Câble d'embrayage 1,1L",
            "nom_traduit": "Câble d'embrayage 1,1L",
            "prix": "30,00€",
            "disponibilite": "en stock",
            "url_photo": "inconnu",
            "url_fiche": "https://www.pro-gt.de/fr/kupplungszug-11l.html",
        }
    ]


def test_atz_extracts_product_title_and_numeric_price_from_woocommerce_card():
    products = atz.parse_catalogue_page(
        1,
        """
        <li class="product instock">
          <a href="/p/opel-gt-kupplungszug-fuer-4-gang/">
            <h2 class="woocommerce-loop-product__title">Opel GT – Kupplungszug für 4-Gang</h2>
          </a>
          <span class="price"><span class="woocommerce-Price-amount">29,90 €</span></span>
          <a href="?add-to-cart=1">In den Warenkorb</a>
        </li>
        """,
    )

    assert products[0]["nom"] == "Opel GT – Kupplungszug für 4-Gang"
    assert products[0]["prix"] == "29,90€"
    assert products[0]["disponibilite"] == "en stock"


def test_opelgtsource_extracts_product_title_and_usd_price_from_its_card():
    result = opelgtsource.parse_page(
        1,
        """
        <div class="product-card">
          <a href="/search/8001/details"><img src="/img/8001.jpg"></a>
          <div>$49.00</div>
          <div>Clutch Cable, Opel GT 1.9L - 2.4L</div>
          <div>Part: 8001</div>
          <div>Add to Cart</div>
        </div>
        """,
    )

    assert result.products[0]["nom"] == "Clutch Cable, Opel GT 1.9L - 2.4L"
    assert result.products[0]["_prix_usd"] == "49.00"
    assert result.products[0]["disponibilite"] == "en stock"


def test_oldtimer_motorenteile_extracts_product_title_and_numeric_price():
    products = oldtimermotorenteile.parser_catalogue(
        """
        <div class="productlist">
          <div class="product-container">
            <div class="title"><a href="product_info.php?products_id=77">Kupplungszug Opel GT 1900</a></div>
            <div class="price">39,90 EUR</div>
            <div class="shipping-info-short">sofort lieferbar</div>
          </div>
        </div>
        """,
        "https://www.oldtimer-motorenteile.com/?cat=c898",
        5.0,
    )

    assert products[0]["nom"] == "Kupplungszug Opel GT 1900"
    assert products[0]["prix"] == "39,90€"
    assert products[0]["disponibilite"] == "en stock"


def test_atz_supplemental_getrag_category_keeps_generic_clutch_cable():
    category_url = atz.SUPPLEMENTAL_CATEGORY_URLS[0]
    products = atz.parse_listing_page(
        category_url,
        """
        <li class="product outofstock">
          <a href="/p/kupplungszug/">
            <h2 class="woocommerce-loop-product__title">Kupplungszug für Getrag-Getriebe</h2>
          </a>
          <span class="price"><span class="woocommerce-Price-amount">39,90 €</span></span>
          <a href="/p/kupplungszug/">Weiterlesen</a>
        </li>
        """,
        "catégorie Opel GT Getrag 5-Gang Typ 240",
    )

    assert atz.is_supplemental_category_url(category_url)
    assert products == [
        {
            "nom": "Kupplungszug für Getrag-Getriebe",
            "nom_traduit": "",
            "prix": "39,90€",
            "disponibilite": "en rupture de stock",
            "url_photo": "inconnu",
            "url_fiche": "https://atz-online.com/p/kupplungszug/",
        }
    ]


def test_opelix_gt_listing_keeps_release_bearing_product():
    card = BeautifulSoup(
        """
        <article class="product-miniature">
          <h2 class="product-title"><a href="/accueil/1157-butee-d-embrayage-.html">Butée embrayage CIH 1.5-3.0.</a></h2>
          <div class="product-price-and-shipping"><span class="price">24,90 €</span></div>
          <span class="availability">En stock</span>
          <button class="add-to-cart">Ajouter au panier</button>
        </article>
        """,
        "html.parser",
    ).article

    item = opelixparts.listing_item(card, opelixparts.ROOT)

    assert item is not None
    assert item["nom"] == "Butée embrayage CIH 1.5-3.0."
    assert item["prix"] == "24,90€"
    assert item["url_fiche"] == "https://www.opelixparts.com/accueil/1157-butee-d-embrayage-.html"


def test_tw_oldtimerteile_counts_direct_categories_and_excludes_request_category():
    category_slugs = [
        "Bremsanlage",
        "Motor-Kupplung",
        "Getriebe",
        "Sprit-Abgasanlage",
        "Vorderachse-Lenkung",
        "Hinterachse",
        "Karosserie",
        "Elektrik",
        "Kuehlung",
        "Innenausstattung",
        "Ich-brauchs-ich-wills",
    ]
    links = "".join(
        f'<a href="/Opel-Typen/Opel-GT/{slug}/">{slug.replace("-", " ")}</a>'
        for slug in category_slugs
    )
    links += '<a href="/Opel-Typen/Opel-GT/Bremsanlage/Bremssattel.html">fiche produit</a>'

    categories = twoldtimerteile.discover_categories(f"<nav>{links}</nav>")
    selected = [category for category in categories if not twoldtimerteile.is_excluded_category(category)]

    assert len(categories) == twoldtimerteile.EXPECTED_CATEGORY_COUNT == 11
    assert len(selected) == 10
    assert all(not category.url.endswith(".html") for category in categories)
    assert twoldtimerteile.is_product_url(
        "https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/Hinterachse/Produit-sans-extension/"
    )
    assert any("ich-brauchs-ich-wills" in category.url.casefold() for category in categories)
    assert all("ich-brauchs-ich-wills" not in category.url.casefold() for category in selected)


def test_tw_oldtimerteile_extracts_products_from_listing_cards_only():
    page_url = "https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/Hinterachse/"
    products = twoldtimerteile.parse_listing_page(
        """
        <main><div class="productlist"><div class="product-container">
          <div class="product-image"><a href="Gummipuffer-Hinterachsbruecke.html"><img data-src="/images/gummipuffer.jpg" alt="Gummipuffer Hinterachsbrücke"></a></div>
          <div class="title"><a href="Gummipuffer-Hinterachsbruecke.html">Gummipuffer in Hinterachsbrücke Opel GT</a></div>
          <div class="price">35,90 € *</div>
          <div class="shipping-info-short">Sofort lieferbar</div>
        </div></div></main>
        """,
        page_url,
    )

    assert products == [
        {
            "nom": "Gummipuffer in Hinterachsbrücke Opel GT",
            "nom_traduit": "Gummipuffer in Hinterachsbrücke Opel GT",
            "prix": "35,90€",
            "disponibilite": "en stock",
            "url_photo": "https://shop.tw-oldtimerteile.de/images/gummipuffer.jpg",
            "url_fiche": (
                "https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/Hinterachse/"
                "Gummipuffer-Hinterachsbruecke.html"
            ),
        }
    ]


def test_tw_oldtimerteile_crawls_only_category_and_pagination_pages():
    category = twoldtimerteile.Category(
        name="Hinterachse",
        url="https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/Hinterachse/",
    )
    first_url = twoldtimerteile.normalized_url(category.url)
    second_url = twoldtimerteile.normalized_url(category.url + "?page=2")
    requested: list[str] = []
    pages = {
        first_url: """
          <div class="productlist"><div class="product-container">
            <div class="title"><a href="Teil-1.html">Teil 1</a></div><div class="price">10,00 €</div>
          </div></div>
          <nav class="pagination"><a href="?page=2">2</a></nav>
        """,
        second_url: """
          <div class="productlist"><div class="product-container">
            <div class="title"><a href="Teil-2.html">Teil 2</a></div><div class="price">20,00 €</div>
          </div></div>
        """,
    }

    def fake_fetcher(url: str, timeout: float, category_url: str | None):
        del timeout
        assert category_url == category.url
        normalized = twoldtimerteile.normalized_url(url)
        requested.append(normalized)
        assert not normalized.casefold().endswith(".html")
        return pages[normalized], normalized

    products = twoldtimerteile.crawl_category(category, 2.0, fake_fetcher)

    assert requested == [first_url, second_url]
    assert [product["nom"] for product in products] == ["Teil 1", "Teil 2"]
    assert all(product["url_fiche"].endswith(".html") for product in products)


def test_tw_oldtimerteile_full_catalogue_uses_public_category_filter(monkeypatch, tmp_path):
    root = twoldtimerteile.ROOT_URL
    category_urls = [f"{root}Categorie-{index}/" for index in range(1, 11)]
    excluded_url = f"{root}Ich-brauchs-ich-wills/"
    root_html = "".join(f'<a href="{url}">Catégorie {index}</a>' for index, url in enumerate(category_urls, 1))
    root_html += f'<a href="{excluded_url}">Ich brauch’s, ich will’s!</a>'
    crawled: list[str] = []

    def fake_fetch(url: str, timeout: float, category_url: str | None = None):
        del timeout
        assert category_url is None
        return root_html, twoldtimerteile.normalized_url(url)

    def fake_crawl(category, timeout):
        del timeout
        crawled.append(category.url)
        slug = category.url.rstrip('/').rsplit('/', 1)[-1]
        return [{
            "nom": f"{slug} Teil",
            "nom_traduit": f"{slug} Teil",
            "prix": "10,00€",
            "disponibilite": "en stock",
            "url_photo": "inconnu",
            "url_fiche": category.url + f"{slug}-Teil.html",
        }]

    monkeypatch.setattr(twoldtimerteile, 'fetch_listing', fake_fetch)
    monkeypatch.setattr(twoldtimerteile, 'crawl_category', fake_crawl)
    monkeypatch.setattr(twoldtimerteile, '_translate_catalogue', lambda products, workers, timeout: None)
    output = tmp_path / 'tw.json'
    catalogue = twoldtimerteile.scrape_catalogue(output, workers=1, timeout=2.0)

    assert len(catalogue) == 10
    assert twoldtimerteile.normalized_url(excluded_url) not in crawled
    assert all(not url.casefold().endswith('.html') for url in crawled)

def test_splendidparts_catalogue_requests_are_throttled_and_session_based():
    source = Path(splendidparts.__file__).read_text(encoding='utf-8')
    assert 'MAX_LISTING_WORKERS = 1' in source
    assert 'REQUEST_DELAY_SECONDS = 0.65' in source
    assert 'session=session' in source
    assert 'ProcessPoolExecutor' not in source
    assert 'Referer' in splendidparts.HEADERS or 'Referer' in source
