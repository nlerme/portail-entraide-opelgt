from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.pieces.models import CatalogSyncStatus, ConnectivityStatus, SearchRequest
from app.pieces.services import search as search_module
from app.pieces.services.cache import cache


@pytest.fixture(autouse=True)
def _disable_price_history(monkeypatch):
    monkeypatch.setattr(search_module, "price_history_map", lambda site_id: {})


def _online_connectivity() -> ConnectivityStatus:
    return ConnectivityStatus(
        online=True,
        detail="Connexion Internet disponible",
        checked_at=datetime.now(timezone.utc).isoformat(),
        response_ms=1,
    )


def _ready_sync() -> CatalogSyncStatus:
    return CatalogSyncStatus(
        running=False,
        ready=True,
        last_success_at="2026-07-10T07:00:00+00:00",
        detail="Catalogues fournisseurs prêts pour la recherche.",
    )


def _record(
    title: str, url: str, *, price: str = "25,90 €", availability: str = "en stock"
) -> dict[str, str]:
    return {
        "nom": title,
        "nom_traduit": title,
        "prix": price,
        "disponibilite": availability,
        "url_photo": "https://example.test/photo.jpg",
        "url_fiche": url,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keywords,records,expected_titles",
    [
        (
            "câble embrayage",
            [
                _record(
                    "Clutch Cable Opel GT",
                    "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt.html",
                ),
                _record(
                    "Clutch Cable Opel Manta A 1900",
                    "https://splenditparts.de/shop/en/manta/900-clutch-cable-opel-manta-a-1900.html",
                ),
                _record(
                    "Clutch Cable Opel GT 1100",
                    "https://splenditparts.de/shop/en/gearbox-clutch/967-clutch-cable-opel-gt-1100.html",
                ),
            ],
            {"Clutch Cable Opel GT"},
        ),
        (
            "essuie glace",
            [
                _record(
                    "Wiper Arm Set Opel GT, black",
                    "https://splenditparts.de/shop/en/body/39-wiper-arm-set-opel-gt-black.html",
                ),
                _record(
                    "Wiper Blade Opel Rekord C",
                    "https://splenditparts.de/shop/en/rekord/901-wiper-blade-opel-rekord-c.html",
                ),
                _record(
                    "Opel GT Wiper Arm Set, chrome",
                    "https://splenditparts.de/shop/en/body/40-opel-gt-wiper-arm-set-chrome.html",
                ),
            ],
            {"Wiper Arm Set Opel GT, black", "Opel GT Wiper Arm Set, chrome"},
        ),
    ],
)
async def test_catalog_search_filters_model_and_uses_canonical_french(
    monkeypatch, keywords, records, expected_titles
):
    cache.delete_namespace("search")
    online = _online_connectivity()
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: records)

    response = await search_module.run_search(
        SearchRequest(model="1900", keywords=keywords, sites=["splendid_parts"]),
        connectivity=online,
    )

    assert {offer.title for offer in response.offers} == expected_titles
    assert response.total_offers == len(expected_titles)
    assert response.reports[0].pages_read == 1
    assert response.reports[0].state == "ok"


@pytest.mark.asyncio
async def test_catalog_search_blocks_until_catalogues_are_ready(monkeypatch):
    cache.delete_namespace("search")
    monkeypatch.setattr(
        search_module,
        "get_sync_status",
        lambda: CatalogSyncStatus(running=True, ready=False, detail="Synchronisation en cours."),
    )

    with pytest.raises(RuntimeError, match="Synchronisation en cours"):
        await search_module.run_search(
            SearchRequest(model="1900", keywords="câble embrayage", sites=["splendid_parts"]),
            connectivity=_online_connectivity(),
        )


@pytest.mark.asyncio
async def test_plain_keywords_use_or_semantics_and_rank_full_match_first(monkeypatch):
    cache.delete_namespace("search")
    records = [
        _record("Clutch component Opel GT reference 001", "https://example.test/1"),
        _record("Cable accessory Opel GT reference 002", "https://example.test/2"),
        _record("Clutch Cable Opel GT reference 003", "https://example.test/3"),
        _record("Distributor Opel GT reference 004", "https://example.test/4"),
    ]
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: records)

    response = await search_module.run_search(
        SearchRequest(model="1900", keywords="câble embrayage", sites=["splendid_parts"]),
        connectivity=_online_connectivity(),
    )

    assert [offer.title for offer in response.offers] == [
        "Clutch Cable Opel GT reference 003",
        "Cable accessory Opel GT reference 002",
        "Clutch component Opel GT reference 001",
    ]
    assert response.offers[0].query_confidence > response.offers[1].query_confidence
    assert response.offers[1].query_confidence == response.offers[2].query_confidence


@pytest.mark.asyncio
async def test_quoted_phrase_and_plus_terms_have_documented_and_semantics(monkeypatch):
    cache.delete_namespace("search")
    records = [
        _record("Clutch component Opel GT reference 001", "https://example.test/1"),
        _record("Cable accessory Opel GT reference 002", "https://example.test/2"),
        _record("Clutch Cable Opel GT reference 003", "https://example.test/3"),
        _record("Cable control for clutch Opel GT reference 004", "https://example.test/4"),
    ]
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: records)

    quoted = await search_module.run_search(
        SearchRequest(model="1900", keywords='"câble embrayage"', sites=["splendid_parts"]),
        connectivity=_online_connectivity(),
    )
    cache.delete_namespace("search")
    required = await search_module.run_search(
        SearchRequest(model="1900", keywords="+câble +embrayage", sites=["splendid_parts"]),
        connectivity=_online_connectivity(),
    )

    assert [offer.title for offer in quoted.offers] == ["Clutch Cable Opel GT reference 003"]
    assert {offer.title for offer in required.offers} == {
        "Clutch Cable Opel GT reference 003",
        "Cable control for clutch Opel GT reference 004",
    }


@pytest.mark.asyncio
async def test_catalog_search_never_uses_category_url_or_surrounding_page_terms(monkeypatch):
    cache.delete_namespace("search")
    records = [
        _record(
            "Distributor Delco Opel GT",
            "https://example.test/gearbox-clutch/distributor-delco-opel-gt",
            price="29,90 €",
        ),
        _record(
            "Front Turn Signal Lens Opel GT",
            "https://example.test/gearbox-clutch/front-turn-signal-lens",
            price="39,90 €",
        ),
        _record(
            "Clutch Cable Opel GT 1.9L",
            "https://example.test/gearbox-clutch/clutch-cable-opel-gt",
            price="49,00 €",
        ),
    ]
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: records)

    response = await search_module.run_search(
        SearchRequest(model="1900", keywords="câble d'embrayage", sites=["splendid_parts"]),
        connectivity=_online_connectivity(),
    )

    assert [offer.title for offer in response.offers] == ["Clutch Cable Opel GT 1.9L"]
    assert response.offers[0].price == 49.0
    assert response.offers[0].query_confidence != pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_catalog_search_matches_original_supplier_title_when_translation_is_bad(monkeypatch):
    cache.delete_namespace("search")
    relevant = _record(
        "Kupplungszug Opel GT 1,9S",
        "https://atz-online.com/p/opel-gt-kupplungszug/",
        price="29,90€",
    )
    relevant["nom_traduit"] = "Commande de transmission Opel GT"
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: [relevant])

    response = await search_module.run_search(
        SearchRequest(model="1900", keywords="câble embrayage", sites=["atz_online"]),
        connectivity=_online_connectivity(),
    )

    assert [offer.url for offer in response.offers] == [relevant["url_fiche"]]


@pytest.mark.asyncio
async def test_clutch_cable_search_is_title_strict_for_all_eight_supplier_catalogues(monkeypatch):
    cache.delete_namespace("search")
    catalogues = {
        "opelix_parts": [
            _record("câble embrayage GT 1900", "https://opelix.test/embrayage/cable", price="37,95 €"),
            _record("Clignotant avant Opel GT", "https://opelix.test/embrayage/clignotant", price="22,00 €"),
        ],
        "splendid_parts": [
            _record(
                "Clutch Cable Opel GT 1.9L", "https://splendid.test/gearbox-clutch/cable", price="25,90 €"
            ),
            _record(
                "Delco Distributor Opel GT",
                "https://splendid.test/gearbox-clutch/distributor",
                price="89,00 €",
            ),
        ],
        "edelschmiede": [
            _record(
                "Clutch cable control Opel GT", "https://edelschmiede.test/clutch/cable", price="32,95 €"
            ),
            _record(
                "Turn signal lens Opel GT", "https://edelschmiede.test/clutch/turn-signal", price="14,90 €"
            ),
        ],
        "pro_gt": [
            _record(
                "Câble d'embrayage Opel GT 1,9L", "https://pro-gt.test/fr/embrayage/cable", price="30,00 €"
            ),
            _record(
                "Distributeur d'allumage Opel GT",
                "https://pro-gt.test/fr/embrayage/distributeur",
                price="95,00 €",
            ),
        ],
        "atz_online": [
            _record(
                "Kupplungszug für Opel GT 1900", "https://atz.test/opel-gt-kupplung/cable", price="29,90 €"
            ),
            _record("Blinker vorne Opel GT", "https://atz.test/opel-gt-kupplung/blinker", price="18,90 €"),
        ],
        "opel_gt_source": [
            _record("Clutch Cable, Opel GT 1.9L - 2.4L", "https://ogs.test/clutch/cable", price="49,00 $"),
            _record("Distributor Cap, Opel GT", "https://ogs.test/clutch/distributor-cap", price="12,00 $"),
        ],
        "oldtimer_motorenteile": [
            _record("Kupplungsseil Opel GT 1900", "https://oldtimer.test/kupplung/cable", price="39,90 €"),
            _record("Blinkerglas Opel GT", "https://oldtimer.test/kupplung/blinkerglas", price="16,90 €"),
        ],
        "tw_oldtimerteile": [
            _record("Kupplungszug Opel GT 1900", "https://tw-oldtimerteile.test/kupplung/cable", price="34,90 €"),
            _record("Blinker vorne Opel GT", "https://tw-oldtimerteile.test/kupplung/blinker", price="19,90 €"),
        ],
    }
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: catalogues[site_id])

    response = await search_module.run_search(
        SearchRequest(
            model="1900",
            keywords="câble d'embrayage",
            sites=list(catalogues),
        ),
        connectivity=_online_connectivity(),
    )

    assert response.total_offers == 8
    assert {offer.site_id for offer in response.offers} == set(catalogues)
    assert all(offer.price is not None and offer.price > 0 for offer in response.offers)
    assert all(offer.query_confidence >= 0.86 for offer in response.offers)
    assert not any(
        forbidden in offer.title.casefold()
        for offer in response.offers
        for forbidden in ("clignotant", "distributor", "distributeur", "turn signal", "blinker")
    )


@pytest.mark.asyncio
async def test_atz_getrag_cable_and_opelix_release_bearing_follow_or_and_quote_rules(monkeypatch):
    cache.delete_namespace("search")
    catalogues = {
        "atz_online": [
            _record(
                "Kupplungszug für Getrag-Getriebe",
                "https://atz-online.com/p/kupplungszug/",
                price="39,90 €",
                availability="en rupture de stock",
            ),
            _record(
                "Opel GT – Kupplungszug für 4-Gang (Original-Opel)",
                "https://atz-online.com/p/opel-gt-kupplungszug-fuer-4-gang-original-opel/",
                price="54,90 €",
            ),
        ],
        "opelix_parts": [
            _record(
                "Butée embrayage CIH 1.5-3.0.",
                "https://www.opelixparts.com/accueil/1157-butee-d-embrayage-.html",
                price="24,90 €",
            )
        ],
    }
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: catalogues[site_id])

    plain = await search_module.run_search(
        SearchRequest(
            model="1900",
            keywords="câble embrayage",
            sites=["atz_online", "opelix_parts"],
        ),
        connectivity=_online_connectivity(),
    )
    cache.delete_namespace("search")
    quoted = await search_module.run_search(
        SearchRequest(
            model="1900",
            keywords='"câble embrayage"',
            sites=["atz_online", "opelix_parts"],
        ),
        connectivity=_online_connectivity(),
    )

    assert {offer.url for offer in plain.offers} == {
        "https://atz-online.com/p/kupplungszug/",
        "https://atz-online.com/p/opel-gt-kupplungszug-fuer-4-gang-original-opel/",
        "https://www.opelixparts.com/accueil/1157-butee-d-embrayage-.html",
    }
    assert {offer.url for offer in quoted.offers} == {
        "https://atz-online.com/p/kupplungszug/",
        "https://atz-online.com/p/opel-gt-kupplungszug-fuer-4-gang-original-opel/",
    }


@pytest.mark.asyncio
async def test_search_offer_contains_previous_price_and_trend(monkeypatch):
    from app.pieces.services.history import PriceHistory, item_history_key

    cache.delete_namespace("search")
    record = _record("Clutch Cable Opel GT", "https://example.test/clutch-cable", price="35,00 €")
    key = item_history_key("splendid_parts", record)
    monkeypatch.setattr(search_module, "get_sync_status", _ready_sync)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: [record])
    monkeypatch.setattr(
        search_module,
        "price_history_map",
        lambda site_id: {
            key: PriceHistory(
                current_price=35.0,
                previous_price=30.0,
                previous_at="2026-07-01T00:00:00+00:00",
                currency="EUR",
            )
        },
    )

    response = await search_module.run_search(
        SearchRequest(model="1900", keywords="câble embrayage", sites=["splendid_parts"]),
        connectivity=_online_connectivity(),
    )

    assert response.offers[0].previous_price == 30.0
    assert response.offers[0].previous_price_date == "2026-07-01T00:00:00+00:00"
    assert response.offers[0].price_trend == "up"
