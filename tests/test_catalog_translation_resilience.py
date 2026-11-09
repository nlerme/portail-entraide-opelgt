from __future__ import annotations

import json
import sys
import threading
from decimal import Decimal
from pathlib import Path

import pytest
import requests

SCRAPERS = Path(__file__).resolve().parents[1] / "scrapers"
if str(SCRAPERS) not in sys.path:
    sys.path.insert(0, str(SCRAPERS))

import atz  # noqa: E402
import catalog_translation as translation  # noqa: E402
import opelgtsource as ogs  # noqa: E402


def _response(status: int, payload: object = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = translation.TRANSLATE_URL
    response._content = json.dumps(payload).encode()
    return response


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_translation_outage_is_bounded_and_does_not_cache_fallback(monkeypatch, tmp_path, failure):
    calls = []
    lock = threading.Lock()

    def get(*args, **kwargs):
        with lock:
            calls.append(kwargs)
        if failure == "timeout":
            raise requests.Timeout("offline")
        return _response(failure)

    monkeypatch.setattr(requests.Session, "get", get)
    names = [f"Clutch Cable {i}" for i in range(200)]
    cache_file = tmp_path / "translations.json"
    result = translation.translate_names(
        names, language="en", cache_file=cache_file, previous_output=tmp_path / "absent.json", workers=16,
    )
    assert result == dict(zip(names, names, strict=True))
    assert 1 <= len(calls) <= 2
    assert all(call["timeout"] == (3, 6) for call in calls)
    assert json.loads(cache_file.read_text()) == {}


def test_translation_seeds_validated_catalogue_and_retries_fallback_next_run(monkeypatch, tmp_path):
    previous = tmp_path / "catalogue.json"
    previous.write_text(json.dumps([
        {"nom": "Clutch Cable", "nom_traduit": "Câble d’embrayage"},
        {"nom": "New Part", "nom_traduit": "New Part"},
    ]))
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(requests.Session, "get", lambda *a, **kw: _response(429))
    kwargs = dict(language="en", cache_file=cache_file, previous_output=previous, workers=2)
    result = translation.translate_names(["Clutch Cable", "New Part"], **kwargs)
    assert result == {"Clutch Cable": "Câble d’embrayage", "New Part": "New Part"}

    calls = []

    def recovered(*args, **kwargs):
        calls.append(kwargs["params"]["q"])
        return _response(200, [[["Nouvelle pièce", None]]])

    monkeypatch.setattr(requests.Session, "get", recovered)
    result = translation.translate_names(["Clutch Cable", "New Part"], **kwargs)
    assert result["New Part"] == "Nouvelle pièce"
    assert calls == ["New Part"]
    calls.clear()
    assert translation.translate_names(["Clutch Cable", "New Part"], **kwargs) == result
    assert calls == []


def test_translation_group_preserves_name_associations(monkeypatch, tmp_path):
    def translated(*args, **kwargs):
        assert kwargs["params"]["q"] == "0001|||Clutch Cable\n0002|||Water Pump"
        return _response(200, [[["0001|||Câble d'embrayage\n0002|||Pompe à eau", None]]])

    monkeypatch.setattr(requests.Session, "get", translated)
    result = translation.translate_names(
        ["Clutch Cable", "Water Pump"], language="en", cache_file=tmp_path / "cache.json",
        previous_output=tmp_path / "absent.json", workers=2,
    )
    assert result == {"Clutch Cable": "Câble d'embrayage", "Water Pump": "Pompe à eau"}


def test_atz_scrape_publishes_prices_when_translation_returns_429(monkeypatch, tmp_path, catalogue_progress):
    listing = """<p class="woocommerce-result-count">1–2 von 2 Ergebnissen</p>
    <li class="product instock"><a href="/p/kupplungszug/">
      <h2>Opel GT Kupplungszug</h2></a><span class="price">29,90 €</span>In den Warenkorb</li>
    <li class="product instock"><a href="/p/wasserpumpe/">
      <h2>Opel GT Wasserpumpe</h2></a><span class="price">49,90 €</span>In den Warenkorb</li>"""
    requested = []
    monkeypatch.setattr(atz, "_requested_urls", requested)

    def fetch(page, attempts):
        requested.append(atz.catalogue_url(page))
        return listing

    def supplemental(url, attempts):
        requested.append(url)
        return listing

    monkeypatch.setattr(atz, "fetch_catalogue_page", fetch)
    monkeypatch.setattr(atz, "fetch_supplemental_category", supplemental)
    monkeypatch.setattr(requests.Session, "get", lambda *a, **kw: _response(429))
    monkeypatch.setenv("ATZ_CACHE_DIR", str(tmp_path / "cache"))
    # Restore this global after the legacy integration sets its output path.
    monkeypatch.setattr(atz, "OUTPUT_FILE", tmp_path / "unused.json")
    result = atz.scrape(output=tmp_path / "atz.staging.json", quiet=True)
    assert result.ok, result.details
    items = json.loads(Path(result.output_path).read_text())
    assert len(items) == 2
    assert items[0]["prix"] == "29,90€"
    assert all(item["nom_traduit"] == item["nom"] for item in items)
    assert "désignations originales conservées" in result.legacy_stdout_tail
    assert any(5 < entry["progress_percent"] < 80 for entry in catalogue_progress)
    assert catalogue_progress[-1]["progress_percent"] == 99
    assert catalogue_progress[-1]["phases"]["translations"]["done"] == 2


def test_ogs_scrape_publishes_prices_when_translation_returns_429(monkeypatch, tmp_path, catalogue_progress):
    from types import SimpleNamespace

    def listing(page):
        return f"""<a href="?page=2">2</a><div class="product-card">
        <a href="/search/{8000 + page}/details"><img src="/img/cable.jpg"></a>
        <div>$49.00</div><div>Clutch Cable {page}</div><div>Part: 8001</div><div>Add to Cart</div>
        </div>"""

    def get(url, *, params=None):
        html = '<select><option value="low_to_high">Price Low to High</option></select>' if params is None else listing(params["page"])
        return SimpleNamespace(text=html)

    monkeypatch.setattr(ogs, "get", get)
    monkeypatch.setattr(ogs, "CACHE_MODE", "off")
    monkeypatch.setattr(ogs, "_request_log", [])
    monkeypatch.setattr(ogs, "TRANSLATION_CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(ogs, "OUTPUT_FILE", tmp_path / "unused.json")
    monkeypatch.setattr(ogs, "usd_to_eur_rate", lambda: Decimal("0.9"))
    monkeypatch.setattr(requests.Session, "get", lambda *a, **kw: _response(429))
    result = ogs.scrape(output=tmp_path / "opelgtsource.staging.json", quiet=True)
    assert result.ok, result.details
    items = json.loads(Path(result.output_path).read_text())
    assert len(items) == 2
    assert items[0]["prix"] == "44,10€"
    assert all(item["nom_traduit"] == item["nom"] for item in items)
    assert any(10 < entry["progress_percent"] < 80 for entry in catalogue_progress)
    assert catalogue_progress[-1]["phases"]["pages"]["done"] == 2
    assert catalogue_progress[-1]["progress_percent"] == 99


def test_ogs_refresh_fetches_current_prices_despite_existing_html_cache(monkeypatch):
    from types import SimpleNamespace

    def listing(price):
        return f"""<div class="product-card"><a href="/search/8001/details">Details</a>
        <div>${price}</div><div>Clutch Cable</div><div>Part: 8001</div><div>Add to Cart</div></div>"""

    calls = []
    monkeypatch.setattr(ogs, "CACHE_MODE", "refresh")
    monkeypatch.setattr(ogs, "_order_by", "low_to_high")
    monkeypatch.setattr(ogs, "_load_cached_page", lambda page: listing("29.00"))
    monkeypatch.setattr(ogs, "_save_cached_page", lambda page, html: None)

    def get(url, *, params):
        calls.append(params)
        return SimpleNamespace(text=listing("49.00"))

    monkeypatch.setattr(ogs, "get", get)
    result = ogs.fetch_page(2)
    assert calls[0]["page"] == 2
    assert result.products[0]["_prix_usd"] == "49.00"
