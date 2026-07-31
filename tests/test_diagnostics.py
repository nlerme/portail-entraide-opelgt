from __future__ import annotations

import json
from pathlib import Path

from app.pieces.models import CatalogSyncStatus, CatalogSyncSupplierStatus
from app.pieces.services import diagnostics


def _record(index: int) -> dict[str, str]:
    return {
        "nom": f"Pièce {index}",
        "nom_traduit": f"Pièce {index}",
        "prix": f"{10 + index},00 €",
        "disponibilite": "en stock",
        "url_photo": "",
        "url_fiche": f"https://example.test/{index}",
    }


def test_diagnostics_reports_catalog_quality_and_history(monkeypatch, tmp_path: Path):
    catalog = tmp_path / "splendidparts.json"
    catalog.write_text(json.dumps([_record(1), _record(2)]), encoding="utf-8")
    monkeypatch.setattr(diagnostics, "MODULE_BY_SITE_ID", {"splendid_parts": "splendidparts"})
    monkeypatch.setattr(diagnostics, "_catalog_path", lambda site_id: catalog)
    monkeypatch.setattr(diagnostics, "_catalog_quality", lambda site_id, path: (True, "", 2, 2))
    monkeypatch.setattr(
        diagnostics,
        "_catalog_metrics",
        lambda site_id, path: type(
            "Metrics",
            (),
            {"item_count": 2, "known_prices": 2, "known_availability": 2, "unique_titles": 2},
        )(),
    )
    monkeypatch.setattr(
        diagnostics,
        "get_sync_status",
        lambda: CatalogSyncStatus(
            ready=True,
            suppliers=[
                CatalogSyncSupplierStatus(
                    site_id="splendid_parts",
                    site_name="SplendidParts",
                    status="ok",
                    ok=True,
                    item_count=2,
                    message="OK",
                    duration_seconds=12.5,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        diagnostics,
        "history_summary",
        lambda site_ids: {
            "splendid_parts": {
                "snapshots": 4,
                "distinct_items": 2,
                "observations": 8,
                "first_at": "2026-06-01T00:00:00+00:00",
                "last_at": "2026-07-01T00:00:00+00:00",
            }
        },
    )

    result = diagnostics.catalog_diagnostics()

    assert len(result) == 1
    row = result[0]
    assert row["usable"] is True
    assert row["price_coverage_percent"] == 100.0
    assert row["availability_coverage_percent"] == 100.0
    assert row["last_duration_seconds"] == 12.5
    assert row["history_snapshots"] == 4
    assert row["history_observations"] == 8
