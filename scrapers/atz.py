#!/usr/bin/env python3
"""Extrait le catalogue ATZ Opel GT depuis les pages de liste autorisées.

Le catalogue principal provient de la recherche exacte ``"opel gt"``. Il est
complété par la catégorie Opel GT / Getrag 5 vitesses, car certaines pièces
compatibles (notamment le ``Kupplungszug``) n'incluent pas « Opel GT » dans
leur titre et sont donc absentes de la recherche textuelle du fournisseur.

Aucune fiche individuelle ``/p/.../`` n'est consultée.

Dépendances :
    python -m pip install requests beautifulsoup4
"""

from __future__ import annotations

import html
import json
import math
import os
import random
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from catalog_progress import advance_phase, report_progress as publish_progress, start_phase
from scraper_common import BUNDLE_VERSION

VERSION = BUNDLE_VERSION
ROOT_URL = "https://atz-online.com/?s=%22opel+gt%22&post_type=product"
BASE_URL = "https://atz-online.com/"
SUPPLEMENTAL_CATEGORY_URLS = (
    "https://atz-online.com/pk/opel-gt/getriebe-getrag-5-gang-typ-240/?orderby=price",
)
OUTPUT_FILE = Path(__file__).resolve().with_name("atz.json")
TIMEOUT = 50
MAX_WORKERS = 3  # Le serveur renvoie parfois des 500 au-delà.
PARALLEL_ATTEMPTS = 4
SEQUENTIAL_ATTEMPTS = 7

TRANSLATION_WORKERS = 2

FIELDS = (
    "nom",
    "nom_traduit",
    "prix",
    "disponibilite",
    "url_photo",
    "url_fiche",
)
VALID_AVAILABILITIES = {
    "en stock",
    "en rupture de stock",
    "réapprovisionnement",
    "sur demande",
    "inconnu",
}

_thread_local = threading.local()
_shared_cookies: dict[str, str] = {}
_shared_lock = threading.Lock()
_http_attempts = 0
_requested_urls: list[str] = []


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def make_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=2,
            connect=2,
            read=2,
            status=0,
            backoff_factor=0.4,
            allowed_methods=frozenset({"GET"}),
        ),
        pool_connections=4,
        pool_maxsize=4,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
        }
    )
    with _shared_lock:
        session.cookies.update(_shared_cookies)
    return session


def session_for_thread() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = make_session()
        _thread_local.session = session
    return session


def catalogue_url(page_number: int) -> str:
    if page_number == 1:
        return ROOT_URL
    query = quote_plus('"opel gt"')
    return f"https://atz-online.com/page/{page_number}/?post_type=product&s={query}"


def is_catalogue_url(url: str, expected_page: int | None = None) -> bool:
    """Autorise uniquement / ou /page/N/ avec la recherche imposée."""
    parts = urlsplit(urljoin(BASE_URL, url))
    if parts.scheme != "https" or parts.netloc.lower() not in {
        "atz-online.com",
        "www.atz-online.com",
    }:
        return False

    query = parse_qs(parts.query)
    if query.get("post_type") != ["product"] or query.get("s") != ['"opel gt"']:
        return False

    path = re.sub(r"/+", "/", parts.path)
    if path == "/":
        page = 1
    else:
        match = re.fullmatch(r"/page/(\d+)/", path)
        if not match:
            return False
        page = int(match.group(1))
    return expected_page is None or page == expected_page


def is_supplemental_category_url(url: str) -> bool:
    """Allow only the explicit Opel GT category required to complete ATZ."""

    parts = urlsplit(urljoin(BASE_URL, url))
    if parts.scheme != "https" or parts.netloc.lower() not in {
        "atz-online.com",
        "www.atz-online.com",
    }:
        return False
    path = re.sub(r"/+", "/", parts.path)
    if path != "/pk/opel-gt/getriebe-getrag-5-gang-typ-240/":
        return False
    query = parse_qs(parts.query)
    return not query or query == {"orderby": ["price"]}


def fetch_supplemental_category(url: str, attempts: int) -> str:
    """Fetch one explicitly allowed Opel GT category, never a product page."""

    global _http_attempts
    if url not in SUPPLEMENTAL_CATEGORY_URLS or not is_supplemental_category_url(url):
        raise RuntimeError(f"URL de catégorie complémentaire refusée : {url}")
    if "/p/" in urlsplit(url).path:
        raise RuntimeError(f"Tentative interdite de lecture d'une fiche : {url}")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        session = session_for_thread()
        with _shared_lock:
            session.cookies.update(_shared_cookies)
            _http_attempts += 1
        try:
            response = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
                headers={"Referer": ROOT_URL},
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = RuntimeError(f"HTTP {response.status_code}")
                if attempt < attempts:
                    time.sleep(min(1.2 * (2 ** (attempt - 1)), 15.0) + random.uniform(0.15, 0.55))
                    continue
                break
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", "").lower():
                raise RuntimeError("réponse non HTML")
            response.encoding = response.apparent_encoding or response.encoding
            with _shared_lock:
                _shared_cookies.update(session.cookies.get_dict())
                _requested_urls.append(url)
            return response.text
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(1.2 * (2 ** (attempt - 1)), 15.0) + random.uniform(0.15, 0.55))
                continue
            break
        except requests.HTTPError as exc:
            raise RuntimeError(f"catégorie complémentaire : {exc}") from exc
    raise RuntimeError(f"catégorie complémentaire indisponible après {attempts} tentative(s): {last_error}")


def fetch_catalogue_page(page_number: int, attempts: int) -> str:
    """Télécharge une page catalogue ; refuse toute URL de fiche produit."""
    global _http_attempts

    url = catalogue_url(page_number)
    if not is_catalogue_url(url, page_number):
        raise RuntimeError(f"URL catalogue refusée : {url}")
    if "/p/" in urlsplit(url).path:
        raise RuntimeError(f"Tentative interdite de lecture d'une fiche : {url}")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        session = session_for_thread()
        with _shared_lock:
            session.cookies.update(_shared_cookies)
            _http_attempts += 1

        try:
            response = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
                headers={"Referer": ROOT_URL},
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = RuntimeError(f"HTTP {response.status_code}")
                if attempt < attempts:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = (
                        float(retry_after) if retry_after.isdigit() else min(1.2 * (2 ** (attempt - 1)), 15.0)
                    )
                    time.sleep(delay + random.uniform(0.15, 0.55))
                    continue
                break

            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", "").lower():
                raise RuntimeError("réponse non HTML")
            response.encoding = response.apparent_encoding or response.encoding

            with _shared_lock:
                _shared_cookies.update(session.cookies.get_dict())
                _requested_urls.append(url)
            return response.text

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(1.2 * (2 ** (attempt - 1)), 15.0) + random.uniform(0.15, 0.55))
                continue
            break
        except requests.HTTPError as exc:
            raise RuntimeError(f"page {page_number}: {exc}") from exc

    raise RuntimeError(f"page {page_number} indisponible après {attempts} tentative(s): {last_error}")


def parse_result_counter(soup: BeautifulSoup) -> tuple[int, int]:
    """Retourne (nombre total de produits, produits par page complète)."""
    candidates = []
    for selector in (
        ".woocommerce-result-count",
        "p.woocommerce-result-count",
        "[class*='result-count']",
    ):
        candidates.extend(soup.select(selector))
    candidates.append(soup)

    pattern = re.compile(
        r"(\d[\d.\s]*)\s*[–—-]\s*(\d[\d.\s]*)\s+von\s+"
        r"(\d[\d.\s]*)\s+Ergebnissen",
        flags=re.I,
    )
    for node in candidates:
        text = clean_text(node.get_text(" ", strip=True))
        match = pattern.search(text)
        if not match:
            continue
        start = int(re.sub(r"\D", "", match.group(1)))
        end = int(re.sub(r"\D", "", match.group(2)))
        total = int(re.sub(r"\D", "", match.group(3)))
        per_page = end - start + 1
        if start == 1 and per_page > 0 and total >= end:
            return total, per_page
    raise RuntimeError("Compteur de résultats ATZ introuvable")


def detect_page_count(soup: BeautifulSoup, total: int, per_page: int) -> int:
    calculated = math.ceil(total / per_page)
    linked_pages = {1}
    for anchor in soup.select("a[href]"):
        href = clean_text(anchor.get("href", ""))
        parts = urlsplit(urljoin(ROOT_URL, href))
        match = re.fullmatch(r"/page/(\d+)/", re.sub(r"/+", "/", parts.path))
        if match:
            query = parse_qs(parts.query)
            if query.get("post_type") == ["product"] and query.get("s") == ['"opel gt"']:
                linked_pages.add(int(match.group(1)))

    linked_max = max(linked_pages)
    if linked_max > 1 and linked_max != calculated:
        raise RuntimeError(f"Pagination incohérente : compteur={calculated}, liens={linked_max}")
    if not 1 <= calculated <= 100:
        raise RuntimeError(f"Nombre de pages incohérent : {calculated}")
    return calculated


def canonical_product_url(value: str) -> str | None:
    parts = urlsplit(urljoin(BASE_URL, clean_text(value)))
    path = re.sub(r"/+", "/", parts.path)
    if not path.endswith("/"):
        path += "/"
    if (
        parts.scheme != "https"
        or parts.netloc.lower() not in {"atz-online.com", "www.atz-online.com"}
        or re.fullmatch(r"/p/[^/]+/", path) is None
    ):
        return None
    return urlunsplit(("https", "atz-online.com", path, "", ""))


def product_urls_inside(node: Tag) -> set[str]:
    urls: set[str] = set()
    for anchor in node.select("a[href]"):
        url = canonical_product_url(anchor.get("href", ""))
        if url:
            urls.add(url)
    return urls


def find_product_container(anchor: Tag, product_url: str) -> Tag:
    """Trouve le plus grand ancêtre qui ne contient qu'un seul produit.

    Cette méthode ne dépend pas des classes CSS du thème ATZ. Elle évite le bug
    précédent où un conteneur global était pris pour une carte produit.
    """
    best: Tag = anchor
    current: Tag | None = anchor
    for _ in range(12):
        parent = current.parent if current is not None else None
        if not isinstance(parent, Tag):
            break
        urls = product_urls_inside(parent)
        if urls == {product_url}:
            best = parent
            current = parent
            continue
        if product_url in urls and len(urls) > 1:
            break
        current = parent
    return best


def select_product_anchors(soup: BeautifulSoup) -> dict[str, list[Tag]]:
    grouped: dict[str, list[Tag]] = {}
    for anchor in soup.select("a[href]"):
        product_url = canonical_product_url(anchor.get("href", ""))
        if product_url:
            grouped.setdefault(product_url, []).append(anchor)
    return grouped


def title_from(container: Tag, anchors: list[Tag]) -> str:
    for selector in (
        ".woocommerce-loop-product__title",
        ".wc-block-grid__product-title",
        "h1",
        "h2",
        "h3",
        "h4",
    ):
        node = container.select_one(selector)
        text = clean_text(node.get_text(" ", strip=True) if node else "")
        if text:
            return text

    generic = {
        "weiterlesen",
        "in den warenkorb",
        "details",
        "mehr erfahren",
        "read more",
        "add to cart",
    }
    texts = []
    for anchor in anchors:
        text = clean_text(anchor.get_text(" ", strip=True))
        if text and text.casefold() not in generic:
            texts.append(text)
    if texts:
        return max(texts, key=len)

    image = container.select_one("img[alt]")
    if image:
        return clean_text(image.get("alt", ""))
    return ""


def photo_from(container: Tag, source_url: str) -> str:
    image = container.select_one("img")
    if not image:
        return "inconnu"
    for attr in (
        "data-large_image",
        "data-src",
        "data-lazy-src",
        "data-original",
        "src",
    ):
        value = clean_text(image.get(attr, ""))
        if value and not value.startswith("data:"):
            return urljoin(source_url, value)
    srcset = clean_text(image.get("data-srcset", "") or image.get("srcset", ""))
    if srcset:
        return urljoin(source_url, srcset.split(",")[-1].strip().split()[0])
    return "inconnu"


def parse_number(value: str) -> float:
    value = clean_text(value).replace("\u00a0", "").replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    return float(value)


def format_euro(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "€"


def price_from(container: Tag) -> str:
    text = clean_text(container.get_text(" ", strip=True))
    if re.search(r"preis\s+auf\s+anfrage|price\s+on\s+request", text, re.I):
        return "inconnu"

    nodes = container.select(
        ".price ins .woocommerce-Price-amount, .price ins .amount, "
        ".price .woocommerce-Price-amount, .price .amount, .price"
    )
    price_text = clean_text(nodes[-1].get_text(" ", strip=True) if nodes else text)
    if "€" not in price_text and not re.search(r"\bEUR\b", price_text, re.I):
        return "inconnu"
    values = re.findall(r"\d[\d.\s]*,\d{2}", price_text)
    return format_euro(parse_number(values[-1])) if values else "inconnu"


def availability_from(container: Tag, price: str) -> str:
    value = (
        " ".join(container.get("class", [])) + " " + clean_text(container.get_text(" ", strip=True))
    ).lower()
    if re.search(r"backorder|onbackorder|nachbestell|vorbestell|wird\s+nachgeliefert", value):
        return "réapprovisionnement"
    if re.search(r"preis\s+auf\s+anfrage|auf\s+anfrage|on\s+request", value):
        return "sur demande"
    if re.search(r"outofstock|out[_ -]?of[_ -]?stock|nicht\s+vorrätig|ausverkauft|sold\s+out", value):
        return "en rupture de stock"
    if re.search(r"instock|in[_ -]?stock|sofort\s+lieferbar|in\s+den\s+warenkorb|add\s+to\s+cart", value):
        return "en stock"
    if price != "inconnu" and re.search(r"weiterlesen|read\s+more", value):
        return "en rupture de stock"
    return "inconnu"


def translate_product_names(products: list[dict[str, str]]) -> None:
    from catalog_translation import translate_names
    start_phase("translations", 80, 94, 0, "Désignations traitées")

    cache_root = Path(os.getenv("ATZ_CACHE_DIR", str(
        Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "entraide-opel-gt" / "atz"
    )))
    translations = translate_names(
        [item["nom"] for item in products], language="de",
        cache_file=cache_root / "atz_translations.json",
        previous_output=Path(os.getenv("CATALOG_PREVIOUS_OUTPUT", str(OUTPUT_FILE))),
        workers=TRANSLATION_WORKERS,
    )
    for item in products:
        item["nom_traduit"] = translations[item["nom"]]


def parse_listing_page(source_url: str, source: str, label: str) -> list[dict[str, str]]:
    """Extract product cards from an allowed ATZ listing without opening details."""

    soup = BeautifulSoup(source, "html.parser")
    grouped = select_product_anchors(soup)
    if not grouped:
        raise RuntimeError(f"{label}: aucune URL produit /p/.../ trouvée")

    products: list[dict[str, str]] = []
    for product_url, anchors in grouped.items():
        container = find_product_container(anchors[0], product_url)
        name = title_from(container, anchors)
        if not name:
            continue
        price = price_from(container)
        products.append(
            {
                "nom": name,
                "nom_traduit": "",
                "prix": price,
                "disponibilite": availability_from(container, price),
                "url_photo": photo_from(container, source_url),
                "url_fiche": product_url,
            }
        )

    if not products:
        raise RuntimeError(f"{label}: aucun produit exploitable")
    return products


def parse_catalogue_page(page_number: int, source: str) -> list[dict[str, str]]:
    """Extract one page from the exact ``opel gt`` ATZ search."""

    return parse_listing_page(catalogue_url(page_number), source, f"page {page_number}")


def fetch_and_parse(page_number: int, attempts: int) -> tuple[int, list[dict[str, str]]]:
    source = fetch_catalogue_page(page_number, attempts)
    return page_number, parse_catalogue_page(page_number, source)


def validate(products: list[dict[str, str]], expected_total: int, *, exact: bool = True) -> None:
    invalid_count = len(products) != expected_total if exact else len(products) < expected_total
    if invalid_count:
        comparison = "exactement" if exact else "au moins"
        raise ValueError(
            f"Catalogue incomplet : {len(products)} produits extraits, "
            f"{comparison} {expected_total} attendus. Aucun JSON n'a été écrit."
        )

    seen: set[str] = set()
    price_pattern = re.compile(r"^(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}€$")
    for index, item in enumerate(products):
        if tuple(item.keys()) != FIELDS:
            raise ValueError(f"Élément {index}: champs incorrects")
        if any(not isinstance(item[field], str) or not item[field].strip() for field in FIELDS):
            raise ValueError(f"Élément {index}: champ vide")
        if item["prix"] != "inconnu" and not price_pattern.fullmatch(item["prix"]):
            raise ValueError(f"Élément {index}: prix invalide {item['prix']}")
        if item["disponibilite"] not in VALID_AVAILABILITIES:
            raise ValueError(f"Élément {index}: disponibilité invalide")
        if canonical_product_url(item["url_fiche"]) != item["url_fiche"]:
            raise ValueError(f"Élément {index}: URL produit invalide")
        if item["url_fiche"] in seen:
            raise ValueError(f"Élément {index}: doublon {item['url_fiche']}")
        seen.add(item["url_fiche"])


def write_json(products: list[dict[str, str]]) -> None:
    temporary = OUTPUT_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(products, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(OUTPUT_FILE)


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"atz.py {VERSION}")
        return 0

    print(f"atz.py version {VERSION}")
    print(f"1/4 Lecture de la première page : {ROOT_URL}")
    first_html = fetch_catalogue_page(1, SEQUENTIAL_ATTEMPTS)
    first_soup = BeautifulSoup(first_html, "html.parser")
    expected_total, per_page = parse_result_counter(first_soup)
    page_count = detect_page_count(first_soup, expected_total, per_page)
    print(f"    {page_count} page(s) catalogue détectée(s).")
    print(f"    {expected_total} produit(s) annoncés, {per_page} par page complète.")

    products_by_page: dict[int, list[dict[str, str]]] = {1: parse_catalogue_page(1, first_html)}
    start_phase("pages", 10, 70, page_count, "Pages traitées")
    advance_phase("pages")
    print(f"    Page 1 : {len(products_by_page[1])} produit(s) extraits.")

    pages = list(range(2, page_count + 1))
    workers = min(MAX_WORKERS, len(pages)) if pages else 1
    print(f"2/4 Lecture et parsing des pages 2 à {page_count} ({workers} requêtes simultanées maximum)")

    failed: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="atz-pages") as executor:
        futures = {executor.submit(fetch_and_parse, page, PARALLEL_ATTEMPTS): page for page in pages}
        for done, future in enumerate(as_completed(futures), start=1):
            page = futures[future]
            try:
                parsed_page, products = future.result()
                products_by_page[parsed_page] = products
                status = f"page {parsed_page}: {len(products)} produits"
            except Exception as exc:
                failed[page] = str(exc)
                status = f"page {page}: reprise nécessaire"
            print(f"\r    Pages terminées : {done}/{len(futures)} ({status})", end="", flush=True)
            advance_phase("pages")
    if pages:
        print()

    if failed:
        start_phase("retries", 70, 75, len(failed), "Pages reprises")
        print(f"    Reprise séquentielle de {len(failed)} page(s)")
        final_errors = []
        for page in sorted(failed):
            try:
                parsed_page, products = fetch_and_parse(page, SEQUENTIAL_ATTEMPTS)
                products_by_page[parsed_page] = products
                advance_phase("retries")
                print(f"    Page {page} reprise : {len(products)} produit(s).")
            except Exception as exc:
                final_errors.append(f"page {page}: {exc} (premier échec: {failed[page]})")
        if final_errors:
            raise RuntimeError("Échec de page(s) catalogue :\n- " + "\n- ".join(final_errors))

    missing_pages = sorted(set(range(1, page_count + 1)) - set(products_by_page))
    if missing_pages:
        raise RuntimeError(f"Pages manquantes : {missing_pages}")

    all_products: list[dict[str, str]] = []
    for page in range(1, page_count + 1):
        page_products = products_by_page[page]
        expected_on_page = min(per_page, expected_total - per_page * (page - 1))
        if len(page_products) != expected_on_page:
            raise RuntimeError(
                f"Page {page} mal parsée : {len(page_products)} produits extraits, "
                f"{expected_on_page} attendus. Aucun JSON n'a été écrit."
            )
        all_products.extend(page_products)

    # La recherche exacte ``opel gt`` doit rester complète avant d'ajouter la
    # catégorie complémentaire. Cela conserve l'audit historique du scraper.
    union = {item["url_fiche"]: item for item in all_products}
    if len(union) != expected_total:
        raise RuntimeError(
            f"Catalogue de base incomplet : {len(union)} produits uniques, "
            f"{expected_total} annoncés. Aucun JSON n'a été écrit."
        )

    print("    Complément : catégorie Opel GT / Getrag 5-Gang / Typ 240")
    start_phase("supplements", 75, 80, len(SUPPLEMENTAL_CATEGORY_URLS), "Catégories complémentaires traitées")
    for category_url in SUPPLEMENTAL_CATEGORY_URLS:
        category_html = fetch_supplemental_category(category_url, SEQUENTIAL_ATTEMPTS)
        category_products = parse_listing_page(
            category_url,
            category_html,
            "catégorie Opel GT Getrag 5-Gang Typ 240",
        )
        for item in category_products:
            union.setdefault(item["url_fiche"], item)
        print(f"    {len(category_products)} produit(s) lus dans la catégorie complémentaire.")
        advance_phase("supplements")

    products = sorted(
        union.values(),
        key=lambda item: (item["nom"].casefold(), item["url_fiche"]),
    )

    print("3/4 Traduction allemand → français des noms")
    translate_product_names(products)

    print("4/4 Validation et écriture de atz.json")
    publish_progress(95, "ATZ : validation du catalogue complet.")
    validate(products, expected_total, exact=False)

    if any("/p/" in urlsplit(url).path for url in _requested_urls):
        raise RuntimeError("Audit HTTP : une fiche individuelle a été consultée")
    expected_requested_pages = set(range(1, page_count + 1))
    actual_requested_pages = {
        1 if urlsplit(url).path == "/" else int(re.search(r"/page/(\d+)/", urlsplit(url).path).group(1))
        for url in _requested_urls
        if is_catalogue_url(url)
    }
    if actual_requested_pages != expected_requested_pages:
        raise RuntimeError(
            f"Audit HTTP : pages obtenues {sorted(actual_requested_pages)}, "
            f"attendues {sorted(expected_requested_pages)}"
        )
    actual_categories = {url for url in _requested_urls if is_supplemental_category_url(url)}
    if actual_categories != set(SUPPLEMENTAL_CATEGORY_URLS):
        raise RuntimeError(
            f"Audit HTTP : catégories obtenues {sorted(actual_categories)}, "
            f"attendues {sorted(SUPPLEMENTAL_CATEGORY_URLS)}"
        )

    write_json(products)
    reloaded = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    validate(reloaded, expected_total, exact=False)

    print(f"    {len(products)} produit(s) écrits dans {OUTPUT_FILE}")
    print(f"    Pages catalogue parsées : {page_count}/{page_count}")
    print(f"    Tentatives HTTP totales : {_http_attempts} (reprises incluses)")
    print("    Fiches individuelles consultées : 0")
    return 0


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import (
    ScrapeResult as ScrapeResult,
    run_legacy_scraper as _run_legacy_scraper,
    scraper_cli as _scraper_cli,
)

_LEGACY_MAIN = main
_SUPPLIER_NAME = "ATZ"
_SUPPLIER_LANG = "de"
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name("atz.json")
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
    _set_legacy_output(output)
    old_argv = _scraper_sys.argv[:]
    # Les anciens scripts avaient des interfaces CLI hétérogènes. Pour garantir
    # une entrée homogène, on neutralise leurs argparse et on pilote les constantes.
    _scraper_sys.argv = [old_argv[0]]
    try:
        return _LEGACY_MAIN()
    finally:
        _scraper_sys.argv = old_argv


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
