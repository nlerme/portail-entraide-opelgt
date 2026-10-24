from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

SCRAPERS = Path(__file__).resolve().parents[1] / "scrapers"
if str(SCRAPERS) not in sys.path:
    sys.path.insert(0, str(SCRAPERS))

import gtteile as gt  # noqa: E402


def listing_html():
    return '''<div class="productlist-viewmode-grid"><div class="product-container">
      <div class="title-description"><div class="title"><a href="/fr/kupplungszug-11l.html">Kupplungszug</a></div></div>
      <div class="price">30,00 EUR</div><div>Temps de livraison: env. 2-3 jours Ajouter au panier</div>
    </div></div>'''


def test_gt_page_extraction_never_calls_translation(monkeypatch):
    monkeypatch.setattr(gt, "translate_to_french", lambda *args: (_ for _ in ()).throw(AssertionError("Individual translation")))
    monkeypatch.setattr(gt, "fetch", lambda *args: (listing_html(), gt.ROOT_URL))
    item = gt.scrape_listing_page(gt.CATEGORY_URLS[0])["products"][0]
    assert item["nom_traduit"] == "Kupplungszug" and item["prix"] == "30,00€"
    assert gt.extract_listing_products(listing_html(), gt.ROOT_URL, requests.Session())[0]["prix"] == "30,00€"


def test_gt_completes_with_batched_translation_throttled_and_real_progress(monkeypatch, tmp_path, catalogue_progress):
    monkeypatch.setattr(gt, "startup_checks", lambda: None)
    monkeypatch.setattr(gt, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(gt, "CATEGORY_URLS", ("category-a", "category-b"))
    monkeypatch.setattr(gt, "inspect_category", lambda category: {"pages": [category]})
    monkeypatch.setenv("GTTEILE_CACHE_DIR", str(tmp_path / "cache"))
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps([{"nom": "Kupplungszug 0", "nom_traduit": "Câble d'embrayage"}]))
    monkeypatch.setenv("CATALOG_PREVIOUS_OUTPUT", str(previous))
    def page(category):
        start = 0 if category.endswith("a") else 50
        return {"products": [{
            "nom": f"Kupplungszug {i}", "nom_traduit": f"Kupplungszug {i}", "prix": "30,00€",
            "disponibilite": "en stock", "url_photo": "inconnu", "url_fiche": f"https://www.pro-gt.de/fr/item-{i}.html",
        } for i in range(start, start + 50)]}
    monkeypatch.setattr(gt, "scrape_listing_page", page)
    calls = []
    def throttled(self, url, **kwargs):
        calls.append(kwargs)
        assert kwargs["timeout"] == (3, 6)
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "3600"
        raise requests.HTTPError("rate limited", response=response)
    monkeypatch.setattr(requests.Session, "get", throttled)
    output = tmp_path / "catalogue.json"
    products = gt.build_catalog(output, workers=2)
    assert len(products) == 100 and all(item["prix"] == "30,00€" for item in products)
    assert next(item for item in products if item["nom"] == "Kupplungszug 0")["nom_traduit"] == "Câble d'embrayage"
    assert 1 <= len(calls) <= 2
    assert json.loads(output.read_text()) == products
    snapshot = catalogue_progress[-1]
    assert snapshot["phases"]["pages"]["done"] == 2
    assert snapshot["phases"]["translations"]["done"] == 100
    assert snapshot["progress_percent"] == 95
    values = [value["progress_percent"] for value in catalogue_progress]
    assert values == sorted(values)
    cache = json.loads((tmp_path / "cache/translations.json").read_text())
    assert "Kupplungszug 0" in cache and "Kupplungszug 1" not in cache


def test_gt_cli_options_bound_parallelism_and_network_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(gt, "TIMEOUT", gt.TIMEOUT)
    monkeypatch.setattr(gt, "MAX_WORKERS", gt.MAX_WORKERS)
    monkeypatch.setattr(gt, "OUTPUT_FILE", gt.OUTPUT_FILE)
    def run():
        assert "--workers" in sys.argv and sys.argv[-1] == "4"
        assert gt.TIMEOUT == (7.0, 7.0)
        retry = gt.make_session().get_adapter("https://").max_retries
        assert retry.total == 1 and retry.read == 0 and retry.status == 0
        assert retry.respect_retry_after_header is False
        return 0
    monkeypatch.setattr(gt, "_LEGACY_MAIN", run)
    assert gt._run_legacy(tmp_path / "gt.json", 100, 7) == 0


def test_all_scrapers_report_same_bundle_version():
    version = (SCRAPERS.parent / "VERSION").read_text().strip()
    for name in ["opelixparts", "splendidparts", "edelschmiede", "gtteile", "atz", "opelgtsource", "oldtimermotorenteile", "twoldtimerteile"]:
        assert (SCRAPERS / f"{name}.py").exists()
        result = subprocess.run([sys.executable, str(SCRAPERS / f"{name}.py"), "--version"], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and version in result.stdout, (name, result.stderr)

