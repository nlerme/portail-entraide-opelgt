#!/usr/bin/env python3
"""Récupère le catalogue Opel GT Source sans ouvrir les fiches produit.

Dépendances :
    python -m pip install requests beautifulsoup4

Sortie : opelgtsource.json, dans le répertoire du script.
"""

from __future__ import annotations

import json
import math
import os
import re
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from datetime import date
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from catalog_progress import advance_phase, report_progress as publish_progress, start_phase
from scraper_common import BUNDLE_VERSION

VERSION = BUNDLE_VERSION
BUILD = "OGS_TURBO_CACHE_V8_20260710"
ROOT_URL = "https://www.opelgtsource.com/search?car_id=4"
BASE_URL = "https://www.opelgtsource.com"
PAGINATE_URL = f"{BASE_URL}/search/paginate"
OUTPUT_FILE = Path(__file__).resolve().with_name("opelgtsource.json")

HTTP_TIMEOUT = (6, 22)
# v8 : mode turbo. On démarre vite, on ralentit seulement si le serveur proteste.
# Sur une machine déjà synchronisée, OGS_CACHE_MODE=prefer lit les pages HTML en cache
# et ne retélécharge rien. Le cache est stable entre versions du script.
PAGE_WORKERS = max(1, min(32, int(os.getenv("OGS_PAGE_WORKERS", "16"))))
PAGE_BATCH_SIZE = max(PAGE_WORKERS, int(os.getenv("OGS_PAGE_BATCH_SIZE", "9999")))
PAGE_BATCH_PAUSE = max(0.0, float(os.getenv("OGS_PAGE_BATCH_PAUSE", "0.0")))
REQUEST_GAP = max(0.0, float(os.getenv("OGS_REQUEST_GAP", "0.0")))
MAX_PAGE_ATTEMPTS = max(1, int(os.getenv("OGS_MAX_PAGE_ATTEMPTS", "2")))
SERVER_COOLDOWN = max(1.0, float(os.getenv("OGS_SERVER_COOLDOWN", "8.0")))
TRANSLATION_WORKERS = max(1, int(os.getenv("OGS_TRANSLATION_WORKERS", min(24, max(8, (os.cpu_count() or 1) * 2)))))
CACHE_MODE = os.getenv("OGS_CACHE_MODE", "prefer").strip().casefold()  # refresh | prefer | only | off
PAGE_SIZE_PROBE = os.getenv("OGS_PAGE_SIZE_PROBE", "0").strip().casefold() not in {"0", "false", "no", "off"}
FORCED_PAGE_SIZE_PARAM = os.getenv("OGS_PAGE_SIZE_PARAM", "").strip()
FORCED_PAGE_SIZE_VALUE = os.getenv("OGS_PAGE_SIZE_VALUE", "").strip()
_DEFAULT_CACHE_DIR = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "entraide-opel-gt" / "opelgtsource"
CACHE_DIR = Path(os.getenv("OGS_CACHE_DIR", str(_DEFAULT_CACHE_DIR)))
PAGE_CACHE_DIR = CACHE_DIR / "opelgtsource_pages"
TRANSLATION_CACHE_FILE = CACHE_DIR / "opelgtsource_translations.json"
RATE_CACHE_FILE = CACHE_DIR / "exchange_rates.json"

DETAIL_PATH_RE = re.compile(r"^/search/\d+/details/?$", re.I)
USD_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
PRICE_EUR_RE = re.compile(r"^(?:inconnu|\d{1,3}(?: \d{3})*,\d{2}€)$")
PART_RE = re.compile(r"^Part\s*:\s*", re.I)
ALLOWED_AVAILABILITY = {
    "en stock",
    "en rupture de stock",
    "réapprovisionnement",
    "sur demande",
    "inconnu",
}
FIELDS = ("nom", "nom_traduit", "prix", "disponibilite", "url_photo", "url_fiche")

_thread_local = threading.local()
_request_lock = threading.Lock()
_request_log: list[str] = []
_bootstrap_cookies: dict[str, str] = {}
_rate_lock = threading.Lock()
_next_request_at = 0.0
_cooldown_until = 0.0
_dynamic_gap = REQUEST_GAP
_success_streak = 0
_order_by = ""
_page_size_param = ""
_page_size_value = ""


@dataclass(frozen=True)
class PageResult:
    page: int
    products: list[dict[str, str]]


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _json_load(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _json_write_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _safe_order_slug() -> str:
    base = (_order_by or "unknown")
    if _page_size_param and _page_size_value:
        base += f"_{_page_size_param}_{_page_size_value}"
    return re.sub(r"[^a-z0-9_-]+", "_", base.casefold()).strip("_") or "unknown"


def _page_cache_path(page: int) -> Path:
    return PAGE_CACHE_DIR / f"{_safe_order_slug()}_page_{page:03d}.html"


def _load_cached_page(page: int) -> str | None:
    if CACHE_MODE == "off":
        return None
    path = _page_cache_path(page)
    try:
        text = path.read_text(encoding="utf-8")
        return text if text.strip() else None
    except OSError:
        return None


def _save_cached_page(page: int, html: str) -> None:
    if CACHE_MODE == "off":
        return
    path = _page_cache_path(page)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(path)


def build_session() -> requests.Session:
    session = requests.Session()
    # Les codes 429/5xx sont repris manuellement afin que tous les threads
    # partagent le même refroidissement au lieu de réessayer en rafale.
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=0,
        backoff_factor=0.5,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.7",
            "Referer": ROOT_URL,
        }
    )
    if _bootstrap_cookies:
        session.cookies.update(_bootstrap_cookies)
    return session


def session() -> requests.Session:
    current = getattr(_thread_local, "session", None)
    if current is None:
        current = build_session()
        _thread_local.session = current
    return current


def is_product_detail_url(url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, url))
    return parsed.netloc.lower() in {"opelgtsource.com", "www.opelgtsource.com"} and bool(
        DETAIL_PATH_RE.fullmatch(parsed.path)
    )


def _retry_after_seconds(response: requests.Response) -> float | None:
    raw = compact(response.headers.get("Retry-After", ""))
    if raw.isdigit():
        return max(1.0, float(raw))
    return None


def _wait_for_catalogue_slot() -> None:
    global _next_request_at
    while True:
        with _rate_lock:
            now = time.monotonic()
            target = max(_next_request_at, _cooldown_until)
            if now >= target:
                _next_request_at = now + _dynamic_gap + random.uniform(0.0, 0.35)
                return
            delay = target - now
        time.sleep(delay)


def _set_shared_cooldown(seconds: float) -> None:
    global _cooldown_until
    with _rate_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


def _register_server_throttle(attempt: int, retry_after: float | None = None) -> float:
    """Ralentit toutes les tâches dès qu'un 429/503 est observé."""
    global _dynamic_gap, _success_streak
    with _rate_lock:
        _success_streak = 0
        _dynamic_gap = min(15.0, max(_dynamic_gap * 1.7, REQUEST_GAP + 1.5))
        delay = retry_after or min(240.0, SERVER_COOLDOWN * (1.55 ** (attempt - 1)))
    _set_shared_cooldown(delay + random.uniform(1.0, 4.0))
    return delay


def _register_catalogue_success() -> None:
    global _dynamic_gap, _success_streak
    with _rate_lock:
        _success_streak += 1
        if _success_streak >= 10 and _dynamic_gap > REQUEST_GAP:
            _dynamic_gap = max(REQUEST_GAP, _dynamic_gap - 0.5)
            _success_streak = 0


def get(url: str, *, params: dict[str, object] | None = None) -> requests.Response:
    final_url = requests.Request("GET", url, params=params).prepare().url or url
    if is_product_detail_url(final_url):
        raise RuntimeError(f"Lecture d'une fiche individuelle interdite : {final_url}")

    host = urlparse(final_url).netloc.lower()
    is_catalogue = host in {"opelgtsource.com", "www.opelgtsource.com"}
    attempts = MAX_PAGE_ATTEMPTS if is_catalogue else 3
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        if is_catalogue:
            _wait_for_catalogue_slot()
        try:
            request_headers = (
                {"X-Requested-With": "XMLHttpRequest"}
                if urlparse(final_url).path.rstrip("/") == "/search/paginate"
                else None
            )
            response = session().get(
                url, params=params, headers=request_headers, timeout=HTTP_TIMEOUT
            )
            if response.status_code < 400:
                if is_catalogue:
                    _register_catalogue_success()
                with _request_lock:
                    _request_log.append(response.url)
                return response

            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()

            retry_after = _retry_after_seconds(response)
            if is_catalogue and response.status_code in {429, 503}:
                delay = _register_server_throttle(attempt, retry_after)
            else:
                delay = retry_after or min(90.0, 4.0 * (2 ** (attempt - 1)))
                delay += random.uniform(0.5, 2.0)
                if is_catalogue:
                    _set_shared_cooldown(delay)
                else:
                    time.sleep(delay)
            last_error = requests.HTTPError(
                f"HTTP {response.status_code} pour {response.url} "
                f"(tentative {attempt}/{attempts})",
                response=response,
            )
        except requests.RequestException as exc:
            last_error = exc
            delay = min(30.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0.2, 1.0)
            if is_catalogue:
                _set_shared_cooldown(delay)
            else:
                time.sleep(delay)

    assert last_error is not None
    raise last_error


def detect_price_ascending_order(html: str) -> str:
    """Retourne la valeur HTML associée à « Price Low to High »."""
    soup = BeautifulSoup(html, "html.parser")

    # Cas normal : <option value="...">Price Low to High</option>.
    for option in soup.find_all("option"):
        label = compact(option.get_text(" ", strip=True)).casefold()
        if label == "price low to high":
            value = compact(str(option.get("value", "")))
            if value:
                return value

    # Repli pour les sélecteurs personnalisés utilisant des attributs data-*.
    for tag in soup.find_all(True):
        label = compact(tag.get_text(" ", strip=True)).casefold()
        if label != "price low to high":
            continue
        for attribute in ("data-value", "data-order-by", "value"):
            value = compact(str(tag.get(attribute, "")))
            if value:
                return value

    # Dernier repli : extraction locale dans le HTML brut.
    patterns = (
        r'<option[^>]+value=["\']([^"\']+)["\'][^>]*>\s*Price\s+Low\s+to\s+High\s*</option>',
        r'Price\s+Low\s+to\s+High[^>]{0,300}data-(?:value|order-by)=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return compact(match.group(1))

    raise RuntimeError(
        "Valeur du tri « Price Low to High » introuvable dans la page initiale."
    )


def page_params(page: int) -> dict[str, object]:
    if not _order_by:
        raise RuntimeError("Le tri prix croissant n'a pas été initialisé.")
    params: dict[str, object] = {"car_id": 4, "order_by": _order_by, "page": page, "search": ""}
    if _page_size_param and _page_size_value:
        params[_page_size_param] = _page_size_value
    return params


def page_params_with_size(page: int, param: str, value: str) -> dict[str, object]:
    params: dict[str, object] = {"car_id": 4, "order_by": _order_by, "page": page, "search": ""}
    if param and value:
        params[param] = value
    return params


def extract_page_number(href: str) -> int | None:
    try:
        values = parse_qs(urlparse(urljoin(BASE_URL, href)).query).get("page", [])
        if values and values[0].isdigit():
            return int(values[0])
    except (ValueError, TypeError):
        pass
    return None


def detect_page_count(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    numbers: set[int] = {1}

    for anchor in soup.find_all("a", href=True):
        page = extract_page_number(str(anchor.get("href", "")))
        if page and page > 0:
            numbers.add(page)

    # Certains gabarits stockent l'URL de la dernière page dans data-*.
    for tag in soup.find_all(True):
        for key, value in tag.attrs.items():
            if key.startswith("data-") and isinstance(value, str):
                page = extract_page_number(value)
                if page and page > 0:
                    numbers.add(page)

    count = max(numbers)
    if count <= 1:
        raise RuntimeError("Nombre de pages introuvable dans la pagination du catalogue.")
    return count


def canonical_detail_url(href: str) -> str | None:
    absolute = urljoin(BASE_URL, href)
    parsed = urlparse(absolute)
    if parsed.netloc.lower() not in {"opelgtsource.com", "www.opelgtsource.com"}:
        return None
    if not DETAIL_PATH_RE.fullmatch(parsed.path):
        return None
    return f"{BASE_URL}{parsed.path.rstrip('/')}"


def detail_urls_in(tag: Tag) -> set[str]:
    urls: set[str] = set()
    for anchor in tag.find_all("a", href=True):
        url = canonical_detail_url(str(anchor.get("href", "")))
        if url:
            urls.add(url)
    return urls


def find_product_card(anchors: list[Tag], product_url: str) -> Tag | None:
    candidates: list[tuple[int, Tag]] = []
    for anchor in anchors:
        depth = 0
        for parent in anchor.parents:
            if not isinstance(parent, Tag) or parent.name in {"body", "html"}:
                break
            depth += 1
            text = compact(parent.get_text(" ", strip=True))
            if "Part:" not in text:
                continue
            urls = detail_urls_in(parent)
            if urls == {product_url}:
                candidates.append((len(str(parent)), parent))
                break
            if len(urls) > 1:
                break
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def text_lines(card: Tag) -> list[str]:
    return [compact(line) for line in card.get_text("\n", strip=True).splitlines() if compact(line)]


def extract_name(card: Tag) -> str:
    lines = text_lines(card)
    for index, line in enumerate(lines):
        if PART_RE.match(line):
            for previous in reversed(lines[:index]):
                if USD_RE.fullmatch(previous):
                    continue
                if previous.lower() in {"details", "add to cart", "out stock", "out of stock"}:
                    continue
                return previous

    # Repli sur un titre ou sur l'attribut alt de l'image.
    for selector in ("h1", "h2", "h3", "h4", "h5", ".title", ".product-title", ".name"):
        node = card.select_one(selector)
        if node:
            value = compact(node.get_text(" ", strip=True))
            if value:
                return value
    for image in card.find_all("img"):
        value = compact(str(image.get("alt", "")))
        if value:
            return value
    raise ValueError("nom introuvable")


def extract_usd_price(card: Tag) -> Decimal | None:
    match = USD_RE.search(card.get_text(" ", strip=True))
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def extract_availability(card: Tag) -> str:
    text = compact(card.get_text(" ", strip=True)).lower()
    if any(token in text for token in ("out stock", "out of stock", "sold out", "unavailable")):
        return "en rupture de stock"
    if any(token in text for token in ("back order", "backorder", "restocking", "temporarily out")):
        return "réapprovisionnement"
    if any(token in text for token in ("special order", "on request", "call to order", "call for price")):
        return "sur demande"
    if "add to cart" in text:
        return "en stock"
    return "inconnu"


def extract_photo(card: Tag, product_url: str) -> str:
    images: list[Tag] = []
    for anchor in card.find_all("a", href=True):
        if canonical_detail_url(str(anchor.get("href", ""))) == product_url:
            images.extend(anchor.find_all("img"))
    images.extend(card.find_all("img"))

    seen: set[int] = set()
    for image in images:
        if id(image) in seen:
            continue
        seen.add(id(image))
        for attribute in ("data-original", "data-lazy-src", "data-src", "src"):
            raw = compact(str(image.get(attribute, "")))
            if not raw or raw.startswith("data:") or raw in {"#", "/"}:
                continue
            return urljoin(BASE_URL, raw)
    return "inconnu"


def parse_page(page: int, html: str) -> PageResult:
    soup = BeautifulSoup(html, "html.parser")
    grouped: dict[str, list[Tag]] = {}
    order: list[str] = []

    for anchor in soup.find_all("a", href=True):
        url = canonical_detail_url(str(anchor.get("href", "")))
        if not url:
            continue
        if url not in grouped:
            grouped[url] = []
            order.append(url)
        grouped[url].append(anchor)

    products: list[dict[str, str]] = []
    for product_url in order:
        card = find_product_card(grouped[product_url], product_url)
        if card is None:
            raise RuntimeError(f"page {page}: bloc produit introuvable pour {product_url}")
        try:
            name = extract_name(card)
        except ValueError as exc:
            raise RuntimeError(f"page {page}: {exc} pour {product_url}") from exc
        usd = extract_usd_price(card)
        products.append(
            {
                "nom": name,
                "nom_traduit": "",
                "_prix_usd": "" if usd is None else str(usd),
                "disponibilite": extract_availability(card),
                "url_photo": extract_photo(card, product_url),
                "url_fiche": product_url,
            }
        )

    if not products:
        raise RuntimeError(f"page {page}: aucune pièce détectée")
    return PageResult(page=page, products=products)


def fetch_page(page: int) -> PageResult:
    cached = _load_cached_page(page)
    if CACHE_MODE in {"prefer", "only"} and cached:
        return parse_page(page, cached)
    if CACHE_MODE == "only" and not cached:
        raise RuntimeError(f"page {page}: cache absent en mode OGS_CACHE_MODE=only")

    try:
        response = get(PAGINATE_URL, params=page_params(page))
        _save_cached_page(page, response.text)
        return parse_page(page, response.text)
    except Exception as exc:
        if cached:
            print(f"\n    Page {page}: réseau indisponible, ancien cache HTML utilisé ({exc})")
            return parse_page(page, cached)
        raise


def usd_to_eur_rate() -> Decimal:
    configured = os.getenv("OGS_USD_EUR_RATE", "").strip()
    if configured:
        try:
            rate = Decimal(configured.replace(",", "."))
            if rate > 0:
                return rate
        except InvalidOperation:
            pass
        raise RuntimeError("OGS_USD_EUR_RATE invalide.")

    today = date.today().isoformat()
    cached = _json_load(RATE_CACHE_FILE, {})
    if isinstance(cached, dict):
        raw = cached.get("USD_EUR")
        if cached.get("date") == today and raw is not None:
            try:
                rate = Decimal(str(raw))
                if rate > 0:
                    return rate
            except InvalidOperation:
                pass

    # Source principale : BCE, où USD indique le nombre de dollars pour 1 euro.
    try:
        response = session().get(
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        match = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([0-9.]+)['\"]", response.text)
        if match:
            usd_per_eur = Decimal(match.group(1))
            if usd_per_eur > 0:
                rate = Decimal("1") / usd_per_eur
                _json_write_atomic(RATE_CACHE_FILE, {"date": today, "USD_EUR": str(rate)})
                return rate
    except (requests.RequestException, InvalidOperation):
        pass

    # Repli : API Frankfurter, adossée aux taux de référence de la BCE.
    try:
        response = session().get(
            "https://api.frankfurter.app/latest",
            params={"from": "USD", "to": "EUR"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        rate = Decimal(str(response.json()["rates"]["EUR"]))
        if rate > 0:
            _json_write_atomic(RATE_CACHE_FILE, {"date": today, "USD_EUR": str(rate)})
            return rate
    except (requests.RequestException, KeyError, ValueError, InvalidOperation):
        pass

    raise RuntimeError(
        "Impossible d'obtenir le taux USD→EUR. "
        "Définissez OGS_USD_EUR_RATE, par exemple OGS_USD_EUR_RATE=0.86."
    )


def format_euro(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{rounded:,.2f}".replace(",", "\u0000").replace(".", ",").replace("\u0000", " ")
    return f"{formatted}€"


def translate_results(results: dict[int, PageResult]) -> dict[int, PageResult]:
    from catalog_translation import translate_names
    start_phase("translations", 85, 94, 0, "Désignations traitées")

    translations = translate_names(
        [product["nom"] for page in sorted(results) for product in results[page].products],
        language="en", cache_file=TRANSLATION_CACHE_FILE,
        previous_output=Path(os.getenv("CATALOG_PREVIOUS_OUTPUT", str(OUTPUT_FILE))),
        workers=TRANSLATION_WORKERS,
    )
    return {
        page: PageResult(page=page, products=[
            {**product, "nom_traduit": translations[product["nom"]]} for product in result.products
        ])
        for page, result in results.items()
    }


def expected_total_from_default_pagination(default_page_count: int, first_result: PageResult) -> int | None:
    """Calcule le total attendu via la dernière page du mode standard.

    L'endpoint ne publie pas toujours un compteur total explicite dans le HTML rendu.
    Pour éviter de valider un mode "taille de page" incomplet, on lit une seule fois
    la dernière page standard et on en déduit :
    total = produits_page_1 * (N - 1) + produits_derniere_page.
    """
    if default_page_count <= 1:
        return len(first_result.products)
    try:
        # Lecture directe avec les paramètres standards, sans _page_size_param.
        response = get(PAGINATE_URL, params=page_params_with_size(default_page_count, "", ""))
        last_result = parse_page(default_page_count, response.text)
        if not last_result.products:
            return None
        return len(first_result.products) * (default_page_count - 1) + len(last_result.products)
    except Exception as exc:
        print(f"    Total attendu non calculé depuis la dernière page standard ({exc}).")
        return None


def probe_page_size_parameter(default_first: PageResult, default_page_count: int, expected_total: int | None) -> tuple[str, str, str, PageResult, int]:
    """Cherche un paramètre serveur réduisant le nombre de pages.

    Beaucoup de backends de pagination acceptent un paramètre non documenté
    (`per_page`, `limit`, `page_size`, etc.). S'il fonctionne ici, on peut réduire
    65 pages à quelques pages sans ouvrir aucune fiche individuelle.
    """
    if FORCED_PAGE_SIZE_PARAM and FORCED_PAGE_SIZE_VALUE:
        candidates = [(FORCED_PAGE_SIZE_PARAM, FORCED_PAGE_SIZE_VALUE)]
    elif not PAGE_SIZE_PROBE:
        return "", "", "désactivé", default_first, default_page_count
    else:
        # Liste volontairement courte : l'objectif est de trouver un vrai
        # raccourci serveur, pas d'ajouter des dizaines de requêtes de probe.
        candidates = [
            ("per_page", "1000"), ("per_page", "500"), ("per_page", "100"),
            ("limit", "1000"), ("limit", "500"), ("limit", "100"),
            ("page_size", "1000"), ("page_size", "500"),
            ("perPage", "1000"), ("pageSize", "1000"),
            ("take", "1000"), ("length", "1000"),
        ]

    baseline_count = len(default_first.products)
    best_param = ""
    best_value = ""
    best_reason = "aucun paramètre accepté"
    best_result = default_first
    best_pages = default_page_count
    best_score = (baseline_count, -default_page_count)
    tested = 0

    for name, value in candidates:
        tested += 1
        try:
            response = get(PAGINATE_URL, params=page_params_with_size(1, name, value))
            result = parse_page(1, response.text)
            count = len(result.products)
            if count <= baseline_count:
                continue
            try:
                pages = detect_page_count(response.text)
            except Exception:
                if expected_total and count >= expected_total:
                    pages = 1
                else:
                    pages = max(1, math.ceil((expected_total or default_page_count * baseline_count) / count))
            # Si on connait le total, un paramètre retournant plus que le total est suspect.
            if expected_total and count > expected_total + baseline_count:
                continue
            score = (count, -pages)
            if score > best_score:
                best_param, best_value = name, value
                best_result, best_pages = result, pages
                best_score = score
                best_reason = f"{name}={value}: {count} produit(s) sur page 1, {pages} page(s) estimée(s)"
                # Cas idéal : tout le catalogue est sur une page.
                if expected_total and count >= expected_total:
                    break
        except Exception:
            continue

    if best_param:
        return best_param, best_value, best_reason, best_result, best_pages
    return "", "", f"{tested} essai(s), aucun gain", default_first, default_page_count


def validate(products: list[dict[str, str]], expected_pages: int, obtained_pages: set[int], expected_total: int | None = None) -> None:
    if obtained_pages != set(range(1, expected_pages + 1)):
        missing = sorted(set(range(1, expected_pages + 1)) - obtained_pages)
        raise RuntimeError(f"pages manquantes : {missing}")
    if not products:
        raise RuntimeError("catalogue vide")
    if expected_total is not None and len(products) != expected_total:
        raise RuntimeError(f"catalogue incomplet : {len(products)} pièce(s) unique(s), {expected_total} attendue(s)")

    urls: set[str] = set()
    for index, product in enumerate(products, 1):
        if tuple(product.keys()) != FIELDS:
            raise RuntimeError(f"élément {index}: champs invalides {tuple(product.keys())}")
        if not product["nom"] or not product["nom_traduit"]:
            raise RuntimeError(f"élément {index}: nom ou traduction vide")
        if not PRICE_EUR_RE.fullmatch(product["prix"]):
            raise RuntimeError(f"élément {index}: prix invalide {product['prix']!r}")
        if product["disponibilite"] not in ALLOWED_AVAILABILITY:
            raise RuntimeError(f"élément {index}: disponibilité invalide")
        if not is_product_detail_url(product["url_fiche"]):
            raise RuntimeError(f"élément {index}: URL de fiche invalide")
        if product["url_fiche"] in urls:
            raise RuntimeError(f"doublon : {product['url_fiche']}")
        urls.add(product["url_fiche"])
        if product["url_photo"] != "inconnu":
            parsed = urlparse(product["url_photo"])
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise RuntimeError(f"élément {index}: URL de photo invalide")

    if any(is_product_detail_url(url) for url in _request_log):
        raise RuntimeError("une fiche individuelle a été consultée")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--version", "-V"}:
        print(f"opelgtsource.py {VERSION} [{BUILD}]")
        return 0
    print(f"opelgtsource.py version {VERSION}")
    print(f"Build : {BUILD}")
    global _order_by, _page_size_param, _page_size_value
    print(f"1/5 Initialisation depuis {ROOT_URL}")
    root_response = get(ROOT_URL)
    _bootstrap_cookies.clear()
    _bootstrap_cookies.update(requests.utils.dict_from_cookiejar(session().cookies))

    _order_by = detect_price_ascending_order(root_response.text)
    print(f"    Tri sélectionné : Price Low to High ({_order_by!r}).")

    # La page racine est affichée avec le tri par défaut. On recharge donc
    # explicitement la page 1 via l'endpoint catalogue avec le tri croissant.
    try:
        first_response = get(PAGINATE_URL, params=page_params(1))
        _save_cached_page(1, first_response.text)
        first_html = first_response.text
    except Exception as exc:
        cached = _load_cached_page(1)
        if not cached:
            raise
        print(f"    Page 1: réseau indisponible, ancien cache HTML utilisé ({exc})")
        first_html = cached
    default_page_count = detect_page_count(first_html)
    default_first_result = parse_page(1, first_html)
    # v8 : on ne télécharge plus la dernière page uniquement pour estimer le total.
    # Cette requête coûtait cher et ne réduisait pas le temps global. La validation
    # stricte des pages et l'union par URL restent assurées.
    expected_total = None
    print(f"    Pagination standard : {default_page_count} page(s), {len(default_first_result.products)} pièce(s) sur page 1.")

    print("2/5 Recherche éventuelle d'un paramètre de taille de page")
    param, value, reason, first_result, page_count = probe_page_size_parameter(default_first_result, default_page_count, expected_total)
    _page_size_param, _page_size_value = param, value
    if param:
        print(f"    Gain détecté : {reason}")
        print(f"    Paramètre appliqué à toutes les pages : {param}={value}")
    else:
        print(f"    Aucun paramètre plus rapide : {reason}. Repli sur pagination standard.")
    print(f"    {page_count} page(s) catalogue à récupérer.")
    print(f"    Page 1 : {len(first_result.products)} pièce(s).")
    start_phase("pages", 10, 80, page_count, "Pages traitées")
    advance_phase("pages")

    print(f"3/5 Téléchargement et parsing des pages 2 à {page_count}")
    results: dict[int, PageResult] = {1: first_result}
    errors: dict[int, str] = {}
    pages = list(range(2, page_count + 1))
    workers = min(PAGE_WORKERS, max(1, len(pages)))
    print(
        f"    {workers} requête(s) simultanée(s) maximum, "
        f"espacement initial ≥ {REQUEST_GAP:.2f} s, "
        f"refroidissement 429/503 ≥ {SERVER_COOLDOWN:.0f} s, cache={CACHE_MODE}."
    )

    if pages:
        completed = 0
        for start in range(0, len(pages), PAGE_BATCH_SIZE):
            batch = pages[start : start + PAGE_BATCH_SIZE]
            with ThreadPoolExecutor(
                max_workers=min(workers, len(batch)), thread_name_prefix="ogs-page"
            ) as executor:
                futures = {executor.submit(fetch_page, page): page for page in batch}
                for future in as_completed(futures):
                    page = futures[future]
                    try:
                        result = future.result()
                        results[page] = result
                    except Exception as exc:
                        errors[page] = str(exc)
                    completed += 1
                    advance_phase("pages")
                    print(f"\r    Pages terminées : {completed}/{len(pages)}", end="", flush=True)
            if start + PAGE_BATCH_SIZE < len(pages) and PAGE_BATCH_PAUSE > 0:
                time.sleep(PAGE_BATCH_PAUSE)
        print()
    if errors:
        failed = sorted(errors)
        start_phase("retries", 80, 85, len(failed), "Pages reprises")
        print(
            f"    Reprise séquentielle de {len(failed)} page(s) après refroidissement "
            "du serveur."
        )
        _set_shared_cooldown(max(SERVER_COOLDOWN, 90.0))
        for index, page in enumerate(failed, 1):
            try:
                results[page] = fetch_page(page)
                advance_phase("retries")
                errors.pop(page, None)
                print(f"\r    Reprises terminées : {index}/{len(failed)}", end="", flush=True)
            except Exception as exc:
                errors[page] = str(exc)
            if index < len(failed):
                time.sleep(max(REQUEST_GAP, 4.0))
        print()

    if errors:
        details = [f"page {page}: {errors[page]}" for page in sorted(errors)]
        raise RuntimeError("Échec de page(s) catalogue :\n- " + "\n- ".join(details))

    raw_count = sum(len(result.products) for result in results.values())
    print(f"    {raw_count} occurrence(s) produit récupérée(s) sur {len(results)}/{page_count} pages.")
    print(f"    Tri prix croissant demandé au serveur avec order_by={_order_by!r}.")

    print("4/5 Traduction parallèle des noms avec cache persistant")
    translated = translate_results(results)

    print("5/5 Conversion EUR, union, validation et écriture")
    publish_progress(95, "Opel GT Source : conversion et validation du catalogue.")
    rate = usd_to_eur_rate()
    print(f"    Taux appliqué : 1 USD = {rate.quantize(Decimal('0.000001'))} EUR")

    union: dict[str, dict[str, str]] = {}
    for page in sorted(translated):
        for raw in translated[page].products:
            usd_text = raw.pop("_prix_usd")
            price = "inconnu" if not usd_text else format_euro(Decimal(usd_text) * rate)
            product = {
                "nom": raw["nom"],
                "nom_traduit": raw["nom_traduit"],
                "prix": price,
                "disponibilite": raw["disponibilite"],
                "url_photo": raw["url_photo"],
                "url_fiche": raw["url_fiche"],
            }
            union.setdefault(product["url_fiche"], product)

    products = list(union.values())
    validate(products, page_count, set(results), expected_total)

    temporary = OUTPUT_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT_FILE)

    print(f"    {len(products)} pièce(s) unique(s) écrite(s) dans {OUTPUT_FILE}")
    print(f"    Pages catalogue obtenues : {len(results)}/{page_count}")
    print(f"    Requêtes vers les fiches individuelles : 0")
    print(f"    Cache : {CACHE_DIR}")
    return 0


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import ScrapeResult as ScrapeResult, run_legacy_scraper as _run_legacy_scraper, scraper_cli as _scraper_cli

_LEGACY_MAIN = main
_SUPPLIER_NAME = 'Opel GT Source'
_SUPPLIER_LANG = 'en'
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name('opelgtsource.json')
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
