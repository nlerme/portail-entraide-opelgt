from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.pieces.services import catalogs

SCRAPERS = Path(__file__).resolve().parents[1] / "scrapers"
if str(SCRAPERS) not in sys.path:
    sys.path.insert(0, str(SCRAPERS))

import catalog_progress as progress  # noqa: E402
import gtteile  # noqa: E402
import oldtimermotorenteile as oldtimer  # noqa: E402
import opelixparts as opelix  # noqa: E402
import splendidparts as splendid  # noqa: E402
import twoldtimerteile as tw  # noqa: E402


def item(index):
    return {
        "nom": f"Pièce {index}", "nom_traduit": f"Pièce {index}", "prix": "29,90€",
        "disponibilite": "en stock", "url_photo": "inconnu",
        "url_fiche": f"https://www.pro-gt.de/fr/piece-{index}.html",
    }


def assert_work_increments(snapshots, phase, total):
    values = [entry["progress_percent"] for entry in snapshots]
    assert values == sorted(values)
    assert len({value for value in values if 10 < value < 95}) >= 3
    assert snapshots[-1]["phases"][phase]["total"] == total
    assert max(values) < 100


def test_opelix_reports_each_completed_detail(monkeypatch, catalogue_progress):
    monkeypatch.setattr(opelix, "fetch", lambda *args: "<html></html>")
    monkeypatch.setattr(opelix, "cards", lambda soup: [1, 2, 3])
    monkeypatch.setattr(opelix, "listing_item", lambda card, url: item(card))
    monkeypatch.setattr(opelix, "enrich", lambda args: args[0])
    progress.start_phase("pages", 10, 90, 2, "Pages et fiches")
    assert len(opelix.scrape_page((1, {}))[1]) == 3
    assert len(opelix.scrape_page((2, {}))[1]) == 3
    assert_work_increments(catalogue_progress, "pages", 2)
    assert catalogue_progress[-1]["progress_percent"] == 90


@pytest.mark.parametrize("workers", [1, 2])
def test_splendid_reports_pages_and_translations(monkeypatch, catalogue_progress, workers):
    monkeypatch.setattr(splendid, "MAX_LISTING_WORKERS", workers)
    monkeypatch.setattr(splendid, "scrape_page", lambda page, cookies, **kw: (page, [item(page)]))
    monkeypatch.setattr(splendid, "translate_one", lambda name: (name, name))
    products = splendid.scrape_all_pages(3, {})
    assert_work_increments(catalogue_progress, "pages", 3)
    splendid.translate_names(products)
    assert catalogue_progress[-1]["phases"]["translations"]["done"] == 3
    assert catalogue_progress[-1]["progress_percent"] == 94


def test_gtteile_reports_category_and_page_completions(monkeypatch, tmp_path, catalogue_progress):
    import catalog_translation
    monkeypatch.setattr(catalog_translation, "translate_names", lambda names, **kw: dict.fromkeys(names, "Pièce"))
    monkeypatch.setattr(gtteile, "startup_checks", lambda: None)
    monkeypatch.setattr(gtteile, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(gtteile, "CATEGORY_URLS", ("a", "b", "c"))
    monkeypatch.setattr(gtteile, "inspect_category", lambda category: {"pages": [category]})
    monkeypatch.setattr(gtteile, "scrape_listing_page", lambda page: {"products": [item(page)]})
    products = gtteile.build_catalog(tmp_path / "gtteile.json", workers=2)
    assert len(products) == 3
    assert_work_increments(catalogue_progress, "categories", 3)
    assert catalogue_progress[-1]["phases"]["pages"]["done"] == 3


def test_oldtimer_reports_both_languages_and_matching(monkeypatch, tmp_path, catalogue_progress):
    monkeypatch.setattr(oldtimer, "telecharger_page_catalogue", lambda *args: "html")
    monkeypatch.setattr(oldtimer, "detecter_pagination", lambda html: (3, 3))
    monkeypatch.setattr(oldtimer, "recuperer_et_parser", lambda page, language, *args: (page, language, [dict(item(page), cle=str(page))]))
    products = oldtimer.scraper(tmp_path / "oldtimer.json", 2, 3)
    assert len(products) == 3
    assert_work_increments(catalogue_progress, "pages", 6)
    assert catalogue_progress[-1]["phases"]["pages"]["done"] == 6
    assert catalogue_progress[-1]["phases"]["matching"]["done"] == 3


def test_tw_reports_pages_discovered_within_each_category(monkeypatch, tmp_path, catalogue_progress):
    category = tw.Category("Moteur", "https://www.tw-oldtimerteile.de/Opel-GT/Motor")
    monkeypatch.setattr(tw, "fetch_listing", lambda *args: ("root", tw.ROOT_URL))
    monkeypatch.setattr(tw, "discover_categories", lambda *args: [category])
    monkeypatch.setattr(tw, "parse_listing_page", lambda html, url: [item(int(html))])
    monkeypatch.setattr(tw, "pagination_urls", lambda html, *args: [f"{category.url}?page={int(html) + 1}"] if int(html) < 3 else [])
    monkeypatch.setattr(tw, "translate_to_french", lambda name, timeout: name)
    crawl = tw.crawl_category

    def fetch(url, *args):
        return url.rsplit("=", 1)[1] if "=" in url else "1", url

    monkeypatch.setattr(tw, "crawl_category", lambda category, timeout: crawl(category, timeout, fetcher=fetch))
    products = tw.scrape_catalogue(tmp_path / "tw.json", 2, 3)
    assert len(products) == 3
    assert_work_increments(catalogue_progress, "categories", 1)
    assert catalogue_progress[-1]["phases"]["translations"]["done"] == 3


def test_progress_updates_are_atomic_across_worker_processes(monkeypatch, tmp_path):
    path = tmp_path / "progress.json"
    monkeypatch.setenv("CATALOG_PROGRESS_FILE", str(path))
    progress.reset_progress("Opelix Parts")
    progress.start_phase("pages", 10, 90, 120, "Pièces traitées")
    env = os.environ | {"PYTHONPATH": str(SCRAPERS)}
    command = [sys.executable, "-c", "from catalog_progress import advance_phase\nfor _ in range(30): advance_phase('pages')"]
    processes = [subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
    values = []
    while any(process.poll() is None for process in processes):
        values.append(json.loads(path.read_text())["progress_percent"])
        time.sleep(0.005)
    for process in processes:
        _, errors = process.communicate(timeout=3)
        assert process.returncode == 0, errors
    data = json.loads(path.read_text())
    assert data["phases"]["pages"]["done"] == 120
    assert data["progress_percent"] == 90
    assert values == sorted(values)
    progress.report_progress(25, "Reprise")
    assert json.loads(path.read_text())["progress_percent"] == 90
    progress.reset_progress("Nouvelle mise à jour")
    assert json.loads(path.read_text())["progress_percent"] == 6
    assert json.loads(path.read_text())["phases"] == {}


def test_unwritable_progress_does_not_break_a_scrape(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_PROGRESS_FILE", str(tmp_path))
    progress.reset_progress("Test")
    progress.start_phase("pages", 10, 90, 3, "Pages")
    progress.advance_phase("pages")


def test_deadline_stops_child_process_pool_and_drains_inherited_pipes(tmp_path):
    child_pid = tmp_path / "pid"
    command = [sys.executable, "-c", (
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        f"Path({str(child_pid)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )]
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        catalogs._run_catalog_process(
            command, site_id="opelix_parts", env=os.environ.copy(), progress_file=tmp_path / "absent.json",
            timeout=0.5, poll_interval=0.02,
        )
    assert time.monotonic() - started < 3
    assert child_pid.exists()
    state = Path(f"/proc/{int(child_pid.read_text())}/stat")
    assert not state.exists() or state.read_text().split()[2] == "Z"
