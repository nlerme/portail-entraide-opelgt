from __future__ import annotations

from typing import Any

from app.pieces.scrapers.sites import SITES
from app.pieces.services.catalogs import (
    MODULE_BY_SITE_ID,
    _catalog_metrics,
    _catalog_path,
    _catalog_quality,
    get_sync_status,
)
from app.pieces.services.history import history_summary


def catalog_diagnostics() -> list[dict[str, Any]]:
    status = get_sync_status()
    by_id = {item.site_id: item for item in status.suppliers}
    histories = history_summary(site_id for site_id in MODULE_BY_SITE_ID if site_id in SITES)
    diagnostics: list[dict[str, Any]] = []
    for site_id in MODULE_BY_SITE_ID:
        if site_id not in SITES:
            continue
        path = _catalog_path(site_id)
        quality_ok, quality_message, _count, _prices = _catalog_quality(site_id, path)
        metrics = _catalog_metrics(site_id, path)
        supplier_status = by_id.get(site_id)
        history = histories.get(site_id, {})
        price_coverage = (metrics.known_prices / metrics.item_count * 100) if metrics.item_count else 0.0
        availability_coverage = (
            metrics.known_availability / metrics.item_count * 100 if metrics.item_count else 0.0
        )
        diagnostics.append(
            {
                "site_id": site_id,
                "site_name": SITES[site_id].name,
                "catalog_path": str(path),
                "usable": quality_ok,
                "quality_message": quality_message,
                "item_count": metrics.item_count,
                "known_prices": metrics.known_prices,
                "price_coverage_percent": round(price_coverage, 1),
                "known_availability": metrics.known_availability,
                "availability_coverage_percent": round(availability_coverage, 1),
                "unique_titles": metrics.unique_titles,
                "last_status": supplier_status.status if supplier_status else "missing",
                "last_message": supplier_status.message if supplier_status else "Statut absent.",
                "last_started_at": supplier_status.started_at if supplier_status else None,
                "last_finished_at": supplier_status.finished_at if supplier_status else None,
                "last_duration_seconds": supplier_status.duration_seconds if supplier_status else None,
                "history_snapshots": int(history.get("snapshots") or 0),
                "history_distinct_items": int(history.get("distinct_items") or 0),
                "history_observations": int(history.get("observations") or 0),
                "history_first_at": history.get("first_at"),
                "history_last_at": history.get("last_at"),
            }
        )
    return diagnostics
