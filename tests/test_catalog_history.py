from __future__ import annotations

import json
from pathlib import Path

from app.pieces.services import history


def _item(price: str, title: str = "Câble embrayage Opel GT") -> dict[str, str]:
    return {
        "nom": title,
        "nom_traduit": title,
        "prix": price,
        "disponibilite": "en stock",
        "url_photo": "https://example.test/photo.jpg",
        "url_fiche": "https://example.test/parts/clutch-cable",
    }


def _configure(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "history"
    monkeypatch.setattr(history, "HISTORY_ROOT", root)
    monkeypatch.setattr(history, "HISTORY_DB", root / "catalog_history.sqlite3")


def test_complete_snapshots_and_piece_price_history_are_retained(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([_item("25,90 €")]), encoding="utf-8")
    history.archive_catalog(
        "splendid_parts",
        catalog,
        captured_at="2026-07-01T00:00:00+00:00",
        currency_hint="EUR",
    )
    catalog.write_text(json.dumps([_item("29,90 €")]), encoding="utf-8")
    history.archive_catalog(
        "splendid_parts",
        catalog,
        captured_at="2026-07-08T00:00:00+00:00",
        currency_hint="EUR",
    )

    snapshots = list((history.HISTORY_ROOT / "splendid_parts").rglob("*.json"))
    assert len(snapshots) == 2
    assert json.loads(snapshots[0].read_text(encoding="utf-8"))[0]["nom"] == "Câble embrayage Opel GT"

    values = history.price_history_map("splendid_parts")
    price = values[history.item_history_key("splendid_parts", _item("29,90 €"))]
    assert price.current_price == 29.90
    assert price.previous_price == 25.90
    assert price.previous_at == "2026-07-01T00:00:00+00:00"
    assert price.trend == "up"

    summary = history.history_summary(["splendid_parts"])["splendid_parts"]
    assert summary["snapshots"] == 2
    assert summary["distinct_items"] == 1
    assert summary["observations"] == 2


def test_stable_and_downward_price_trends(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    catalog = tmp_path / "catalog.json"
    for date, price in (
        ("2026-07-01T00:00:00+00:00", "30,00 €"),
        ("2026-07-08T00:00:00+00:00", "30,00 €"),
    ):
        catalog.write_text(json.dumps([_item(price)]), encoding="utf-8")
        history.archive_catalog("atz_online", catalog, captured_at=date, currency_hint="EUR")
    stable = next(iter(history.price_history_map("atz_online").values()))
    assert stable.trend == "stable"

    catalog.write_text(json.dumps([_item("27,00 €")]), encoding="utf-8")
    history.archive_catalog(
        "atz_online", catalog, captured_at="2026-07-15T00:00:00+00:00", currency_hint="EUR"
    )
    down = next(iter(history.price_history_map("atz_online").values()))
    assert down.previous_price == 30.0
    assert down.trend == "down"


def test_restore_previous_snapshot_keeps_rollback_in_history(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    current = tmp_path / "catalog.json"
    current.write_text(json.dumps([_item("20,00 €")]), encoding="utf-8")
    history.archive_catalog(
        "opelix_parts", current, captured_at="2026-07-01T00:00:00+00:00", currency_hint="EUR"
    )
    current.write_text(json.dumps([_item("24,00 €")]), encoding="utf-8")
    history.archive_catalog(
        "opelix_parts", current, captured_at="2026-07-08T00:00:00+00:00", currency_hint="EUR"
    )

    restored_at = history.restore_previous_snapshot("opelix_parts", current, currency_hint="EUR")

    assert restored_at == "2026-07-01T00:00:00+00:00"
    assert json.loads(current.read_text(encoding="utf-8"))[0]["prix"] == "20,00 €"
    assert history.history_summary(["opelix_parts"])["opelix_parts"]["snapshots"] == 3
