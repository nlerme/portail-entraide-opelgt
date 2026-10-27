from __future__ import annotations

import hashlib
import time

import pytest
import requests

from app.annonces import geography as g
from app.annonces import service as s
from app.annonces import tracking as t


def item(number=0, source="lesanciennes"):
    return {"id": f"{source}:{number}", "source_id": source, "source_name": source, "location": f"Ville{number}",
            "postal_code": f"91{number:03d}", "department": "91", "seller_type": "particulier", "number": number + 1,
            "price": 19000, "first_seen_at": "2026-10-23", "observed_at": "2026-10-26"}


def commune(number=0):
    return {"nom": f"Ville{number}", "codeDepartement": "91", "codesPostaux": [f"91{number:03d}"],
            "centre": {"coordinates": [2.0 + number / 100, 48.0]}}


def point():
    return {"lat": 48.0, "lon": 2.0, "precision": "commune", "label": "Centre de la commune de Ville0"}


def cache_key(row):
    town, department, postal = g.location_parts(row)
    return hashlib.sha256(f"{g.normalized(town)}|{department}|{postal}".encode()).hexdigest()


def test_twenty_one_locations_survive_slow_collection_and_more_than_thirty_seconds_of_geocoding(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])
    def fetch(self, params):
        clock[0] += 5
        return [commune(int(params["codePostal"][2:]))]
    monkeypatch.setattr(g.GeoResolver, "fetch", fetch)
    resolver = g.GeoResolver(tmp_path)
    clock[0] += 13  # The previous implementation localized only 3/21 in this scenario.
    found = [resolver.resolve(item(number)) for number in range(21)]
    assert all(found) and len(found) == 21
    assert resolver.network_seconds == 105 and resolver.request_count == 21
    clock[0] += 300  # A slow source must not expire the next geocoding request.
    assert resolver.resolve(item(21)) and resolver.network_seconds == 110
    resolver.close()


@pytest.mark.parametrize("location", ["91000 Ville0", "Ville0 (91000)", "Ville0 91000", "FR-91000 Ville0", "Ville0 (91000), France", "Ville0 (91) 91000 CEDEX01"])
def test_postcode_is_recovered_from_existing_location_labels(tmp_path, monkeypatch, location):
    calls = []
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: calls.append(params) or [commune()])
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve({"location": location, "department": "91"}) == point()
    assert calls[0]["codePostal"] == "91000" and "nom" not in calls[0]
    resolver.close()


def test_shared_postcode_does_not_truncate_the_target_town(tmp_path, monkeypatch):
    rows = [{**commune(i), "codesPostaux": ["91000"]} for i in range(21)]
    calls = []
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: calls.append(params) or rows)
    resolver = g.GeoResolver(tmp_path)
    geo = resolver.resolve({**item(20), "postal_code": "91000"})
    assert geo["label"].endswith("Ville20") and len(calls) == 1
    assert "limit" not in calls[0]
    resolver.close()


def test_ambiguous_postcode_does_not_choose_the_first_town(tmp_path, monkeypatch):
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: [commune(), {**commune(1), "codesPostaux": ["91000"]}])
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve({**item(), "location": "Commune inconnue"}) is None
    resolver.close()


def test_legacy_negative_entries_are_retried_while_valid_positive_cache_is_kept(tmp_path, monkeypatch):
    t.write_json(tmp_path / "geography.json", {
        cache_key(item()): {"geo": None, "expires": time.time() + 86400},
        cache_key(item(1)): {"geo": point(), "expires": time.time() + 86400},
    })
    calls = []
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: calls.append(params) or [commune()])
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve(item()) == point() and resolver.resolve(item(1)) == point()
    assert len(calls) == 1
    resolver.close()


def test_temporary_failure_does_not_mask_a_valid_town_for_a_day(tmp_path, monkeypatch):
    def fail(self, params):
        raise requests.Timeout("temporary")
    monkeypatch.setattr(g.GeoResolver, "fetch", fail)
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve(item()) is None
    assert 0 < resolver.cache[cache_key(item())]["expires"] - time.time() <= 300
    resolver.close()
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: [commune()])
    # The next scheduled attempt after this short backoff can repair it.
    payload = t.read_json(tmp_path / "geography.json")
    payload[cache_key(item())]["expires"] = 0
    t.write_json(tmp_path / "geography.json", payload)
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve(item()) == point()
    resolver.close()


def test_spent_budget_does_not_poison_the_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: calls.append(params) or [commune()])
    resolver = g.GeoResolver(tmp_path)
    resolver.network_seconds = g.NETWORK_BUDGET_SECONDS
    assert resolver.resolve(item()) is None and not calls
    assert cache_key(item()) not in resolver.cache
    resolver.close()


def test_postal_results_are_reused_for_multiple_towns_and_sources(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: calls.append(params) or [commune(), {**commune(1), "codesPostaux": ["91000"]}])
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve(item())
    assert resolver.resolve({**item(1, "leboncoin"), "postal_code": "91000"})
    assert len(calls) == 1
    resolver.close()


def test_saved_ads_and_their_history_are_repaired_before_any_source_is_requested(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "directory", lambda: tmp_path)
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: [commune(int(params["codePostal"][2:]))])
    rows = [item(i) for i in range(21)]
    rows[0]["geo"] = point()
    old = {"items": rows, "status": "restricted", "last_success_at": "2026-10-25", "last_attempt_at": "2026-10-26", "message": "HTTP 403"}
    t.write_json(tmp_path / "lesanciennes.json", old)
    t.write_json(tmp_path / "history.json", {"ads": {row["id"]: {"latest": dict(row), "number": row["number"], "first_seen_at": "2026-10-23", "prices": []} for row in rows}, "events": [], "next_number": 22})
    def blocked(client):
        saved = s.snapshot()
        assert saved["running"] and len(saved["items"]) == 21 and all(g.valid_geo(row.get("geo")) for row in saved["items"])
        raise s.AccessRestricted("HTTP 403")
    for source in s.SOURCES:
        monkeypatch.setitem(s.COLLECTORS, source.id, blocked)
    assert s.synchronize() == 1
    updated = t.read_json(tmp_path / "lesanciennes.json")
    assert len(updated["items"]) == 21 and updated["last_success_at"] == old["last_success_at"]
    assert all(g.valid_geo(row.get("geo")) for row in updated["items"])
    history = t.read_json(tmp_path / "history.json")
    assert history["events"] == [] and history["next_number"] == 22
    assert all(g.valid_geo(entry["latest"].get("geo")) for entry in history["ads"].values())


def test_old_coordinates_are_not_reused_after_a_postcode_or_department_change(tmp_path):
    class Resolver:
        def resolve(self, row):
            return None
    original = {**item(), "geo": point()}
    first = {"items": [original]}
    t.record_observations(tmp_path, "lesanciennes", first, first, set(), "2026-10-26", Resolver())
    moved = {"items": [{**item(), "department": "75", "postal_code": "75000"}]}
    t.record_observations(tmp_path, "lesanciennes", first, moved, set(), "2026-10-27", Resolver())
    assert "geo" not in moved["items"][0]
