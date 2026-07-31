from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.pieces.config import settings
from app.pieces.models import Offer
from app.pieces.scrapers.sites import SiteConfig
from app.pieces.services.cache import cache
from app.pieces.services.compatibility import keep_for_model
from app.pieces.services.http_utils import resilient_get
from app.pieces.services.text import (
    clean_url,
    extract_price,
    extract_reference,
    normalize_text,
    stable_id,
    strip_accents,
)
from app.pieces.services.translation import (
    TranslationError,
    canonical_french,
    verified_query_candidates_for_language,
)


@dataclass
class ScrapeResult:
    offers: list[Offer]
    pages_read: int
    detail: str = ""


def _stock_normalize(text: str) -> str:
    text = strip_accents(text).lower()
    text = re.sub(r"[\s_\-/]+", " ", text)
    return " ".join(text.split())


_RESTOCK_MARKERS = (
    "reapprovisionnement",
    "reappro",
    "sur commande",
    "uniquement sur commande",
    "backorder",
    "back order",
    "available on backorder",
    "preorder",
    "pre order",
    "auf bestellung",
    "nachbestellung",
    "wieder lieferbar",
    "bestellbar",
    "nalevering",
    "nabestelling",
    "restocking",
)
_OUT_MARKERS = (
    "out of stock",
    "out stock",
    "sold out",
    "not available",
    "unavailable",
    "epuise",
    "rupture de stock",
    "indisponible",
    "non disponible",
    "temporairement indisponible",
    "nicht lieferbar",
    "nicht verfugbar",
    "nicht vorratig",
    "ausverkauft",
    "uitverkocht",
    "niet op voorraad",
    "schema org outofstock",
)
_LOW_MARKERS = (
    "limitedavailability",
    "limited availability",
    "low stock",
    "derniers articles",
    "dernier article",
    "nur noch",
    "wenige auf lager",
    "schema org limitedavailability",
)
_IN_MARKERS = (
    "schema org instock",
    "in stock",
    "en stock",
    "auf lager",
    "vorratig",
    "lieferbar",
    "sofort lieferbar",
    "op voorraad",
    "available now",
    "add to cart",
    "in den warenkorb",
    "ajouter au panier",
    "1 8 work days",
    "work days",
)


def availability_from_text(text: str) -> tuple[str, str]:
    normalized = _stock_normalize(text)
    # Une mention de réapprovisionnement est plus informative qu'un simple bouton
    # d'achat ou qu'une rupture temporaire et doit donc gagner la priorité.
    if any(marker in normalized for marker in _RESTOCK_MARKERS):
        return "restocking", "Réapprovisionnement"
    if any(marker in normalized for marker in _OUT_MARKERS):
        return "out_of_stock", "Pas de stock"
    if any(marker in normalized for marker in _LOW_MARKERS):
        return "low_stock", "En stock"
    if any(marker in normalized for marker in _IN_MARKERS):
        return "in_stock", "En stock"
    if "preis auf anfrage" in normalized or "price on request" in normalized:
        return "unknown", "À confirmer"
    return "unknown", "À confirmer"


def _flatten_jsonld(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        type_value = payload.get("@type")
        if type_value == "Product" or (isinstance(type_value, list) and "Product" in type_value):
            yield payload
        for key in ("@graph", "itemListElement", "mainEntity", "item"):
            if key in payload:
                yield from _flatten_jsonld(payload[key])
    elif isinstance(payload, list):
        for item in payload:
            yield from _flatten_jsonld(item)


def _jsonld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        products.extend(_flatten_jsonld(payload))
    return products


def _visible_text(node: Tag | BeautifulSoup) -> str:
    parts: list[str] = []
    for value in node.find_all(string=True):
        parent_name = value.parent.name if value.parent else ""
        if parent_name in {"script", "style", "noscript", "template"}:
            continue
        cleaned = " ".join(str(value).split())
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)


def _first_text(node: Tag | BeautifulSoup, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            text = _visible_text(found)
            if text:
                return text
    return ""


def _first_attr(node: Tag | BeautifulSoup, selectors: tuple[str, ...], attr: str) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found and found.get(attr):
            return str(found.get(attr))
    return ""


def _models_from_text(text: str) -> list[str]:
    lowered = strip_accents(text).lower().replace(",", ".")
    models: list[str] = []
    if any(token in lowered for token in ("gt/j", "gtj", "gt j")):
        models.append("gtj")
    if re.search(r"(?<!\d)(?:1100|1\.1)(?!\d)", lowered) or "ohv" in lowered:
        models.append("1100")
    if re.search(r"(?<!\d)(?:1900|1\.9)(?!\d)", lowered) or "cih" in lowered:
        models.append("1900")
    return models


_QUERY_STOPWORDS = {"a", "au", "aux", "d", "de", "des", "du", "l", "la", "le", "les", "pour"}
_TECHNICAL_TITLE_MARKERS = (
    "rendered products",
    "add to cart url",
    "canonical url",
    "sort orders",
    "pagination total items",
    "products add to cart",
    "urlparameter",
)


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def _plausible_title(title: str) -> bool:
    compact = " ".join(title.split())
    lowered = compact.lower()
    return (
        3 <= len(compact) <= 220
        and len(compact.split()) <= 28
        and not any(marker in lowered for marker in _TECHNICAL_TITLE_MARKERS)
        and lowered.count("u00") < 2
        and lowered.count("\\n") < 2
    )


def _nested_image_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        for item in value:
            if found := _nested_image_url(item):
                return found
    if isinstance(value, dict):
        if direct := value.get("url") or value.get("src"):
            return str(direct)
        by_size = value.get("bySize") or value.get("by_size")
        if isinstance(by_size, dict):
            for key in ("home_default", "medium_default", "large_default", "cart_default", "small_default"):
                if found := _nested_image_url(by_size.get(key)):
                    return found
            for item in by_size.values():
                if found := _nested_image_url(item):
                    return found
    return None


class GenericScraper:
    detail_scope_selectors = (
        "main .product-container",
        "main .product-detail",
        "main #product",
        ".product-page",
        ".product-info-main",
        "#content .product-container",
        "main",
    )
    title_selectors = ("h1[itemprop=name]", "h1.product-title", ".product-name h1", "h1")
    price_selectors = (
        ".current-price [itemprop=price]",
        ".current-price .price",
        ".special-price .price",
        ".price ins .amount",
        "ins .woocommerce-Price-amount",
        ".product-info-price .price",
        ".price-box .price",
        "#our_price_display",
        ".productPrice",
        ".product-price [itemprop=price]",
        "[data-price-type=finalPrice] .price",
        "[itemprop=offers] [itemprop=price]",
        ".summary .price",
        ".woocommerce-Price-amount",
        'meta[property="product:price:amount"]',
        "meta[itemprop=price]",
        ".price",
    )
    stock_selectors = (
        '[itemprop="availability"]',
        'meta[property="product:availability"]',
        "#product-availability",
        ".product-availability",
        ".availability",
        ".availability-value",
        ".delivery-status",
        ".shippingtime",
        ".stock-status",
        ".stock",
        ".product-stock",
        ".summary .stock",
    )
    description_selectors = (
        ".product-description",
        "#description",
        "[itemprop=description]",
        ".description",
        ".short-description",
        ".product.attribute.description",
        ".woocommerce-product-details__short-description",
    )
    reference_selectors = (
        ".product-reference",
        ".product-sku",
        ".product-number",
        ".product-id",
        ".art-nr",
        ".sku",
        "[itemprop=sku]",
    )

    def __init__(self, site: SiteConfig, client: httpx.AsyncClient):
        self.site = site
        self.client = client

    async def _query_candidates(self, keywords_fr: str, models: list[str]) -> list[str]:
        return await verified_query_candidates_for_language(
            keywords_fr, self.site.language, models, self.client
        )

    def _request_headers(self, url: str, scope: str) -> dict[str, str] | None:
        """Optional per-supplier headers for normal public catalogue navigation."""
        return None

    def _page_worker_count(self) -> int:
        """Number of listing pages fetched concurrently for this supplier."""
        return max(1, settings.max_concurrent_pages_per_site)

    async def search(self, keywords_fr: str, models: list[str]) -> ScrapeResult:
        """Search one supplier according to the strategy declared in suppliers_infos.txt.

        Catalogue suppliers are crawled from their configured Opel GT root and
        filtered locally. Suppliers explicitly marked as using their website
        engine are queried through the search form discovered on that root. In
        both cases every reachable pagination page is visited before filtering.
        """
        selected_model = models[0] if models else "1900"
        pages_read = 0
        errors: list[str] = []
        page_cache: dict[str, str] = {}
        deadline = time.monotonic() + max(1.0, settings.search_site_timeout_seconds)
        deadline_reported = False
        try:
            queries = await asyncio.wait_for(
                self._query_candidates(keywords_fr, models),
                timeout=min(10.0, max(0.1, deadline - time.monotonic())),
            )
        except asyncio.TimeoutError as exc:
            raise TranslationError(f"Traduction interrompue après 10 s pour {self.site.name}") from exc

        def remaining_time() -> float:
            return max(0.0, deadline - time.monotonic())

        def report_deadline() -> None:
            nonlocal deadline_reported
            if not deadline_reported:
                errors.append(
                    f"délai fournisseur atteint ({settings.search_site_timeout_seconds:g} s), "
                    "résultats partiels conservés"
                )
                deadline_reported = True

        async def fetch(url: str, scope: str) -> tuple[str, str] | None:
            nonlocal pages_read
            remaining = remaining_time()
            if remaining <= 0:
                report_deadline()
                return None
            try:
                response = await asyncio.wait_for(
                    resilient_get(
                        self.client,
                        url,
                        self.site.id,
                        circuit_scope=scope,
                        headers=self._request_headers(url, scope),
                    ),
                    timeout=remaining,
                )
                if response.status_code in {401, 403, 429}:
                    errors.append(f"HTTP {response.status_code}")
                    return None
                response.raise_for_status()
            except asyncio.TimeoutError:
                report_deadline()
                return None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append(type(exc).__name__)
                return None
            final_url = str(response.url)
            page_cache[final_url] = response.text
            pages_read += 1
            return final_url, response.text

        async def crawl(
            start_urls: Iterable[str],
            scope: str,
            *,
            discover_categories: bool = False,
        ) -> list[Offer]:
            queue = deque(dict.fromkeys(url for url in start_urls if url))
            queued = set(queue)
            visited: set[str] = set()
            collected: list[Offer] = []
            worker_count = self._page_worker_count()

            while queue and remaining_time() > 0:
                batch: list[str] = []
                while queue and len(batch) < worker_count:
                    current_url = queue.popleft()
                    queued.discard(current_url)
                    if current_url in visited:
                        continue
                    if settings.max_pages_per_site > 0 and len(visited) >= settings.max_pages_per_site:
                        errors.append(f"limite configurée atteinte ({settings.max_pages_per_site} pages)")
                        queue.clear()
                        break
                    visited.add(current_url)
                    batch.append(current_url)
                if not batch:
                    break

                fetched_pages = await asyncio.gather(
                    *(fetch(url, scope) for url in batch),
                    return_exceptions=False,
                )
                for fetched in fetched_pages:
                    if fetched is None:
                        continue
                    final_url, html = fetched
                    visited.add(final_url)
                    page_offers, next_url = self.parse_page(html, final_url)
                    collected = self._deduplicate([*collected, *page_offers])
                    pagination_urls = self._pagination_urls(html, final_url)
                    if self.site.id == "opel_gt_source":
                        pagination_urls.extend(self._opel_gt_source_navigation_urls(html, final_url))
                    if next_url:
                        pagination_urls.insert(0, next_url)

                    # Product categories that match the translated query must be
                    # visited before the generic pagination. Both SplendidParts
                    # and OpelixParts expose the relevant clutch products through
                    # a dedicated category link from the configured Opel GT root.
                    # The previous crawler followed only result pages, so it could
                    # exhaust its deadline without ever opening that category.
                    category_urls = (
                        self._catalog_navigation_urls(html, final_url, keywords_fr, queries)
                        if discover_categories
                        else []
                    )
                    for candidate in reversed(category_urls):
                        if candidate not in visited and candidate not in queued:
                            queue.appendleft(candidate)
                            queued.add(candidate)
                    for candidate in dict.fromkeys(pagination_urls):
                        if candidate not in visited and candidate not in queued:
                            queue.append(candidate)
                            queued.add(candidate)

            if queue and remaining_time() <= 0:
                report_deadline()
            return collected

        if self.site.use_website_engine_search:
            root = await fetch(self.site.home_url, "search-discovery")
            if root is None:
                candidates: list[Offer] = []
            else:
                root_url, root_html = root
                search_urls = self._website_search_urls(root_html, root_url, queries)
                if not search_urls:
                    errors.append("formulaire de recherche introuvable")
                    candidates = []
                else:
                    candidates = await crawl(search_urls, "search")
        else:
            start_urls = [self.site.home_url]
            if self.site.id == "oldtimer_motorenteile":
                root = await fetch(self.site.home_url, "catalog-models")
                if root is not None:
                    root_url, root_html = root
                    selected_url = self._oldtimer_model_url(root_html, root_url, selected_model)
                    if selected_url:
                        start_urls = [selected_url]
                    else:
                        errors.append(f"modèle Opel GT {selected_model} introuvable")
                        start_urls = []
            # Opel GT Source renders its categories dynamically. Its configured
            # root remains the source of truth, but the catalogue endpoint must
            # receive the translated term to expose the corresponding products.
            if self.site.id == "opel_gt_source":
                start_urls.extend(self._opel_gt_source_catalog_urls(queries))
            candidates = await crawl(start_urls, "catalog", discover_categories=True)

        candidates = [
            offer for offer in candidates if self._candidate_keyword_match(offer, keywords_fr, queries)
        ]
        strict_offers = await self._finalize(
            candidates, page_cache, keywords_fr, selected_model, queries, deadline
        )
        detail = "; ".join(dict.fromkeys(errors))
        if settings.max_results_per_site > 0:
            strict_offers = strict_offers[: settings.max_results_per_site]
        return ScrapeResult(strict_offers, pages_read, detail)

    @staticmethod
    def _search_input(form: Tag) -> Tag | None:
        preferred_names = {
            "q",
            "s",
            "query",
            "search",
            "search_query",
            "keywords",
            "keyword",
            "term",
        }
        inputs = [node for node in form.select("input[name]") if isinstance(node, Tag)]
        for node in inputs:
            input_type = str(node.get("type") or "text").lower()
            name = str(node.get("name") or "").lower()
            if input_type == "search" or name in preferred_names:
                return node
        for node in inputs:
            if str(node.get("type") or "text").lower() in {"text", "search"}:
                return node
        return None

    def _website_search_urls(self, html: str, page_url: str, queries: list[str]) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        ranked: list[tuple[int, Tag, Tag]] = []
        for form in soup.select("form"):
            if not isinstance(form, Tag):
                continue
            query_input = self._search_input(form)
            if query_input is None:
                continue
            method = str(form.get("method") or "get").lower()
            if method != "get":
                continue
            action = urljoin(page_url, str(form.get("action") or page_url))
            action_text = normalize_text(action)
            form_text = normalize_text(_visible_text(form))
            input_type = str(query_input.get("type") or "text").lower()
            input_name = str(query_input.get("name") or "").lower()
            score = 0
            if input_type == "search":
                score += 5
            if input_name in {"q", "s", "query", "search", "search_query", "keywords"}:
                score += 5
            if "search" in action_text or "search" in form_text or "suche" in form_text:
                score += 4
            if any(token in action_text for token in ("login", "newsletter", "contact")):
                score -= 20
            ranked.append((score, form, query_input))

        urls: list[str] = []
        if ranked:
            _, form, query_input = max(ranked, key=lambda item: item[0])
            action = urljoin(page_url, str(form.get("action") or page_url))
            action_parts = urlparse(action)
            root_parts = urlparse(self.site.home_url)
            base_params = dict(parse_qsl(action_parts.query, keep_blank_values=True))
            for key, value in parse_qsl(root_parts.query, keep_blank_values=True):
                base_params.setdefault(key, value)
            for node in form.select('input[type="hidden"][name]'):
                name = str(node.get("name") or "")
                if name:
                    base_params.setdefault(name, str(node.get("value") or ""))
            query_name = str(query_input.get("name") or "q")
            for query in queries:
                params = dict(base_params)
                params[query_name] = query
                urls.append(urlunparse(action_parts._replace(query=urlencode(params, doseq=True))))
        else:
            # Platform-level fallbacks are used only when the actual form is
            # rendered by JavaScript or hidden behind an anti-bot interstitial.
            root = urlparse(self.site.home_url)
            preserved = dict(parse_qsl(root.query, keep_blank_values=True))
            if self.site.platform == "magento":
                action = urljoin(self.site.home_url, "catalogsearch/result/")
                query_name = "q"
            elif self.site.platform == "oscommerce":
                action = urljoin(self.site.home_url, "advanced_search_result.php")
                query_name = "keywords"
                preserved.setdefault("search_in_description", "1")
                preserved.setdefault("categories_id", "0")
                preserved.setdefault("inc_subcat", "1")
            else:
                return []
            for query in queries:
                params = dict(preserved)
                params[query_name] = query
                urls.append(f"{action}?{urlencode(params)}")
        return list(dict.fromkeys(urls))

    def _opel_gt_source_catalog_urls(self, queries: list[str]) -> list[str]:
        """Build Opel GT Source catalogue-filter URLs from the configured root.

        The supplier's category tree is JavaScript-driven, so a plain GET of the
        root exposes only a sales carousel. The ``/search/paginate`` endpoint is
        the catalogue itself and accepts the ``car_id`` declared in the supplied
        configuration file.
        """
        root = urlparse(self.site.home_url)
        params = dict(parse_qsl(root.query, keep_blank_values=True))
        params.setdefault("car_id", "4")
        urls: list[str] = []
        for query in queries:
            regular = dict(params)
            regular["search"] = query
            urls.append(urlunparse(root._replace(query=urlencode(regular))))

            paginated = dict(regular)
            paginated.setdefault("order_by", "featured")
            paginated.setdefault("page", "1")
            urls.append(urlunparse(root._replace(path="/search/paginate", query=urlencode(paginated))))
        return list(dict.fromkeys(urls))

    def _opel_gt_source_navigation_urls(self, html: str, page_url: str) -> list[str]:
        """Extract dynamic category and pagination URLs embedded by Opel GT Source."""
        if self.site.id != "opel_gt_source":
            return []
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(self.site.base_url).netloc.lower()
        raw_values: list[str] = []
        for node in soup.select("a[href], option[value], [data-url], [data-href]"):
            if not isinstance(node, Tag):
                continue
            for attribute in ("href", "value", "data-url", "data-href"):
                value = str(node.get(attribute) or "").strip()
                if value:
                    raw_values.append(value)
        # Rails templates also keep catalogue URLs inside script blocks.
        raw_values.extend(
            value.replace("&amp;", "&")
            for value in re.findall(
                r"""["']([^"']*/search(?:/paginate)?\?[^"']+)["']""",
                html,
                flags=re.IGNORECASE,
            )
        )

        urls: list[str] = []
        for value in raw_values:
            url = clean_url(value, page_url)
            parsed = urlparse(url)
            if parsed.netloc.lower() != host or not parsed.path.startswith("/search"):
                continue
            if "/details" in parsed.path.lower():
                continue
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if not ({"car_id", "category_id", "sub_category_id", "page", "search"} & set(params)):
                continue
            urls.append(url)
        return list(dict.fromkeys(urls))

    @staticmethod
    def _oldtimer_model_url(html: str, page_url: str, selected_model: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[tuple[str, str]] = []
        for node in soup.select("a[href]"):
            label = strip_accents(_visible_text(node)).lower()
            label = " ".join(re.sub(r"[^a-z0-9]+", " ", label).split())
            href = str(node.get("href") or "")
            if href and "opel gt" in label:
                candidates.append((label, urljoin(page_url, href)))

        if selected_model == "gtj":
            matches = [url for label, url in candidates if "gt j" in label or "gtj" in label]
        elif selected_model == "1100":
            matches = [url for label, url in candidates if "1100" in label and "gt j" not in label]
        else:
            matches = [
                url
                for label, url in candidates
                if "1900" in label and "gt j" not in label and "gtj" not in label
            ]
        return matches[0] if matches else None

    async def _finalize(
        self,
        candidates: list[Offer],
        page_cache: dict[str, str],
        keywords_fr: str,
        selected_model: str,
        translated_queries: list[str] | None = None,
        deadline: float | None = None,
    ) -> list[Offer]:
        # Detail-page refresh is bounded. Rank listing candidates first so this
        # budget is spent on the most relevant products, not catalogue order.
        ranked_candidates = sorted(
            self._deduplicate(candidates),
            key=lambda offer: -(self._query_match_score(offer, keywords_fr, translated_queries) or 0.0),
        )
        refreshed = await self._refresh_product_details(ranked_candidates, page_cache, deadline)
        strict: list[Offer] = []
        for offer in self._deduplicate(refreshed):
            score = self._query_match_score(offer, keywords_fr, translated_queries)
            if score is None or not keep_for_model(offer, selected_model):
                continue
            if offer.compatibility == "uncertain":
                score = max(0.0, score - 0.03)
            offer.query_confidence = round(score, 3)
            strict.append(offer)
        return sorted(strict, key=lambda offer: (-offer.query_confidence, offer.site_name, offer.title))

    @staticmethod
    def _query_parts(keywords_fr: str) -> tuple[list[str], list[str], list[str]]:
        tokens: list[str] = []
        phrases: list[str] = []
        excluded: list[str] = []
        for match in re.finditer(r'"([^"]+)"|(\S+)', keywords_fr):
            phrase, raw_token = match.groups()
            value = phrase if phrase is not None else (raw_token or "")
            is_excluded = phrase is None and value.startswith("-")
            value = value.lstrip("+-").strip()
            normalized = normalize_text(canonical_french(value))
            parts = [part for part in normalized.split() if len(part) > 1 and part not in _QUERY_STOPWORDS]
            if is_excluded:
                excluded.extend(parts)
            else:
                tokens.extend(parts)
                if phrase is not None and parts:
                    phrases.append(" ".join(parts))
        return list(dict.fromkeys(tokens)), list(dict.fromkeys(phrases)), list(dict.fromkeys(excluded))

    @classmethod
    def _query_match_score(
        cls,
        offer: Offer,
        keywords_fr: str,
        translated_queries: list[str] | None = None,
    ) -> float | None:
        """Match every query concept against the product title only.

        Descriptions, category text and URLs are deliberately excluded.  A
        multi-word request is an AND request: every significant concept must be
        present in the same title after automotive synonym canonicalization.
        """
        required, phrases, excluded = cls._query_parts(keywords_fr)
        title = normalize_text(canonical_french(offer.title))
        title_concepts = [token for token in title.split() if token not in _QUERY_STOPWORDS]
        concept_title = " ".join(title_concepts)
        title_tokens = set(title_concepts)

        compact_query = re.sub(r"[^A-Z0-9]", "", keywords_fr.upper())
        if (
            offer.reference
            and len(compact_query) >= 3
            and compact_query == re.sub(r"[^A-Z0-9]", "", offer.reference.upper())
        ):
            return 1.0
        if any(token in title_tokens for token in excluded):
            return None

        if required and all(token in title_tokens for token in required):
            if any(phrase not in concept_title for phrase in phrases):
                return None
            exact = " ".join(required)
            if concept_title == exact:
                return 1.0
            if exact and exact in concept_title:
                return 0.98
            return 0.92

        # Fallback for a remotely translated unknown automotive phrase.  It is
        # also strict: one complete translated phrase must occur in the title.
        return cls._translated_match_score(offer, translated_queries or [])

    @staticmethod
    def _translated_match_score(offer: Offer, translated_queries: list[str]) -> float | None:
        title = normalize_text(offer.title)
        title_tokens = set(title.split())
        best: float | None = None
        for translated in translated_queries:
            phrase = normalize_text(translated)
            tokens = [token for token in phrase.split() if len(token) > 1]
            if not tokens or any(token not in title_tokens for token in tokens):
                continue
            score = 0.95 if phrase and phrase in title else 0.90
            best = score if best is None else max(best, score)
        return round(best, 3) if best is not None else None

    @classmethod
    def _candidate_keyword_match(
        cls,
        offer: Offer,
        keywords_fr: str,
        translated_queries: list[str] | None = None,
    ) -> bool:
        return cls._query_match_score(offer, keywords_fr, translated_queries) is not None

    async def _refresh_product_details(
        self,
        offers: list[Offer],
        page_cache: dict[str, str],
        deadline: float | None = None,
    ) -> list[Offer]:
        offers = self._deduplicate(offers)
        if deadline is not None and time.monotonic() >= deadline:
            return offers
        limit = min(len(offers), settings.max_detail_pages_per_site)
        semaphore = asyncio.Semaphore(settings.max_concurrent_details)

        async def refresh(offer: Offer) -> Offer:
            parsed = urlparse(offer.url)
            if not offer.url or parsed.netloc != urlparse(self.site.base_url).netloc:
                return offer
            path = parsed.path.rstrip("/").lower()
            if path == "/search" or "advanced_search_result" in path or "catalogsearch/result" in path:
                return offer
            cache_key = stable_id(offer.url)
            cached = cache.get("product_detail", cache_key)
            if cached:
                try:
                    detail = Offer.model_validate(cached)
                    detail.id = offer.id
                    return self._merge_detail(detail, offer)
                except Exception:
                    pass
            try:
                async with semaphore:
                    html = page_cache.get(offer.url)
                    if html is None:
                        remaining = (deadline - time.monotonic()) if deadline is not None else None
                        if remaining is not None and remaining <= 0:
                            return offer
                        request = resilient_get(
                            self.client,
                            offer.url,
                            self.site.id,
                            circuit_scope="detail",
                        )
                        response = (
                            await asyncio.wait_for(request, timeout=remaining)
                            if remaining is not None
                            else await request
                        )
                        response.raise_for_status()
                        html = response.text
                        page_cache[str(response.url)] = html
                detail = self._offer_from_detail_page(html, offer.url)
            except asyncio.CancelledError:
                raise
            except Exception:
                return offer
            if detail is None:
                return offer
            detail.id = offer.id
            detail = self._merge_detail(detail, offer)
            cache.set(
                "product_detail", cache_key, detail.model_dump(mode="json"), settings.detail_cache_seconds
            )
            return detail

        refreshed = await asyncio.gather(*(refresh(offer) for offer in offers[:limit]))
        return [*refreshed, *offers[limit:]]

    @staticmethod
    def _merge_detail(detail: Offer, listing: Offer) -> Offer:
        if detail.price is None:
            detail.price, detail.currency = listing.price, listing.currency
            detail.price_source = listing.price_source
        if detail.availability == "unknown":
            detail.availability = listing.availability
            detail.availability_label = listing.availability_label
            detail.availability_source = listing.availability_source
        detail.image_url = detail.image_url or listing.image_url
        detail.reference = detail.reference or listing.reference
        detail.raw_description = detail.raw_description or listing.raw_description
        detail.models = list(dict.fromkeys([*detail.models, *listing.models]))
        return detail

    def _scope(self, soup: BeautifulSoup) -> Tag | BeautifulSoup:
        for selector in self.detail_scope_selectors:
            found = soup.select_one(selector)
            if isinstance(found, Tag):
                return found
        return soup

    def _offer_from_detail_page(self, html: str, page_url: str) -> Offer | None:
        stripped = html.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                offers, _ = self._offers_from_json_payload(payload, page_url)
                return offers[0] if offers else None

        soup = BeautifulSoup(html, "html.parser")
        json_offers = [
            offer
            for product in _jsonld_products(soup)
            if (offer := self._offer_from_jsonld(product, page_url)) is not None
        ]
        json_offer = json_offers[0] if json_offers else None
        scope = self._scope(soup)

        title = _first_text(scope, self.title_selectors)
        if not title:
            og_title = soup.select_one('meta[property="og:title"]')
            title = str(og_title.get("content") or "") if og_title else ""
        if not _plausible_title(title) and json_offer:
            title = json_offer.title
        if not _plausible_title(title):
            return None

        canonical = soup.select_one('link[rel="canonical"]')
        url = clean_url(str(canonical.get("href") or page_url), self.site.base_url) if canonical else page_url

        currency = self.site.currency_hint
        currency_node = soup.select_one(
            '[itemprop="priceCurrency"][content], meta[property="product:price:currency"]'
        )
        if currency_node and currency_node.get("content"):
            candidate = str(currency_node.get("content")).strip().upper()
            if candidate in {"EUR", "USD", "GBP"}:
                currency = candidate

        price: float | None = None
        price_source = "unknown"
        for selector in self.price_selectors:
            node = scope.select_one(selector) or soup.select_one(selector)
            if not node:
                continue
            raw = next(
                (
                    str(node.get(attr))
                    for attr in ("content", "data-price", "data-price-amount", "value")
                    if node.get(attr)
                ),
                "",
            )
            raw = raw or _visible_text(node)
            candidate, parsed_currency = extract_price(raw, currency)
            if candidate is not None:
                price, currency = candidate, parsed_currency or currency
                price_source = f"fiche:{self.site.platform}"
                break
        if price is None and json_offer and json_offer.price is not None:
            price, currency = json_offer.price, json_offer.currency or currency
            price_source = "jsonld"

        description = _first_text(scope, self.description_selectors)
        availability_parts: list[str] = []
        for selector in self.stock_selectors:
            node = scope.select_one(selector) or soup.select_one(selector)
            if not node:
                continue
            availability_parts.extend(
                str(node.get(attr)) for attr in ("content", "href", "data-stock") if node.get(attr)
            )
            availability_parts.append(_visible_text(node))
        if description:
            availability_parts.append(description)
        add_button = scope.select_one(
            "button.add-to-cart, button[name=add], .add-to-cart button, input[type=submit][name=Submit], "
            "button.single_add_to_cart_button, button.tocart"
        )
        if add_button:
            classes = " ".join(add_button.get("class") or [])
            disabled = add_button.has_attr("disabled") or "disabled" in classes
            availability_parts.append("out of stock" if disabled else "add to cart")
        availability, availability_label = availability_from_text(" ".join(availability_parts))
        availability_source = f"fiche:{self.site.platform}" if availability_parts else "unknown"
        if availability == "unknown" and json_offer:
            availability, availability_label = json_offer.availability, json_offer.availability_label
            availability_source = "jsonld"

        image_url: str | None = None
        image_node = scope.select_one(
            '.product-cover img, [itemprop="image"], .product-image img, .product-image-gallery img, '
            "img.js-qv-product-cover, #image, .gallery-placeholder img, .woocommerce-product-gallery img"
        )
        if image_node:
            raw_image = (
                image_node.get("data-image-large-src") or image_node.get("data-src") or image_node.get("src")
            )
            if raw_image:
                image_url = clean_url(str(raw_image), self.site.base_url)
        if not image_url:
            og_image = soup.select_one('meta[property="og:image"]')
            if og_image and og_image.get("content"):
                image_url = clean_url(str(og_image.get("content")), self.site.base_url)
        if not image_url and json_offer:
            image_url = json_offer.image_url

        reference_text = _first_text(scope, self.reference_selectors)
        reference = extract_reference(reference_text or _visible_text(scope))
        if not reference and json_offer:
            reference = json_offer.reference
        combined = f"{title} {description}"
        return Offer(
            id=stable_id(self.site.id, url, reference or title),
            site_id=self.site.id,
            site_name=self.site.name,
            title=title,
            url=url,
            image_url=image_url,
            reference=reference,
            price=price,
            currency=currency,
            availability=availability,
            availability_label=availability_label,
            models=_models_from_text(combined),
            raw_description=description[:1600],
            checked_at=datetime.now(timezone.utc).isoformat(),
            price_source=price_source,
            availability_source=availability_source,
        )

    def parse_page(self, html: str, page_url: str) -> tuple[list[Offer], str | None]:
        stripped = html.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                return self._offers_from_json_payload(payload, page_url)

        soup = BeautifulSoup(html, "html.parser")
        offers = [
            offer
            for product in _jsonld_products(soup)
            if (offer := self._offer_from_jsonld(product, page_url)) is not None
        ]
        offers.extend(self._offers_from_html(soup, page_url))

        # A product page can also contain recommendation cards. Previously, the
        # presence of one such card prevented the main product from being parsed
        # at all, which made direct fallback URLs return only unrelated products.
        # Always add the current product when the document has a real detail-page
        # structure; retain the legacy fallback for simpler supplier pages.
        detail_document = bool(
            soup.select_one(
                "body#product, body.product, main .product-container, "
                "#main .product-container, main #product, .product-detail"
            )
            and soup.select_one("h1")
        )
        if detail_document or (not offers and soup.select_one("h1")):
            detail = self._offer_from_detail_page(html, page_url)
            if detail:
                offers.append(detail)
        return self._deduplicate(offers), self._next_page(soup, page_url)

    def _offers_from_json_payload(self, payload: Any, page_url: str) -> tuple[list[Offer], str | None]:
        offers: list[Offer] = []
        next_url: str | None = None
        if isinstance(payload, list):
            products, rendered, pagination = payload, None, None
        elif isinstance(payload, dict):
            products = payload.get("products") or payload.get("items") or payload.get("results") or []
            if isinstance(products, dict):
                products = [products]
            rendered = payload.get("rendered_products") or payload.get("html") or payload.get("content")
            pagination = payload.get("pagination")
        else:
            return [], None
        if isinstance(products, list):
            for product in products:
                if isinstance(product, dict) and (
                    offer := self._offer_from_payload_product(product, page_url)
                ):
                    offers.append(offer)
        if not offers and isinstance(rendered, str) and "<" in rendered:
            soup = BeautifulSoup(rendered, "html.parser")
            offers.extend(self._offers_from_html(soup, page_url))
            next_url = self._next_page(soup, page_url)
        if isinstance(pagination, dict) and isinstance(pagination.get("pages"), list):
            current = pagination.get("current_page") or pagination.get("currentPage")
            for item in pagination["pages"]:
                if (
                    isinstance(item, dict)
                    and item.get("url")
                    and (item.get("type") == "next" or (current and item.get("page") == int(current) + 1))
                ):
                    next_url = clean_url(str(item["url"]), self.site.base_url)
                    break
        return self._deduplicate(offers), next_url

    def _offer_from_payload_product(self, product: dict[str, Any], page_url: str) -> Offer | None:
        title = _plain_text(product.get("name") or product.get("title"))
        if not _plausible_title(title):
            return None
        description = _plain_text(product.get("description_short") or product.get("description"))
        url = clean_url(str(product.get("url") or product.get("link") or page_url), self.site.base_url)
        image = _nested_image_url(product.get("cover") or product.get("image") or product.get("images"))
        image_url = clean_url(image, self.site.base_url) if image else None
        raw_reference = product.get("reference") or product.get("sku") or product.get("mpn")
        reference = (
            re.sub(r"[^A-Z0-9]", "", str(raw_reference).upper())
            if raw_reference
            else extract_reference(f"{title} {description}")
        )
        raw_price = product.get("price") or product.get("regular_price") or product.get("unit_price")
        if isinstance(raw_price, dict):
            raw_price = raw_price.get("amount") or raw_price.get("value") or raw_price.get("price")
        currency = str(
            product.get("currency") or product.get("price_currency") or self.site.currency_hint
        ).upper()
        if isinstance(raw_price, (int, float)):
            price = float(raw_price)
        else:
            price, parsed_currency = extract_price(str(raw_price or ""), self.site.currency_hint)
            currency = parsed_currency or currency
        availability_text = " ".join(
            str(product.get(key) or "")
            for key in (
                "availability",
                "availability_message",
                "available_now",
                "available_later",
                "condition",
            )
        )
        quantity = product.get("quantity")
        try:
            quantity_value = float(quantity) if quantity is not None else None
        except (TypeError, ValueError):
            quantity_value = None
        if quantity_value is not None and quantity_value <= 0:
            availability_text += " out of stock"
            if product.get("available_for_order") in {True, 1, "1", "true", "True"}:
                availability_text += " backorder"
        elif quantity_value is not None and quantity_value > 0:
            availability_text += " in stock"
        elif product.get("add_to_cart_url"):
            availability_text += " add to cart"
        availability, availability_label = availability_from_text(availability_text)
        return Offer(
            id=stable_id(self.site.id, url, reference or title),
            site_id=self.site.id,
            site_name=self.site.name,
            title=title,
            url=url,
            image_url=image_url,
            reference=reference,
            price=price,
            currency=currency,
            availability=availability,
            availability_label=availability_label,
            models=_models_from_text(f"{title} {description}"),
            raw_description=description[:1600],
            checked_at=datetime.now(timezone.utc).isoformat(),
            price_source="payload",
            availability_source="payload",
        )

    def _offer_from_jsonld(self, product: dict[str, Any], page_url: str) -> Offer | None:
        title = _plain_text(product.get("name"))
        if not _plausible_title(title):
            return None
        url = clean_url(str(product.get("url") or page_url), self.site.base_url)
        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url")
        image_url = clean_url(str(image), self.site.base_url) if image else None
        description = _plain_text(product.get("description"))
        sku = product.get("sku") or product.get("mpn") or product.get("productID")
        reference = (
            re.sub(r"[^A-Z0-9]", "", str(sku).upper()) if sku else extract_reference(f"{title} {description}")
        )
        raw_offers = product.get("offers") or {}
        if isinstance(raw_offers, list):
            raw_offers = raw_offers[0] if raw_offers else {}
        price_raw = raw_offers.get("price") or raw_offers.get("lowPrice")
        currency = str(raw_offers.get("priceCurrency") or self.site.currency_hint).upper()
        try:
            price = float(str(price_raw).replace(",", ".")) if price_raw is not None else None
        except ValueError:
            price = None
        availability, availability_label = availability_from_text(
            str(raw_offers.get("availability") or raw_offers.get("description") or description)
        )
        return Offer(
            id=stable_id(self.site.id, url, reference or title),
            site_id=self.site.id,
            site_name=self.site.name,
            title=title,
            url=url,
            image_url=image_url,
            reference=reference,
            price=price,
            currency=currency,
            availability=availability,
            availability_label=availability_label,
            models=_models_from_text(f"{title} {description}"),
            raw_description=description[:1600],
            checked_at=datetime.now(timezone.utc).isoformat(),
            price_source="jsonld",
            availability_source="jsonld",
        )

    _PRODUCT_PATH_PATTERNS = (
        re.compile(r"/(?:product|products|produit|artikel)/", re.IGNORECASE),
        re.compile(r"/product_info\.php(?:\?|$)", re.IGNORECASE),
        re.compile(r"/search/\d+/details/?$", re.IGNORECASE),
        re.compile(r"/(?:accueil|shop/[^/]+/[^/]+)/\d+[-_][^/]+\.html$", re.IGNORECASE),
        re.compile(r"/\d+[-_][^/]+\.html$", re.IGNORECASE),
    )

    @classmethod
    def _looks_like_product_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        lowered = path.lower()
        if (
            not path
            or any(
                token in lowered
                for token in (
                    "/category/",
                    "/categorie/",
                    "/manufacturer/",
                    "/brands/",
                    "/login",
                    "/account",
                    "/cart",
                    "/contact",
                    "/search",
                    "/page/",
                )
            )
            and not re.search(r"/search/\d+/details/?$", lowered)
        ):
            return False
        if any(
            key in dict(parse_qsl(parsed.query, keep_blank_values=True))
            for key in ("page", "p", "paged", "seite")
        ):
            return False
        return any(
            pattern.search(path + ("?" + parsed.query if parsed.query else ""))
            for pattern in cls._PRODUCT_PATH_PATTERNS
        )

    def _catalog_navigation_urls(
        self,
        html: str,
        page_url: str,
        keywords_fr: str,
        translated_queries: list[str],
    ) -> list[str]:
        """Return query-relevant category links from a supplier catalogue page.

        The configured URL is the root from which the search starts, not always
        the category containing the requested part. We therefore follow only
        same-site category links whose label or URL matches one of the French or
        translated concepts, while explicitly excluding product/detail and
        pagination URLs.
        """
        if html.lstrip().startswith(("{", "[")):
            return []
        soup = BeautifulSoup(html, "html.parser")
        current_host = urlparse(self.site.base_url).netloc.lower()
        raw_terms: set[str] = set()
        for value in (keywords_fr, *translated_queries):
            normalized = normalize_text(canonical_french(value))
            raw_terms.update(
                token for token in normalized.split() if len(token) > 2 and token not in _QUERY_STOPWORDS
            )
            raw_terms.update(
                token
                for token in normalize_text(value).split()
                if len(token) > 2 and token not in _QUERY_STOPWORDS
            )

        # Category vocabulary commonly used by the configured suppliers. This
        # is concept expansion, not a hard-coded result URL: links are still
        # discovered from the configured root page.
        if raw_terms & {"embrayage", "clutch", "kupplung", "kupplungszug", "kupplungsseil"}:
            raw_terms.update({"gearbox", "transmission", "getriebe", "boite", "kupplung", "clutch"})
        if raw_terms & {"essuie", "glace", "wiper", "wischer", "wischerarme"}:
            raw_terms.update({"body", "karosserie", "wiper", "wischer"})

        ranked: list[tuple[int, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            if not isinstance(anchor, Tag):
                continue
            href = str(anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            url = clean_url(href, page_url)
            parsed = urlparse(url)
            if parsed.netloc.lower() != current_host or url == page_url or url in seen:
                continue
            if self._looks_like_product_url(url):
                continue
            lowered = f" {parsed.path.lower()} "
            if any(token in lowered for token in ("/login", "/account", "/cart", "/contact", "/search")):
                continue
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if any(key in params for key in ("page", "p", "paged", "seite", "start", "offset")):
                continue
            label = normalize_text(
                f"{_visible_text(anchor)} {parsed.path.replace('-', ' ').replace('_', ' ')}"
            )
            matched = sum(term in label for term in raw_terms)
            if not matched:
                continue
            # Prefer explicit category/menu links over incidental footer links.
            context = (
                " ".join(anchor.get("class") or [])
                + " "
                + " ".join(
                    parent.name or "" for parent in list(anchor.parents)[:3] if isinstance(parent, Tag)
                )
            )
            score = matched * 10 + (
                3 if any(word in context.lower() for word in ("nav", "menu", "category")) else 0
            )
            ranked.append((score, url))
            seen.add(url)
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [url for _, url in ranked[:16]]

    def _offer_from_listing_node(self, node: Tag, page_url: str) -> Offer | None:
        title = _first_text(
            node,
            (
                ".product-title",
                ".product-name",
                ".name",
                "h2",
                "h3",
                "h4",
                "a[title]",
                "a[aria-label]",
                "img[alt]",
            ),
        )
        link = _first_attr(
            node,
            ("a.product-link", ".product-title a", ".product-name a", "h2 a", "h3 a", "a[href]"),
            "href",
        )
        if not link:
            return None
        url = clean_url(link, page_url)
        if not url or url == page_url:
            return None
        parsed_url = urlparse(url)
        if parsed_url.netloc.lower() != urlparse(self.site.base_url).netloc.lower():
            return None
        lowered_path = parsed_url.path.lower()
        if any(token in lowered_path for token in ("/login", "/account", "/cart", "/contact")):
            return None
        if any(
            key in dict(parse_qsl(parsed_url.query, keep_blank_values=True))
            for key in ("page", "p", "paged", "seite")
        ):
            return None
        if not _plausible_title(title):
            anchor = node.select_one(f'a[href="{link}"]') or node.select_one("a[href]")
            if isinstance(anchor, Tag):
                title = " ".join(
                    str(anchor.get(attr) or "").strip()
                    for attr in ("title", "aria-label")
                    if anchor.get(attr)
                ) or _visible_text(anchor)
                if not _plausible_title(title):
                    image = anchor.select_one("img[alt]")
                    title = str(image.get("alt") or "") if image else title
        if not _plausible_title(title):
            return None

        text = _visible_text(node)
        price_text = _first_text(
            node,
            (
                ".current-price",
                ".special-price .price",
                ".product-price-and-shipping .price",
                ".product-price",
                ".price",
                ".amount",
                "[itemprop=price]",
            ),
        )
        price_node = node.select_one(
            '[itemprop="price"][content], meta[itemprop="price"], [data-price-amount], [data-price]'
        )
        if price_node:
            price_text = str(
                price_node.get("content")
                or price_node.get("data-price-amount")
                or price_node.get("data-price")
                or price_text
            )
        price, currency = (
            extract_price(price_text, self.site.currency_hint)
            if price_text
            else (None, self.site.currency_hint)
        )
        image = (
            _first_attr(node, ("img[data-src]",), "data-src")
            or _first_attr(node, ("img[data-original]",), "data-original")
            or _first_attr(node, ("img[src]",), "src")
        )
        reference = extract_reference(text)
        availability, availability_label = availability_from_text(text)
        return Offer(
            id=stable_id(self.site.id, url, reference or title),
            site_id=self.site.id,
            site_name=self.site.name,
            title=title,
            url=url,
            image_url=clean_url(image, self.site.base_url) if image else None,
            reference=reference,
            price=price,
            currency=currency,
            availability=availability,
            availability_label=availability_label,
            models=_models_from_text(text),
            raw_description=text[:1600],
            checked_at=datetime.now(timezone.utc).isoformat(),
            price_source="liste",
            availability_source="liste",
        )

    def _offers_from_product_anchors(self, soup: BeautifulSoup, page_url: str) -> list[Offer]:
        """Theme-independent fallback based on same-site product detail URLs."""
        host = urlparse(self.site.base_url).netloc.lower()
        offers: list[Offer] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            if not isinstance(anchor, Tag):
                continue
            url = clean_url(str(anchor.get("href") or ""), page_url)
            if urlparse(url).netloc.lower() != host or url in seen or not self._looks_like_product_url(url):
                continue
            seen.add(url)
            card: Tag = anchor
            for parent in anchor.parents:
                if not isinstance(parent, Tag):
                    continue
                if parent.name in {"article", "li"} or any(
                    token in " ".join(parent.get("class") or []).lower()
                    for token in ("product", "item", "thumbnail")
                ):
                    card = parent
                    break
                if parent.name in {"main", "body"}:
                    break
            offer = self._offer_from_listing_node(card, page_url)
            if offer is None:
                title = str(anchor.get("title") or anchor.get("aria-label") or "").strip() or _visible_text(
                    anchor
                )
                image = anchor.select_one("img[alt]")
                if not _plausible_title(title) and image:
                    title = str(image.get("alt") or "").strip()
                if not _plausible_title(title):
                    continue
                text = _visible_text(card)
                price, currency = extract_price(text, self.site.currency_hint)
                availability, availability_label = availability_from_text(text)
                image_url = None
                image_node = card.select_one("img[data-src], img[data-original], img[src]")
                if image_node:
                    raw_image = (
                        image_node.get("data-src") or image_node.get("data-original") or image_node.get("src")
                    )
                    image_url = clean_url(str(raw_image), self.site.base_url) if raw_image else None
                reference = extract_reference(text)
                offer = Offer(
                    id=stable_id(self.site.id, url, reference or title),
                    site_id=self.site.id,
                    site_name=self.site.name,
                    title=title,
                    url=url,
                    image_url=image_url,
                    reference=reference,
                    price=price,
                    currency=currency,
                    availability=availability,
                    availability_label=availability_label,
                    models=_models_from_text(text),
                    raw_description=text[:1600],
                    checked_at=datetime.now(timezone.utc).isoformat(),
                    price_source="liste:ancre",
                    availability_source="liste:ancre",
                )
            offers.append(offer)
        return self._deduplicate(offers)

    def _offers_from_html(self, soup: BeautifulSoup, page_url: str) -> list[Offer]:
        # Do not stop at the first CSS selector that merely matches DOM nodes.
        # A theme wrapper can match ``.product`` without containing any actual
        # product card. Parse every configured selector, retain valid detail
        # links, then run a URL-based fallback independent of theme classes.
        offers: list[Offer] = []
        seen_nodes: set[int] = set()
        for selector in (*self.site.product_selectors, "article", "li.product", "div.product"):
            for node in soup.select(selector):
                if not isinstance(node, Tag) or id(node) in seen_nodes:
                    continue
                seen_nodes.add(id(node))
                offer = self._offer_from_listing_node(node, page_url)
                if offer is not None:
                    offers.append(offer)
        offers.extend(self._offers_from_product_anchors(soup, page_url))
        return self._deduplicate(offers)

    def _pagination_urls(self, html: str, page_url: str) -> list[str]:
        """Return every explicit result-page link from a listing document.

        Supplier themes use standard pagination containers, numeric labels,
        query parameters, ``/page/2`` paths, or JTL suffixes such as ``_s2``.
        Detect all of them while refusing product/detail links.
        """
        if html.lstrip().startswith(("{", "[")):
            return []
        soup = BeautifulSoup(html, "html.parser")
        current_host = urlparse(page_url).netloc.lower()
        selectors = (
            'link[rel="next"][href]',
            'a[rel="next"][href]',
            "nav.pagination a[href]",
            ".pagination a[href]",
            ".pagination-wrapper a[href]",
            ".page-list a[href]",
            ".pages a[href]",
            ".pager a[href]",
            ".toolbar .pages a[href]",
            ".woocommerce-pagination a[href]",
            ".products-list-pagination a[href]",
        )
        nodes: list[Tag] = []
        seen_nodes: set[int] = set()
        for selector in selectors:
            for node in soup.select(selector):
                if isinstance(node, Tag) and id(node) not in seen_nodes:
                    nodes.append(node)
                    seen_nodes.add(id(node))

        next_words = {
            "next",
            "suivant",
            "weiter",
            "volgende",
            "nachste",
            "nachste seite",
            "page suivante",
            "older",
        }
        page_url_pattern = re.compile(
            r"(?:[?&](?:page|p|paged|pagenum|seite|start|offset)=\d+"
            r"|/page/\d+(?:/|$)|[_/-]s\d+(?:[/?#]|$))",
            re.IGNORECASE,
        )
        for node in soup.select("a[href]"):
            if not isinstance(node, Tag) or id(node) in seen_nodes:
                continue
            href = str(node.get("href") or "").strip()
            label = normalize_text(
                " ".join(
                    filter(
                        None,
                        (
                            _visible_text(node),
                            str(node.get("aria-label") or ""),
                            str(node.get("title") or ""),
                        ),
                    )
                )
            )
            candidate = clean_url(href, page_url) if href else ""
            page_label = bool(re.fullmatch(r"(?:page|seite)?\s*\d+", label))
            next_label = label in next_words or any(label.startswith(f"{word} ") for word in next_words)
            if (
                next_label
                or (page_label and page_url_pattern.search(candidate))
                or page_url_pattern.search(candidate)
            ):
                nodes.append(node)
                seen_nodes.add(id(node))

        urls: list[str] = []
        for node in nodes:
            href = str(node.get("href") or "").strip()
            if not href:
                continue
            url = clean_url(href, page_url)
            parsed = urlparse(url)
            lowered_path = parsed.path.lower()
            if parsed.netloc.lower() != current_host or url == page_url:
                continue
            if any(marker in lowered_path for marker in ("/details", "/product/", "/products/")):
                continue
            urls.append(url)
        return list(dict.fromkeys(urls))

    def _next_page(self, soup: BeautifulSoup, page_url: str) -> str | None:
        current_host = urlparse(page_url).netloc
        for selector in (
            'link[rel="next"]',
            'a[rel="next"]',
            ".next a",
            "a.next",
            ".pagination-next a",
            ".pages-item-next a",
            ".woocommerce-pagination .next",
        ):
            node = soup.select_one(selector)
            if node and node.get("href"):
                url = clean_url(str(node.get("href")), page_url)
                if urlparse(url).netloc == current_host:
                    return url
        return None

    @staticmethod
    def _deduplicate(offers: list[Offer]) -> list[Offer]:
        by_key: dict[tuple[str, str], Offer] = {}
        for offer in offers:
            key = (offer.site_id, offer.reference or f"{offer.url}|{normalize_text(offer.title)}")
            current = by_key.get(key)
            if current is None or (current.price is None and offer.price is not None):
                by_key[key] = offer
        return list(by_key.values())
