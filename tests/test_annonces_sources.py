from __future__ import annotations

import html
import json

import pytest

from app.annonces import collectors as c


class Pages:
    def __init__(self, *pages):
        self.pages = iter(pages)

    def get(self, url):
        return next(self.pages)


def number_card(ident, country="France", title="Opel GT 1900", year=1969, price="16 000 €"):
    return f'''<div class="gridint"><div class="car_grid_pays">{country}</div>
    <h3><a class="carhit" carid="{ident}" href="opel-gt-collection-a-vendre-{ident}.html">{title}</a></h3>
    <ul class="car-list-infos-1"><li>{year}</li></ul><div class="adprice">{price}</div></div>'''


def test_classicnumber_filters_france_and_uses_original_date_price_photo():
    results = (
        '<h1>Les annonces de Opel GT</h1><p>3 véhicules trouvés</p><ul class="searchList">'
        + number_card(1)
        + number_card(2, "Belgium")
        + number_card(3, title="Opel GT Roadster", year=2008)
        + "</ul>"
    )
    detail = """<h1>Opel GT 1900</h1><div class="pro-part">PART</div>
    <div class="seller-address">ESSONNE (91) - Limours (91470)</div>
    <div class="car_info_date">Annonce publiée le 03/10/2026 (actualisée hier)</div>
    <meta property="og:image" content="https://www.classicnumber.com/images/stories/test.jpg">"""
    rows = c.collect_classicnumber(Pages(results, detail))
    assert len(rows) == 1
    assert rows[0]["price"] == 16000 and rows[0]["seller_type"] == "particulier"
    assert rows[0]["department"] == "91" and rows[0]["location"] == "Limours"
    assert rows[0]["published_at"] == "2026-10-03"
    assert rows[0]["image_url"].endswith("/images/stories/test.jpg")
    assert rows[0]["url"].endswith("-a-vendre-1.html")


def encode(value):
    if isinstance(value, dict):
        return [0, {k: encode(v) for k, v in value.items()}]
    if isinstance(value, list):
        return [1, [encode(v) for v in value]]
    return [0, value]


def trader_card(ident, **changes):
    raw = {
        **dict(
            id=ident,
            type="CarAd",
            state="published",
            title="1973 | Opel GT/J 1900",
            yearOfProduction=1973,
            publishDate="2026-10-01",
            updateDate="2026-10-23",
            location={"countryCode": "FR", "city": "Bastia", "postalCode": "20200"},
            seller={"isDealer": True, "isPrivate": False},
            vehicle={"cubicCapacity": 1897},
            price={"amount": 20490, "currency": "EUR"},
            images=[{"originalImageUrl": "https://cdn.classic-trader.com/I/images/test.jpg"}],
            canonicalUrl=f"https://www.classic-trader.com/fr/voitures/annonce/opel/gt/gt-j-1900/1973/{ident}",
        ),
        **changes,
    }
    props = {"vehicleAd": encode(raw)}
    return (
        '<astro-island component-export="ResultPageCarDataClassifiedAd" props="'
        + html.escape(json.dumps(props), quote=True)
        + '"></astro-island>'
    )


def test_classictrader_public_props_filter_country_modern_sold_and_price():
    ld = json.dumps({"mainEntity": [{"name": "Opel GT (4 offres)"}]})
    page = '<h1>Opel GT voitures anciennes</h1><script type="application/ld+json">' + ld + "</script>"
    page += (
        trader_card(1)
        + trader_card(2, location={"countryCode": "NL"})
        + trader_card(3, yearOfProduction=2008)
        + trader_card(4, state="sold")
    )
    rows = c.collect_classictrader(Pages(page))
    assert len(rows) == 1 and rows[0]["model"] == "GT/J"
    assert rows[0]["published_at"] == "2026-10-01" and rows[0]["price"] == 20490
    assert rows[0]["department"] == "2B" and rows[0]["seller_type"] == "professionnel"


@pytest.mark.parametrize("collector", [c.collect_classicnumber, c.collect_classictrader])
def test_new_sources_fail_closed_on_changed_structure(collector):
    with pytest.raises(c.CollectionError):
        collector(Pages("<h1>Maintenance</h1>"))


def test_price_units_and_unknowns():
    for raw, expected in [
        ("16 500 €", 16500),
        ("16\u202f500,50 €", 16500.5),
        ("Prix sur demande", None),
        ("Faire offre", None),
    ]:
        assert c.french_price(raw)[0] == expected
    assert c.price_value(float("nan")) is None and c.price_value(-1) is None
    assert c.price_value(True) is None
