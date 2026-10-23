from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.common.version import VERSION


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    host: str


SOURCES = (
    Source("lesanciennes", "lesAnciennes", "https://www.lesanciennes.com/annonces/voiture-collection/opel-gt/", "www.lesanciennes.com"),
    Source("leboncoin", "Leboncoin", "https://www.leboncoin.fr/recherche?category=2&text=opel%20gt", "www.leboncoin.fr"),
    Source("classicnumber", "Classic Number", "https://www.classicnumber.com/opel-gt-collection-m-58-2648.html", "www.classicnumber.com"),
    Source("classictrader", "Classic Trader", "https://www.classic-trader.com/fr/voitures/recherche/opel/gt", "www.classic-trader.com"),
)
PHOTO_HOSTS = {"assets.lesanciennes.com", "images.lesanciennes.com", "www.lesanciennes.com", "img.leboncoin.fr", "images.leboncoin.fr", "www.classicnumber.com", "classicnumber.com", "cdn.classic-trader.com"}


class CollectionError(RuntimeError):
    pass


class AccessRestricted(CollectionError):
    pass


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text(value).lower()) if not unicodedata.combining(c))


def safe_url(value: Any, base: str, *, photo: bool = False) -> str | None:
    url = urljoin(base, text(value))
    try:
        parsed = urlsplit(url)
        allowed = PHOTO_HOSTS if photo else {urlsplit(base).hostname}
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    if not photo and not (parsed.path.startswith("/annonce/") or parsed.path.startswith("/ad/") or re.match(r"/[a-z_]+/\d+\.htm$", parsed.path) or (parsed.hostname == "www.classicnumber.com" and re.fullmatch(r"/[a-z0-9-]+-collection-a-vendre-\d+\.html", parsed.path)) or (parsed.hostname == "www.classic-trader.com" and re.fullmatch(r"/fr/voitures/annonce/[a-z0-9/-]+/\d+", parsed.path))):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query if photo else "", ""))


def iso_date(value: Any) -> str | None:
    raw = text(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (parsed.astimezone(ZoneInfo("Europe/Paris")) if parsed.tzinfo else parsed).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return None


def department_code(region_code: Any = "", postal_code: Any = "") -> str | None:
    code = text(region_code).upper()
    if re.fullmatch(r"(?:0[1-9]|1[0-9]|2[1-9AB]|[3-8][0-9]|9[0-5]|97[1-8]|98[46-8])", code):
        return code
    postal = text(postal_code)
    if re.fullmatch(r"\d{5}", postal):
        if postal.startswith("20"):
            return "2A" if int(postal) < 20200 else "2B"
        return department_code(postal[:3] if postal.startswith(("97", "98")) else postal[:2])
    return None


def model_of(title: str, description: str, engine: Any, year: int | None) -> str | None:
    name = re.sub(r"\b(opel\s*gt)(?=1100|1900)", r"\1 ", fold(title))
    if not re.search(r"\bopel\s*gt(?:\b|j\b)", name):
        return None
    if year is not None and year >= 1990:
        return None
    if any(word in name for word in ("roadster", "cabriolet", "miniature", "echelle", "piece detachee")):
        return None
    if re.search(r"\bgt\s*[/ -]?\s*j\b|\bgtj\b|\bjunior\b", name):
        return "GT/J"
    displacement = re.sub(r"[^\d.,]", "", str(engine or ""))
    if re.search(r"\b1100\b|\b1[.,]1\s*(?:l|litre)?\b", name) or displacement in {"1100", "1078", "1.1", "1,1"}:
        return "1100"
    if re.search(r"\b1900\s*s?\b|\b1[.,]9\s*(?:l|litre)?\b", name) or displacement in {"1900", "1897", "1.9", "1,9"}:
        return "1900"
    if year is not None and 1968 <= year <= 1976:
        content = fold(f"{title} {description}")
        if re.search(r"\b1100\b|\b1078\b", content):
            return "1100"
        if re.search(r"\b1900\b|\b1897\b|\b1[.,]9\b", content):
            return "1900"
        return "Modèle non précisé"
    return None


def price_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return round(number, 2) if math.isfinite(number) and 0 <= number <= 100_000_000 else None
    except (ValueError, TypeError):
        return None


def listing(source: Source, *, ident: Any, title: Any, description: Any = "", year: Any = None,
            engine: Any = None, country: Any = "", town: Any = "", region: Any = "", postal: Any = "",
            seller_type: Any = "", published_at: Any = None, image: Any = "", url: Any = "",
            price: Any = None, currency: Any = "EUR", price_label: Any = "") -> dict | None:
    try:
        numeric_year = int(year)
        if not 1900 <= numeric_year <= 2100:
            numeric_year = None
    except (TypeError, ValueError):
        numeric_year = None
    model = model_of(text(title), text(description), engine, numeric_year)
    if fold(country) not in {"fr", "france", "fra"} or model is None:
        return None
    destination = safe_url(url, source.url)
    if destination is None:
        raise CollectionError("Lien d'annonce inattendu ; récupération refusée.")
    seller = fold(seller_type)
    seller = "professionnel" if seller in {"pro", "professional", "professionnel", "dealer", "business"} else (
        "particulier" if seller in {"private", "particulier", "personal"} else "inconnu"
    )
    return {
        "id": f"{source.id}:{text(ident) or destination}", "source_id": source.id,
        "source_name": source.name, "url": destination, "title": text(title)[:300],
        "seller_type": seller, "model": model, "year": numeric_year,
        "location": text(town)[:150] or "Lieu non précisé", "department": department_code(region, postal),
        "price": price_value(price), "currency": text(currency).upper() if re.fullmatch(r"[A-Za-z]{3}", text(currency)) else "EUR",
        "price_label": text(price_label)[:100] if price_value(price) is None else "",
        "published_at": iso_date(published_at), "image_url": safe_url(image, source.url, photo=True) if image else None,
    }


class PublicClient:
    """Bounded public requests; honour robots.txt and stop on access refusal."""

    def __init__(self, source: Source, *, timeout: float = 20, deadline: float = 180):
        self.source = source
        self.timeout = min(30, max(2, timeout))
        self.deadline = time.monotonic() + deadline
        self.session = requests.Session()
        retry = Retry(total=1, connect=1, read=1, status=0, backoff_factor=0.5, respect_retry_after_header=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": f"PortailEntraideOpelGT/{VERSION} (annonces)", "Accept-Language": "fr-FR,fr;q=0.9", "Accept": "text/html"})
        self.robots: RobotFileParser | None = None
        self.requests = 0
        self.last_request = 0.0

    def close(self):
        self.session.close()

    def _get(self, url: str) -> str:
        for _ in range(4):
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname != self.source.host or parsed.port not in (None, 443) or parsed.username or parsed.password:
                raise CollectionError("Redirection hors de la source refusée.")
            remaining = self.deadline - time.monotonic()
            if remaining < 1 or self.requests >= 100:
                raise CollectionError("Délai ou nombre maximal de requêtes atteint ; données précédentes conservées.")
            delay = max(0, 0.5 - (time.monotonic() - self.last_request))
            if delay:
                time.sleep(delay)
            self.requests += 1
            self.last_request = time.monotonic()
            with self.session.get(url, timeout=(min(10, remaining), min(self.timeout, remaining)), allow_redirects=False, stream=True) as response:
                if response.status_code in {401, 403, 429}:
                    raise AccessRestricted(f"Accès automatisé restreint (HTTP {response.status_code}).")
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                response.raise_for_status()
                chunks = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 8 * 1024 * 1024 or time.monotonic() > self.deadline:
                        raise CollectionError("Réponse trop volumineuse ou délai de collecte dépassé.")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                if encoding.lower() in {"iso-8859-1", "latin-1"}:
                    encoding = "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace")
        raise CollectionError("Trop de redirections.")

    def get(self, url: str) -> str:
        if self.robots is None:
            robots_url = f"https://{self.source.host}/robots.txt"
            try:
                raw = self._get(robots_url)
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
                raw = "User-agent: *\nAllow: /"
            self.robots = RobotFileParser(robots_url)
            self.robots.parse(raw.splitlines())
        if not self.robots.can_fetch("PortailEntraideOpelGT", url):
            raise AccessRestricted("La source restreint l'accès automatisé à ces annonces (robots.txt).")
        return self._get(url)


def inertia_props(soup: BeautifulSoup) -> dict | None:
    script = soup.select_one('script[data-page="app"][type="application/json"]')
    node = soup.select_one('div[data-page]')
    raw = script.get_text() if script else node.get("data-page", "") if node else ""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CollectionError("Données structurées lesAnciennes illisibles.") from exc
    return payload.get("props") if isinstance(payload, dict) else None


def next_page(url: str, number: int) -> str:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    query["page"] = [str(number)]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))


def collect_lesanciennes(client: PublicClient) -> list[dict]:
    source = SOURCES[0]
    result: dict[str, dict] = {}
    pages = 1
    expected = None
    seen = set()
    for page in range(1, 21):
        html = client.get(source.url if page == 1 else next_page(source.url, page))
        soup = BeautifulSoup(html, "html.parser")
        props = inertia_props(soup)
        if not props or not isinstance(props.get("listings"), list):
            raise CollectionError("Structure lesAnciennes non reconnue ; données précédentes conservées.")
        raw_items = props["listings"]
        pagination = props.get("pagination") or {}
        pages = max(pages, int(pagination.get("last_page") or 1))
        if pages > 20:
            raise CollectionError("Pagination lesAnciennes trop importante ; catalogue incomplet refusé.")
        if expected is None and pagination.get("total") is not None:
            expected = int(pagination["total"])
        if not raw_items and pages > 1:
            raise CollectionError("Page lesAnciennes vide au milieu de la pagination.")
        cards = soup.select('article[data-testid="card-listing"]')
        for raw in raw_items:
            seen.add(raw["id"])
            if raw.get("isSold"):
                continue
            location = raw.get("location") or {}
            attributes = raw.get("attributes") or {}
            seller = raw.get("seller") or {}
            # A missing badge is not proof that the seller is a private person.
            seller_kind = raw.get("sellerType") or seller.get("type") or (
                "professionnel" if "/traders/" in str(seller.get("thumbnailUrl", "")) else ""
            )
            card = next((node for node in cards if any(a.get("href") == raw.get("url") for a in node.select('a[href]'))), None)
            if not seller_kind and card:
                badge = card.select_one('[data-testid="seller-type"], .seller-type')
                if badge:
                    seller_kind = badge.get_text(" ", strip=True)
            images = raw.get("images") or []
            photo = images[0].get("url", "") if images and isinstance(images[0], dict) else ""
            if photo.startswith("/"):
                photo = urljoin("https://assets.lesanciennes.com/", photo)
            item = listing(
                source, ident=raw["id"], title=raw.get("title"), description=raw.get("shortDescription"),
                year=raw.get("year"), engine=attributes.get("engineSize"), country=location.get("countryCode"),
                town=location.get("town"), region=location.get("regionCode"), postal=location.get("postalCode"),
                seller_type=seller_kind, published_at=(raw.get("advert") or {}).get("createdAt"),
                image=photo, url=raw.get("url"),
                price=(raw.get("price") or {}).get("value") / 100 if price_value((raw.get("price") or {}).get("value")) is not None else None,
                currency=((raw.get("price") or {}).get("currency") or {}).get("name", "EUR"),
            )
            if item:
                result[item["id"]] = item
        if page >= pages:
            break
    if expected is not None and len(seen) != expected:
        raise CollectionError("Pagination lesAnciennes incomplète ; données précédentes conservées.")
    return list(result.values())


def create_lbc_client():
    import lbc
    return lbc.Client(request_verify=True, timeout=20, max_retries=0)


def collect_leboncoin(client: PublicClient) -> list[dict]:
    """Use etienne-hd/lbc's search API, without fetching seller profiles."""
    import lbc
    from lbc.exceptions import DatadomeError, RequestError

    source = SOURCES[1]
    result = {}
    deadline = time.monotonic() + 180
    remote = None
    try:
        remote = create_lbc_client()
        # Search results do not expose the seller type in lbc.Ad. Explicit
        # server-side filters preserve it without one user lookup per advert.
        for owner in (lbc.OwnerType.PRIVATE, lbc.OwnerType.PRO):
            seen = set()
            expected = None
            for page in range(1, 21):
                if time.monotonic() > deadline:
                    raise CollectionError("Délai maximal Leboncoin atteint ; données précédentes conservées.")
                if page > 1 or owner == lbc.OwnerType.PRO:
                    time.sleep(0.75)
                data = remote.search(text="opel gt", category=lbc.Category.VEHICULES_VOITURES,
                                     sort=lbc.Sort.NEWEST, ad_type=lbc.AdType.OFFER,
                                     owner_type=owner, limit=35, limit_alu=0, page=page)
                if expected is None:
                    if data.total is None:
                        raise CollectionError("Nombre total d'annonces Leboncoin absent ; pagination invérifiable.")
                    expected = int(data.total)
                for ad in data.ads:
                    seen.add(ad.id)
                    if str(ad.category_id) != "2" or ad.status not in (None, "active"):
                        continue
                    def attribute(key):
                        value = ad.attributes.get(key)
                        return (value.value or (value.values or [None])[0]) if value else None
                    location = ad.location
                    item = listing(
                        source, ident=ad.id, title=ad.subject, description=ad.body,
                        year=attribute("regdate"), engine=attribute("cubic_capacity"),
                        country=location.country_id or ("FR" if location.department_id or location.zipcode else ""),
                        town=location.city_label or location.city, region=location.department_id, postal=location.zipcode,
                        seller_type=owner.value, published_at=ad.first_publication_date,
                        image=(ad.images or [""])[0], url=ad.url, price=ad.price,
                    )
                    if item:
                        result[item["id"]] = item
                if len(seen) >= expected:
                    break
                if not data.ads:
                    raise CollectionError("Pagination Leboncoin incomplète ; données précédentes conservées.")
            else:
                raise CollectionError("Nombre maximal de pages Leboncoin atteint ; données précédentes conservées.")
        return list(result.values())
    except DatadomeError as exc:
        raise AccessRestricted("Leboncoin refuse la requête du client lbc (HTTP 403 / DataDome).") from exc
    except RequestError as exc:
        raise CollectionError("Échec de la requête Leboncoin avec le client lbc ; données précédentes conservées.") from exc
    finally:
        if remote is not None:
            remote.session.close()


def french_price(value: str) -> tuple[float | None, str]:
    raw = text(value)
    if "€" in raw:
        match = re.search(r"(\d[\d\s.,]*)\s*€", raw)
        if match:
            number = re.sub(r"\s", "", match[1]).replace(",", ".")
            return price_value(number), ""
    for marker, label in (("encheres", "Enchères"), ("sur demande", "Prix sur demande"), ("faire offre", "Faire offre")):
        if marker in fold(raw):
            return None, label
    return None, ""


def next_result_link(soup: BeautifulSoup, source: Source, page: int) -> str | None:
    for link in soup.select('a[rel~="next"], .pagination a[href], a[href*="page="]'):
        href = urljoin(source.url, str(link.get("href", "")))
        parsed = urlsplit(href)
        if parsed.hostname != source.host:
            continue
        number = (parse_qs(parsed.query).get("page") or [""])[0]
        if "next" in (link.get("rel") or []) or number == str(page + 1) or text(link.get_text()) == str(page + 1):
            return href
    return None


def collect_classicnumber(client: PublicClient) -> list[dict]:
    source = SOURCES[2]
    result, seen = {}, set()
    url = source.url
    expected = None
    for page in range(1, 21):
        soup = BeautifulSoup(client.get(url), "html.parser")
        heading = soup.select_one("h1")
        if not heading or "opel gt" not in fold(heading.get_text()):
            raise CollectionError("Structure Classic Number non reconnue ; données précédentes conservées.")
        if expected is None:
            total = re.search(r"(\d+)\s+vehicules?\s+trouve", fold(soup.get_text(" ", strip=True)))
            if not total:
                raise CollectionError("Nombre d'annonces Classic Number absent ; pagination invérifiable.")
            expected = int(total[1])
        for card in soup.select("ul.searchList .gridint"):
            anchor = card.select_one("h3 a.carhit[href]")
            if not anchor:
                raise CollectionError("Carte Classic Number incomplète.")
            ident = anchor.get("carid") or anchor["href"]
            seen.add(ident)
            title = anchor.get_text(" ", strip=True)
            year_node = card.select_one(".car-list-infos-1 li")
            year = text(year_node.get_text()) if year_node else None
            if model_of(title, "", None, int(year) if year and year.isdigit() else None) is None:
                continue
            flag = card.select_one(".car_grid_pays")
            country = flag.get_text(" ", strip=True) if flag else ""
            if country and fold(country) not in {"france", "fr"}:
                continue
            destination = safe_url(anchor["href"], source.url)
            if not destination:
                raise CollectionError("Lien Classic Number inattendu.")
            detail = BeautifulSoup(client.get(destination), "html.parser")
            name = detail.select_one("h1")
            if not name or "opel gt" not in fold(name.get_text()):
                raise CollectionError("Fiche Classic Number non reconnue.")
            address = detail.select_one(".seller-address")
            place = text(address.get_text(" ", strip=True)) if address else ""
            mapping = address.select_one("a[adresse]") if address else None
            if not country and mapping and "france" in fold(mapping.get("adresse")):
                country = "FR"
            location = re.search(r"\(([0-9AB]{2,3})\)\s*-\s*(.*?)\s*\((\d{5})\)", place, re.I)
            badge = detail.select_one(".pro-part")
            seller = text(badge.get_text()) if badge else ""
            seller = "pro" if seller.upper() == "PRO" else "private" if seller.upper() in {"PART", "PARTICULIER"} else ""
            date_node = next((n for n in detail.select(".car_info_date") if "Annonce publiée le" in n.get_text()), None)
            date = re.search(r"\d{2}/\d{2}/\d{4}", date_node.get_text()) if date_node else None
            photo = detail.select_one('meta[property="og:image"]')
            price_node = card.select_one(".adprice")
            price, label = french_price(price_node.get_text(" ", strip=True) if price_node else "")
            if price_node and price_node.select_one('img[alt="Enchères"]'):
                price, label = None, "Enchères"
            item = listing(
                source, ident=ident, title=title, year=year, country=country,
                town=location[2] if location else place, region=location[1] if location else "", postal=location[3] if location else "",
                seller_type=seller, published_at=date[0] if date else None,
                image=photo.get("content", "") if photo else "", url=destination, price=price, price_label=label,
            )
            if item:
                result[item["id"]] = item
        if len(seen) >= expected:
            return list(result.values())
        url = next_result_link(soup, source, page)
        if not url:
            raise CollectionError("Pagination Classic Number incomplète ; données précédentes conservées.")
    raise CollectionError("Nombre maximal de pages Classic Number atteint.")


def astro_value(value: Any) -> Any:
    """Decode Astro's public [type, value] JSON props, without evaluating JS."""
    if isinstance(value, dict):
        return {key: astro_value(item) for key, item in value.items()}
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        kind, payload = value
        if kind == 0:
            return astro_value(payload)
        if kind == 1 and isinstance(payload, list):
            return [astro_value(item) for item in payload]
        return None
    return value


def collect_classictrader(client: PublicClient) -> list[dict]:
    source = SOURCES[3]
    result, seen = {}, set()
    expected = None
    url = source.url
    for page in range(1, 21):
        soup = BeautifulSoup(client.get(url), "html.parser")
        heading = soup.select_one("h1")
        if not heading or "opel gt" not in fold(heading.get_text()):
            raise CollectionError("Structure Classic Trader non reconnue ; données précédentes conservées.")
        if expected is None:
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    payload = json.loads(script.get_text())
                    for entity in payload.get("mainEntity", []) if isinstance(payload, dict) else []:
                        total = re.search(r"\((\d+)\s+offres?\)", text(entity.get("name")))
                        if total:
                            expected = int(total[1])
                except (ValueError, TypeError, AttributeError):
                    continue
            if expected is None:
                raise CollectionError("Nombre d'annonces Classic Trader absent ; pagination invérifiable.")
        cards = soup.select('astro-island[component-export="ResultPageCarDataClassifiedAd"][props]')
        for card in cards:
            try:
                raw = astro_value(json.loads(card["props"]))["vehicleAd"]
            except (ValueError, TypeError, KeyError) as exc:
                raise CollectionError("Données Classic Trader illisibles.") from exc
            seen.add(raw["id"])
            if raw.get("state") != "published" or raw.get("type") != "CarAd":
                continue
            location, seller, vehicle, price = (raw.get(key) or {} for key in ("location", "seller", "vehicle", "price"))
            photos = raw.get("images") or []
            item = listing(
                source, ident=raw["id"], title=raw.get("title"), year=raw.get("yearOfProduction"), engine=vehicle.get("cubicCapacity"),
                country=location.get("countryCode"), town=location.get("city"), postal=location.get("postalCode"),
                seller_type="pro" if seller.get("isDealer") else "private" if seller.get("isPrivate") else "",
                published_at=raw.get("publishDate"), image=photos[0].get("originalImageUrl", "") if photos else "",
                url=raw.get("canonicalUrl") or raw.get("url"), price=None if price.get("isOnRequest") else price.get("amount"),
                currency=price.get("currency", "EUR"), price_label="Prix sur demande" if price.get("isOnRequest") else "",
            )
            if item:
                result[item["id"]] = item
        if len(seen) >= expected:
            return list(result.values())
        url = next_result_link(soup, source, page)
        if not url:
            raise CollectionError("Pagination Classic Trader incomplète ; données précédentes conservées.")
    raise CollectionError("Nombre maximal de pages Classic Trader atteint.")


COLLECTORS = {"lesanciennes": collect_lesanciennes, "leboncoin": collect_leboncoin,
              "classicnumber": collect_classicnumber, "classictrader": collect_classictrader}
