from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent / ".runtime"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
TEST_ROOT.mkdir(parents=True)
CONFIG = Path(__file__).resolve().parents[1] / "config.example.json"
SECRETS = TEST_ROOT / "secrets.json"
SECRETS.write_text(json.dumps({"app_secret": "test-secret", "admin_password_hash": ""}), encoding="utf-8")
os.environ["PORTAIL_CONFIG"] = str(CONFIG)
os.environ["PORTAIL_SECRETS"] = str(SECRETS)
os.environ["PORTAIL_DATA_DIR"] = str(TEST_ROOT / "data")


@pytest.fixture(autouse=True)
def no_live_geocoding(monkeypatch):
    """The normal suite never sends advertised towns to a live external API."""
    from app.annonces.geography import GeoResolver
    monkeypatch.setattr(GeoResolver, "fetch", lambda self, params: [])


@pytest.fixture
def catalogue_progress(monkeypatch, tmp_path):
    """Observe real scraper counters without contacting a supplier."""
    scraper_dir = str(Path(__file__).resolve().parents[1] / "scrapers")
    monkeypatch.syspath_prepend(scraper_dir)
    import catalog_progress

    path = tmp_path / "progress.json"
    monkeypatch.setenv("CATALOG_PROGRESS_FILE", str(path))
    snapshots = []
    lock = threading.Lock()
    update = catalog_progress._update

    def observe(change, **kwargs):
        with lock:
            update(change, **kwargs)
            snapshots.append(json.loads(path.read_text()))

    monkeypatch.setattr(catalog_progress, "_update", observe)
    catalog_progress.reset_progress("Test")
    return snapshots
