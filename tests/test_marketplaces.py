"""Public marketplace formats, strict scope and complete pagination; no network."""
from __future__ import annotations

import json

import pytest
from bs4 import BeautifulSoup

from app.annonces import collectors as c
from app.annonces import marketplaces as m
from app.annonces import service


class Pages:
    def __init__(self, *pages, posts=()):
        self.pages, self.posts = iter(pages), iter(posts)
        self.urls, self.payloads = [], []
        self.closed = False

    def get(self, url):
        self.urls.append(url)
        return next(self.pages)

    def post_json(self, url, payload, **options):
        self.payloads.append((url, payload, options))
        return next(self.posts)

    def close(self):
        self.closed = True


def inertia(props):
    return '<script data-page="app" type="application/json">' + json.dumps({"props": props}) + '</script>'


def ld(data):
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


def vehicle(**changes):
    return {**{"@type": "Car", "name": "Opel GT 1900", "vehicleModelDate": "1971",
               "image": "https://public.carjager.com/fixture.jpg", "offers": {
                   "price": "22000", "priceCurrency": "EUR", "availability": "https://schema.org/InStock",
                   "seller": {"@type": "AutoDealer"}}}, **changes}


def cc_card(ident=1, **changes):
    return {**{"id": ident, "type": "basic", "isSold": False, "url": f"/fr/voiture/C{ident}",
               "location": {"countryCode": "FR", "region": "Essonne"}}, **changes}


def cc_index(cards, **changes):
    return inertia({"make": {"slug": "opel"}, "model": {"slug": "gt"}, "listings": cards,
                    "totalListingCount": len(cards), **changes})


def cc_detail(ident=1, **changes):
    return inertia({"listing": {**{"advertRef": f"C{ident}", "title": "Opel GT 1900", "isAvailable": True,
                                   "isPart": False, "advertTypeId": 1, "countryCode": "FR", "vehicle": {"year": 1971},
                                   "price": {"money": {"value": 1950050, "currency": {"name": "EUR"}}},
                                   "seller": {"sellerType": "private"}, "listingDate": "01/11/2026",
                                   "updatedAt": "2026-11-18", "location": {"shortLocation": "Limours"},
                                   "images": [{"md": {"src": "https://assets.carandclassic.com/fixture.jpg?width=800"}}]}, **changes}})


def test_carandclassic_real_fields_and_filters():
    cards = [cc_card(), cc_card(2, location={"countryCode": "NL"}), cc_card(3, isSold=True),
             cc_card(4), cc_card(5), cc_card(6), cc_card(7), cc_card(8)]
    pages = Pages(cc_index(cards), cc_detail(), cc_detail(4, vehicle={"year": 2007}),
                  cc_detail(5, isPart=True), cc_detail(6, advertTypeId=2),
                  cc_detail(7, isAvailable=False), cc_detail(8, title="Opel GT/J", vehicle={"year": 1973}))
    rows = m.collect_carandclassic(pages)
    assert [r["model"] for r in rows] == ["1900", "GT/J"]
    row = rows[0]
    assert (row["price"], row["currency"], row["published_at"]) == (19500.5, "EUR", "2026-11-01")
    assert (row["department"], row["seller_type"]) == ("91", "particulier")
    assert row["image_url"].endswith("fixture.jpg?width=800")
    assert len(pages.urls) == 7  # Foreign and sold cards never fetch a detail.


@pytest.mark.parametrize("page", [cc_index([], totalListingCount=1), inertia({}), cc_index([], totalListingCount="0")])
def test_carandclassic_missing_or_partial_results_are_errors(page):
    with pytest.raises(c.CollectionError):
        m.collect_carandclassic(Pages(page))


def retro_ad(ident=1, **changes):
    return {**{"id": ident, "titre": "Opel GT 1100 1969", "description": "<p>Prix : 18 500 €</p>",
               "estVisible": True, "type": {"name": "PROPOSE"}, "categorie": {"nom": "Véhicules de Collection"},
               "departement": {"numero": "91"}, "ville": "Limours", "estPro": False,
               "valideLe": {"date": "2026-11-01T12:00:00+01:00"}, "mini": "/glide/fixture.jpg",
               "email": "ignored@example.invalid", "tokenRenouvellement": "never-persist"}, **changes}


def retro_index(rows, count=None):
    return f'<h1>{len(rows) if count is None else count} Résultats</h1><script>const allItems = {json.dumps(rows)};</script>'


def test_retrocalage_public_ads_only_no_contact_or_renewal_data():
    rows = m.collect_retrocalage(Pages(retro_index([
        retro_ad(), retro_ad(2, type={"name": "RECHERCHE"}), retro_ad(3, categorie={"nom": "Pièces"}),
        retro_ad(4, estVisible=False), retro_ad(5, departement={"numero": "BE"}),
        retro_ad(6, titre="Opel GT 2007"), retro_ad(7, titre="Opel GT/J 1973", estPro=True),
    ])))
    assert [r["model"] for r in rows] == ["1100", "GT/J"]
    assert rows[0]["url"] == "https://www.retrocalage.com/api/annonces/1?expanded=true"
    assert rows[0]["price"] == 18500 and rows[1]["seller_type"] == "professionnel"
    assert "never-persist" not in json.dumps(rows) and "ignored@" not in json.dumps(rows)
    with pytest.raises(c.CollectionError, match="incomplète"):
        m.collect_retrocalage(Pages(retro_index([], count=1)))


def scout_ad(ident=1, **changes):
    return {**{"id": str(ident), "title": "Opel GT", "vehicle": {"modelVersionInput": "1900", "engineDisplacementInCCM": 1900},
               "location": {"countryCode": "FR", "city": "Limours", "zip": "91470"}, "seller": {"type": "Dealer"},
               "vehicleDetails": [{"iconName": "calendar", "data": "02/1973"}], "availableNow": True,
               "url": f"/offres/opel-gt-cat_ma54mo16604-{ident}", "images": ["https://prod.pictures.autoscout24.net/fixture.jpg"],
               "price": {"priceRaw": 18500, "priceFormatted": "18 500 €"}}, **changes}


def scout_index(rows, total=None):
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {
        "listings": rows, "numberOfResults": len(rows) if total is None else total}}}) + '</script>'


def test_autoscout_pagination_country_modern_filter_and_unknown_publication_date():
    pages = Pages(scout_index([scout_ad(), scout_ad(2, location={"countryCode": "DE"})], 4),
                  scout_index([scout_ad(3, vehicleDetails=[{"iconName": "calendar", "data": "2007"}]),
                               scout_ad(4, seller={"type": "Private"})], 4))
    rows = m.collect_autoscout24(pages)
    assert len(rows) == 2 and rows[0]["year"] == 1973
    assert rows[0]["published_at"] is None  # Registration year is not publication.
    assert rows[0]["department"] == "91" and rows[1]["seller_type"] == "particulier"
    assert "page=2" in pages.urls[1]
    with pytest.raises(c.CollectionError, match="répétée"):
        m.collect_autoscout24(Pages(scout_index([scout_ad()], 2), scout_index([scout_ad()], 2)))


def test_query_only_robots_rule_does_not_block_make_model_path(monkeypatch):
    client = c.PublicClient(m.source("autoscout24"))
    calls = []
    def get(url):
        calls.append(url)
        return "User-agent: *\nDisallow: /lst? # generic search\nDisallow: /lst/?\nDisallow: /private\n" if url.endswith("/robots.txt") else "page"
    monkeypatch.setattr(client, "_get", get)
    try:
        assert client.get(client.source.url) == "page"
        for forbidden in ["/lst?x=1", "/lst/?x=1", "/private/x"]:
            with pytest.raises(c.AccessRestricted, match="robots.txt"):
                client.get("https://www.autoscout24.fr" + forbidden)
        assert len(calls) == 2
    finally:
        client.close()


def test_paruvendu_location_from_vehicle_card_not_country_of_origin():
    url = "/a/voiture-occasion/opel/gt/123A1KVVOOPGT"
    cards = '<h1>3 annonces Opel GT</h1>'
    for ident, year, place in [(1, 1971, "Limours (91470)"), (2, 1969, "Rome (Italie)"), (3, 2007, "Paris (75015)")]:
        cards += f'<article data-id="{ident}"><a href="{url}" title="Opel GT">Voiture</a>Année {year}<p><img src="/marker.svg"><span>{place}</span></p></article>'
    pages = Pages(cards, ld(vehicle(countryOfOrigin="Germany", image="https://img.paruvendu.fr/fixture.jpg")))
    rows = m.collect_paruvendu(pages)
    assert len(rows) == 1 and rows[0]["location"] == "Limours" and rows[0]["department"] == "91"
    assert len(pages.urls) == 2 and rows[0]["published_at"] is None
    with pytest.raises(c.CollectionError):
        m.collect_paruvendu(Pages('<h1>Opel GT</h1>'))


def test_carjager_location_flag_postal_spaces_and_original_schema():
    targets = [f"https://www.carjager.com/acheter/voiture-collection/opel-gt-CJVCL{i}A.html" for i in (1, 2)]
    index = ld({"@type": "ItemList", "itemListElement": [{"url": u} for u in targets]})
    def detail(country):
        return ld(vehicle(countryOfOrigin="France")) + f'''<li><span>Emplacement de l'auto</span>
             <img alt="Drapeau" src="/flag-icons/{country}.svg">Paris ( <span>75015</span> )</li>'''
    rows = m.collect_carjager(Pages(index, detail("fr"), detail("it")))
    assert len(rows) == 1
    assert (rows[0]["location"], rows[0]["postal_code"], rows[0]["department"]) == ("Paris", "75015", "75")
    assert rows[0]["seller_type"] == "professionnel" and rows[0]["published_at"] is None


def plethore_ad(ident=1, **changes):
    return {**{"id": ident, "titre": "Opel GT 1900", "annee": 1971, "actif": 1, "id_pays": {"code": "FR"},
               "ville": "Limours", "prix": 22000, "date_creation": "2026-11-01T12:00:00Z", "pro": True,
               "images": [{"directus_files_id": {"id": "fixture-asset"}}]}, **changes}


@pytest.mark.parametrize("cards,expected", [([], 0), ([plethore_ad(), plethore_ad(2, actif=2), plethore_ad(3, id_pays={"code": "BE"}), plethore_ad(4, annee=2007)], 1)])
def test_plethore_anonymous_public_search_no_account(monkeypatch, cards, expected):
    remote = Pages(posts=[{"data": cards, "meta": {"filter_count": len(cards)}}])
    monkeypatch.setattr(c, "PublicClient", lambda source: remote)
    rows = m.collect_plethorecars(Pages())
    assert len(rows) == expected and remote.closed
    assert remote.payloads == [(m.PLETHORE_API, {"search": "Opel", "limit": 50, "page": 1}, {})]
    if rows:
        assert rows[0]["url"].endswith("/opel-gt-1900-0000001.html")
        assert rows[0]["price"] == 22000 and rows[0]["published_at"] == "2026-11-01"
        assert rows[0]["image_url"].startswith("https://edge.plethorecars.fr/api/v1/assets/")


def test_plethore_incomplete_collection_closes_client(monkeypatch):
    remote = Pages(posts=[{"data": [], "meta": {"filter_count": 1}}])
    monkeypatch.setattr(c, "PublicClient", lambda source: remote)
    with pytest.raises(c.CollectionError, match="incomplète"):
        m.collect_plethorecars(Pages())
    assert remote.closed


def dyler_ad(ident=1, **changes):
    return {**{"id": ident, "title": "1971 Opel GT 1900", "published": True, "status": "published", "auction": False,
               "location_country": "FR", "car_path": f"/cars/opel/gt-for-sale/1971/{ident}/opel-gt-for-sale",
               "price": 24000, "image": "https://assets.dyler.com/fixture.jpg"}, **changes}


def dyler_data(cards, total=None):
    return {"total": len(cards) if total is None else total, "cars": cards, "currency": "USD",
            "searchLabels": [{"field": "manufacturer_id", "title": "Opel", "value": 215}]}


def dyler_html(data):
    return '<script>App.State.initialSearchData = ' + json.dumps(data) + '; App.State.csrfToken="anonymous"; App.State.searchSessionId="stable-order";</script>'


def test_dyler_full_pagination_same_search_context_original_currency():
    first = dyler_data([dyler_ad(1, location_country="NL"), dyler_ad(2, title="Opel Manta")], 4)
    second = dyler_data([dyler_ad(3), dyler_ad(4, published=False)], 4)
    detail = ld(vehicle(image="https://assets.dyler.com/fixture.jpg", offers={"price": 24000, "priceCurrency": "USD", "seller": {"@type": "Person"}}))
    pages = Pages(dyler_html(first), detail, posts=[second])
    rows = m.collect_dyler(pages)
    assert len(rows) == 1 and rows[0]["currency"] == "USD" and rows[0]["price"] == 24000
    assert pages.payloads[0][1] == {"subjects": ["opel"], "page": 2, "popstate": 0, "search_session_id": "stable-order"}
    assert pages.payloads[0][2]["headers"]["X-CSRF-Token"] == "anonymous"


def test_dyler_repeated_page_is_error_not_successful_empty():
    page = dyler_data([dyler_ad(location_country="NL")], 2)
    with pytest.raises(c.CollectionError, match="répétée"):
        m.collect_dyler(Pages(dyler_html(page), posts=[page]))


@pytest.mark.parametrize("ident,path", [
    ("carandclassic", "/fr/voiture/C123"), ("retrocalage", "/api/annonces/123?expanded=true"),
    ("paruvendu", "/a/voiture-occasion/opel/gt/123A1KVVOOPGT"), ("autoscout24", "/offres/opel-gt-cat_ma54-123"),
    ("carjager", "/acheter/voiture-collection/opel-gt-CJVCL123A.html"),
    ("plethorecars", "/voiture-collection/opel-gt-0000123.html"), ("dyler", "/cars/opel/gt-for-sale/1971/123/opel-gt-for-sale"),
])
def test_direct_urls_only_for_seven_new_sources(ident, path):
    src = m.source(ident)
    assert c.safe_url(path, src.url) == f"https://{src.host}{path}"
    for malicious in ["/", "/login", "https://evil.invalid" + path, f"https://{src.host}.evil.invalid" + path,
                      f"https://user@{src.host}" + path, f"https://{src.host}:8080" + path]:
        assert c.safe_url(malicious, src.url) is None


@pytest.mark.parametrize("availability", ["SoldOut", "OutOfStock", "Discontinued"])
def test_schema_sold_vehicle_is_excluded(availability):
    soup = BeautifulSoup(ld(vehicle(offers={"availability": "https://schema.org/" + availability})), "html.parser")
    assert m.schema_listing("carjager", soup, "https://www.carjager.com/acheter/voiture-collection/opel-gt-CJVCL1A.html", country="FR") is None


@pytest.mark.parametrize("configured,expected", [
    (["lesanciennes", "leboncoin", "classicnumber", "classictrader"], [s.id for s in c.SOURCES]),
    (["lesanciennes"], ["lesanciennes"]), ([], []), (["dyler", "carandclassic"], ["carandclassic", "dyler"]),
])
def test_new_defaults_and_existing_custom_selection(monkeypatch, configured, expected):
    monkeypatch.setattr(service, "section", lambda name: {"default_enabled_sources": configured})
    assert service.default_enabled_sources() == expected


@pytest.mark.parametrize("status", [401, 403, 429])
def test_read_only_search_post_stops_on_refusal(monkeypatch, status):
    client = c.PublicClient(m.source("dyler"))
    calls = []
    class Response:
        status_code = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def post(url, **kwargs):
        calls.append(url)
        assert kwargs["json"] == {"subjects": ["opel"]} and kwargs["allow_redirects"] is False
        return Response()
    monkeypatch.setattr(client.session, "post", post)
    try:
        with pytest.raises(c.AccessRestricted):
            client._get("https://dyler.com/cars/search.json", payload={"subjects": ["opel"]})
        assert len(calls) == 1
    finally:
        client.close()
