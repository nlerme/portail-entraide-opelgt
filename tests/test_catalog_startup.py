from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.pieces.models import CatalogSyncStatus
from app.pieces.services import catalogs, history

PARIS = ZoneInfo("Europe/Paris")


def record() -> list[dict[str, str]]:
    return [
        {
            "nom": "Pièce Opel GT",
            "nom_traduit": "Pièce Opel GT",
            "prix": "10,00 €",
            "disponibilite": "en stock",
            "url_photo": "https://example.test/a.jpg",
            "url_fiche": "https://example.test/a",
        }
    ]


def configure_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(catalogs, "CATALOG_DIR", tmp_path)
    monkeypatch.setattr(catalogs, "SYNC_STATUS_PATH", tmp_path / "sync_status.json")
    monkeypatch.setattr(catalogs, "_STATUS", None)
    monkeypatch.setattr(catalogs, "_RUNNING_THREAD", None)
    monkeypatch.setattr(history, "HISTORY_ROOT", tmp_path / "history")
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history" / "catalog_history.sqlite3")


def write_all_catalogs(tmp_path: Path) -> None:
    for module in catalogs.MODULE_BY_SITE_ID.values():
        (tmp_path / f"{module}.json").write_text(json.dumps(record()), encoding="utf-8")


def write_status(tmp_path: Path, completed: str) -> None:
    status = CatalogSyncStatus(last_completed_at=completed, last_success_at=completed)
    (tmp_path / "sync_status.json").write_text(status.model_dump_json(), encoding="utf-8")


def test_missing_catalogs_require_startup_update(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    now = datetime(2026, 7, 16, 10, 0, tzinfo=PARIS)
    check = catalogs.catalog_startup_check(now)
    assert check.update_required is True
    assert len(check.missing_site_ids) == 8


def test_partial_catalogs_require_startup_update(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    write_all_catalogs(tmp_path)
    (tmp_path / "atz.json").unlink()
    write_status(tmp_path, "2026-07-15T02:05:00+02:00")
    check = catalogs.catalog_startup_check(datetime(2026, 7, 16, 10, 0, tzinfo=PARIS))
    assert check.update_required is True
    assert "atz_online" in check.missing_site_ids


def test_old_complete_catalogs_require_update(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    write_all_catalogs(tmp_path)
    write_status(tmp_path, "2026-07-05T23:59:00+02:00")
    check = catalogs.catalog_startup_check(datetime(2026, 7, 16, 10, 0, tzinfo=PARIS))
    assert check.update_required is True
    assert any("échéance planifiée" in reason for reason in check.reasons)


def test_recent_complete_catalogs_are_kept(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    write_all_catalogs(tmp_path)
    write_status(tmp_path, "2026-07-15T02:05:00+02:00")
    check = catalogs.catalog_startup_check(datetime(2026, 7, 16, 10, 0, tzinfo=PARIS))
    assert check.update_required is False


def test_latest_catalog_boundary_for_monday_wednesday_friday_schedule():
    friday = datetime(2026, 7, 17, 2, 0, tzinfo=PARIS)
    assert catalogs.latest_scheduled_catalog_update(friday) == friday
    before_friday = datetime(2026, 7, 17, 1, 59, tzinfo=PARIS)
    assert catalogs.latest_scheduled_catalog_update(before_friday) == datetime(2026, 7, 15, 2, 0, tzinfo=PARIS)
    monday = datetime(2026, 7, 20, 2, 0, tzinfo=PARIS)
    assert catalogs.latest_scheduled_catalog_update(monday) == monday


def test_catalog_with_only_unknown_prices_is_rejected(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    site_id = "splendid_parts"
    path = tmp_path / "splendidparts.json"
    item = record()[0]
    item["prix"] = "inconnu"
    path.write_text(json.dumps([item]), encoding="utf-8")

    ok, message, item_count, known_prices = catalogs._catalog_quality(site_id)

    assert ok is False
    assert "aucun prix numérique" in message
    assert item_count == 1
    assert known_prices == 0


def test_catalog_with_numeric_price_is_usable(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    site_id = "splendid_parts"
    path = tmp_path / "splendidparts.json"
    path.write_text(json.dumps(record()), encoding="utf-8")

    ok, message, item_count, known_prices = catalogs._catalog_quality(site_id)

    assert ok is True
    assert message == ""
    assert item_count == 1
    assert known_prices == 1


def test_monitoring_snapshot_preserves_live_worker_progress(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    site_id = "splendid_parts"
    status = CatalogSyncStatus(
        running=True,
        global_progress_percent=5,
        suppliers=[
            {
                "site_id": site_id,
                "site_name": "SplendidParts",
                "status": "running",
                "ok": False,
                "item_count": 0,
                "message": "Synchronisation en cours.",
                "progress_percent": 5,
            }
        ],
    )
    (tmp_path / "sync_status.json").write_text(status.model_dump_json(), encoding="utf-8")

    snapshot = catalogs.read_sync_status_snapshot()

    supplier = next(item for item in snapshot.suppliers if item.site_id == site_id)
    assert snapshot.running is True
    assert supplier.status == "running"
    assert supplier.progress_percent == 5


def test_failed_refresh_keeps_previous_valid_catalog_searchable(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    site_id = "splendid_parts"
    (tmp_path / "splendidparts.json").write_text(json.dumps(record()), encoding="utf-8")
    completed = "2026-07-12T00:05:00+02:00"
    status = CatalogSyncStatus(
        last_completed_at=completed,
        last_success_at=completed,
        suppliers=[
            {
                "site_id": site_id,
                "site_name": "SplendidParts",
                "status": "failed",
                "ok": False,
                "item_count": 1,
                "message": "Catalogue nouvellement récupéré refusé : aucun prix numérique.",
                "progress_percent": 100,
            }
        ],
    )

    recomputed = catalogs._recompute_ready(status)
    supplier = next(item for item in recomputed.suppliers if item.site_id == site_id)

    assert supplier.ok is True
    assert supplier.status == "ok"
    assert supplier.item_count == 1
    assert "catalogue local valide conservé" in supplier.message


def test_bad_staging_catalog_never_replaces_last_valid_catalog(monkeypatch, tmp_path):
    import subprocess

    configure_paths(monkeypatch, tmp_path)
    scraper_root = tmp_path / "scrapers"
    scraper_root.mkdir()
    (scraper_root / "splendidparts.py").write_text("# fake scraper\n", encoding="utf-8")
    monkeypatch.setattr(catalogs, "SCRAPER_ROOT", scraper_root)

    final_path = tmp_path / "splendidparts.json"
    previous = record()
    final_path.write_text(json.dumps(previous), encoding="utf-8")

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        status_path = Path(command[command.index("--status-file") + 1])
        bad_item = record()[0]
        bad_item["prix"] = "inconnu"
        output.write_text(json.dumps([bad_item]), encoding="utf-8")
        status_path.write_text(
            json.dumps(
                {
                    "supplier": "SplendidParts",
                    "status": "ok",
                    "ok": True,
                    "output_path": str(output),
                    "status_path": str(status_path),
                    "item_count": 1,
                    "duration_seconds": 0.1,
                    "message": "scraping terminé",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(catalogs.subprocess, "run", fake_run)

    result = catalogs._run_supplier_scraper_subprocess("splendid_parts", "splendidparts")

    assert result["ok"] is False
    assert "aucun prix numérique" in result["message"]
    assert json.loads(final_path.read_text(encoding="utf-8")) == previous
    assert not (tmp_path / "splendidparts.staging.json").exists()


def test_valid_staging_catalog_atomically_replaces_previous_catalog(monkeypatch, tmp_path):
    import subprocess

    configure_paths(monkeypatch, tmp_path)
    scraper_root = tmp_path / "scrapers"
    scraper_root.mkdir()
    (scraper_root / "splendidparts.py").write_text("# fake scraper\n", encoding="utf-8")
    monkeypatch.setattr(catalogs, "SCRAPER_ROOT", scraper_root)

    final_path = tmp_path / "splendidparts.json"
    previous = record()
    final_path.write_text(json.dumps(previous), encoding="utf-8")
    replacement = record()
    replacement[0]["nom"] = "Câble embrayage Opel GT 1900"
    replacement[0]["nom_traduit"] = replacement[0]["nom"]
    replacement[0]["prix"] = "37,95 €"

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        status_path = Path(command[command.index("--status-file") + 1])
        output.write_text(json.dumps(replacement), encoding="utf-8")
        status_path.write_text(
            json.dumps(
                {
                    "supplier": "SplendidParts",
                    "status": "ok",
                    "ok": True,
                    "output_path": str(output),
                    "status_path": str(status_path),
                    "item_count": 1,
                    "duration_seconds": 0.1,
                    "message": "scraping terminé",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(catalogs.subprocess, "run", fake_run)

    result = catalogs._run_supplier_scraper_subprocess("splendid_parts", "splendidparts")

    assert result["ok"] is True
    assert result["item_count"] == 1
    assert "1 prix numérique" in result["message"]
    assert json.loads(final_path.read_text(encoding="utf-8")) == replacement


def test_scraper_timeout_preserves_previous_valid_catalog(monkeypatch, tmp_path):
    import subprocess

    configure_paths(monkeypatch, tmp_path)
    scraper_root = tmp_path / "scrapers"
    scraper_root.mkdir()
    (scraper_root / "splendidparts.py").write_text("# fake scraper\n", encoding="utf-8")
    monkeypatch.setattr(catalogs, "SCRAPER_ROOT", scraper_root)

    final_path = tmp_path / "splendidparts.json"
    previous = record()
    final_path.write_text(json.dumps(previous), encoding="utf-8")

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=1)

    monkeypatch.setattr(catalogs.subprocess, "run", fake_run)
    result = catalogs._run_supplier_scraper_subprocess("splendid_parts", "splendidparts")

    assert result["ok"] is False
    assert "Délai maximal dépassé" in result["message"]
    assert json.loads(final_path.read_text(encoding="utf-8")) == previous


def test_missing_scraper_status_preserves_previous_valid_catalog(monkeypatch, tmp_path):
    import subprocess

    configure_paths(monkeypatch, tmp_path)
    scraper_root = tmp_path / "scrapers"
    scraper_root.mkdir()
    (scraper_root / "splendidparts.py").write_text("# fake scraper\n", encoding="utf-8")
    monkeypatch.setattr(catalogs, "SCRAPER_ROOT", scraper_root)

    final_path = tmp_path / "splendidparts.json"
    previous = record()
    final_path.write_text(json.dumps(previous), encoding="utf-8")

    monkeypatch.setattr(
        catalogs.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="bad", stderr="failed"),
    )

    result = catalogs._run_supplier_scraper_subprocess("splendid_parts", "splendidparts")

    assert result["ok"] is False
    assert "n'a pas écrit de statut exploitable" in result["message"]
    assert json.loads(final_path.read_text(encoding="utf-8")) == previous

def test_interrupted_parallel_sync_cannot_remain_at_seventy_three_percent(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    write_all_catalogs(tmp_path)
    suppliers = []
    defaults = catalogs._supplier_defaults()
    for index, supplier in enumerate(defaults):
        interrupted = index < 2
        suppliers.append(
            supplier.model_copy(
                update={
                    "status": "running" if interrupted else "ok",
                    "ok": not interrupted,
                    "progress_percent": 5 if interrupted else 100,
                    "message": "Traitement interrompu." if interrupted else "Prêt.",
                }
            )
        )
    status = CatalogSyncStatus(
        running=False,
        last_completed_at="2026-07-05T00:05:00+02:00",
        suppliers=suppliers,
    )

    recomputed = catalogs._recompute_ready(status)

    assert round(sum(item.progress_percent for item in recomputed.suppliers) / len(recomputed.suppliers)) == 100
    assert all(item.progress_percent == 100 for item in recomputed.suppliers)
    assert all(item.status == "ok" for item in recomputed.suppliers)
    assert all("interrompue" in item.message.lower() or item.message == "Prêt." for item in recomputed.suppliers)

def test_catalog_orchestrator_exception_always_closes_progress(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    catalogs._STATUS = CatalogSyncStatus(
        running=True,
        suppliers=[item.model_copy(update={"status": "pending"}) for item in catalogs._supplier_defaults()],
    )
    monkeypatch.setattr(catalogs, "_supplier_jobs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        catalogs._sync_worker()

    assert catalogs._STATUS is not None
    assert catalogs._STATUS.running is False
    assert all(item.progress_percent == 100 for item in catalogs._STATUS.suppliers)
    assert all(item.status == "failed" for item in catalogs._STATUS.suppliers)



def test_partial_catalogues_remain_ready_when_one_supplier_is_unavailable(monkeypatch, tmp_path):
    configure_paths(monkeypatch, tmp_path)
    write_all_catalogs(tmp_path)
    missing_site_id = "atz_online"
    (tmp_path / "atz.json").unlink()
    status = CatalogSyncStatus(
        running=False,
        last_completed_at="2026-07-05T00:05:00+02:00",
        suppliers=catalogs._supplier_defaults(),
    )

    recomputed = catalogs._recompute_ready(status)
    usable = [supplier for supplier in recomputed.suppliers if supplier.ok and supplier.item_count > 0]
    missing = next(supplier for supplier in recomputed.suppliers if supplier.site_id == missing_site_id)

    assert len(usable) == 7
    assert recomputed.ready is True
    assert missing.ok is False
    assert missing.status in {"missing", "failed"}
    assert "7/8 catalogue(s) prêt(s)" in recomputed.detail
    assert "restent utilisables" in recomputed.detail
    assert "avant d'autoriser la recherche" not in recomputed.detail
