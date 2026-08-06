#!/usr/bin/env python3
"""Récupère le catalogue Opel GT de https://www.pro-gt.de/fr/.

Dépendances :
    python -m pip install requests beautifulsoup4

Le script n'utilise ni le moteur de recherche du site, ni Selenium,
Playwright, Chrome ou un autre navigateur automatisé.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

VERSION = "2026.07.03-fr-listings-only-7"
BUILD_MARKER = "PROGT_FR_LISTINGS_ONLY_7_TRANSLATED_20260703"
ROOT_URL = "https://www.pro-gt.de/fr/"
OUTPUT_FILE = Path(__file__).with_name("gtteile.json")
TIMEOUT = 45

# Liste explicite des catégories françaises d'intérêt.
# « Véhicules » et « Kadett, Ascona, Manta, autre » sont volontairement absentes.
CATEGORY_URLS = (
    "https://www.pro-gt.de/fr/articles-en-caoutchouc-pu/",
    "https://www.pro-gt.de/fr/autre/",
    "https://www.pro-gt.de/fr/cabel-isolation/",
    "https://www.pro-gt.de/fr/carosserie/",
    "https://www.pro-gt.de/fr/conduite/",
    "https://www.pro-gt.de/fr/echappement/",
    "https://www.pro-gt.de/fr/elecricite-feux/",
    "https://www.pro-gt.de/fr/getriebe-motorraum-fr/",
    "https://www.pro-gt.de/fr/equipement-interieur/",
    "https://www.pro-gt.de/fr/freins/",
    "https://www.pro-gt.de/fr/instruments-boutons/",
    "https://www.pro-gt.de/fr/moulure-chrome/",
    "https://www.pro-gt.de/fr/pieces-utilidees/",
    "https://www.pro-gt.de/fr/suspension/",
    "https://www.pro-gt.de/fr/vitres/",
)

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
PRICE_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}€$")

# Les pages françaises comportent encore quelques titres allemands.
GERMAN_HINTS = re.compile(
    r"\b(?:für|und|satz|hinten|vorne|links|rechts|neu|schraube|scheibe|"
    r"dichtung|lager|kabel|blech|schalter|lenkung|heizung|tür|fenster|"
    r"auspuff|getriebe|zündung|schaltkulisse|gummipuffer|zierkeder|"
    r"heck|front|emblem|griff|rahmen|tülle)\b",
    re.IGNORECASE,
)
TRANSLATION_OVERRIDES = {
    "Schaltkulisse für 5-Gang Umbau": "Tringlerie de changement de vitesse pour conversion 5 rapports",
    "Zierkeder Heckscheibe, schwarz": "Jonc décoratif noir de lunette arrière",
    "Zierkeder Frontscheibe, schwarz": "Jonc décoratif noir de pare-brise",
    "Schale für Türöffnergriff, rechts": "Coquille de poignée d'ouverture intérieure droite",
    "Schale für Türöffnergriff, links": "Coquille de poignée d'ouverture intérieure gauche",
    "Türöffnergriff innen, links": "Poignée d'ouverture intérieure gauche",
    "Heckzierleiste Chrom": "Moulure arrière chromée",
    'Tülle "klein" für Emblem': "Petit passe-fil pour emblème",
    'Tülle "groß" für Emblem': "Grand passe-fil pour emblème",
    "GT Buchstaben, neu": "Lettres GT neuves",
    "OPEL Heckbuchstaben, neu": "Lettres arrière OPEL neuves",
}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def absolute_url(base: str, value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base, value)


def normalize_url(url: str, keep_query: bool = False) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/{2,}", "/", parsed.path)
    query = parsed.query if keep_query else ""
    return urlunparse(("https", "www.pro-gt.de", path, "", query, ""))


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
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
                "Mozilla/5.0 (X11; Linux) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,de;q=0.7,en;q=0.5",
            "Cache-Control": "no-cache",
            "DNT": "1",
        }
    )
    # La boutique est déjà en euros, mais ces cookies forcent EUR si le thème les lit.
    session.cookies.set("currency", "EUR")
    session.cookies.set("gx_currency", "EUR")
    return session


def fetch(session: requests.Session, url: str) -> tuple[str, str]:
    # Sécurité absolue : ce script ne doit jamais télécharger une fiche produit.
    # Les URL de fiches sont uniquement conservées dans le JSON de sortie.
    if is_product_url(url):
        raise RuntimeError(f"Consultation d'une fiche individuelle interdite : {url}")
    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    html = response.text
    low = html.lower()
    if (
        "please wait while your request is being verified" in low
        or "cf-chl-" in low
        or ("just a moment" in low and "challenge" in low)
    ):
        raise RuntimeError(f"Page de vérification anti-robot reçue pour {url}")
    if len(html) < 300:
        raise RuntimeError(f"Réponse HTML anormalement courte pour {url}")
    return html, response.url


def page_number(url: str) -> int | None:
    query = parse_qs(urlparse(url).query)
    for key in ("page", "p", "page_number"):
        try:
            if query.get(key):
                return max(1, int(query[key][0]))
        except ValueError:
            pass
    return None


def set_page(url: str, number: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["page"] = [str(number)]
    flat = [(key, item) for key, values in query.items() for item in values]
    return urlunparse(parsed._replace(query=urlencode(flat), fragment=""))


def infer_listing_pages(category_url: str, html: str) -> list[str]:
    """Détermine toutes les pages d'une catégorie à partir de sa première page."""
    soup = BeautifulSoup(html, "html.parser")
    category_path = urlparse(category_url).path.rstrip("/")
    pages: dict[int, str] = {1: category_url}

    for anchor in soup.select("a[href], link[href]"):
        candidate = absolute_url(category_url, anchor.get("href"))
        parsed = urlparse(candidate)
        if parsed.netloc.lower() not in {"pro-gt.de", "www.pro-gt.de"}:
            continue
        if parsed.path.rstrip("/") != category_path:
            continue
        number = page_number(candidate)
        if number:
            pages[number] = normalize_url(candidate, keep_query=True)

    # Exemples rencontrés sur le site :
    # « 1 bis 47 (von insgesamt 47) » ou « 1 à 100 (sur un total de 153) ».
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(
        r"(\d+)\s*(?:bis|to|à|a|-)\s*(\d+)\s*\(\s*"
        r"(?:von insgesamt|from a total of|sur un total de)\s*([\d .]+)\s*\)",
        text,
        re.IGNORECASE,
    )
    if match:
        first = int(match.group(1))
        last = int(match.group(2))
        total = int(re.sub(r"\D", "", match.group(3)))
        per_page = max(1, last - first + 1)
        for number in range(1, math.ceil(total / per_page) + 1):
            pages.setdefault(number, set_page(category_url, number))

    return [pages[number] for number in sorted(pages)]


def inspect_category(category_url: str) -> dict[str, Any]:
    session = make_session()
    html, final_url = fetch(session, category_url)
    final = normalize_url(final_url, keep_query=True)
    if "/en/" in final.lower() or ".php" in urlparse(final).path.lower():
        raise RuntimeError(f"Redirection inattendue vers une URL non autorisée : {final}")
    return {"category": category_url, "pages": infer_listing_pages(category_url, html)}


NON_PRODUCT_HTML_FILES = {
    "versand-und-zahlungsbedingungen.html",
    "shipping-and-payment-conditions.html",
    "conditions-dexpedition-et-de-paiement.html",
    "conditions-generales-de-vente.html",
    "datenschutz.html",
    "privacy.html",
    "widerrufsrecht.html",
    "withdrawal.html",
    "impressum.html",
    "contact.html",
    "sitemap.html",
}


def is_product_url(url: str) -> bool:
    """N'accepte que les véritables fiches produit françaises.

    Les fiches Gambio de pro-gt.de sont publiées directement sous
    ``/fr/<produit>.html``. Les pages techniques, notamment les fenêtres
    ``/fr/popup/*.html``, peuvent être présentes dans chaque carte produit ;
    elles ne doivent jamais être envoyées au parseur de fiches.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc.lower() not in {"pro-gt.de", "www.pro-gt.de"}:
        return False

    path = re.sub(r"/{2,}", "/", unquote(parsed.path or "/"))
    segments = [segment for segment in path.split("/") if segment]

    # Une fiche réelle a exactement la forme /fr/nom-du-produit.html.
    # Ce test élimine notamment /fr/<categorie>/fr/popup/...html.
    if len(segments) != 2 or segments[0].casefold() != "fr":
        return False

    filename = segments[1].casefold()
    if not filename.endswith(".html") or filename in NON_PRODUCT_HTML_FILES:
        return False
    if filename in {"index.html", "shop.html"}:
        return False
    return True


def _node_classes(node: Any) -> str:
    if not hasattr(node, "get"):
        return ""
    values = node.get("class") or []
    if isinstance(values, str):
        values = values.split()
    return " ".join(str(value) for value in values).casefold()


def _inside_non_catalogue_area(node: Any) -> bool:
    for parent in getattr(node, "parents", []):
        name = str(getattr(parent, "name", "") or "").casefold()
        if name in {"aside", "footer", "nav"}:
            return True
        marker = f"{_node_classes(parent)} {clean_text(parent.get('id') if hasattr(parent, 'get') else '')}".casefold()
        if any(word in marker for word in ("bestseller", "swiper", "recommend", "footer", "sidebar")):
            return True
    return False


def _product_url_from_card(card: Any, base_url: str) -> str:
    preferred_selectors = (
        ".title-description .title a[href]",
        ".title a[href]",
        ".product-name a[href]",
        "h2 a[href]",
        "h3 a[href]",
        ".product-image a[href]",
    )
    for selector in preferred_selectors:
        for anchor in card.select(selector):
            candidate = absolute_url(base_url, anchor.get("href"))
            if is_product_url(candidate):
                return normalize_url(candidate)

    candidates: list[str] = []
    for anchor in card.select("a[href]"):
        candidate = absolute_url(base_url, anchor.get("href"))
        if is_product_url(candidate):
            normalized = normalize_url(candidate)
            if normalized not in candidates:
                candidates.append(normalized)
    return candidates[0] if len(candidates) == 1 else ""


def _extract_listing_name(card: Any, product_url: str, base_url: str) -> str:
    candidates: list[tuple[int, int, str]] = []
    selectors = (
        ".title-description .title a[href]",
        ".title a[href]",
        ".product-name a[href]",
        "h2 a[href]",
        "h3 a[href]",
        "a[href]",
    )
    for priority, selector in enumerate(selectors):
        for anchor in card.select(selector):
            candidate = absolute_url(base_url, anchor.get("href"))
            if not is_product_url(candidate) or normalize_url(candidate) != product_url:
                continue
            text = clean_text(anchor.get_text(" ", strip=True))
            if text:
                candidates.append((priority, -len(text), text))

    if candidates:
        candidates.sort()
        return candidates[0][2]

    for image in card.select(".product-image img, figure img, img"):
        text = clean_text(image.get("alt") or image.get("title"))
        if text and not fold_text(text).startswith("preview"):
            return text
    return ""


def _extract_listing_photo(card: Any, base_url: str) -> str:
    selectors = (
        ".product-image img",
        "figure.product-image img",
        "figure img",
        "img[itemprop='image']",
        "img",
    )
    for selector in selectors:
        for image in card.select(selector):
            values = (
                image.get("data-src"),
                image.get("data-original"),
                image.get("data-lazy-src"),
                image.get("src"),
                image.get("srcset"),
            )
            for raw in values:
                if not raw:
                    continue
                value = str(raw).split(",")[0].strip().split(" ")[0]
                url = absolute_url(base_url, value)
                low = url.casefold()
                if url.startswith(("http://", "https://")) and not any(
                    marker in low
                    for marker in ("logo", "icon", "spinner", "pixel", "spacer", "placeholder")
                ):
                    return url
    return "inconnu"


def _candidate_product_cards(soup: BeautifulSoup, base_url: str) -> list[Any]:
    selectors = (
        ".productlist-viewmode-grid .product-container, "
        ".productlist-viewmode-list .product-container, "
        ".productlist-viewmode .product-container, "
        ".product-listing .product-container, "
        ".productlist .product-container, "
        "article.product, .product-box, .product-tile"
    )
    cards: list[Any] = []
    seen_nodes: set[int] = set()
    for card in soup.select(selectors):
        if id(card) in seen_nodes or _inside_non_catalogue_area(card):
            continue
        if _product_url_from_card(card, base_url):
            cards.append(card)
            seen_nodes.add(id(card))

    if cards:
        return cards

    # Repli : remonter depuis chaque lien produit jusqu'au plus petit bloc qui
    # contient prix et informations de livraison, sans jamais ouvrir le lien.
    main = soup.select_one("main, #content, .main-inside, .content-wrapper") or soup
    price_hint = re.compile(r"\d+[,.]\d{2}\s*(?:EUR|€)", re.IGNORECASE)
    for anchor in main.select("a[href]"):
        if _inside_non_catalogue_area(anchor):
            continue
        candidate = absolute_url(base_url, anchor.get("href"))
        if not is_product_url(candidate):
            continue
        for parent in anchor.parents:
            if getattr(parent, "name", None) in {"main", "body", "html", None}:
                break
            context = clean_text(parent.get_text(" ", strip=True))
            folded = fold_text(context)
            urls = {
                normalize_url(absolute_url(base_url, a.get("href")))
                for a in parent.select("a[href]")
                if is_product_url(absolute_url(base_url, a.get("href")))
            }
            if len(urls) == 1 and price_hint.search(context) and any(
                marker in folded
                for marker in ("temps de livraison", "ajouter au panier", "sold out")
            ):
                if id(parent) not in seen_nodes:
                    cards.append(parent)
                    seen_nodes.add(id(parent))
                break
    return cards


def extract_listing_products(
    html: str,
    base_url: str,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Extrait toutes les informations directement depuis une page catalogue."""
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, dict[str, str]] = {}

    for card in _candidate_product_cards(soup, base_url):
        product_url = _product_url_from_card(card, base_url)
        if not product_url:
            continue
        name = _extract_listing_name(card, product_url, base_url)
        if not name:
            continue
        translated = translate_to_french(session, name) if session is not None else name
        product = {
            "nom": name,
            "nom_traduit": translated,
            "prix": extract_price(card, {}),
            "disponibilite": extract_availability(card, {}),
            "url_photo": _extract_listing_photo(card, base_url),
            "url_fiche": product_url,
        }
        previous = products.get(product_url)
        if previous is None:
            products[product_url] = product
        else:
            # En cas de double représentation grille/liste, conserver les
            # informations les plus complètes sans aucune nouvelle requête.
            for field in ("prix", "disponibilite", "url_photo"):
                if previous[field] == "inconnu" and product[field] != "inconnu":
                    previous[field] = product[field]
            if previous["nom_traduit"] == previous["nom"] and product["nom_traduit"] != product["nom"]:
                previous["nom_traduit"] = product["nom_traduit"]

    return list(products.values())


def scrape_listing_page(page_url: str) -> dict[str, Any]:
    if is_product_url(page_url):
        raise RuntimeError(f"Une fiche produit a été envoyée au parseur catalogue : {page_url}")
    session = make_session()
    html, final_url = fetch(session, page_url)
    return {
        "page": page_url,
        "products": extract_listing_products(html, final_url, session),
    }


def parse_decimal(raw: str) -> Decimal:
    value = re.sub(r"[^\d,.-]", "", raw.replace("\xa0", " ").strip())
    if not value:
        raise InvalidOperation
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif value.count(".") > 1:
        value = value.replace(".", "")
    return Decimal(value)


@lru_cache(maxsize=1)
def ecb_rates() -> dict[str, Decimal]:
    """Retourne le nombre d'unités de chaque devise pour un euro."""
    response = make_session().get(
        "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    rates = {"EUR": Decimal("1")}
    for currency, rate in re.findall(
        r"currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([\d.]+)['\"]",
        response.text,
    ):
        rates[currency] = Decimal(rate)
    return rates


def to_euro(amount: Decimal, currency: str) -> Decimal:
    currency = currency.upper()
    if currency == "EUR":
        return amount
    rates = ecb_rates()
    if currency not in rates:
        raise ValueError(f"Devise non publiée par la BCE : {currency}")
    return amount / rates[currency]


def format_euro(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, decimals = f"{amount:.2f}".split(".")
    return f"{int(integer):,}".replace(",", ".") + f",{decimals}€"


def extract_price(soup: BeautifulSoup, structured: dict[str, Any]) -> str:
    offers = structured.get("offers", {})
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), {})
    if isinstance(offers, dict) and offers.get("price") not in (None, ""):
        try:
            amount = parse_decimal(str(offers["price"]))
            currency = clean_text(offers.get("priceCurrency") or "EUR")
            return format_euro(to_euro(amount, currency))
        except (InvalidOperation, ValueError, ArithmeticError):
            pass

    candidates: list[str] = []
    for selector in (
        "meta[itemprop='price']",
        "meta[property='product:price:amount']",
        "[itemprop='price']",
        ".current-price-container",
        ".product-info-price",
        ".product-price",
        "#product_info .price",
        ".price",
    ):
        for node in soup.select(selector):
            value = node.get("content") or node.get_text(" ", strip=True)
            if value:
                candidates.append(clean_text(value))
    candidates.append(clean_text(soup.get_text(" ", strip=True)))

    pattern = re.compile(
        r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*|\d+)(?:[,.](\d{1,2}))?\s*"
        r"(EUR|€|USD|GBP|CHF|CAD|AUD)",
        re.IGNORECASE,
    )
    for text in candidates:
        match = pattern.search(text)
        if not match:
            continue
        major = match.group(1).replace(" ", "")
        cents = (match.group(2) or "0").ljust(2, "0")
        currency = match.group(3).upper().replace("€", "EUR")
        try:
            return format_euro(to_euro(parse_decimal(f"{major},{cents}"), currency))
        except (InvalidOperation, ValueError, ArithmeticError):
            pass
    return "inconnu"


def extract_availability(soup: BeautifulSoup, structured: dict[str, Any]) -> str:
    text = fold_text(soup.get_text(" ", strip=True))

    if any(marker in text for marker in ("sur demande", "prix sur demande", "on request", "auf anfrage")):
        return "sur demande"
    if any(
        marker in text
        for marker in (
            "sold out",
            "out of stock",
            "temporairement epuise",
            "temporairement equise",
            "article est actuellement indisponible",
            "artikel ist aktuell nicht verfugbar",
        )
    ):
        return "en rupture de stock"
    if any(
        marker in text
        for marker in (
            "reapprovisionnement",
            "bientot disponible",
            "available soon",
            "backorder",
            "back order",
            "preorder",
            "pre order",
            "lieferbar ab",
            "wieder lieferbar",
        )
    ):
        return "réapprovisionnement"

    offers = structured.get("offers", {})
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), {})
    availability = fold_text(offers.get("availability") if isinstance(offers, dict) else "")
    if "outofstock" in availability or "discontinued" in availability:
        return "en rupture de stock"
    if "preorder" in availability or "backorder" in availability:
        return "réapprovisionnement"
    if "instock" in availability:
        return "en stock"

    delivery = re.search(
        r"(?:env(?:iron)?|approx?|ca)?\s*(\d+)\s*(?:a|to|-)?\s*(\d+)?\s*"
        r"(jours?|days?|tage?|semaines?|weeks?|wochen?)",
        text,
        re.IGNORECASE,
    )
    if delivery:
        maximum = int(delivery.group(2) or delivery.group(1))
        unit = delivery.group(3).lower()
        if any(word in unit for word in ("semaine", "week", "woche")) or maximum > 7:
            return "réapprovisionnement"
        return "en stock"

    if any(marker in text for marker in ("ajouter au panier", "add to cart", "in den warenkorb")):
        return "en stock"
    return "inconnu"


def translate_to_french(session: requests.Session, name: str) -> str:
    """Traduit systématiquement le nom source en français.

    La version précédente ne lançait la traduction que si quelques mots
    allemands étaient détectés. Cela laissait beaucoup de désignations
    inchangées dans ``nom_traduit``. Ici, chaque nom extrait depuis une page
    catalogue est envoyé au service de traduction ; si le nom est déjà en
    français, la réponse reste naturellement identique ou quasi identique.
    Aucune fiche produit n'est consultée.
    """
    name = clean_text(name)
    if not name:
        return name
    if name in TRANSLATION_OVERRIDES:
        return TRANSLATION_OVERRIDES[name]

    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=auto&tl=fr&dt=t&q=" + quote(name)
    )
    try:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        translated = "".join(part[0] for part in payload[0] if part and part[0])
        translated = clean_text(translated)
        return translated or name
    except Exception:
        return name


def parallel_map(function: Any, values: list[str], workers: int, label: str) -> list[Any]:
    if not values:
        return []
    results: list[Any] = []
    errors: list[str] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(values))) as executor:
        futures = {executor.submit(function, value): value for value in values}
        for done, future in enumerate(as_completed(futures), start=1):
            source = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(f"{source}: {exc}")
            print(f"\r{label}: {done}/{len(values)}", end="", flush=True)
    print()
    if errors:
        detail = "\n".join(errors[:20])
        if len(errors) > 20:
            detail += f"\n... et {len(errors) - 20} autre(s) erreur(s)"
        raise RuntimeError(f"Échec de {len(errors)} tâche(s):\n{detail}")
    return results


def validate_catalog(catalog: Any) -> None:
    if not isinstance(catalog, list):
        raise ValueError("La racine du JSON doit être un tableau.")
    if not catalog:
        raise ValueError("Le catalogue est vide.")

    seen: set[str] = set()
    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            raise ValueError(f"Élément {index}: objet JSON attendu.")
        if tuple(item.keys()) != FIELDS:
            raise ValueError(f"Élément {index}: les six champs sont incorrects ou mal ordonnés.")
        if not clean_text(item["nom"]) or not clean_text(item["nom_traduit"]):
            raise ValueError(f"Élément {index}: nom vide.")
        if item["prix"] != "inconnu" and not PRICE_RE.fullmatch(item["prix"]):
            raise ValueError(f"Élément {index}: prix invalide {item['prix']!r}.")
        if item["disponibilite"] not in AVAILABILITIES:
            raise ValueError(f"Élément {index}: disponibilité invalide.")
        if item["url_photo"] != "inconnu" and not str(item["url_photo"]).startswith(("http://", "https://")):
            raise ValueError(f"Élément {index}: URL photo invalide.")
        fiche = str(item["url_fiche"])
        if not is_product_url(fiche):
            raise ValueError(f"Élément {index}: URL fiche produit invalide {fiche!r}.")
        if fiche in seen:
            raise ValueError(f"Élément {index}: doublon {fiche}.")
        seen.add(fiche)


def write_json_atomic(path: Path, catalog: list[dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def startup_checks() -> None:
    if ROOT_URL != "https://www.pro-gt.de/fr/":
        raise AssertionError(f"Racine inattendue : {ROOT_URL}")
    if len(CATEGORY_URLS) != 15:
        raise AssertionError(f"15 catégories attendues, {len(CATEGORY_URLS)} trouvées.")
    if len(set(CATEGORY_URLS)) != len(CATEGORY_URLS):
        raise AssertionError("Une catégorie est dupliquée.")
    forbidden = ("/en/", ".php", "/vehicules/", "/kadett-ascona-manta-autre/")
    for url in CATEGORY_URLS:
        if not url.startswith(ROOT_URL) or any(marker in url.lower() for marker in forbidden):
            raise AssertionError(f"Catégorie interdite ou invalide : {url}")

    # Tests de non-régression sur le bug des liens de conditions de livraison.
    valid_product = "https://www.pro-gt.de/fr/Warnblinkschalter.html"
    invalid_products = (
        "https://www.pro-gt.de/fr/popup/Versand-und-Zahlungsbedingungen.html",
        "https://www.pro-gt.de/fr/echappement/fr/popup/Versand-und-Zahlungsbedingungen.html",
        "https://www.pro-gt.de/fr/info/conditions-generales-de-vente.html",
        "https://www.pro-gt.de/fr/shop.php/",
    )
    if not is_product_url(valid_product):
        raise AssertionError(f"Une vraie fiche produit est rejetée : {valid_product}")
    for url in invalid_products:
        if is_product_url(url):
            raise AssertionError(f"Une page technique est acceptée comme produit : {url}")

    test_html = """
    <div class="productlist-viewmode-grid">
      <div class="product-container">
        <div class="product-tile">
          <figure class="product-image"><a href="/fr/Testprodukt.html"><img data-src="/images/test.jpg" alt="Testprodukt"></a></figure>
          <div class="title-description"><div class="title"><a href="/fr/Testprodukt.html">Testprodukt</a></div></div>
          <div class="shipping-info-short">Temps de livraison: env. 2-3 jours</div>
          <div class="price-tax"><span class="price">19,90 EUR</span></div>
          <a href="/fr/popup/Versand-und-Zahlungsbedingungen.html">Livraison</a>
          <button>Ajouter au panier</button>
        </div>
      </div>
    </div>
    """
    parsed = extract_listing_products(test_html, ROOT_URL)
    if len(parsed) != 1:
        raise AssertionError(f"Test du parseur catalogue en échec : {len(parsed)} produit(s).")
    sample = parsed[0]
    if sample["url_fiche"] != valid_product.replace("Warnblinkschalter", "Testprodukt"):
        raise AssertionError("URL produit incorrecte dans le test du parseur catalogue.")
    if sample["prix"] != "19,90€" or sample["disponibilite"] != "en stock":
        raise AssertionError("Prix ou disponibilité incorrects dans le test du parseur catalogue.")
    if translate_to_french(make_session(), "Schaltkulisse für 5-Gang Umbau") != TRANSLATION_OVERRIDES["Schaltkulisse für 5-Gang Umbau"]:
        raise AssertionError("Test de traduction en échec.")


def file_fingerprint() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return "indisponible"


def build_catalog(output: Path, workers: int) -> list[dict[str, str]]:
    startup_checks()
    print(f"gtteile.py version {VERSION}")
    print(f"Build : {BUILD_MARKER}")
    print(f"Script exécuté : {Path(__file__).resolve()}")
    print(f"Empreinte SHA-256 : {file_fingerprint()}")
    print(f"Racine imposée : {ROOT_URL}")

    print(f"1/4 Visite parallèle des {len(CATEGORY_URLS)} catégories françaises autorisées")
    category_data = parallel_map(inspect_category, list(CATEGORY_URLS), workers, "    Catégories")
    listing_pages = sorted({page for item in category_data for page in item["pages"]})
    if not listing_pages:
        raise RuntimeError("Aucune page catalogue détectée.")
    print(f"    {len(listing_pages)} page(s) catalogue détectée(s).")

    print("2/4 Lecture et parsing parallèles de toutes les pages catalogue")
    listing_data = parallel_map(scrape_listing_page, listing_pages, workers, "    Pages")
    occurrences = sum(len(item["products"]) for item in listing_data)

    print("3/4 Union des informations extraites des pages catalogue")
    union: dict[str, dict[str, str]] = {}
    for item in listing_data:
        for product in item["products"]:
            url = product["url_fiche"]
            if not is_product_url(url):
                continue
            previous = union.get(url)
            if previous is None:
                union[url] = product
                continue
            for field in ("prix", "disponibilite", "url_photo"):
                if previous[field] == "inconnu" and product[field] != "inconnu":
                    previous[field] = product[field]
            if previous["nom_traduit"] == previous["nom"] and product["nom_traduit"] != product["nom"]:
                previous["nom_traduit"] = product["nom_traduit"]

    catalog = list(union.values())
    if not catalog:
        raise RuntimeError("Aucun produit détecté dans les pages catalogue.")
    catalog.sort(key=lambda item: (item["nom_traduit"].casefold(), item["url_fiche"]))
    print(f"    {occurrences} occurrence(s), {len(catalog)} produit(s) unique(s).")
    print("    Fiches individuelles consultées : 0")

    print("4/4 Validation stricte et écriture du JSON")
    validate_catalog(catalog)
    write_json_atomic(output, catalog)
    print(f"    JSON valide : {len(catalog)} produits, exactement 6 champs par produit.")
    print(f"    Fichier écrit : {output.resolve()}")
    return catalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT_FILE)
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=os.cpu_count() or 1,
        help="nombre de processus (par défaut : tous les processeurs disponibles)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="valide uniquement le fichier JSON existant",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION} [{BUILD_MARKER}]")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers doit être supérieur ou égal à 1")

    if args.validate_only:
        startup_checks()
        data = json.loads(args.output.read_text(encoding="utf-8"))
        validate_catalog(data)
        print(f"JSON valide : {len(data)} éléments, six champs conformes par élément.")
        return 0

    started = time.monotonic()
    build_catalog(args.output, args.workers)
    print(f"Terminé en {time.monotonic() - started:.1f} s.")
    return 0


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import ScrapeResult as ScrapeResult, run_legacy_scraper as _run_legacy_scraper, scraper_cli as _scraper_cli

_LEGACY_MAIN = main
_SUPPLIER_NAME = 'GT Teile / Pro-GT'
_SUPPLIER_LANG = 'fr'
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name('gtteile.json')
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
