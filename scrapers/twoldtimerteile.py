#!/usr/bin/env python3
"""Récupère le catalogue Opel GT de TW-Oldtimerteile depuis les listes publiques.

Le parcours est volontairement limité aux pages de catégorie et à leur
pagination. Les fiches individuelles ``*.html`` ne sont jamais téléchargées :
leur URL, leur titre, leur prix, leur disponibilité et leur image sont lus
directement dans les cartes produit des listes.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper_common import ScrapeResult, run_legacy_scraper, scraper_cli

from catalog_progress import advance_phase, report_progress as publish_progress, start_phase
from scraper_common import BUNDLE_VERSION

VERSION = BUNDLE_VERSION
ROOT_URL = "https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/"
BASE_URL = "https://shop.tw-oldtimerteile.de/"
EXPECTED_CATEGORY_COUNT = 11
DEFAULT_OUTPUT = Path(__file__).resolve().with_name("twoldtimerteile.json")
DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT = 35.0
REQUEST_DELAY_SECONDS = 0.25

PRODUCT_CARD_SELECTORS = (
    ".productlist-viewmode-grid .product-container",
    ".productlist-viewmode-list .product-container",
    ".productlist-viewmode .product-container",
    ".product-listing .product-container",
    ".productlist .product-container",
    ".product-container",
    ".product-box",
    ".productlist-item",
    "article.product",
)
PRODUCT_LINK_SELECTORS = (
    ".title-description .title a[href]",
    ".title a[href]",
    ".product-name a[href]",
    ".product-title a[href]",
    "h2 a[href]",
    "h3 a[href]",
    ".product-image a[href]",
    "a[href]",
)
PRICE_SELECTORS = (
    ".current-price-container",
    ".current-price",
    ".product-price",
    ".price",
    "[class*='price']",
)
IMAGE_SELECTORS = (
    ".product-image img",
    "figure img",
    "img[itemprop='image']",
    "img",
)

_THREAD_LOCAL = threading.local()


class ScraperError(RuntimeError):
    """Erreur contrôlée du scraper TW-Oldtimerteile."""


@dataclass(frozen=True)
class Category:
    name: str
    url: str


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fold_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def normalized_url(url: str) -> str:
    parts = urlsplit(urljoin(BASE_URL, url))
    scheme = "https"
    host = (parts.hostname or "").casefold()
    if host == "www.shop.tw-oldtimerteile.de":
        host = "shop.tw-oldtimerteile.de"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    query = "&".join(
        f"{key}={value}"
        for key, value in sorted(parse_qsl(parts.query, keep_blank_values=True))
        if key.casefold() not in {"xoid", "gclid", "fbclid", "utm_source", "utm_medium", "utm_campaign"}
    )
    return urlunsplit((scheme, host, path, query, ""))


def _site_path(url: str) -> str:
    return re.sub(r"/{2,}", "/", urlsplit(normalized_url(url)).path or "/")


def is_product_url(url: str) -> bool:
    """Reconnaît une fiche sans l'ouvrir, y compris si son URL finit par ``/``."""

    parsed = urlsplit(normalized_url(url))
    if parsed.hostname != "shop.tw-oldtimerteile.de":
        return False
    root_path = _site_path(ROOT_URL)
    path = _site_path(url)
    if not path.startswith(root_path) or path == root_path:
        return False

    suffix = path[len(root_path) :].strip("/")
    segments = [segment for segment in suffix.split("/") if segment]
    filename = (segments[-1] if segments else "").casefold()
    if filename in {
        "index.html",
        "impressum.html",
        "kontakt.html",
        "datenschutz.html",
        "agb.html",
        "widerrufsrecht.html",
    }:
        return False

    # Une catégorie directe possède un unique segment et se termine par « / ».
    # Une fiche est soit un fichier HTML, soit un chemin situé sous une catégorie.
    return filename.endswith(".html") or len(segments) >= 2


def is_direct_category_url(url: str) -> bool:
    parsed = urlsplit(normalized_url(url))
    if parsed.hostname != "shop.tw-oldtimerteile.de" or parsed.query:
        return False
    root_path = _site_path(ROOT_URL)
    path = _site_path(url)
    if not path.startswith(root_path) or path == root_path or not path.endswith("/"):
        return False
    suffix = path[len(root_path) :].strip("/")
    return bool(suffix) and "/" not in suffix


def is_listing_url(url: str, category_url: str) -> bool:
    parsed = urlsplit(normalized_url(url))
    category = urlsplit(normalized_url(category_url))
    if parsed.hostname != "shop.tw-oldtimerteile.de" or parsed.path != category.path:
        return False
    if parsed.path.casefold().endswith(".html"):
        return False
    allowed_query_keys = {
        "page",
        "p",
        "sort",
        "view_mode",
        "listing_count",
        "filter_fv_id",
        "filter_id",
    }
    return all(key.casefold() in allowed_query_keys for key, _value in parse_qsl(parsed.query, keep_blank_values=True))


def is_excluded_category(category: Category) -> bool:
    marker = fold_text(f"{category.name} {urlsplit(category.url).path}")
    return (
        ("ich brauch" in marker and "ich will" in marker)
        or ("ich benotige" in marker and "ich will" in marker)
        or "j en ai besoin je le veux" in marker
    )


def discover_categories(root_html: str, page_url: str = ROOT_URL) -> list[Category]:
    """Compte et retourne les catégories Opel GT directement liées par la racine."""

    soup = BeautifulSoup(root_html, "html.parser")
    categories: list[Category] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        url = normalized_url(urljoin(page_url, str(anchor.get("href") or "")))
        if not is_direct_category_url(url) or url in seen:
            continue
        name = clean_text(anchor.get_text(" ", strip=True))
        if not name:
            image = anchor.select_one("img[alt], img[title]")
            if isinstance(image, Tag):
                name = clean_text(image.get("alt") or image.get("title"))
        if not name:
            name = clean_text(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
        categories.append(Category(name=name, url=url))
        seen.add(url)
    return categories


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,fr;q=0.7,en;q=0.5",
            "Cache-Control": "no-cache",
            "DNT": "1",
            "Referer": ROOT_URL,
        }
    )
    return session


def thread_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = make_session()
        _THREAD_LOCAL.session = session
    return session


def fetch_listing(url: str, timeout: float, category_url: str | None = None) -> tuple[str, str]:
    """Télécharge une racine/catégorie/pagination et refuse toute fiche produit."""

    absolute = normalized_url(url)
    if is_product_url(absolute):
        raise ScraperError(f"Consultation d'une fiche individuelle interdite : {absolute}")
    if category_url is None:
        if absolute != normalized_url(ROOT_URL):
            raise ScraperError(f"URL racine refusée : {absolute}")
    elif not is_listing_url(absolute, category_url):
        raise ScraperError(f"URL de liste refusée : {absolute}")

    response = thread_session().get(absolute, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    final_url = normalized_url(response.url)
    if is_product_url(final_url):
        raise ScraperError(f"Redirection inattendue vers une fiche produit : {final_url}")
    if category_url is not None and not is_listing_url(final_url, category_url):
        raise ScraperError(f"Redirection hors de la catégorie autorisée : {final_url}")
    content_type = response.headers.get("Content-Type", "").casefold()
    if "html" not in content_type and not response.text.lstrip().startswith("<"):
        raise ScraperError(f"Réponse non HTML pour {absolute}")
    low = response.text.casefold()
    if "cf-chl-" in low or ("just a moment" in low and "challenge" in low):
        raise ScraperError(f"Page de vérification anti-robot reçue pour {absolute}")
    if len(response.text) < 250:
        raise ScraperError(f"Réponse HTML anormalement courte pour {absolute}")
    if REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS)
    return response.text, final_url


def _inside_non_catalogue_area(node: Tag) -> bool:
    for parent in node.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in {"aside", "footer", "nav"}:
            return True
        marker = fold_text(f"{' '.join(parent.get('class', []))} {parent.get('id', '')}")
        if any(word in marker for word in ("bestseller", "recommend", "slider", "carousel", "footer", "sidebar")):
            return True
    return False


def _product_url_from_card(card: Tag, page_url: str) -> str:
    for selector in PRODUCT_LINK_SELECTORS:
        for anchor in card.select(selector):
            url = normalized_url(urljoin(page_url, str(anchor.get("href") or "")))
            if is_product_url(url):
                return url
    return ""


def _candidate_cards(soup: BeautifulSoup, page_url: str) -> list[Tag]:
    cards: list[Tag] = []
    seen_nodes: set[int] = set()
    for selector in PRODUCT_CARD_SELECTORS:
        for card in soup.select(selector):
            if not isinstance(card, Tag) or id(card) in seen_nodes or _inside_non_catalogue_area(card):
                continue
            if _product_url_from_card(card, page_url):
                cards.append(card)
                seen_nodes.add(id(card))
    if cards:
        return cards

    main = soup.select_one("main, #content, .main-inside, .content-wrapper") or soup
    price_hint = re.compile(r"\d[\d .]*(?:[,.]\d{1,2})?\s*(?:€|EUR)", re.IGNORECASE)
    for anchor in main.select("a[href]"):
        if not isinstance(anchor, Tag) or _inside_non_catalogue_area(anchor):
            continue
        url = normalized_url(urljoin(page_url, str(anchor.get("href") or "")))
        if not is_product_url(url):
            continue
        for parent in anchor.parents:
            if not isinstance(parent, Tag) or parent.name in {"main", "body", "html"}:
                break
            text = clean_text(parent.get_text(" ", strip=True))
            product_urls = {
                normalized_url(urljoin(page_url, str(link.get("href") or "")))
                for link in parent.select("a[href]")
                if is_product_url(urljoin(page_url, str(link.get("href") or "")))
            }
            if len(product_urls) == 1 and price_hint.search(text):
                if id(parent) not in seen_nodes:
                    cards.append(parent)
                    seen_nodes.add(id(parent))
                break
    return cards


def _product_name(card: Tag, product_url: str, page_url: str) -> str:
    candidates: list[tuple[int, int, str]] = []
    for priority, selector in enumerate(PRODUCT_LINK_SELECTORS):
        for anchor in card.select(selector):
            url = normalized_url(urljoin(page_url, str(anchor.get("href") or "")))
            if url != product_url:
                continue
            text = clean_text(anchor.get_text(" ", strip=True) or anchor.get("title"))
            if text and fold_text(text) not in {"mehr informationen", "details", "zum artikel"}:
                candidates.append((priority, -len(text), text))
    if candidates:
        candidates.sort()
        return candidates[0][2]
    for image in card.select("img[alt], img[title]"):
        text = clean_text(image.get("alt") or image.get("title"))
        if text and fold_text(text) not in {"produktbild", "artikelbild"}:
            return text
    return ""


def _decimal_price(value: str) -> Decimal:
    normalized = re.sub(r"[^0-9,.-]", "", value.replace("\xa0", " "))
    if not normalized:
        raise InvalidOperation
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif normalized.count(".") > 1:
        normalized = normalized.replace(".", "")
    return Decimal(normalized)


def _format_euro(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}".replace(".", ",") + "€"


def _price(card: Tag) -> str:
    pattern = re.compile(r"(?<!\d)(\d[\d .]*(?:[,.]\d{1,2})?)\s*(?:€|EUR)", re.IGNORECASE)
    nodes: Iterable[Tag] = []
    for selector in PRICE_SELECTORS:
        selected = [node for node in card.select(selector) if isinstance(node, Tag)]
        if selected:
            nodes = selected
            break
    if not nodes:
        nodes = [card]
    for node in nodes:
        for match in pattern.finditer(clean_text(node.get_text(" ", strip=True))):
            try:
                return _format_euro(_decimal_price(match.group(1)))
            except InvalidOperation:
                continue
    return "inconnu"


def _availability(card: Tag) -> str:
    text = fold_text(card.get_text(" ", strip=True))
    if any(marker in text for marker in ("auf anfrage", "preis auf anfrage", "nur auf anfrage")):
        return "sur demande"
    if any(
        marker in text
        for marker in (
            "nicht lieferbar",
            "nicht verfugbar",
            "ausverkauft",
            "vergriffen",
            "derzeit nicht erhaltlich",
        )
    ):
        return "en rupture de stock"
    if any(marker in text for marker in ("bald lieferbar", "wieder lieferbar", "im zulauf", "nachbestellt")):
        return "réapprovisionnement"
    if any(
        marker in text
        for marker in (
            "sofort lieferbar",
            "wenige exemplare auf lager",
            "auf lager",
            "in den warenkorb",
        )
    ):
        return "en stock"
    delivery = re.search(r"lieferzeit\s*(?:ca)?\s*(\d+)\s*(?:-|bis)?\s*(\d+)?\s*(tag|tage|woche|wochen)", text)
    if delivery:
        maximum = int(delivery.group(2) or delivery.group(1))
        return "réapprovisionnement" if "woch" in delivery.group(3) or maximum > 7 else "en stock"
    return "inconnu"


def _image_url(card: Tag, page_url: str) -> str:
    for selector in IMAGE_SELECTORS:
        for image in card.select(selector):
            for attribute in ("data-src", "data-original", "data-lazy-src", "src", "srcset"):
                raw = clean_text(image.get(attribute))
                if not raw or raw.startswith("data:image/"):
                    continue
                source = raw.split(",")[-1].strip().split()[0]
                url = normalized_url(urljoin(page_url, source))
                if not url.startswith("https://"):
                    continue
                low = url.casefold()
                if any(marker in low for marker in ("logo", "icon", "spinner", "pixel", "spacer", "placeholder")):
                    continue
                return url
    return "inconnu"


def parse_listing_page(page_html: str, page_url: str) -> list[dict[str, str]]:
    """Extrait les cartes d'une page de catégorie sans ouvrir leurs liens."""

    soup = BeautifulSoup(page_html, "html.parser")
    products: dict[str, dict[str, str]] = {}
    for card in _candidate_cards(soup, page_url):
        product_url = _product_url_from_card(card, page_url)
        if not product_url:
            continue
        name = _product_name(card, product_url, page_url)
        if not name:
            continue
        product = {
            "nom": name,
            "nom_traduit": name,
            "prix": _price(card),
            "disponibilite": _availability(card),
            "url_photo": _image_url(card, page_url),
            "url_fiche": product_url,
        }
        previous = products.get(product_url)
        if previous is None:
            products[product_url] = product
            continue
        for field in ("prix", "disponibilite", "url_photo"):
            if previous[field] == "inconnu" and product[field] != "inconnu":
                previous[field] = product[field]
    return list(products.values())


def pagination_urls(page_html: str, page_url: str, category_url: str) -> list[str]:
    soup = BeautifulSoup(page_html, "html.parser")
    urls: list[str] = []
    selectors = (
        ".pagination a[href]",
        ".page-navigation a[href]",
        "nav[aria-label*='pagination' i] a[href]",
        "a.page-link[href]",
        "a[href*='page=']",
        "a[href*='p=']",
    )
    for selector in selectors:
        for anchor in soup.select(selector):
            url = normalized_url(urljoin(page_url, str(anchor.get("href") or "")))
            if is_listing_url(url, category_url) and url != normalized_url(page_url):
                urls.append(url)
    return list(dict.fromkeys(urls))


def crawl_category(
    category: Category,
    timeout: float,
    fetcher: Callable[[str, float, str | None], tuple[str, str]] = fetch_listing,
) -> list[dict[str, str]]:
    queue = [normalized_url(category.url)]
    seen_pages: set[str] = set()
    products: dict[str, dict[str, str]] = {}
    completed_pages = 0
    while queue:
        requested = queue.pop(0)
        if requested in seen_pages:
            continue
        page_html, final_url = fetcher(requested, timeout, category.url)
        seen_pages.add(requested)
        seen_pages.add(final_url)
        for product in parse_listing_page(page_html, final_url):
            previous = products.get(product["url_fiche"])
            if previous is None:
                products[product["url_fiche"]] = product
            else:
                for field in ("prix", "disponibilite", "url_photo"):
                    if previous[field] == "inconnu" and product[field] != "inconnu":
                        previous[field] = product[field]
        for next_url in pagination_urls(page_html, final_url, category.url):
            if next_url not in seen_pages and next_url not in queue:
                queue.append(next_url)
        completed_pages += 1
        advance_phase(
            "categories", unit=category.url, completed=completed_pages,
            unit_total=completed_pages + len(queue),
            message=f"TW-Oldtimerteile : {category.name}, {completed_pages} page(s) traitée(s).",
        )
    return list(products.values())


def translate_to_french(title: str, timeout: float) -> str:
    """Traduit le titre sans jamais consulter la fiche du produit."""

    title = clean_text(title)
    if not title:
        return title
    try:
        response = thread_session().get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "de", "tl": "fr", "dt": "t", "q": title},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        translated = clean_text("".join(part[0] for part in payload[0] if part and part[0]))
        return translated or title
    except Exception:
        return title


def _translate_catalogue(products: list[dict[str, str]], workers: int, timeout: float) -> None:
    titles = list(dict.fromkeys(product["nom"] for product in products))
    start_phase("translations", 75, 94, len(titles), "Désignations traitées")
    translations: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(titles) or 1))) as executor:
        futures = {executor.submit(translate_to_french, title, timeout): title for title in titles}
        for future in as_completed(futures):
            title = futures[future]
            try:
                translations[title] = clean_text(future.result()) or title
            except Exception:
                translations[title] = title
            advance_phase("translations")
    for product in products:
        product["nom_traduit"] = translations.get(product["nom"], product["nom"])


def scrape_catalogue(output: Path, workers: int, timeout: float) -> list[dict[str, str]]:
    root_html, root_final_url = fetch_listing(ROOT_URL, timeout, None)
    categories = discover_categories(root_html, root_final_url)
    print(f"TW-Oldtimerteile : {len(categories)} catégorie(s) Opel GT détectée(s).")
    if len(categories) != EXPECTED_CATEGORY_COUNT:
        print(
            f"AVERTISSEMENT : {EXPECTED_CATEGORY_COUNT} catégories étaient attendues, "
            f"{len(categories)} ont été détectées."
        )
    if not categories:
        raise ScraperError("Aucune catégorie Opel GT détectée sur la page racine.")

    excluded = [category for category in categories if is_excluded_category(category)]
    selected = [category for category in categories if not is_excluded_category(category)]
    for category in excluded:
        print(f"TW-Oldtimerteile : catégorie ignorée sans inspection : {category.name}")
    if not selected:
        raise ScraperError("Toutes les catégories détectées ont été exclues.")

    products: dict[str, dict[str, str]] = {}
    start_phase("categories", 10, 75, len(selected), "Catégories et pages traitées")
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(selected)))) as executor:
        futures = {executor.submit(crawl_category, category, timeout): category for category in selected}
        for future in as_completed(futures):
            category = futures[future]
            category_products = future.result()
            advance_phase("categories", unit=category.url, completed=1, unit_total=1)
            print(f"TW-Oldtimerteile : {category.name} : {len(category_products)} pièce(s).")
            for product in category_products:
                previous = products.get(product["url_fiche"])
                if previous is None:
                    products[product["url_fiche"]] = product
                else:
                    for field in ("prix", "disponibilite", "url_photo"):
                        if previous[field] == "inconnu" and product[field] != "inconnu":
                            previous[field] = product[field]

    catalogue = list(products.values())
    if not catalogue:
        raise ScraperError("Aucune pièce extraite depuis les catégories autorisées.")
    _translate_catalogue(catalogue, workers, timeout)
    catalogue.sort(key=lambda item: (fold_text(item["nom_traduit"]), item["url_fiche"]))

    output.parent.mkdir(parents=True, exist_ok=True)
    publish_progress(95, "TW-Oldtimerteile : écriture du catalogue.")
    output.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return catalogue


def _run(output: Path, workers: int | None, timeout: float | None) -> object:
    return scrape_catalogue(
        output,
        max(1, workers or DEFAULT_WORKERS),
        max(1.0, timeout or DEFAULT_TIMEOUT),
    )


def scrape(
    output: str | Path | None = None,
    workers: int | None = None,
    timeout: float | None = None,
    status_file: str | Path | None = None,
    quiet: bool = False,
) -> ScrapeResult:
    out = Path(output) if output is not None else DEFAULT_OUTPUT
    status = Path(status_file) if status_file is not None else out.with_suffix(".status.json")
    return run_legacy_scraper(
        supplier="TW-Oldtimerteile",
        language="de",
        output_path=out,
        status_path=status,
        legacy_callable=_run,
        workers=workers,
        timeout=timeout,
        quiet=quiet,
    )


def main() -> int:
    return scraper_cli(
        supplier="TW-Oldtimerteile",
        version=VERSION,
        default_output=DEFAULT_OUTPUT,
        scrape_func=scrape,
    )


if __name__ == "__main__":
    raise SystemExit(main())
