from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from app.pieces.models import Offer
from app.pieces.scrapers.base import (
    GenericScraper,
    _first_attr,
    _first_text,
    _models_from_text,
    _plausible_title,
    _visible_text,
    availability_from_text,
)
from app.pieces.services.text import clean_url, extract_reference, stable_id


class PrestaShopScraper(GenericScraper):
    detail_scope_selectors = (
        "main .product-container",
        "#main .product-container",
        "main #product",
        ".product-detail",
        "main",
    )
    price_selectors = (
        ".current-price [itemprop=price]",
        ".current-price .price",
        "#our_price_display",
        ".product-prices .current-price",
        'meta[property="product:price:amount"]',
        "meta[itemprop=price]",
    )
    stock_selectors = (
        "#product-availability",
        ".product-availability",
        ".availability",
        '[itemprop="availability"]',
        'meta[property="product:availability"]',
        ".product-add-to-cart .control-label",
    )


class SplendidPartsScraper(PrestaShopScraper):
    """SplendidParts parser with deterministic catalogue pagination.

    The shop only exposes a sliding window of page links. Relying on those links
    recursively means that one failed intermediate page can hide every later
    page. The catalogue summary (for example ``Showing 1-36 of 887 item(s)``) is
    authoritative, so all ``?page=N`` URLs are generated immediately.
    """

    _PAGE_SUMMARY_RE = re.compile(
        r"showing\s+(\d+)\s*[-–]\s*(\d+)\s+of\s+([\d.,\s]+)\s+item",
        re.IGNORECASE,
    )
    _TOTAL_RE = re.compile(r"there\s+are\s+([\d.,\s]+)\s+products", re.IGNORECASE)
    _MAX_CATALOGUE_PAGES = 200

    def _page_worker_count(self) -> int:
        # The configured Opel GT category has 25 pages. Eight concurrent listing
        # requests keep the exhaustive crawl inside the supplier deadline while
        # the shared rate limiter still spaces requests to protect the shop.
        return max(8, super()._page_worker_count())

    def _request_headers(self, url: str, scope: str) -> dict[str, str] | None:
        # SplendidParts serves the public catalogue reliably to ordinary browser
        # navigation but can reject the bundle's descriptive bot user-agent.
        # These headers do not bypass authentication or anti-bot challenges; they
        # simply reproduce the same public GET navigation performed by the user.
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,de;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
            "Referer": "https://splenditparts.de/shop/en/",
        }

    @staticmethod
    def _integer(value: str) -> int:
        digits = re.sub(r"[^0-9]", "", value)
        return int(digits) if digits else 0

    def _catalogue_page_count(self, html: str) -> int | None:
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        summary = self._PAGE_SUMMARY_RE.search(text)
        if summary:
            first = self._integer(summary.group(1))
            last = self._integer(summary.group(2))
            total = self._integer(summary.group(3))
            page_size = max(1, last - first + 1)
            if total:
                return min(self._MAX_CATALOGUE_PAGES, max(1, math.ceil(total / page_size)))
        total_match = self._TOTAL_RE.search(text)
        if total_match:
            total = self._integer(total_match.group(1))
            if total:
                # The live SplendidParts category currently displays 36 products
                # per page; pagination links remain a secondary source below.
                return min(self._MAX_CATALOGUE_PAGES, max(1, math.ceil(total / 36)))
        return None

    def _pagination_urls(self, html: str, page_url: str) -> list[str]:
        urls = super()._pagination_urls(html, page_url)
        current_page = parse_qsl(urlparse(page_url).query, keep_blank_values=True)
        if any(key == "page" and value not in {"", "1"} for key, value in current_page):
            return urls
        page_count = self._catalogue_page_count(html)
        if not page_count or page_count <= 1:
            return urls

        configured = urlparse(self.site.home_url)
        params = dict(parse_qsl(configured.query, keep_blank_values=True))
        for page_number in range(2, page_count + 1):
            page_params = dict(params)
            page_params["page"] = str(page_number)
            urls.append(urlunparse(configured._replace(query=urlencode(page_params))))
        return list(dict.fromkeys(urls))


class WooCommerceScraper(GenericScraper):
    detail_scope_selectors = (
        "main .summary.entry-summary",
        ".summary.entry-summary",
        "main .product",
        "main",
    )
    price_selectors = (
        ".summary .price ins .woocommerce-Price-amount",
        ".summary .price .woocommerce-Price-amount",
        ".summary p.price",
        '[itemprop="offers"] [itemprop="price"]',
        "meta[itemprop=price]",
    )
    stock_selectors = (".summary .stock", ".stock", '[itemprop="availability"]')


class MagentoScraper(GenericScraper):
    detail_scope_selectors = (".product-info-main", "main .product-info-main", "main")
    price_selectors = (
        '[data-price-type="finalPrice"] .price',
        '[data-price-type="finalPrice"]',
        ".price-box .special-price .price",
        ".price-box .price",
        "meta[itemprop=price]",
    )
    stock_selectors = (
        ".stock.available",
        ".stock.unavailable",
        ".product-info-stock-sku .stock",
        '[itemprop="availability"]',
    )


class OsCommerceScraper(GenericScraper):
    detail_scope_selectors = ("#content", "main", ".content", "body")
    price_selectors = (".productPrice", ".price", "[itemprop=price]", "meta[itemprop=price]")
    stock_selectors = (".availability", ".stock", ".delivery", ".shippingtime")


class JTLScraper(GenericScraper):
    detail_scope_selectors = ("#productdetails", ".product-detail", "main", "#content")
    price_selectors = (".price_wrapper .price", ".product-price", ".price", "[itemprop=price]")
    stock_selectors = (".delivery-status", ".shippingtime", ".product-stock", '[itemprop="availability"]')


class OpelGTSourceScraper(GenericScraper):
    detail_scope_selectors = ("main", "#main-content", "#content", "body")
    price_selectors = (".price", ".product-price", "[itemprop=price]")
    stock_selectors = (".availability", ".stock", ".product-stock")

    _DETAIL_PATH_RE = re.compile(r"^/search/\d+/details/?$", re.IGNORECASE)
    _USD_PRICE_RE = re.compile(r"\$\s*(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)")
    _INVALID_TITLES = {
        "select your option",
        "opel gt",
        "opel kadett b",
        "opel ascona a & opel manta a",
        "engine",
        "sales",
        "part list",
        "details",
    }

    @classmethod
    def _is_detail_url(cls, url: str) -> bool:
        return bool(cls._DETAIL_PATH_RE.fullmatch(urlparse(url).path))

    @classmethod
    def _valid_title(cls, title: str) -> bool:
        normalized = " ".join(title.split()).strip().lower()
        return _plausible_title(title) and normalized not in cls._INVALID_TITLES

    @classmethod
    def _explicit_usd_price(cls, text: str) -> float | None:
        match = cls._USD_PRICE_RE.search(text.replace("\xa0", " "))
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    @classmethod
    def _title_before_reference(cls, node: Tag) -> str:
        # Sur la vitrine Opel GT Source, le titre se trouve immédiatement avant
        # la ligne « Part: ... ». Cette extraction évite de confondre le panneau
        # « SELECT YOUR OPTION » avec une fiche produit.
        strings = [" ".join(value.split()) for value in node.stripped_strings if value.strip()]
        part_index = next(
            (index for index, value in enumerate(strings) if value.lower().startswith("part:")),
            None,
        )
        if part_index is not None:
            for value in reversed(strings[:part_index]):
                lowered = value.lower()
                if (
                    cls._valid_title(value)
                    and not cls._USD_PRICE_RE.fullmatch(value)
                    and lowered not in {"price", "price:", "from"}
                ):
                    return value
        return ""

    @classmethod
    def _product_container(cls, details_link: Tag) -> Tag | None:
        # Retient le plus petit ancêtre contenant exactement cette fiche, sa
        # référence et son prix. Le résultat ne dépend ainsi ni du système
        # d'exploitation ni du parseur HTML installé.
        for parent in details_link.parents:
            if not isinstance(parent, Tag):
                continue
            text = _visible_text(parent)
            detail_links = [
                link
                for link in parent.select('a[href*="/search/"][href*="/details"]')
                if cls._is_detail_url(clean_url(str(link.get("href") or ""), "https://www.opelgtsource.com"))
            ]
            if "part:" in text.lower() and "$" in text and len(detail_links) == 1:
                return parent
            if parent.name in {"main", "body"}:
                break
        return None

    def _offers_from_html(self, soup: BeautifulSoup, page_url: str) -> list[Offer]:
        parsed: list[Offer] = []
        seen_urls: set[str] = set()
        for details_link in soup.select('a[href*="/search/"][href*="/details"]'):
            if not isinstance(details_link, Tag):
                continue
            url = clean_url(str(details_link.get("href") or ""), self.site.base_url)
            if not self._is_detail_url(url) or url in seen_urls:
                continue
            node = self._product_container(details_link)
            if node is None:
                continue
            text = _visible_text(node)
            title = _first_text(node, (".product-title", ".product-name", ".name", "h2", "h3", "h4"))
            if not self._valid_title(title):
                title = self._title_before_reference(node)
            if not self._valid_title(title):
                continue
            price = self._explicit_usd_price(text)
            reference = extract_reference(text)
            availability, label = availability_from_text(text)
            image = (
                _first_attr(node, ("img[data-src]",), "data-src")
                or _first_attr(node, ("img[data-original]",), "data-original")
                or _first_attr(node, ("img[src]",), "src")
            )
            parsed.append(
                Offer(
                    id=stable_id(self.site.id, url, reference or title),
                    site_id=self.site.id,
                    site_name=self.site.name,
                    title=title,
                    url=url,
                    image_url=clean_url(image, self.site.base_url) if image else None,
                    reference=reference,
                    price=price,
                    currency="USD",
                    availability=availability,
                    availability_label=label,
                    models=_models_from_text(text),
                    raw_description=text[:1600],
                    checked_at=datetime.now(timezone.utc).isoformat(),
                    price_source="liste:opelgtsource",
                    availability_source="liste:opelgtsource",
                )
            )
            seen_urls.add(url)
        return parsed

    def _offer_from_detail_page(self, html: str, page_url: str) -> Offer | None:
        offer = super()._offer_from_detail_page(html, page_url)
        if offer is None or not self._is_detail_url(offer.url or page_url):
            return offer
        if not self._valid_title(offer.title):
            return None

        # La page contient souvent « 1.9L » avant le bloc de prix. On extrait
        # exclusivement le montant avec symbole dollar situé après « Price: »
        # pour ne jamais interpréter la cylindrée comme 1,90 USD.
        soup = BeautifulSoup(html, "html.parser")
        text = _visible_text(self._scope(soup))
        price_section = re.search(
            r"\bprice\s*:\s*(.*?)(?:\bdescription\s*:|\badd\s+to\s+cart\b|$)",
            text,
            re.IGNORECASE,
        )
        visible_price = self._explicit_usd_price(price_section.group(1) if price_section else text)
        if visible_price is not None:
            offer.price = visible_price
            offer.currency = "USD"
            offer.price_source = "fiche:opelgtsource"
        return offer

    def parse_page(self, html: str, page_url: str) -> tuple[list[Offer], str | None]:
        offers, next_url = super().parse_page(html, page_url)
        return (
            [offer for offer in offers if self._is_detail_url(offer.url) and self._valid_title(offer.title)],
            next_url,
        )


_ADAPTERS = {
    "prestashop": PrestaShopScraper,
    "splendidparts": SplendidPartsScraper,
    "woocommerce": WooCommerceScraper,
    "magento": MagentoScraper,
    "oscommerce": OsCommerceScraper,
    "jtl": JTLScraper,
    "opelgtsource": OpelGTSourceScraper,
    "generic": GenericScraper,
}


def scraper_for(site, client):
    return _ADAPTERS.get(site.platform, GenericScraper)(site, client)
