#!/usr/bin/env python3
"""Récupère le catalogue Opel GT d'Edelschmiede dans edelschmiede.json.

Dépendances :
    python -m pip install requests beautifulsoup4

Le script n'utilise ni navigateur, ni Selenium, ni Playwright. Il détermine
le nombre de pages avant de traiter les pages indépendamment et en parallèle.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup, Tag
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as exc:
    raise SystemExit(
        "Dépendances manquantes. Exécutez : "
        "python -m pip install requests beautifulsoup4"
    ) from exc

from catalog_progress import report_progress as publish_progress, start_phase
from scraper_common import BUNDLE_VERSION

ROOT_URL = "https://www.edelschmiede.com/GT_1"
OUTPUT_FILE = Path(__file__).with_name("edelschmiede.json")
TIMEOUT = (5, 18)
MAX_WORKERS = 2
_PROGRESS_LOCK = threading.RLock()
_completed_items = 0
_expected_items = 0
_progress_percent = 5
_detail_failures = 0
_details_unavailable = threading.Event()


def report_progress(percent: int, message: str) -> None:
    """Publish real work counters independently of captured legacy stdout."""
    global _progress_percent
    with _PROGRESS_LOCK:
        _progress_percent = max(_progress_percent, min(99, int(percent)))
        publish_progress(_progress_percent, message)


def item_completed() -> None:
    global _completed_items
    with _PROGRESS_LOCK:
        _completed_items += 1
        percent = 10 + 75 * _completed_items // max(1, _expected_items)
        report_progress(percent, f"Edelschmiede : {_completed_items}/{_expected_items} pièces traitées.")

FIELDS = (
    "nom",
    "nom_traduit",
    "prix",
    "disponibilite",
    "url_photo",
    "url_fiche",
)
AVAILABILITIES = {
    "en stock",
    "en rupture de stock",
    "réapprovisionnement",
    "sur demande",
    "inconnu",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9,de;q=0.8,fr;q=0.6",
}
PRICE_RE = re.compile(
    r"^(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}€$|^inconnu$"
)


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalized(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def make_session(cookies: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        backoff_factor=0.7,
        status_forcelist=(408, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        # A remote Retry-After must not suspend every product for hours.
        # Access restrictions (403/429) fail immediately, without retries.
        respect_retry_after_header=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    if cookies:
        session.cookies.update(cookies)
    return session


def fetch(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def euro_is_displayed(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    scope = find_product_list(soup) or soup
    return bool(re.search(r"\d[\d.\s\u00a0\u202f]*,\d{2}\s*€", scope.get_text(" ")))


def select_euro(session: requests.Session, html: str) -> str:
    """Sélectionne EUR si un sélecteur de devise est présent."""
    if euro_is_displayed(html):
        return html

    soup = BeautifulSoup(html, "html.parser")
    for select in soup.select("select[name]"):
        marker = normalized(
            f"{select.get('name', '')} {select.get('id', '')} "
            f"{' '.join(select.get('class', []))}"
        )
        options = select.select("option")
        eur = next(
            (
                option
                for option in options
                if re.search(
                    r"(?:\bEUR\b|€|\beuro\b)",
                    f"{option.get_text(' ', strip=True)} {option.get('value', '')}",
                    re.I,
                )
            ),
            None,
        )
        if eur is None or not re.search(r"currency|waehrung|devise", marker):
            continue

        form = select.find_parent("form")
        if not isinstance(form, Tag):
            continue
        data: dict[str, str] = {}
        for field in form.select("input[name], select[name]"):
            name = field.get("name")
            if not name:
                continue
            if field.name == "select":
                chosen = field.select_one("option[selected]") or field.select_one("option")
                data[name] = chosen.get("value", "") if chosen else ""
            elif field.get("type", "").lower() not in {"submit", "button", "image"}:
                data[name] = field.get("value", "")
        data[select["name"]] = eur.get("value", "EUR")
        action = urljoin(ROOT_URL, form.get("action") or ROOT_URL)
        method = (form.get("method") or "get").lower()
        response = (
            session.post(action, data=data, timeout=TIMEOUT)
            if method == "post"
            else session.get(action, params=data, timeout=TIMEOUT)
        )
        response.raise_for_status()
        refreshed = fetch(session, ROOT_URL)
        if euro_is_displayed(refreshed):
            return refreshed

    for link in soup.select("a[href]"):
        marker = f"{link.get_text(' ', strip=True)} {link.get('href', '')}"
        if re.search(r"(?:\bEUR\b|€|currency[^\s]*=EUR)", marker, re.I):
            session.get(urljoin(ROOT_URL, link["href"]), timeout=TIMEOUT).raise_for_status()
            refreshed = fetch(session, ROOT_URL)
            if euro_is_displayed(refreshed):
                return refreshed
    return html


def find_product_list(soup: BeautifulSoup) -> Tag | None:
    selectors = (
        "#product-list",
        "#product-list-container",
        "#result-wrapper",
        ".product-list",
        ".productlist",
        ".product-listing",
        "[data-page='product-list']",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return None


def product_cards(soup: BeautifulSoup) -> list[Tag]:
    scope: Tag | BeautifulSoup = find_product_list(soup) or soup
    selectors = (
        ".product-wrapper",
        "article.productbox",
        "div.productbox",
        ".product-box",
        "article[itemtype*='Product']",
    )
    for selector in selectors:
        cards = [node for node in scope.select(selector) if isinstance(node, Tag)]
        usable = [card for card in cards if product_link(card) is not None]
        if usable:
            return usable
    return []


def product_link(card: Tag) -> Tag | None:
    selectors = (
        "a.productbox-title[href]",
        ".productbox-title a[href]",
        "a[itemprop='url'][href]",
        "h2 a[href]",
        "h3 a[href]",
        "a[href][title]",
    )
    for selector in selectors:
        node = card.select_one(selector)
        if not isinstance(node, Tag):
            continue
        name = clean(node.get("title")) or clean(node.get_text(" ", strip=True))
        if name and node.get("href"):
            return node
    return None


def pagination_information(html: str) -> tuple[int, int]:
    """Retourne d'abord le nombre de pages et le total annoncé."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))

    match = re.search(
        r"(?:Items?|Artikel)\s+(\d+)\s*[-–]\s*(\d+)\s+(?:of|von)\s+(\d+)",
        page_text,
        re.I,
    )
    if match:
        start, end, total = map(int, match.groups())
        per_page = max(1, end - start + 1)
        return math.ceil(total / per_page), total

    pages = {1}
    for link in soup.select("a[href]"):
        href = urljoin(ROOT_URL, link.get("href", ""))
        for value in re.findall(r"_s(\d+)(?:\D|$)", href):
            pages.add(int(value))
        for value in parse_qs(urlparse(href).query).get("page", []):
            if value.isdigit():
                pages.add(int(value))
        label = clean(link.get_text(" ", strip=True))
        if label.isdigit():
            pages.add(int(label))

    cards = product_cards(soup)
    total_match = re.search(r"(?:of|von)\s+(\d+)\b", page_text, re.I)
    total = int(total_match.group(1)) if total_match else 0
    if total and cards:
        pages.add(math.ceil(total / len(cards)))
    if not pages or (max(pages) == 1 and not cards):
        raise RuntimeError("Impossible de déterminer la pagination du catalogue.")
    if not total:
        raise RuntimeError("Impossible de déterminer le nombre total de pièces.")
    return max(pages), total


def page_url(page: int) -> str:
    return ROOT_URL if page == 1 else f"{ROOT_URL}_s{page}"


def decimal_value(raw: str) -> Decimal | None:
    value = re.sub(r"[\s\u00a0\u202f]", "", raw)
    if "," in value and "." in value:
        decimal_separator = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if decimal_separator == "," else ",", "")
        value = value.replace(decimal_separator, ".")
    else:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def currency_code(text: str) -> str | None:
    upper = text.upper()
    if "€" in text or re.search(r"\bEUR\b", upper):
        return "EUR"
    if "£" in text or re.search(r"\bGBP\b", upper):
        return "GBP"
    if "$" in text and not re.search(r"\b(?:CAD|AUD)\b", upper):
        return "USD"
    for code in ("USD", "CHF", "CAD", "AUD", "SEK", "NOK", "DKK", "PLN", "CZK"):
        if re.search(rf"\b{code}\b", upper):
            return code
    return None


@lru_cache(maxsize=None)
def eur_rate(code: str) -> Decimal:
    if code == "EUR":
        return Decimal("1")
    response = requests.get(
        "https://api.frankfurter.app/latest",
        params={"from": code, "to": "EUR"},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return Decimal(str(response.json()["rates"]["EUR"]))


def format_price(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, decimals = f"{amount:.2f}".split(".")
    groups = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    return ".".join(reversed(groups)) + "," + decimals + "€"


def price_from_text(text: str) -> str:
    if re.search(r"preis\s+auf\s+anfrage|price\s+on\s+request", normalized(text)):
        return "inconnu"
    match = re.search(
        r"(?<!\d)(\d{1,3}(?:[.\s\u00a0\u202f]\d{3})*|\d+)"
        r"(?:[,.](\d{1,2}))?\s*(€|EUR|CHF|GBP|USD|CAD|AUD|SEK|NOK|DKK|PLN|CZK|£|\$)",
        text,
        re.I,
    )
    if not match:
        return "inconnu"
    raw_amount = match.group(1) + (("," + match.group(2)) if match.group(2) else "")
    amount = decimal_value(raw_amount)
    code = currency_code(match.group(0))
    if amount is None or code is None:
        return "inconnu"
    try:
        return format_price(amount * eur_rate(code))
    except (requests.RequestException, KeyError, ValueError, InvalidOperation):
        return "inconnu"


def price_from_container(
    container: Tag | BeautifulSoup, *, strict: bool = False
) -> str:
    selectors = (
        "[itemprop='price']",
        ".price_wrapper",
        ".productbox-price",
        ".price",
        ".current-price",
    )
    for selector in selectors:
        for node in container.select(selector):
            raw = clean(
                " ".join(
                    part
                    for part in (
                        node.get_text(" ", strip=True),
                        node.get("content"),
                    )
                    if part
                )
            )
            if re.search(r"preis\s+auf\s+anfrage|price\s+on\s+request", normalized(raw)):
                return "inconnu"
            value = price_from_text(raw)
            if value != "inconnu":
                return value
    if strict:
        return "inconnu"
    return price_from_text(clean(container.get_text(" ", strip=True)))


def image_from_container(container: Tag | BeautifulSoup, base_url: str) -> str:
    meta = container.select_one("meta[property='og:image'][content]")
    if isinstance(meta, Tag) and clean(meta.get("content")):
        return urljoin(base_url, meta["content"])

    candidates = container.select(
        ".product-gallery img, .product-detail img[itemprop='image'], "
        ".productbox-image img, a.productbox-image img, picture img, img[itemprop='image'], img"
    )
    for image in candidates:
        for attr in (
            "data-full-size-image-url",
            "data-zoom-image",
            "data-src",
            "data-lazy-src",
            "data-original",
            "src",
        ):
            value = clean(image.get(attr))
            if value and not value.startswith("data:") and "kein-bild" not in value.lower():
                return urljoin(base_url, value)
        for attr in ("data-srcset", "srcset"):
            srcset = clean(image.get(attr))
            if srcset:
                urls = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
                if urls:
                    return urljoin(base_url, urls[-1])
    for source in container.select("picture source[data-srcset], picture source[srcset]"):
        srcset = clean(source.get("data-srcset") or source.get("srcset"))
        urls = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        if urls:
            return urljoin(base_url, urls[-1])
    return "inconnu"


def availability_from_page(soup: BeautifulSoup) -> str:
    scope: Tag | BeautifulSoup = soup
    for selector in (
        "#product-offer",
        "#product-detail",
        ".product-detail",
        "[itemtype*='Product']",
        "main",
    ):
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            scope = node
            break
    text = normalized(scope.get_text(" ", strip=True))

    for node in scope.select("link[itemprop='availability'][href], meta[itemprop='availability'][content]"):
        text += " " + normalized(node.get("href") or node.get("content"))

    if re.search(r"preis auf anfrage|price on request|sur demande", text):
        return "sur demande"
    if re.search(
        r"voraussichtlich lieferbar|wieder lieferbar|nachliefer|nachbestell|"
        r"back[ -]?order|restock|re-stock|pre[- ]?order|vorbestell|"
        r"lieferzeit\s*:\s*\d+(?:\s*[-–]\s*\d+)?\s*(?:woche|wochen|monat|monate)|"
        r"delivery time\s*:\s*\d+(?:\s*[-–]\s*\d+)?\s*(?:week|weeks|month|months)",
        text,
    ):
        return "réapprovisionnement"
    if re.search(
        r"artikel zurzeit vergriffen|zurzeit vergriffen|nicht lieferbar|"
        r"nicht verfugbar|ausverkauft|out of stock|sold out|currently unavailable|"
        r"benachrichtigen, wenn verfugbar",
        text,
    ):
        return "en rupture de stock"
    if re.search(
        r"lieferzeit\s*:\s*\d|delivery time\s*:\s*\d|sofort lieferbar|"
        r"auf lager|lagernd|in stock|instock",
        text,
    ):
        return "en stock"
    if scope.select_one(
        "button[name='inWarenkorb'], input[name='inWarenkorb'], "
        "button[name='add-to-cart'], .add-to-cart, [data-button-action='add-to-cart']"
    ):
        return "en stock"
    return "inconnu"


def listing_item(card: Tag, listing_url: str) -> dict[str, str] | None:
    link = product_link(card)
    if link is None:
        return None
    name = clean(link.get("title")) or clean(link.get_text(" ", strip=True))
    detail_url = urljoin(listing_url, link.get("href", ""))
    if not name or not detail_url.startswith(("http://", "https://")):
        return None

    return {
        "nom": name,
        "nom_traduit": "",
        "prix": price_from_container(card),
        "disponibilite": availability_from_page(card),
        "url_photo": image_from_container(card, listing_url),
        "url_fiche": detail_url,
    }


def enrich_item(session: requests.Session, item: dict[str, str]) -> dict[str, str]:
    global _detail_failures
    if _details_unavailable.is_set():
        return item
    try:
        html = fetch(session, item["url_fiche"])
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.select_one("link[rel='canonical'][href]")
        if isinstance(canonical, Tag):
            item["url_fiche"] = urljoin(item["url_fiche"], canonical["href"])

        name_node = soup.select_one("h1[itemprop='name'], h1.product-title, main h1, h1")
        if isinstance(name_node, Tag) and clean(name_node.get_text(" ", strip=True)):
            item["nom"] = clean(name_node.get_text(" ", strip=True))

        if item["prix"] == "inconnu":
            detail_scope: Tag | BeautifulSoup = soup
            for selector in ("#product-offer", "#product-detail", ".product-detail", "main"):
                node = soup.select_one(selector)
                if isinstance(node, Tag):
                    detail_scope = node
                    break
            item["prix"] = price_from_container(detail_scope, strict=True)

        photo = image_from_container(soup, item["url_fiche"])
        if photo != "inconnu":
            item["url_photo"] = photo
        availability = availability_from_page(soup)
        if availability != "inconnu":
            item["disponibilite"] = availability
        with _PROGRESS_LOCK:
            _detail_failures = 0
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
        with _PROGRESS_LOCK:
            _detail_failures += 1
            if code in {403, 429} or _detail_failures >= 2:
                _details_unavailable.set()
        print(f"Avertissement : fiche non récupérée {item['url_fiche']} ({exc})", file=sys.stderr)
    return item


def scrape_page(job: tuple[int, dict[str, str]], initial_html: str | None = None) -> tuple[int, list[dict[str, str]]]:
    page, cookies = job
    url = page_url(page)
    with make_session(cookies) as session:
        soup = BeautifulSoup(initial_html if initial_html is not None else fetch(session, url), "html.parser")
        cards = product_cards(soup)
        if not cards:
            raise RuntimeError(f"Aucune pièce trouvée sur la page {page}: {url}")

        items: list[dict[str, str]] = []
        for card in cards:
            item = listing_item(card, url)
            if item is not None:
                items.append(enrich_item(session, item))
                item_completed()
    if not items:
        raise RuntimeError(f"Aucune pièce exploitable sur la page {page}: {url}")
    return page, items


def translate_items(items: list[dict[str, str]]) -> None:
    from catalog_translation import translate_names
    start_phase("translations", 90, 94, 0, "Désignations traitées")

    cache_root = Path(os.getenv("EDELSCHMIEDE_CACHE_DIR", str(
        Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "entraide-opel-gt" / "edelschmiede"
    )))
    translations = translate_names(
        [item["nom"] for item in items], language="auto",
        cache_file=cache_root / "edelschmiede_translations.json",
        previous_output=Path(os.getenv("CATALOG_PREVIOUS_OUTPUT", str(OUTPUT_FILE))),
        workers=MAX_WORKERS,
    )
    for item in items:
        item["nom_traduit"] = translations[item["nom"]]


def validate(items: list[dict[str, Any]], expected_total: int) -> None:
    if len(items) != expected_total:
        raise ValueError(
            f"Catalogue incomplet : {len(items)} pièces récupérées, "
            f"{expected_total} annoncées par le site."
        )

    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if tuple(item.keys()) != FIELDS:
            raise ValueError(f"Élément {index}: champs invalides ou mal ordonnés.")
        if not all(isinstance(item[field], str) and item[field].strip() for field in FIELDS):
            raise ValueError(f"Élément {index}: un champ est vide ou n'est pas une chaîne.")
        if item["disponibilite"] not in AVAILABILITIES:
            raise ValueError(f"Élément {index}: disponibilité invalide.")
        if not PRICE_RE.fullmatch(item["prix"]):
            raise ValueError(f"Élément {index}: prix invalide {item['prix']!r}.")
        if not item["url_fiche"].startswith(("http://", "https://")):
            raise ValueError(f"Élément {index}: URL de fiche invalide.")
        if item["url_photo"] != "inconnu" and not item["url_photo"].startswith(("http://", "https://")):
            raise ValueError(f"Élément {index}: URL de photo invalide.")
        if item["url_fiche"] in seen:
            raise ValueError(f"Élément {index}: fiche dupliquée {item['url_fiche']}.")
        seen.add(item["url_fiche"])


def atomic_write_json(items: list[dict[str, str]]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=OUTPUT_FILE.stem + "-", suffix=".json", dir=OUTPUT_FILE.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(items, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, OUTPUT_FILE)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def main() -> None:
    global _completed_items, _expected_items, _progress_percent, _detail_failures
    _completed_items = _expected_items = _detail_failures = 0
    _progress_percent = 5
    _details_unavailable.clear()
    started = time.monotonic()
    report_progress(6, "Edelschmiede : lecture de la première page du catalogue.")
    with make_session() as session:
        first_html = fetch(session, ROOT_URL)
        first_html = select_euro(session, first_html)
        cookies = requests.utils.dict_from_cookiejar(session.cookies)

    page_count, expected_total = pagination_information(first_html)
    _expected_items = expected_total
    workers = min(MAX_WORKERS, page_count)
    report_progress(10, f"Edelschmiede : {expected_total} pièces, {page_count} pages à traiter.")
    print(
        f"Catalogue annoncé : {expected_total} pièces sur {page_count} pages. "
        f"Traitement avec {workers} requêtes simultanées au maximum."
    )

    pages: dict[int, list[dict[str, str]]] = {}
    jobs = [(page, cookies) for page in range(1, page_count + 1)]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(scrape_page, job, first_html if job[0] == 1 else None): job[0]
            for job in jobs
        }
        for future in as_completed(futures):
            page, items = future.result()
            pages[page] = items
            print(f"Page {page}/{page_count} : {len(items)} pièces")

    items = [item for page in range(1, page_count + 1) for item in pages[page]]

    # Déduplication conservatrice avant le contrôle strict du total.
    unique: dict[str, dict[str, str]] = {}
    for item in items:
        unique.setdefault(item["url_fiche"], item)
    items = list(unique.values())

    report_progress(90, "Edelschmiede : réutilisation et complément des traductions.")
    translate_items(items)
    report_progress(95, "Edelschmiede : validation du catalogue complet.")
    validate(items, expected_total)
    atomic_write_json(items)
    report_progress(99, f"Edelschmiede : {len(items)} pièces récupérées ; contrôle final du catalogue.")

    elapsed = time.monotonic() - started
    print(f"{len(items)} pièces validées et écrites dans {OUTPUT_FILE} en {elapsed:.1f} s.")


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import ScrapeResult as ScrapeResult, run_legacy_scraper as _run_legacy_scraper, scraper_cli as _scraper_cli

_LEGACY_MAIN = main
_SUPPLIER_NAME = 'Edelschmiede'
_SUPPLIER_LANG = 'de'
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name('edelschmiede.json')
_HARMONIZED_VERSION = BUNDLE_VERSION


def _set_legacy_output(output: _ScraperPath) -> None:
    """Adapte les constantes de sortie historiques sans changer le parsing."""
    global OUTPUT_FILE, OUTPUT, FICHIER_SORTIE
    if "OUTPUT_FILE" in globals():
        OUTPUT_FILE = output
    if "OUTPUT" in globals():
        OUTPUT = output
    if "FICHIER_SORTIE" in globals():
        FICHIER_SORTIE = str(output)


def _run_legacy(output: _ScraperPath, workers: int | None, timeout: float | None) -> object:
    global MAX_WORKERS, TIMEOUT
    _set_legacy_output(output)
    old_argv = _scraper_sys.argv[:]
    previous_workers, previous_timeout = MAX_WORKERS, TIMEOUT
    if workers is not None:
        MAX_WORKERS = max(1, min(4, int(workers)))
    if timeout is not None:
        value = max(0.1, float(timeout))
        TIMEOUT = (min(5.0, value), value)
    # Les anciens scripts avaient des interfaces CLI hétérogènes. Pour garantir
    # une entrée homogène, on neutralise leurs argparse et on pilote les constantes.
    _scraper_sys.argv = [old_argv[0]]
    try:
        return _LEGACY_MAIN()
    finally:
        _scraper_sys.argv = old_argv
        MAX_WORKERS, TIMEOUT = previous_workers, previous_timeout


def scrape(
    output: str | _ScraperPath | None = None,
    workers: int | None = None,
    timeout: float | None = None,
    status_file: str | _ScraperPath | None = None,
    quiet: bool = False,
) -> ScrapeResult:
    """Point d'entrée homogène attendu par le bundle.

    Retourne toujours un ScrapeResult. En cas de site down, maintenance ou
    congés fournisseur, aucune exception n'est propagée et l'ancien JSON n'est
    pas écrasé.
    """
    out = _ScraperPath(output) if output is not None else _DEFAULT_OUTPUT
    status = _ScraperPath(status_file) if status_file is not None else out.with_suffix(".status.json")
    return _run_legacy_scraper(
        supplier=_SUPPLIER_NAME,
        language=_SUPPLIER_LANG,
        output_path=out,
        status_path=status,
        legacy_callable=_run_legacy,
        workers=workers,
        timeout=timeout,
        quiet=quiet,
    )


def main() -> int:
    return _scraper_cli(
        supplier=_SUPPLIER_NAME,
        version=_HARMONIZED_VERSION,
        default_output=_DEFAULT_OUTPUT,
        scrape_func=scrape,
    )


if __name__ == "__main__":
    raise SystemExit(main())
