#!/usr/bin/env python3
"""Extrait le catalogue Opel GT d'OpelixParts dans opelixparts.json.

Dépendances : requests, beautifulsoup4
Installation : python -m pip install requests beautifulsoup4
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import unicodedata
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = "https://www.opelixparts.com/9-gt-1968-73"
OUTPUT = Path(__file__).with_name("opelixparts.json")
TIMEOUT = (10, 45)
DETAIL_THREADS = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}
FIELDS = ("nom", "nom_traduit", "prix", "disponibilite", "url_photo", "url_fiche")
AVAILABILITIES = {
    "en stock",
    "en rupture de stock",
    "réapprovisionnement",
    "sur demande",
    "inconnu",
}
LOCAL = threading.local()


def text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", text(value))
    return "".join(c for c in value if not unicodedata.combining(c)).lower()


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retries = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "POST")),
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def fetch(s: requests.Session, url: str) -> str:
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def euro_is_displayed(html: str) -> bool:
    root = BeautifulSoup(html, "html.parser").select_one("#js-product-list")
    return bool(root and re.search(r"\d[\d\s\u00a0\u202f]*[,.]\d{2}\s*€", root.get_text(" ")))


def select_euro(s: requests.Session, html: str) -> str:
    """Choisit EUR si la boutique affiche une autre devise."""
    if euro_is_displayed(html):
        return html

    soup = BeautifulSoup(html, "html.parser")
    for select in soup.select("select[name]"):
        marker = norm(f"{select.get('name', '')} {select.get('id', '')}")
        if "currency" not in marker and "devise" not in marker:
            continue
        option = next(
            (o for o in select.select("option[value]") if re.search(r"\bEUR\b|€|\beuro\b", o.get_text(" "), re.I)),
            None,
        )
        form = select.find_parent("form")
        if option is None or form is None:
            continue
        data = {i["name"]: i.get("value", "") for i in form.select("input[name]")}
        data[select["name"]] = option["value"]
        action = urljoin(ROOT, form.get("action") or ROOT)
        if (form.get("method") or "GET").upper() == "POST":
            s.post(action, data=data, timeout=TIMEOUT).raise_for_status()
        else:
            s.get(action, params=data, timeout=TIMEOUT).raise_for_status()
        return fetch(s, ROOT)

    for a in soup.select("a[href]"):
        marker = norm(f"{a.get_text(' ')} {a.get('href', '')} {' '.join(a.get('class', []))}")
        if ("currency" in marker or "devise" in marker) and re.search(r"\b(?:eur|euro)\b", marker):
            s.get(urljoin(ROOT, a["href"]), timeout=TIMEOUT).raise_for_status()
            return fetch(s, ROOT)
    return html


def cards(soup: BeautifulSoup) -> list[Tag]:
    root = soup.select_one("#js-product-list") or soup
    return root.select("article.product-miniature, article.js-product-miniature, .product-miniature.js-product-miniature")


def page_information(html: str) -> tuple[int, int | None]:
    soup = BeautifulSoup(html, "html.parser")
    pages = {1}
    for a in soup.select(".pagination a[href], nav.pagination a[href]"):
        for value in parse_qs(urlparse(urljoin(ROOT, a["href"])).query).get("page", []):
            if value.isdigit():
                pages.add(int(value))
        label = text(a.get_text(" "))
        if label.isdigit():
            pages.add(int(label))

    match = re.search(r"Affichage\s+\d+\s*[-–]\s*\d+\s+de\s+(\d+)\s+article", soup.get_text(" "), re.I)
    total = int(match.group(1)) if match else None
    if max(pages) == 1 and total:
        pages.add(math.ceil(total / max(1, len(cards(soup)))))
    return max(pages), total


def decimal_number(raw: str) -> Decimal | None:
    value = re.sub(r"[\s\u00a0\u202f]", "", raw)
    if "," in value and "." in value:
        decimal_sep = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    else:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def currency(raw: str) -> str | None:
    upper = raw.upper()
    if "€" in raw or "EUR" in upper:
        return "EUR"
    for code in ("CHF", "GBP", "USD", "CAD", "AUD", "SEK", "NOK", "DKK", "PLN"):
        if re.search(rf"\b{code}\b", upper):
            return code
    if "£" in raw:
        return "GBP"
    if "$" in raw:
        return "USD"
    return None


@lru_cache(maxsize=None)
def euro_rate(code: str) -> Decimal:
    if code == "EUR":
        return Decimal("1")
    r = requests.get(
        "https://api.frankfurter.app/latest",
        params={"from": code, "to": "EUR"},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return Decimal(str(r.json()["rates"]["EUR"]))


def price_from(raw: str) -> str:
    match = re.search(r"\d[\d\s\u00a0\u202f]*(?:[,.]\d{1,2})?", raw)
    code = currency(raw)
    amount = decimal_number(match.group(0)) if match else None
    if amount is None or code is None:
        return "inconnu"
    try:
        value = (amount * euro_rate(code)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return f"{value:.2f}".replace(".", ",") + "€"
    except (requests.RequestException, KeyError, InvalidOperation, ValueError):
        return "inconnu"


def price_in(node: Tag | None, container: Tag | BeautifulSoup) -> str:
    if node is None:
        return "inconnu"
    currency_meta = container.select_one("[itemprop='priceCurrency']")
    raw = text(" ".join(filter(None, (
        node.get_text(" "),
        node.get("content"),
        currency_meta.get("content") if currency_meta else None,
    ))))
    return price_from(raw)


def availability(availability_text: str, description_text: str = "", add_to_cart: bool = False) -> str:
    a, d = norm(availability_text), norm(description_text)
    combined = f"{a} {d}"
    if re.search(r"reappro|reassort|back[ _-]?order|precommande", combined):
        return "réapprovisionnement"
    if re.search(r"sur demande|uniquement sur commande|sur commande|on request", combined):
        return "sur demande"
    if re.search(r"rupture|epuise|indisponible|out[ _-]?of[ _-]?stock", a):
        return "en rupture de stock"
    if re.search(r"en stock|disponible|in[ _-]?stock", a):
        return "en stock"
    return "en stock" if add_to_cart else "inconnu"


def image_url(container: Tag | BeautifulSoup, base: str, detail: bool = False) -> str:
    if detail:
        meta = container.select_one("meta[property='og:image'][content]")
        if meta:
            return urljoin(base, meta["content"])
        img = container.select_one(".product-cover img, img.js-qv-product-cover, #main img[itemprop='image']")
    else:
        img = container.select_one("a.product-thumbnail img, .thumbnail-container img, img")
    if img is None:
        return "inconnu"
    for attr in ("data-full-size-image-url", "data-image-large-src", "data-src", "src"):
        value = text(img.get(attr))
        if value and not value.startswith("data:"):
            return urljoin(base, value)
    return "inconnu"


def listing_item(card: Tag, page_url: str) -> dict[str, str] | None:
    a = card.select_one(".product-title a[href], h2.product-title a[href], h3.product-title a[href]")
    if a is None or not text(a.get_text(" ")):
        return None
    name = text(a.get_text(" "))
    price_node = card.select_one(".product-price-and-shipping .price, .current-price .price, [itemprop='price'], .price")
    flags = " ".join(n.get_text(" ") for n in card.select(".product-flags, .product-flag, .availability, [class*='stock']"))
    return {
        "nom": name,
        "nom_traduit": name,  # Le catalogue source est déjà en français.
        "prix": price_in(price_node, card),
        "disponibilite": availability(flags, add_to_cart=bool(card.select_one(".add-to-cart, [data-button-action='add-to-cart']"))),
        "url_photo": image_url(card, page_url),
        "url_fiche": urljoin(page_url, a["href"]),
    }


def thread_session(cookies: dict[str, str]) -> requests.Session:
    if not hasattr(LOCAL, "session"):
        LOCAL.session = session()
        LOCAL.session.cookies.update(cookies)
    return LOCAL.session


def enrich(job: tuple[dict[str, str], dict[str, str]]) -> dict[str, str]:
    item, cookies = job
    try:
        soup = BeautifulSoup(fetch(thread_session(cookies), item["url_fiche"]), "html.parser")
        main = soup.select_one("#main") or soup
        title = main.select_one("h1")
        if title and text(title.get_text(" ")):
            item["nom"] = text(title.get_text(" "))
            item["nom_traduit"] = item["nom"]

        p = main.select_one(".current-price .current-price-value, .current-price span, [itemprop='price']")
        detailed_price = price_in(p, main)
        if detailed_price != "inconnu":
            item["prix"] = detailed_price

        availability_nodes = main.select("#product-availability, .product-availability, [itemprop='availability']")
        description_nodes = main.select("#description, .product-description, .product-information")
        item["disponibilite"] = availability(
            " ".join(n.get_text(" ") + " " + str(n.get("content", "")) for n in availability_nodes),
            " ".join(n.get_text(" ") for n in description_nodes),
            add_to_cart=bool(main.select_one("[data-button-action='add-to-cart'], .add-to-cart")),
        )
        photo = image_url(main, item["url_fiche"], detail=True)
        if photo != "inconnu":
            item["url_photo"] = photo
    except requests.RequestException:
        pass
    return item


def scrape_page(job: tuple[int, dict[str, str]]) -> tuple[int, list[dict[str, str]]]:
    page, cookies = job
    page_url = ROOT if page == 1 else f"{ROOT}?page={page}"
    s = session()
    s.cookies.update(cookies)
    soup = BeautifulSoup(fetch(s, page_url), "html.parser")
    items = [item for card in cards(soup) if (item := listing_item(card, page_url))]
    if not items:
        raise RuntimeError(f"Aucune pièce détectée sur la page {page}: {page_url}")
    with ThreadPoolExecutor(max_workers=min(DETAIL_THREADS, len(items))) as pool:
        items = list(pool.map(enrich, ((item, cookies) for item in items)))
    return page, items


def validate(data: Any, expected_total: int | None = None) -> None:
    if not isinstance(data, list) or not data:
        raise ValueError("Le JSON doit être une liste non vide.")
    if expected_total is not None and len(data) != expected_total:
        raise ValueError(f"Catalogue incomplet: {len(data)} pièces extraites, {expected_total} attendues.")
    for i, item in enumerate(data):
        if not isinstance(item, dict) or tuple(item) != FIELDS:
            raise ValueError(f"Élément {i}: les six champs requis ne sont pas respectés.")
        if not re.fullmatch(r"inconnu|\d+,\d{2}€", item["prix"]):
            raise ValueError(f"Élément {i}: prix invalide {item['prix']!r}.")
        if item["disponibilite"] not in AVAILABILITIES:
            raise ValueError(f"Élément {i}: disponibilité invalide.")
        for key in ("url_photo", "url_fiche"):
            if item[key] != "inconnu" and not item[key].startswith(("http://", "https://")):
                raise ValueError(f"Élément {i}: {key} invalide.")


def main() -> None:
    s = session()
    first_html = select_euro(s, fetch(s, ROOT))
    page_count, expected_total = page_information(first_html)
    cookies = requests.utils.dict_from_cookiejar(s.cookies)
    workers = min(page_count, os.cpu_count() or 1)

    with ProcessPoolExecutor(max_workers=workers) as pool:
        by_page = dict(pool.map(scrape_page, ((page, cookies) for page in range(1, page_count + 1))))

    catalog, seen = [], set()
    for page in range(1, page_count + 1):
        for item in by_page[page]:
            if item["url_fiche"] not in seen:
                seen.add(item["url_fiche"])
                catalog.append(item)

    validate(catalog, expected_total)
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate(json.loads(OUTPUT.read_text(encoding="utf-8")), expected_total)
    print(f"{len(catalog)} pièces, {page_count} pages, {workers} processus -> {OUTPUT}")


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import ScrapeResult as ScrapeResult, run_legacy_scraper as _run_legacy_scraper, scraper_cli as _scraper_cli

_LEGACY_MAIN = main
_SUPPLIER_NAME = 'OpelixParts'
_SUPPLIER_LANG = 'fr'
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name('opelixparts.json')
_HARMONIZED_VERSION = "2026.07.10-harmonized-v1"


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
