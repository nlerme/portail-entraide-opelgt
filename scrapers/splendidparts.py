#!/usr/bin/env python3
"""Scrape le catalogue Opel GT de Splendid Parts dans splendidparts.json.

Dépendances : pip install requests beautifulsoup4

Le script :
  1. détermine d'abord le nombre de pages du catalogue ;
  2. télécharge ensuite toutes les pages en parallèle (un processus par page,
     dans la limite du nombre de processeurs disponibles) ;
  3. traduit les désignations en français ;
  4. contrôle strictement le format avant d'écrire le JSON.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
        "Dépendances manquantes. Exécutez : pip install requests beautifulsoup4"
    ) from exc

ROOT_URL = "https://splenditparts.de/shop/en/70-opel-gt"
OUTPUT_FILE = Path(__file__).with_name("splendidparts.json")
TIMEOUT = 40
FIELDS = ("nom", "nom_traduit", "prix", "disponibilite", "url_photo", "url_fiche")
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
    "Accept-Language": "en-GB,en;q=0.9,de;q=0.7,fr;q=0.6",
}


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def plain_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return clean_text(value).lower()


def make_session(cookies: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,
        status_forcelist=(408, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8))
    session.headers.update(HEADERS)
    if cookies:
        session.cookies.update(cookies)
    return session


def get_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def has_euro_price(soup: BeautifulSoup) -> bool:
    for node in soup.select(".price, [itemprop='price'], meta[itemprop='priceCurrency']"):
        text = " ".join((node.get_text(" ", strip=True), node.get("content", "")))
        if "€" in text or re.search(r"\bEUR\b", text, re.I):
            return True
    return False


def select_euro_currency(session: requests.Session, html: str) -> str:
    """Sélectionne EUR si le site propose un sélecteur ; sinon laisse la conversion au script."""
    soup = BeautifulSoup(html, "html.parser")
    if has_euro_price(soup):
        return html

    for select in soup.select("select[name]"):
        eur_option = None
        for option in select.select("option"):
            label = f"{option.get_text(' ', strip=True)} {option.get('value', '')}"
            if "EUR" in label.upper() or "€" in label:
                eur_option = option
                break
        if eur_option is None:
            continue

        form = select.find_parent("form")
        if not isinstance(form, Tag):
            continue
        payload: dict[str, str] = {}
        for field in form.select("input[name], select[name]"):
            name = field.get("name")
            if not name:
                continue
            if field.name == "select":
                chosen = field.select_one("option[selected]") or field.select_one("option")
                payload[name] = chosen.get("value", "") if chosen else ""
            elif field.get("type", "").lower() not in {"submit", "button", "image"}:
                payload[name] = field.get("value", "")
        payload[select["name"]] = eur_option.get("value", "EUR")
        action = urljoin(ROOT_URL, form.get("action") or ROOT_URL)
        method = (form.get("method") or "get").lower()
        response = (
            session.post(action, data=payload, timeout=TIMEOUT)
            if method == "post"
            else session.get(action, params=payload, timeout=TIMEOUT)
        )
        response.raise_for_status()
        refreshed = get_html(session, ROOT_URL)
        if has_euro_price(BeautifulSoup(refreshed, "html.parser")):
            return refreshed

    # Certains thèmes utilisent un lien plutôt qu'un <select>.
    for link in soup.select("a[href]"):
        label = f"{link.get_text(' ', strip=True)} {link.get('href', '')}"
        if re.search(r"(?:\bEUR\b|currency[^\s]*=EUR)", label, re.I):
            session.get(urljoin(ROOT_URL, link["href"]), timeout=TIMEOUT).raise_for_status()
            refreshed = get_html(session, ROOT_URL)
            if has_euro_price(BeautifulSoup(refreshed, "html.parser")):
                return refreshed
    return html


def product_cards(soup: BeautifulSoup) -> list[Tag]:
    selectors = (
        "#js-product-list article.product-miniature",
        "article.js-product-miniature",
        "article.product-miniature",
        ".product-miniature",
    )
    for selector in selectors:
        cards = [node for node in soup.select(selector) if isinstance(node, Tag)]
        if cards:
            # Déduplication conservant l'ordre si plusieurs sélecteurs se recouvrent.
            seen: set[int] = set()
            result: list[Tag] = []
            for card in cards:
                marker = id(card)
                if marker not in seen:
                    seen.add(marker)
                    result.append(card)
            return result
    return []


def discover_pagination(html: str) -> tuple[int, int | None]:
    """Retourne (nombre_de_pages, nombre_total_de_produits)."""
    soup = BeautifulSoup(html, "html.parser")
    page_numbers = {1}
    for link in soup.select(".pagination a[href], nav.pagination a[href], a[rel='next'][href]"):
        query = parse_qs(urlparse(urljoin(ROOT_URL, link.get("href", ""))).query)
        for value in query.get("page", []):
            if value.isdigit():
                page_numbers.add(int(value))
        label = clean_text(link.get_text(" ", strip=True))
        if label.isdigit():
            page_numbers.add(int(label))

    text = clean_text(soup.get_text(" ", strip=True))
    total = None
    total_patterns = (
        r"there\s+(?:are|is)\s+([\d\s.,]+)\s+products?",
        r"showing\s+\d+\s*[-–]\s*\d+\s+of\s+([\d\s.,]+)\s+items?",
        r"([\d\s.,]+)\s+products?",
        r"([\d\s.,]+)\s+artikel",
        r"affichage\s+de\s+\d+\s*[-–]\s*\d+\s+sur\s+([\d\s.,]+)",
    )
    lowered = plain_text(text)
    for pattern in total_patterns:
        match = re.search(pattern, lowered, re.I)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                total = int(digits)
                break

    cards_on_first_page = len(product_cards(soup))
    max_page = max(page_numbers)
    if total and cards_on_first_page:
        max_page = max(max_page, math.ceil(total / cards_on_first_page))
    if max_page < 1:
        raise RuntimeError("Impossible de déterminer le nombre de pages du catalogue.")
    return max_page, total


def page_url(page: int) -> str:
    return ROOT_URL if page == 1 else f"{ROOT_URL}?page={page}"


def extract_name_and_url(card: Tag) -> tuple[str, str]:
    selectors = (
        ".product-title a[href]",
        "h2 a[href]",
        "h3 a[href]",
        "a.product-name[href]",
        "a[href][itemprop='url']",
    )
    for selector in selectors:
        link = card.select_one(selector)
        if not isinstance(link, Tag):
            continue
        name = clean_text(link.get("title")) or clean_text(link.get_text(" ", strip=True))
        href = link.get("href")
        if name and href:
            return name, urljoin(ROOT_URL, href)
    raise ValueError("Carte produit sans nom ou URL de fiche")


def extract_photo(card: Tag) -> str:
    image = card.select_one(
        "a.product-thumbnail img, .thumbnail-container img, img[itemprop='image'], img"
    )
    if not isinstance(image, Tag):
        return "inconnu"
    for attr in (
        "data-full-size-image-url",
        "data-image-large-src",
        "data-src",
        "data-lazy-src",
        "src",
    ):
        value = clean_text(image.get(attr))
        if value and not value.startswith("data:"):
            return urljoin(ROOT_URL, value)
    srcset = clean_text(image.get("srcset"))
    if srcset:
        candidates = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        if candidates:
            return urljoin(ROOT_URL, candidates[-1])
    return "inconnu"


def parse_number(raw: str) -> Decimal | None:
    value = re.sub(r"[^0-9,.-]", "", raw)
    if not re.search(r"\d", value):
        return None
    value = value.replace("-", "")
    if "," in value and "." in value:
        decimal_sep = "," if value.rfind(",") > value.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        value = value.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in value:
        tail = value.rsplit(",", 1)[1]
        value = value.replace(",", ".") if len(tail) in {1, 2} else value.replace(",", "")
    elif "." in value:
        tail = value.rsplit(".", 1)[1]
        if len(tail) not in {1, 2}:
            value = value.replace(".", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def detect_currency(text: str, node: Tag | None = None) -> str | None:
    candidates = [text]
    if node is not None:
        for attr in ("content", "data-currency", "data-currency-code"):
            candidates.append(clean_text(node.get(attr)))
    joined = " ".join(candidates).upper()
    if "€" in joined or re.search(r"\bEUR\b", joined):
        return "EUR"
    if "£" in joined or re.search(r"\bGBP\b", joined):
        return "GBP"
    if re.search(r"\bCHF\b", joined):
        return "CHF"
    if re.search(r"\bCAD\b", joined):
        return "CAD"
    if re.search(r"\bAUD\b", joined):
        return "AUD"
    if "$" in joined or re.search(r"\bUSD\b", joined):
        return "USD"
    return None


def extract_price(card: Tag, page_currency: str | None) -> tuple[Decimal | None, str | None]:
    selectors = (
        ".current-price .price",
        ".product-price-and-shipping .price:not(.regular-price)",
        ".price:not(.regular-price):not(.old-price)",
        "[itemprop='price']",
    )
    for selector in selectors:
        for node in card.select(selector):
            if not isinstance(node, Tag):
                continue
            raw = clean_text(node.get("content")) or clean_text(node.get_text(" ", strip=True))
            amount = parse_number(raw)
            if amount is not None:
                return amount, detect_currency(raw, node) or page_currency
    return None, None


def page_currency(soup: BeautifulSoup) -> str | None:
    meta = soup.select_one("meta[itemprop='priceCurrency'], meta[property='product:price:currency']")
    if isinstance(meta, Tag):
        code = clean_text(meta.get("content")).upper()
        if re.fullmatch(r"[A-Z]{3}", code):
            return code
    for node in soup.select(".price, [itemprop='price']")[:10]:
        code = detect_currency(clean_text(node.get_text(" ", strip=True)), node)
        if code:
            return code
    return None


def extract_availability(card: Tag) -> str:
    focused_nodes = card.select(
        ".product-availability, .availability, .product-flags, "
        ".product-add-to-cart, button.add-to-cart, [data-button-action='add-to-cart']"
    )
    focused = plain_text(" ".join(node.get_text(" ", strip=True) for node in focused_nodes))
    whole = plain_text(card.get_text(" ", strip=True))
    text = f"{focused} {whole}"

    add_buttons = card.select("button.add-to-cart, [data-button-action='add-to-cart']")
    enabled_add_button = any(
        not button.has_attr("disabled")
        and plain_text(button.get_text(" ", strip=True)) not in {"", "out of stock"}
        for button in add_buttons
    )

    if re.search(r"out[ -]?of[ -]?stock|currently unavailable|sold out|nicht lieferbar", focused):
        return "en rupture de stock"
    if re.search(
        r"back[- ]?order|available again soon|again available soon|restock|replenish|"
        r"delivery expected|temporarily unavailable|nachliefer|wieder lieferbar ab",
        text,
    ):
        return "réapprovisionnement"
    if enabled_add_button or re.search(r"\bin stock\b|available now|back in stock|add to cart|sofort lieferbar", focused):
        return "en stock"
    if re.search(r"on request|on order|upon request|ask for availability|please (?:inquire|enquire)|auf anfrage", text):
        return "sur demande"
    return "inconnu"


def scrape_page(page: int, cookies: dict[str, str]) -> tuple[int, list[dict[str, Any]]]:
    session = make_session(cookies)
    html = get_html(session, page_url(page))
    soup = BeautifulSoup(html, "html.parser")
    currency = page_currency(soup)
    records: list[dict[str, Any]] = []
    for card in product_cards(soup):
        try:
            name, fiche = extract_name_and_url(card)
        except ValueError:
            continue
        amount, code = extract_price(card, currency)
        records.append(
            {
                "nom": name,
                "nom_traduit": "",  # rempli après le scraping
                "prix": "inconnu",
                "disponibilite": extract_availability(card),
                "url_photo": extract_photo(card),
                "url_fiche": fiche,
                "_amount": str(amount) if amount is not None else None,
                "_currency": code,
            }
        )
    if not records:
        raise RuntimeError(f"Aucun produit trouvé sur la page {page}: {page_url(page)}")
    return page, records


def euro_rate(currency: str, session: requests.Session, cache: dict[str, Decimal]) -> Decimal:
    currency = currency.upper()
    if currency == "EUR":
        return Decimal("1")
    if currency in cache:
        return cache[currency]
    response = session.get(
        "https://api.frankfurter.app/latest",
        params={"from": currency, "to": "EUR"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    rate = Decimal(str(response.json()["rates"]["EUR"]))
    cache[currency] = rate
    return rate


def format_prices(records: list[dict[str, Any]]) -> None:
    session = make_session()
    rates: dict[str, Decimal] = {}
    for record in records:
        raw_amount = record.pop("_amount", None)
        currency = record.pop("_currency", None)
        if raw_amount is None:
            record["prix"] = "inconnu"
            continue
        amount = Decimal(raw_amount)
        if currency and currency.upper() != "EUR":
            amount *= euro_rate(currency, session, rates)
        elif currency is None:
            # Le site est normalement en EUR. Une devise absente est traitée comme EUR
            # seulement si le montant provient bien d'un élément de prix.
            currency = "EUR"
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        record["prix"] = f"{amount:.2f}".replace(".", ",") + "€"


FALLBACK_TRANSLATIONS = (
    (r"\bwiper arm set\b", "jeu de bras d’essuie-glace"),
    (r"\bwiper arm\b", "bras d’essuie-glace"),
    (r"\bwiper\b", "essuie-glace"),
    (r"\bwindshield\b|\bwindscreen\b", "pare-brise"),
    (r"\bfront grille\b|\bfrontgrill\b", "calandre avant"),
    (r"\brear panel\b", "panneau arrière"),
    (r"\bdoor sill\b", "bas de caisse"),
    (r"\bheadlight\b", "phare"),
    (r"\btail light\b|\brear light\b", "feu arrière"),
    (r"\bturn signal\b|\bindicator\b", "clignotant"),
    (r"\bbrake\b", "frein"),
    (r"\bclutch\b", "embrayage"),
    (r"\bgearbox\b|\btransmission\b", "boîte de vitesses"),
    (r"\bengine\b", "moteur"),
    (r"\bexhaust\b", "échappement"),
    (r"\bradiator\b", "radiateur"),
    (r"\bheater\b", "chauffage"),
    (r"\bsteering\b", "direction"),
    (r"\bshock absorber\b", "amortisseur"),
    (r"\bspring\b", "ressort"),
    (r"\bbearing\b", "roulement"),
    (r"\bbushing\b|\bbush\b", "silentbloc"),
    (r"\bgasket\b", "joint"),
    (r"\bseal\b", "joint d’étanchéité"),
    (r"\brubber\b", "caoutchouc"),
    (r"\bcable\b", "câble"),
    (r"\bhose\b", "durite"),
    (r"\bfuel\b", "carburant"),
    (r"\boil\b", "huile"),
    (r"\bfilter\b", "filtre"),
    (r"\bpump\b", "pompe"),
    (r"\btank\b", "réservoir"),
    (r"\bmirror\b", "rétroviseur"),
    (r"\bbumper\b", "pare-chocs"),
    (r"\bfender\b", "aile"),
    (r"\bdoor\b", "porte"),
    (r"\bwindow\b", "vitre"),
    (r"\bseat\b", "siège"),
    (r"\bdashboard\b", "tableau de bord"),
    (r"\bcover\b", "couvercle"),
    (r"\btrim\b", "garniture"),
    (r"\bpanel\b", "panneau"),
    (r"\bbracket\b", "support"),
    (r"\bmounting\b|\bmount\b", "fixation"),
    (r"\bclip\b", "agrafe"),
    (r"\bscrew\b", "vis"),
    (r"\bbolt\b", "boulon"),
    (r"\bnut\b", "écrou"),
    (r"\bwasher\b", "rondelle"),
    (r"\bswitch\b", "interrupteur"),
    (r"\bconnector\b", "connecteur"),
    (r"\bset\b", "jeu"),
    (r"\bkit\b", "kit"),
    (r"\bfront\b", "avant"),
    (r"\brear\b", "arrière"),
    (r"\bleft\b", "gauche"),
    (r"\bright\b", "droit"),
    (r"\bupper\b", "supérieur"),
    (r"\blower\b", "inférieur"),
    (r"\binner\b", "intérieur"),
    (r"\bouter\b", "extérieur"),
    (r"\bblack\b", "noir"),
    (r"\bchrome\b", "chromé"),
    (r"\boriginal\b", "d’origine"),
)


def fallback_translate(name: str) -> str:
    result = name
    for pattern, replacement in FALLBACK_TRANSLATIONS:
        result = re.sub(pattern, replacement, result, flags=re.I)
    return clean_text(result)


def translate_one(name: str) -> tuple[str, str]:
    session = make_session()
    for attempt in range(4):
        try:
            response = session.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "fr", "dt": "t", "q": name},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            translated = clean_text("".join(part[0] for part in payload[0] if part and part[0]))
            if translated:
                return name, translated
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError):
            if attempt < 3:
                time.sleep(0.7 * (2**attempt))
    return name, fallback_translate(name)


def translate_names(records: list[dict[str, Any]]) -> None:
    names = list(dict.fromkeys(record["nom"] for record in records))
    workers = min(16, max(1, len(names)))
    translations: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(translate_one, name): name for name in names}
        for future in as_completed(futures):
            original, translated = future.result()
            translations[original] = translated
    for record in records:
        record["nom_traduit"] = translations[record["nom"]]


def validate(records: list[dict[str, Any]], expected_total: int | None) -> None:
    if not records:
        raise ValueError("Le catalogue JSON est vide.")
    seen_urls: set[str] = set()
    price_re = re.compile(r"^(?:inconnu|\d+,\d{2}€)$")
    for index, record in enumerate(records, start=1):
        if tuple(record.keys()) != FIELDS:
            raise ValueError(f"Élément {index}: champs incorrects ou mal ordonnés: {tuple(record.keys())}")
        if not all(isinstance(record[field], str) for field in FIELDS):
            raise ValueError(f"Élément {index}: chaque champ doit être une chaîne.")
        if not record["nom"] or not record["nom_traduit"]:
            raise ValueError(f"Élément {index}: nom ou traduction vide.")
        if not price_re.fullmatch(record["prix"]):
            raise ValueError(f"Élément {index}: prix invalide: {record['prix']!r}")
        if record["disponibilite"] not in AVAILABILITIES:
            raise ValueError(f"Élément {index}: disponibilité invalide.")
        if not re.match(r"^https?://", record["url_fiche"]):
            raise ValueError(f"Élément {index}: URL de fiche invalide.")
        if record["url_photo"] != "inconnu" and not re.match(r"^https?://", record["url_photo"]):
            raise ValueError(f"Élément {index}: URL de photo invalide.")
        if record["url_fiche"] in seen_urls:
            raise ValueError(f"Doublon détecté: {record['url_fiche']}")
        seen_urls.add(record["url_fiche"])
    if expected_total is not None and len(records) != expected_total:
        raise ValueError(
            f"Catalogue incomplet: {len(records)} fiches uniques récupérées, "
            f"mais le site en annonce {expected_total}. Relancez le script; "
            "le catalogue a peut-être changé pendant le téléchargement."
        )


def scrape_all_pages(page_count: int, cookies: dict[str, str]) -> list[dict[str, Any]]:
    workers = min(page_count, os.cpu_count() or 1)
    print(f"Scraping de {page_count} pages avec {workers} processus…", file=sys.stderr)
    pages: dict[int, list[dict[str, Any]]] = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scrape_page, page, cookies): page for page in range(1, page_count + 1)}
        for future in as_completed(futures):
            page, records = future.result()
            pages[page] = records
            print(f"  page {page}/{page_count}: {len(records)} pièce(s)", file=sys.stderr)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, page_count + 1):
        for record in pages[page]:
            if record["url_fiche"] not in seen:
                seen.add(record["url_fiche"])
                merged.append(record)
    return merged


def main() -> None:
    # Étape imposée : déterminer le nombre de pages avant de lancer leur scraping.
    bootstrap = make_session()
    first_html = get_html(bootstrap, ROOT_URL)
    first_html = select_euro_currency(bootstrap, first_html)
    page_count, expected_total = discover_pagination(first_html)
    announced = str(expected_total) if expected_total is not None else "inconnu"
    print(f"Catalogue annoncé: {announced} pièce(s), {page_count} page(s).", file=sys.stderr)
    cookies = requests.utils.dict_from_cookiejar(bootstrap.cookies)

    # Le catalogue peut évoluer pendant l'exécution. Une seconde tentative est faite
    # automatiquement si le total final ne correspond plus au total initial.
    last_error: Exception | None = None
    for attempt in range(2):
        records = scrape_all_pages(page_count, cookies)
        format_prices(records)
        translate_names(records)
        records = [{field: record[field] for field in FIELDS} for record in records]
        try:
            validate(records, expected_total)
            break
        except ValueError as exc:
            last_error = exc
            if attempt == 1:
                raise
            print(f"Le catalogue a changé pendant le scraping ({exc}). Nouvelle tentative…", file=sys.stderr)
            first_html = get_html(bootstrap, ROOT_URL)
            page_count, expected_total = discover_pagination(first_html)
    else:  # pragma: no cover
        raise RuntimeError(str(last_error))

    temp_file = OUTPUT_FILE.with_suffix(".json.tmp")
    temp_file.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_file.replace(OUTPUT_FILE)
    print(f"OK: {len(records)} pièces validées dans {OUTPUT_FILE}")


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import ScrapeResult as ScrapeResult, run_legacy_scraper as _run_legacy_scraper, scraper_cli as _scraper_cli

_LEGACY_MAIN = main
_SUPPLIER_NAME = 'Splendid Parts'
_SUPPLIER_LANG = 'en'
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name('splendidparts.json')
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
