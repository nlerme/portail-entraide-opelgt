from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

from app.pieces.models import CatalogSyncStatus, CatalogSyncSupplierStatus
from app.pieces.services import catalogs

SCRAPERS = Path(__file__).resolve().parents[1] / "scrapers"
if str(SCRAPERS) not in sys.path:
    sys.path.insert(0, str(SCRAPERS))

import edelschmiede as edel  # noqa: E402


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    for name, value in {
        "_completed_items": 0, "_expected_items": 0, "_detail_failures": 0, "_progress_percent": 5,
        "_details_unavailable": threading.Event(), "OUTPUT_FILE": tmp_path / "edelschmiede.json",
    }.items():
        monkeypatch.setattr(edel, name, value)
    monkeypatch.setenv("EDELSCHMIEDE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("EDELSCHMIEDE_PROGRESS_FILE", str(tmp_path / "progress.json"))
    monkeypatch.delenv("CATALOG_PREVIOUS_OUTPUT", raising=False)
    monkeypatch.setattr(catalogs, "CATALOG_DIR", tmp_path / "catalogues")
    monkeypatch.setattr(catalogs, "SYNC_STATUS_PATH", tmp_path / "catalogues/sync_status.json")
    monkeypatch.setattr(catalogs, "_STATUS", CatalogSyncStatus(running=True, suppliers=[
        CatalogSyncSupplierStatus(site_id="edelschmiede", site_name="Edelschmiede", status="running", progress_percent=5),
    ]))


def _item(index=1):
    return {
        "nom": f"Clutch Cable {index}", "nom_traduit": f"Câble {index}", "prix": "29,90€",
        "disponibilite": "en stock", "url_photo": "inconnu",
        "url_fiche": f"https://www.edelschmiede.com/cable-{index}",
    }


def _listing(indices):
    return '<p>Items 1 - 2 of 3</p><div id="product-list">' + "".join(
        f'''<article class="productbox"><a class="productbox-title" href="/cable-{i}">Clutch Cable {i}</a>
        <span class="price">29,90 €</span><button name="inWarenkorb">In den Warenkorb</button></article>'''
        for i in indices
    ) + "</div>"


def test_scrape_completes_with_live_progress_when_translation_is_throttled(monkeypatch, tmp_path):
    calls = []
    progress = []
    original_report = edel.report_progress

    def report(percent, message):
        original_report(percent, message)
        progress.append(json.loads((tmp_path / "progress.json").read_text())["progress_percent"])

    def fetch(session, url):
        calls.append(url)
        if url == edel.ROOT_URL:
            return _listing([1, 2])
        if url == edel.page_url(2):
            return _listing([3])
        index = url.rsplit("-", 1)[-1]
        return f'<h1>Clutch Cable {index}</h1><div>In stock</div>'

    translation_calls = []

    def translation_get(*args, **kwargs):
        translation_calls.append(kwargs)
        response = requests.Response()
        response.status_code = 429
        response.url = "https://translate.googleapis.com/translate_a/single"
        return response

    monkeypatch.setattr(edel, "fetch", fetch)
    monkeypatch.setattr(edel, "report_progress", report)
    monkeypatch.setattr(requests.Session, "get", translation_get)
    result = edel.scrape(output=tmp_path / "edelschmiede.json", workers=2, timeout=3, quiet=True)
    assert result.ok, result.details
    assert result.item_count == 3
    assert calls.count(edel.ROOT_URL) == 1
    assert 1 <= len(translation_calls) <= 2
    assert translation_calls[0]["params"]["sl"] == "auto"
    assert progress == sorted(progress)
    assert any(10 < value < 90 for value in progress)
    assert progress[-1] == 99
    assert json.loads(Path(result.output_path).read_text())[0]["nom_traduit"] == "Clutch Cable 1"


@pytest.mark.parametrize("failure", [429, "timeout"])
def test_detail_failures_stop_repeating_over_the_whole_catalogue(monkeypatch, failure):
    calls = []

    def fetch(session, url):
        calls.append(url)
        if failure == "timeout":
            raise requests.Timeout("offline")
        response = requests.Response()
        response.status_code = failure
        raise requests.HTTPError("rate limited", response=response)

    monkeypatch.setattr(edel, "fetch", fetch)
    with edel.make_session() as session:
        items = [edel.enrich_item(session, _item(i)) for i in range(50)]
    assert len(calls) == (1 if failure == 429 else 2)
    assert all(item["prix"] == "29,90€" and item["disponibilite"] == "en stock" for item in items)


def test_http_retries_cannot_wait_for_an_unbounded_retry_after():
    with edel.make_session() as session:
        retry = session.adapters["https://"].max_retries
        assert retry.total == 1
        assert retry.read == 1
        assert not retry.respect_retry_after_header
        assert 429 not in retry.status_forcelist


def test_cli_worker_and_timeout_options_are_applied_and_restored(monkeypatch, tmp_path):
    seen = []
    previous = edel.MAX_WORKERS, edel.TIMEOUT
    monkeypatch.setattr(edel, "_LEGACY_MAIN", lambda: seen.append((edel.MAX_WORKERS, edel.TIMEOUT)))
    edel._run_legacy(tmp_path / "catalogue.json", workers=32, timeout=7.5)
    assert seen == [(4, (5.0, 7.5))]
    assert (edel.MAX_WORKERS, edel.TIMEOUT) == previous


def test_partial_catalogue_never_overwrites_previous_valid_output(monkeypatch, tmp_path):
    output = tmp_path / "edelschmiede.json"
    original = json.dumps([_item()]).encode()
    output.write_bytes(original)
    monkeypatch.setattr(edel, "fetch", lambda session, url: _listing([1]) if url == edel.ROOT_URL else _listing([2]))
    monkeypatch.setattr(edel, "enrich_item", lambda session, item: item)
    monkeypatch.setattr(edel, "translate_items", lambda items: [item.update(nom_traduit=item["nom"]) for item in items])
    result = edel.scrape(output=output, quiet=True)
    assert not result.ok
    assert output.read_bytes() == original
    assert "Catalogue incomplet" in result.details


@pytest.mark.parametrize("value", [-1, 100, "50", True, None])
def test_progress_relay_rejects_invalid_values(tmp_path, value):
    progress = tmp_path / "progress.json"
    progress.write_text(json.dumps({"progress_percent": value, "message": "invalid"}))
    catalogs._relay_edelschmiede_progress(progress)
    assert catalogs._STATUS.suppliers[0].progress_percent == 5


def test_progress_relay_is_monotonic_and_respects_terminal_state(tmp_path):
    progress = tmp_path / "progress.json"
    progress.write_text(json.dumps({"progress_percent": 62, "message": "150/277 pièces traitées"}))
    catalogs._relay_edelschmiede_progress(progress)
    assert catalogs.read_sync_status_snapshot().suppliers[2].progress_percent == 62
    progress.write_text(json.dumps({"progress_percent": 12, "message": "stale"}))
    catalogs._relay_edelschmiede_progress(progress)
    assert catalogs._STATUS.suppliers[0].progress_percent == 62
    catalogs._STATUS.suppliers[0].status = "ok"
    progress.write_text(json.dumps({"progress_percent": 99, "message": "late"}))
    catalogs._relay_edelschmiede_progress(progress)
    assert catalogs._STATUS.suppliers[0].progress_percent == 62


def test_deadline_kills_the_scraper_and_reaps_it(monkeypatch, tmp_path):
    processes = []
    original_popen = subprocess.Popen

    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(catalogs.subprocess, "Popen", popen)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        catalogs._run_edelschmiede_process(
            [sys.executable, "-c", "import time; time.sleep(60)"], env=os.environ.copy(),
            progress_file=tmp_path / "absent.json", timeout=0.2, poll_interval=0.02,
        )
    assert time.monotonic() - started < 3
    assert processes[0].poll() is not None


@pytest.mark.parametrize("site_id,module", catalogs.MODULE_BY_SITE_ID.items())
def test_orchestrator_cleans_timed_out_progress_and_preserves_catalogue(monkeypatch, site_id, module):
    catalogs._STATUS.suppliers = [CatalogSyncSupplierStatus(site_id=site_id, site_name=site_id, status="running", progress_percent=5)]
    output = catalogs._catalog_path(site_id)
    output.parent.mkdir(parents=True)
    original = json.dumps([_item()]).encode()
    output.write_bytes(original)

    def run(command, *, site_id, env, progress_file, timeout):
        expected = min(catalogs.settings.catalog_update_timeout_seconds, 1800) if site_id in {"edelschmiede", "pro_gt"} else catalogs.settings.catalog_update_timeout_seconds
        assert timeout == expected
        if site_id in {"edelschmiede", "pro_gt"}:
            assert "--workers" in command and "--timeout" in command
        assert env["CATALOG_PROGRESS_FILE"] == str(progress_file)
        progress_file.write_text('{"progress_percent": 50}')
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(catalogs, "_run_catalog_process", run)
    catalogs._sync_one_supplier(site_id, module)
    assert output.read_bytes() == original
    supplier = catalogs._STATUS.suppliers[0]
    assert supplier.status == "failed" and supplier.progress_percent == 100
    assert "Délai maximal dépassé" in supplier.message
    assert not list(output.parent.glob("*.progress.json"))


@pytest.mark.parametrize("site_id,module", catalogs.MODULE_BY_SITE_ID.items())
def test_real_child_progress_is_visible_before_catalogue_publication(monkeypatch, tmp_path, site_id, module):
    catalogs._STATUS.suppliers = [CatalogSyncSupplierStatus(site_id=site_id, site_name=site_id, status="running", progress_percent=5)]
    scraper_root = tmp_path / "scripts"
    scraper_root.mkdir()
    script = scraper_root / f"{module}.py"
    items = [_item(1), _item(2)]
    script.write_text(
        "import json, os, sys, time\nfrom pathlib import Path\n"
        "args=sys.argv\n"
        "output=Path(args[args.index('--output')+1])\n"
        "status=Path(args[args.index('--status-file')+1])\n"
        "progress=Path(os.environ['CATALOG_PROGRESS_FILE'])\n"
        "for value in (10, 50, 90):\n"
        " temp=progress.with_suffix('.tmp')\n"
        " temp.write_text(json.dumps({'progress_percent':value,'message':str(value)}))\n"
        " temp.replace(progress)\n time.sleep(0.15)\n"
        f"output.write_text(json.dumps({items!r}))\n"
        "status.write_text(json.dumps({'ok':True,'status':'ok','duration_seconds':0.45}))\n"
    )
    output = catalogs._catalog_path(site_id)
    output.parent.mkdir(parents=True)
    old = json.dumps([_item()]).encode()
    output.write_bytes(old)
    monkeypatch.setattr(catalogs, "SCRAPER_ROOT", scraper_root)
    monkeypatch.setattr(catalogs, "archive_catalog", lambda *a, **kw: None)
    original_run = catalogs._run_catalog_process
    monkeypatch.setattr(catalogs, "_run_catalog_process", lambda *a, **kw: original_run(*a, **kw, poll_interval=0.02))
    original_set = catalogs._set_supplier_status
    observed = []

    def set_status(site_id, update):
        if 5 < update.get("progress_percent", 0) < 100:
            observed.append((update["progress_percent"], output.read_bytes() == old))
        original_set(site_id, update)

    monkeypatch.setattr(catalogs, "_set_supplier_status", set_status)
    catalogs._sync_one_supplier(site_id, module)
    assert any(value == 50 and preserved for value, preserved in observed)
    assert [value for value, _ in observed] == sorted(value for value, _ in observed)
    assert all(preserved for _, preserved in observed)
    assert catalogs._STATUS.suppliers[0].status == "ok"
    assert catalogs._STATUS.suppliers[0].progress_percent == 100
    assert json.loads(output.read_text()) == items
    assert not list(output.parent.glob("*.progress.json"))
