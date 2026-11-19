"""Collectors for the seven direct marketplaces added in bundle 1.1.40."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.annonces import collectors as c

_DEPARTMENTS = json.loads((Path(__file__).resolve().parents[2] / "resources/annonces/marketplace_departments.json").read_text())["departments"]
DEPARTMENTS = {c.fold(name): code for name, code in _DEPARTMENTS.items()}
MAX_PAGES = 20


def source(ident):
    return next(item for item in c.SOURCES if item.id == ident)


def mapping(value):
    return value if isinstance(value, dict) else {}


def year_of(value):
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
    return int(match[1]) if match else None


def title_year(value):
    match = re.search(r"\b(196[89]|197[0-6]|20\d{2})\b", str(value or ""))
    return int(match[1]) if match else None


def integer(value, label):
    if type(value) is not int or value < 0:
        raise c.CollectionError(f"Compteur {label} non reconnu ; données précédentes conservées.")
    return value


def assigned_json(html, pattern, label):
    match = re.search(pattern, html)
    if not match:
        raise c.CollectionError(f"Données structurées {label} absentes.")
    try:
        return json.JSONDecoder().raw_decode(html[match.end():].lstrip())[0]
    except (ValueError, TypeError) as exc:
        raise c.CollectionError(f"Données structurées {label} illisibles.") from exc


def ld_nodes(soup):
    def walk(value, depth=0):
        if depth > 20:
            return
        if isinstance(value, dict):
            if "@type" in value:
                yield value
            for key in ("@graph", "itemListElement", "item", "mainEntity"):
                yield from walk(value.get(key), depth + 1)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item, depth + 1)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.get_text()))
        except (ValueError, TypeError) as exc:
            raise c.CollectionError("Données JSON-LD de l'annonce illisibles.") from exc


def car_schema(soup, url):
    candidates = []
    for node in ld_nodes(soup):
        kinds = node.get("@type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(kind in {"Car", "Vehicle", "Product"} for kind in kinds):
            continue
        candidate_url = node.get("url") or mapping(node.get("offers")).get("url")
        if candidate_url and urlsplit(urljoin(url, candidate_url)).path != urlsplit(url).path:
            continue
        candidates.append(node)
    if len(candidates) != 1:
        raise c.CollectionError("Fiche du véhicule non reconnue ; données précédentes conservées.")
    return candidates[0]


def published(soup, data):
    value = data.get("datePosted") or data.get("datePublished") or mapping(data.get("offers")).get("datePosted")
    if not value:
        node = soup.select_one('meta[property="article:published_time"],meta[itemprop="datePublished"],time[itemprop="datePublished"][datetime],time[itemprop="datePosted"][datetime]')
        value = node.get("content") or node.get("datetime") if node else None
    return value


def department(*names):
    for name in names:
        code = c.department_code(name)
        if code:
            return code
        code = DEPARTMENTS.get(c.fold(name))
        if code:
            return code
    return ""


def schema_listing(ident, soup, url, *, country="", town="", postal="", region="", title="", year=None, engine=None,
                   image="", price=None, currency="EUR"):
    data = car_schema(soup, url)
    offer = data.get("offers")
    offer = mapping(offer[0] if isinstance(offer, list) and offer else offer)
    if c.text(offer.get("availability")).rsplit("/", 1)[-1] in {"SoldOut", "OutOfStock", "Discontinued"}:
        return None
    location = mapping(data.get("location")) or mapping(offer.get("availableAtOrFrom"))
    address = mapping(location.get("address")) or mapping(data.get("address"))
    advertised_country = address.get("addressCountry") or country
    if isinstance(advertised_country, dict):
        advertised_country = advertised_country.get("identifier") or advertised_country.get("name")
    advertised_title = c.text(data.get("name") or title)
    brand = mapping(data.get("brand")).get("name")
    if c.fold(brand) == "opel" and "opel" not in c.fold(advertised_title):
        advertised_title = "Opel " + advertised_title
    seller = mapping(offer.get("seller"))
    seller_type = "pro" if seller.get("@type") in {"AutoDealer", "Organization", "LocalBusiness"} else "private" if seller.get("@type") == "Person" else ""
    images = data.get("image") or image
    first_image = images[0] if isinstance(images, list) and images else images
    if isinstance(first_image, dict):
        first_image = first_image.get("url") or first_image.get("contentUrl")
    amount = offer.get("price", price)
    label = ""
    if c.price_value(amount) is None:
        amount, label = c.french_price(c.text(amount))
    displacement = mapping(data.get("vehicleEngine")).get("engineDisplacement") or mapping(data.get("vehicleEngine")).get("name") or engine
    if isinstance(displacement, dict):
        displacement = displacement.get("value") or displacement.get("name")
    return c.listing(source(ident), ident=data.get("sku") or urlsplit(url).path, title=advertised_title,
                     description=data.get("description", ""), year=year_of(data.get("vehicleModelDate") or data.get("productionDate") or data.get("dateVehicleFirstRegistered") or year),
                     engine=displacement,
                     country=advertised_country, town=address.get("addressLocality") or town,
                     region=department(address.get("addressRegion"), region), postal=address.get("postalCode") or postal,
                     seller_type=seller_type, published_at=published(soup, data), image=first_image,
                     url=url, price=amount, currency=offer.get("priceCurrency") or currency, price_label=label)


def collect_carandclassic(client):
    src = source("carandclassic")
    result, seen = {}, set()
    url = src.url
    expected = None
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(client.get(url), "html.parser")
        props = c.inertia_props(soup, src.name)
        if not isinstance(props, dict) or mapping(props.get("make")).get("slug") != "opel" or mapping(props.get("model")).get("slug") != "gt" or not isinstance(props.get("listings"), list):
            raise c.CollectionError("Structure Car & Classic non reconnue.")
        total = integer(props.get("totalListingCount"), src.name)
        if expected is not None and expected != total:
            raise c.CollectionError("La liste Car & Classic a changé pendant sa lecture.")
        expected = total
        before = len(seen)
        for card in props["listings"]:
            if not isinstance(card, dict) or not card.get("id"):
                raise c.CollectionError("Carte Car & Classic incomplète.")
            if card["id"] in seen:
                continue
            seen.add(card["id"])
            if card.get("type") != "basic" or card.get("isSold") is True:
                continue
            loc = mapping(card.get("location"))
            if loc.get("countryCode") and c.fold(loc["countryCode"]) not in {"fr", "france"}:
                continue
            target = c.safe_url(card.get("url"), src.url)
            if not target:
                raise c.CollectionError("Lien Car & Classic inattendu.")
            detail_soup = BeautifulSoup(client.get(target), "html.parser")
            detail = c.inertia_props(detail_soup, src.name)
            raw = mapping(mapping(detail).get("listing"))
            if not raw or raw.get("advertRef") != urlsplit(target).path.rsplit("/", 1)[-1] or type(raw.get("isAvailable")) is not bool:
                raise c.CollectionError("Fiche Car & Classic non reconnue.")
            if not raw["isAvailable"] or raw.get("isPart") or raw.get("advertTypeId") != 1:
                continue
            vehicle = mapping(raw.get("vehicle"))
            price = mapping(raw.get("price"))
            money = mapping(price.get("money"))
            amount = c.price_value(money.get("value"))
            location = mapping(raw.get("location"))
            complete = c.text(location.get("completeLocation")).split(",")
            images = raw.get("images") or []
            first = mapping(images[0]) if images else {}
            photo = mapping(first.get("md") or first.get("lg") or first.get("sm")).get("src", "")
            kind = mapping(raw.get("seller")).get("sellerType", "")
            row = c.listing(src, ident=raw["advertRef"], title=raw.get("title"), description=raw.get("description"),
                            year=vehicle.get("year"), engine=vehicle.get("engineSize"), country=raw.get("countryCode") or raw.get("country"),
                            town=location.get("shortLocation") or loc.get("town"), region=department(loc.get("region"), *complete[1:]),
                            postal=location.get("postalCode", ""), seller_type=kind, published_at=raw.get("listingDate"), image=photo, url=target,
                            price=amount / 100 if amount is not None else None, currency=mapping(money.get("currency")).get("name", "EUR"),
                            price_label=c.text(price.get("display")) if amount is None else "")
            if row:
                result[row["id"]] = row
        if len(seen) == expected:
            return list(result.values())
        if len(seen) > expected or len(seen) == before:
            raise c.CollectionError("Pagination Car & Classic incohérente.")
        url = c.next_result_link(soup, src, page)
        if not url or urlsplit(url).path != urlsplit(src.url).path:
            raise c.CollectionError("Pagination Car & Classic incomplète.")
    raise c.CollectionError("Nombre maximal de pages Car & Classic atteint.")


def collect_retrocalage(client):
    src = source("retrocalage")
    html = client.get(src.url)
    rows = assigned_json(html, r"(?:const|let|var)\s+allItems\s*=\s*", src.name)
    soup = BeautifulSoup(html, "html.parser")
    count = re.search(r"(\d+)\s+R[ée]sultats?", soup.get_text(" ", strip=True), re.I)
    if not isinstance(rows, list) or not count or len(rows) != int(count[1]):
        raise c.CollectionError("Liste Rétrocalage incomplète ou non reconnue.")
    result = {}
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("id"):
            raise c.CollectionError("Annonce Rétrocalage non reconnue.")
        if raw.get("estVisible") is not True or mapping(raw.get("type")).get("name") != "PROPOSE" or c.fold(mapping(raw.get("categorie")).get("nom")) != "vehicules de collection":
            continue
        dep = mapping(raw.get("departement"))
        code = c.department_code(dep.get("numero"))
        if not code:
            continue
        description = c.text(BeautifulSoup(c.text(raw.get("description")), "html.parser").get_text(" "))
        title = c.text(raw.get("titre"))
        year = title_year(title) or title_year(description)
        price, label = c.french_price(description)
        row = c.listing(src, ident=raw.get("reference") or raw["id"], title=title, description=description, year=year,
                        country="FR", town=raw.get("ville"), region=code, seller_type="pro" if raw.get("estPro") is True else "private" if raw.get("estPro") is False else "",
                        published_at=mapping(raw.get("valideLe")).get("date"), image=raw.get("mini"),
                        url=f"https://{src.host}/api/annonces/{int(raw['id'])}?expanded=true", price=price, price_label=label)
        if row:
            result[row["id"]] = row
    return list(result.values())


def collect_autoscout24(client):
    src = source("autoscout24")
    result, seen = {}, set()
    expected = None
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(client.get(src.url if page == 1 else c.next_page(src.url, page)), "html.parser")
        node = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
        if not node:
            raise c.CollectionError("Données AutoScout24 absentes.")
        try:
            props = json.loads(node.get_text())["props"]["pageProps"]
            cards = props["listings"]
        except (ValueError, TypeError, KeyError) as exc:
            raise c.CollectionError("Structure AutoScout24 non reconnue.") from exc
        if not isinstance(cards, list):
            raise c.CollectionError("Liste AutoScout24 non reconnue.")
        expected = max(expected or 0, integer(props.get("numberOfResults"), src.name))
        before = len(seen)
        for raw in cards:
            if not isinstance(raw, dict) or not raw.get("id"):
                raise c.CollectionError("Annonce AutoScout24 non reconnue.")
            seen.add(raw["id"])
            location, vehicle = mapping(raw.get("location")), mapping(raw.get("vehicle"))
            if raw.get("availableNow") is False or c.fold(location.get("countryCode")) not in {"fr", "france"}:
                continue
            details = raw.get("vehicleDetails") or []
            registered = next((mapping(d).get("data") for d in details if mapping(d).get("iconName") == "calendar"), None)
            title = c.text(raw.get("title")) + " " + c.text(vehicle.get("modelVersionInput"))
            seller, price = mapping(raw.get("seller")), mapping(raw.get("price"))
            images = raw.get("images") or []
            row = c.listing(src, ident=raw["id"], title=title, year=year_of(registered), engine=vehicle.get("engineDisplacementInCCM"),
                            country=location.get("countryCode"), town=location.get("city"), postal=location.get("zip"), seller_type=seller.get("type"),
                            published_at=raw.get("publicationDate") or raw.get("firstPublicationDate"),
                            image=images[0] if images else "", url=raw.get("url"), price=price.get("priceRaw"),
                            currency=price.get("currency") or ("EUR" if "€" in c.text(price.get("priceFormatted")) else ""))
            if row:
                result[row["id"]] = row
        if len(seen) >= expected:
            return list(result.values())
        if len(seen) == before:
            raise c.CollectionError("Pagination AutoScout24 répétée ou incomplète.")
    raise c.CollectionError("Nombre maximal de pages AutoScout24 atteint.")


def collect_paruvendu(client):
    src = source("paruvendu")
    result, seen = {}, set()
    expected = None
    url = src.url
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(client.get(url), "html.parser")
        heading = soup.select_one("h1")
        count = re.search(r"(\d+)\s+annonces?", heading.get_text(" ", strip=True) if heading else "", re.I)
        cards = soup.select("article[data-id]")
        if not count or "opel" not in c.fold(heading.get_text()) or "gt" not in c.fold(heading.get_text()):
            raise c.CollectionError("Structure ParuVendu non reconnue.")
        expected = max(expected or 0, int(count[1]))
        before = len(seen)
        for card in cards:
            seen.add(card["data-id"])
            anchor = card.select_one('a[href*="/a/voiture-occasion/opel/gt/"]')
            if not anchor:
                raise c.CollectionError("Lien ParuVendu absent.")
            text = card.get_text(" ", strip=True)
            year_match = re.search(r"Ann[ée]e\s+((?:19|20)\d{2})", text)
            year = int(year_match[1]) if year_match else title_year(anchor.get("title"))
            if year is not None and year >= 1990:
                continue
            location_node = card.select_one('p:has(img[src*="marker"]) span,span:has(> img[src*="marker"])')
            location = location_node.get_text(" ", strip=True) if location_node else ""
            place = re.fullmatch(r"(.*?)\s*\((\d{5})\)", location)
            if re.search(r"\b(?:italia|italie|belgique|belgium|germany|allemagne|espagne|spain|netherlands|pays-bas)\b", location + " " + anchor.get("title", ""), re.I):
                continue
            url_ad = c.safe_url(anchor["href"], src.url)
            if not url_ad:
                raise c.CollectionError("Lien ParuVendu inattendu.")
            detail = BeautifulSoup(client.get(url_ad), "html.parser")
            row = schema_listing(src.id, detail, url_ad, country="FR" if place else "", town=place[1].strip() if place else location,
                                 postal=place[2] if place else "", year=year)
            if row:
                result[row["id"]] = row
        if len(seen) >= expected:
            return list(result.values())
        if len(seen) == before:
            raise c.CollectionError("Pagination ParuVendu répétée ou incomplète.")
        url = c.next_result_link(soup, src, page)
        if not url:
            raise c.CollectionError("Pagination ParuVendu incomplète.")
    raise c.CollectionError("Nombre maximal de pages ParuVendu atteint.")


def collect_carjager(client):
    src = source("carjager")
    result, seen = {}, set()
    url = src.url
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(client.get(url), "html.parser")
        lists = [n for n in ld_nodes(soup) if n.get("@type") == "ItemList"]
        if len(lists) != 1 or not isinstance(lists[0].get("itemListElement"), list):
            raise c.CollectionError("Liste CarJager non reconnue.")
        before = len(seen)
        for entry in lists[0]["itemListElement"]:
            href = mapping(entry).get("url") or mapping(mapping(entry).get("item")).get("url")
            target = c.safe_url(href, src.url)
            if not target:
                raise c.CollectionError("Lien CarJager inattendu.")
            if target in seen:
                continue
            seen.add(target)
            if not re.search(r"/opel-gt(?:-|\d)", urlsplit(target).path, re.I):
                continue
            detail = BeautifulSoup(client.get(target), "html.parser")
            label = detail.find(string=lambda value: value and value.strip() in {"Emplacement de l'auto", "Car location"})
            location = label.find_parent("li") if label else None
            if location is None:
                raise c.CollectionError("Emplacement de la voiture CarJager absent.")
            flag = location.select_one('img[alt*="Drapeau"],img[alt*="flag"],img[src*="flag-icons"]')
            flag_match = re.search(r"/([a-z]{2})\.svg", flag.get("src", "")) if flag else None
            country = flag_match[1].upper() if flag_match else ""
            if country != "FR":
                continue
            place = location.get_text(" ", strip=True).replace(c.text(label), "").strip()
            postal = re.search(r"\(\s*(\d{5})\s*\)", place)
            town = re.sub(r"\(\s*\d{5}\s*\)", "", place).strip()
            row = schema_listing(src.id, detail, target, country=country, town=town, postal=postal[1] if postal else "")
            if row:
                result[row["id"]] = row
        nxt = soup.select_one('a[rel~="next"][href]')
        if not nxt:
            return list(result.values())
        if len(seen) == before:
            raise c.CollectionError("Pagination CarJager répétée.")
        url = urljoin(src.url, nxt["href"])
        if urlsplit(url).hostname != src.host or urlsplit(url).path != urlsplit(src.url).path:
            raise c.CollectionError("Pagination CarJager inattendue.")
    raise c.CollectionError("Nombre maximal de pages CarJager atteint.")


PLETHORE_API = "https://qqywzwuktoehefxmtfez.supabase.co/functions/v1/fetch-annonces-graphql"


def collect_plethorecars(client):
    src = source("plethorecars")
    remote = c.PublicClient(c.Source(src.id, src.name, PLETHORE_API, urlsplit(PLETHORE_API).hostname))
    result, seen = {}, set()
    try:
        for page in range(1, MAX_PAGES + 1):
            payload = remote.post_json(PLETHORE_API, {"search": "Opel", "limit": 50, "page": page})
            meta = mapping(payload.get("meta"))
            expected = integer(meta.get("filter_count"), src.name)
            cards = payload.get("data")
            if not isinstance(cards, list):
                raise c.CollectionError("Liste Pléthore Cars non reconnue.")
            before = len(seen)
            for raw in cards:
                if not isinstance(raw, dict) or not raw.get("id"):
                    raise c.CollectionError("Annonce Pléthore Cars non reconnue.")
                seen.add(str(raw["id"]))
                if raw.get("actif") not in {1, "1"}:
                    continue
                country = mapping(raw.get("id_pays"))
                if c.fold(country.get("code")) != "fr":
                    continue
                title = c.text(raw.get("titre"))
                slug = re.sub(r"[^a-z0-9]+", "-", c.fold(title)).strip("-")
                target = f"https://{src.host}/voiture-collection/{slug}-{int(raw['id']):07d}.html"
                photos = raw.get("images") or []
                file = mapping(mapping(photos[0]).get("directus_files_id")) if photos else {}
                image = f"https://edge.plethorecars.fr/api/v1/assets/{file['id']}?width=800&format=webp&quality=75" if file.get("id") else ""
                place = mapping(raw.get("location"))
                professional = raw.get("pro")
                seller = "pro" if professional in (True, 1, "1") else "private" if professional in (False, 0, "0") else ""
                row = c.listing(src, ident=raw["id"], title=title, description=raw.get("description"), year=raw.get("annee"),
                                engine=raw.get("moteur_detail_nom"), country=country.get("code"),
                                town=raw.get("ville") or place.get("city"), postal=place.get("postalCode", ""), seller_type=seller,
                                published_at=raw.get("date_creation"), image=image, url=target, price=raw.get("prix"), currency="EUR")
                if row:
                    result[row["id"]] = row
            if len(seen) == expected:
                return list(result.values())
            if len(seen) > expected or len(seen) == before:
                raise c.CollectionError("Pagination Pléthore Cars incohérente ou incomplète.")
        raise c.CollectionError("Nombre maximal de pages Pléthore Cars atteint.")
    finally:
        remote.close()


def collect_dyler(client):
    src = source("dyler")
    html = client.get(src.url)
    data = assigned_json(html, r"App\.State\.initialSearchData\s*=\s*", src.name)
    csrf = assigned_json(html, r"App\.State\.csrfToken\s*=\s*", src.name)
    session = assigned_json(html, r"App\.State\.searchSessionId\s*=\s*", src.name)
    if not isinstance(data, dict) or any(not isinstance(v, str) or not v or len(v) > 1000 or "\r" in v or "\n" in v for v in (csrf, session)):
        raise c.CollectionError("Contexte public Dyler non reconnu.")
    maker = next((n.get("value") for n in data.get("searchLabels", []) if mapping(n).get("field") == "manufacturer_id" and c.fold(mapping(n).get("title")) == "opel"), None)
    if type(maker) is not int:
        raise c.CollectionError("Recherche Opel Dyler non reconnue.")
    result, seen = {}, set()
    expected = 0
    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            data = client.post_json(f"https://{src.host}/cars/search.json", {"subjects": ["opel"], "page": page, "popstate": 0, "search_session_id": session},
                                    headers={"X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest"})
        expected = max(expected, integer(data.get("total"), src.name))
        cards = data.get("cars")
        if not isinstance(cards, list):
            raise c.CollectionError("Liste Dyler non reconnue.")
        currency = c.text(data.get("currency")).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise c.CollectionError("Devise Dyler non reconnue.")
        before = len(seen)
        for raw in cards:
            if not isinstance(raw, dict) or not raw.get("id"):
                raise c.CollectionError("Annonce Dyler non reconnue.")
            seen.add(raw["id"])
            if raw.get("published") is not True or raw.get("status") != "published" or raw.get("auction") or c.fold(raw.get("location_country")) != "fr":
                continue
            title = c.text(raw.get("title"))
            year = title_year(title)
            if c.model_of(title, "", None, year) is None:
                continue
            target = c.safe_url(raw.get("car_path"), src.url)
            if not target:
                raise c.CollectionError("Lien Dyler inattendu.")
            detail = BeautifulSoup(client.get(target), "html.parser")
            row = schema_listing(src.id, detail, target, country="FR", title=title, year=year, image=raw.get("image"), price=raw.get("price"), currency=currency)
            if row:
                result[row["id"]] = row
        if len(seen) >= expected:
            return list(result.values())
        if len(seen) == before:
            raise c.CollectionError("Pagination Dyler répétée ou incomplète.")
    raise c.CollectionError("Nombre maximal de pages Dyler atteint.")


COLLECT = {"carandclassic": collect_carandclassic, "retrocalage": collect_retrocalage, "paruvendu": collect_paruvendu,
           "autoscout24": collect_autoscout24, "carjager": collect_carjager, "plethorecars": collect_plethorecars, "dyler": collect_dyler}


def collect_source(ident, client):
    return COLLECT[ident](client)
