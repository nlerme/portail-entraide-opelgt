from __future__ import annotations

import json
from pathlib import Path

from app.pieces.services import catalogs


def _items(count: int, *, known_prices: int | None = None, known_availability: int | None = None):
    prices = count if known_prices is None else known_prices
    availabilities = count if known_availability is None else known_availability
    return [
        {
            "nom": f"Pièce Opel GT {index}",
            "nom_traduit": f"Pièce Opel GT {index}",
            "prix": "10,00 €" if index < prices else "inconnu",
            "disponibilite": "en stock" if index < availabilities else "inconnu",
            "url_photo": "",
            "url_fiche": f"https://example.test/{index}",
        }
        for index in range(count)
    ]


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(catalogs, "CATALOG_DIR", tmp_path)


def test_rejects_large_item_count_drop(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "splendidparts.json").write_text(json.dumps(_items(100)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_items(50)), encoding="utf-8")
    reasons = catalogs._catalog_suspicion_reasons("splendid_parts", candidate)
    assert any("nombre de pièces anormalement faible" in reason for reason in reasons)


def test_rejects_large_price_loss(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "atz.json").write_text(json.dumps(_items(100)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_items(100, known_prices=20)), encoding="utf-8")
    reasons = catalogs._catalog_suspicion_reasons("atz_online", candidate)
    assert any("forte disparition des prix" in reason for reason in reasons)


def test_rejects_total_availability_loss(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "opelixparts.json").write_text(json.dumps(_items(100)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_items(100, known_availability=0)), encoding="utf-8")
    reasons = catalogs._catalog_suspicion_reasons("opelix_parts", candidate)
    assert any("aucune disponibilité reconnue" in reason for reason in reasons)


def test_accepts_normal_catalog_variation(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    (tmp_path / "gtteile.json").write_text(json.dumps(_items(100)), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_items(85, known_prices=80, known_availability=75)), encoding="utf-8")
    assert catalogs._catalog_suspicion_reasons("pro_gt", candidate) == ()
