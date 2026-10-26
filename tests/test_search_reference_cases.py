from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.pieces.models import CatalogSyncStatus, ConnectivityStatus, SearchRequest
from app.pieces.services import search as search_module
from app.pieces.services.cache import cache

FIXTURE = Path(__file__).parent / "fixtures" / "search_reference_cases.json"


def _record(title: str, url: str, price: str, availability: str = "en stock") -> dict[str, str]:
    return {
        "nom": title,
        "nom_traduit": title,
        "prix": price,
        "disponibilite": availability,
        "url_photo": "https://example.test/photo.jpg",
        "url_fiche": url,
    }


CATALOGS = {
    "atz_online": [
        _record(
            "Kupplungszug für Getrag-Getriebe",
            "https://atz-online.com/p/kupplungszug/",
            "39,90 €",
            "en rupture de stock",
        ),
        _record(
            "Opel GT – Kupplungszug für 4-Gang (Original-Opel)",
            "https://atz-online.com/p/opel-gt-kupplungszug-fuer-4-gang-original-opel/",
            "54,90 €",
        ),
        _record("Blinker vorne Opel GT", "https://atz-online.com/p/blinker-vorne/", "18,90 €"),
    ],
    "opelix_parts": [
        _record(
            "Butée embrayage CIH 1.5-3.0.",
            "https://www.opelixparts.com/accueil/1157-butee-d-embrayage-.html",
            "24,90 €",
        ),
        _record(
            "Clignotant avant Opel GT", "https://www.opelixparts.com/accueil/999-clignotant.html", "22,00 €"
        ),
        _record("Joint de capot neuf Opel GT", "https://opelix.test/joint-capot-neuf", "16,00 €"),
        _record("Joint de capot occasion Opel GT", "https://opelix.test/joint-capot-occasion", "8,00 €"),
    ],
    "splendid_parts": [
        _record(
            "Clutch Cable Opel GT",
            "https://splenditparts.de/shop/en/gearbox-clutch/966-clutch-cable-opel-gt.html",
            "25,90 €",
        ),
        _record(
            "Distributor Opel GT",
            "https://splenditparts.de/shop/en/gearbox-clutch/999-distributor.html",
            "89,00 €",
        ),
        _record(
            "Wiper Arm Set Opel GT, black",
            "https://splenditparts.de/shop/en/body/39-wiper-arm-set-opel-gt-black.html",
            "29,90 €",
        ),
        _record(
            "Opel GT Wiper Arm Set, chrome",
            "https://splenditparts.de/shop/en/body/40-opel-gt-wiper-arm-set-chrome.html",
            "35,90 €",
        ),
        _record("Door Seal Opel GT", "https://splenditparts.de/shop/en/body/41-door-seal.html", "49,90 €"),
    ],
}


def _ready() -> CatalogSyncStatus:
    return CatalogSyncStatus(running=False, ready=True, last_success_at="2026-07-16T00:00:00+00:00")


def _online() -> ConnectivityStatus:
    return ConnectivityStatus(
        online=True,
        detail="OK",
        checked_at=datetime.now(timezone.utc).isoformat(),
        response_ms=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", json.loads(FIXTURE.read_text(encoding="utf-8")), ids=lambda case: case["name"]
)
async def test_reference_search_cases(monkeypatch, case):
    cache.delete_namespace("search")
    monkeypatch.setattr(search_module, "get_sync_status", _ready)
    monkeypatch.setattr(search_module, "load_catalog", lambda site_id: CATALOGS[site_id])
    monkeypatch.setattr(search_module, "price_history_map", lambda site_id: {})

    response = await search_module.run_search(
        SearchRequest(model="1900", keywords=case["query"], sites=case["sites"]),
        connectivity=_online(),
    )
    offers = {offer.url: offer for offer in response.offers}

    expected_urls = set(case.get("expected_urls", []))
    expected_urls.update(item["url"] for item in case.get("expected", []))
    assert set(offers) == expected_urls
    assert not set(case.get("excluded_urls", [])) & set(offers)

    for expected in case.get("expected", []):
        offer = offers[expected["url"]]
        assert offer.site_id == expected["site_id"]
        assert offer.title == expected["title"]
        assert offer.price == pytest.approx(expected["price"])
        assert offer.availability == expected["availability"]
        assert offer.query_confidence >= expected["min_confidence"]
