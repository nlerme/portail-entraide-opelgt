from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.annonces import geography as g
from app.annonces import service as s
from app.annonces import tracking as t
from app.annonces.digest import queue_digest

ROOT = Path(__file__).resolve().parents[1]
DAY1, DAY2, DAY3 = (f"2026-10-{day}T02:00:00+00:00" for day in (23, 24, 25))


def ad(ident=1, price=19000, source="lesanciennes"):
    urls = {"lesanciennes": f"https://www.lesanciennes.com/annonce/opel-gt-a{ident}",
            "leboncoin": f"https://www.leboncoin.fr/ad/voitures/{ident}"}
    return {"id": f"{source}:{ident}", "source_id": source, "source_name": source, "price": price, "currency": "EUR",
            "model": "1900", "year": 1969, "location": "Limours", "department": "91", "seller_type": "particulier",
            "url": urls[source]}


class Resolver:
    def resolve(self, item):
        return None


def record(root, items, previous=None, timestamp=DAY1, observed=None):
    payload = {"items": items}
    t.record_observations(root, "lesanciennes", previous or {}, payload,
                          {item["id"] for item in items} if observed is None else observed, timestamp, Resolver())
    return payload


def test_numbers_price_history_and_new_events_survive_updates(tmp_path):
    one = record(tmp_path, [ad()])
    two = record(tmp_path, [ad(price=18000), ad(2)], one, DAY2)
    by_id = {item["id"]: item for item in two["items"]}
    first = by_id["lesanciennes:1"]
    assert first["number"] == one["items"][0]["number"] == 1
    assert first["first_seen_at"] == DAY1 and first["observed_at"] == DAY2
    assert [p["price"] for p in first["price_history"]] == [19000, 18000]
    assert first["price_change"]["delta"] == -1000
    three = record(tmp_path, [ad(price=18500), ad(2)], two, DAY3)
    assert three["items"][0]["price_change"]["delta"] == 500
    assert [event["kind"] for event in t.read_json(tmp_path / "history.json")["events"]] == ["new", "drop", "new"]


def test_migration_does_not_notify_old_ads_and_retained_rows_are_not_reobserved(tmp_path):
    old = {"items": [ad()], "last_success_at": DAY1}
    baseline = record(tmp_path, [ad()], old, DAY2, observed=set())
    assert baseline["items"][0]["first_seen_at"] == DAY1
    assert baseline["items"][0]["observed_at"] is None
    assert t.read_json(tmp_path / "history.json")["events"] == []
    changed = record(tmp_path, [ad(price=17000)], baseline, DAY3)
    assert changed["items"][0]["price_change"]["previous"] == 19000


def test_price_reappearing_compares_against_last_known_value(tmp_path):
    first = record(tmp_path, [ad()])
    missing = record(tmp_path, [ad(price=None)], first, DAY2)
    again = record(tmp_path, [ad(price=17000)], missing, DAY3)
    assert again["items"][0]["price_change"]["delta"] == -2000


def test_archived_favorites_preserve_last_information_without_claiming_sold(tmp_path):
    original = record(tmp_path, [ad()])
    record(tmp_path, [], original, DAY2)
    saved = t.archived_favorites(tmp_path, [ad()["id"]], set())
    assert saved[0]["archived"] and saved[0]["number"] == 1 and saved[0]["price"] == 19000
    assert not t.archived_favorites(tmp_path, [ad()["id"]], {ad()["id"]})


def test_preferences_are_per_account_atomic_and_persistent(tmp_path):
    t.save_preferences(tmp_path, "../../Alice", {"id": ad()["id"], "favorite": True}, DAY1)
    assert t.preferences(tmp_path, "Alice")["favorites"] == []
    assert t.preferences(tmp_path, "../../Alice")["favorites"] == [ad()["id"]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: t.save_preferences(tmp_path, "Alice", {"id": ad(i)["id"], "favorite": True}, DAY2), range(10)))
    assert len(t.preferences(tmp_path, "Alice")["favorites"]) == 10
    prefs = t.save_preferences(tmp_path, "Alice", {"mark_seen": True, "notify_new": True}, DAY3)
    assert prefs["last_seen_at"] == DAY3 and prefs["notify_since"] == DAY3
    path = t.preferences_path(tmp_path, "Alice")
    assert path.stat().st_mode & 0o777 == 0o640 and path.parent == tmp_path / "users"
    assert t.preferences(tmp_path, "alice")["favorites"] == []


@pytest.mark.parametrize("patch", [{}, {"favorite": True}, {"id": "x", "hidden": True}, {"notify_new": 1}, {"favorites": []}, {"id": "x:y", "favorite": "true"}])
def test_preferences_reject_invalid_operations(tmp_path, patch):
    with pytest.raises(ValueError):
        t.save_preferences(tmp_path, "a", patch, DAY1)


def test_geography_only_accepts_unique_matching_communes_and_caches(tmp_path, monkeypatch):
    calls = []
    def fetch(self, params):
        calls.append(params)
        return [{"nom": "Limours", "codeDepartement": "91", "centre": {"coordinates": [2.0823, 48.6463]}}]
    monkeypatch.setattr(g.GeoResolver, "fetch", fetch)
    resolver = g.GeoResolver(tmp_path)
    place = resolver.resolve({**ad(), "postal_code": "91470"})
    assert place == {"lat": 48.6463, "lon": 2.0823, "precision": "commune", "label": "Centre de la commune de Limours"}
    resolver.close()
    again = g.GeoResolver(tmp_path)
    assert again.resolve({**ad(), "postal_code": "91470"}) == place and len(calls) == 1
    assert calls[0]["codePostal"] == "91470" and calls[0]["codeDepartement"] == "91"
    again.close()


@pytest.mark.parametrize("rows", [[], [{"nom": "Limours", "codeDepartement": "92"}],
    [{"nom": "Limours", "codeDepartement": "91", "centre": {"coordinates": [999, 48]}}],
    [{"nom": "Limours", "codeDepartement": "91", "centre": None}],
    [{"nom": "Limours", "codeDepartement": "91"}] * 2])
def test_geography_does_not_invent_a_location(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(g.GeoResolver, "fetch", lambda self, params: rows)
    resolver = g.GeoResolver(tmp_path)
    assert resolver.resolve(ad()) is None
    assert resolver.resolve({"location": "Lieu non précisé"}) is None
    resolver.close()


def test_refresh_is_nonblocking_and_globally_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "directory", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(s, "request_system_action", lambda action: calls.append(action) or {"ok": True})
    assert s.request_refresh()["ok"] and s.snapshot()["running"]
    assert s.request_refresh()["running"] and len(calls) == 1
    t.write_json(tmp_path / "sync.json", {"started_at": "9999-01-01", "finished_at": DAY3})
    second = s.request_refresh()
    assert not second["ok"] and 1700 < second["retry_after"] <= 1800
    assert len(calls) == 1


def test_snapshots_publish_each_source_while_collection_is_running(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "directory", lambda: tmp_path)
    for source in s.SOURCES:
        monkeypatch.setitem(s.COLLECTORS, source.id, lambda client: [])
    monkeypatch.setitem(s.COLLECTORS, "lesanciennes", lambda client: [ad()])
    def later(client):
        snapshot = s.snapshot()
        assert snapshot["running"] and snapshot["items"][0]["id"] == ad()["id"]
        assert snapshot["progress"]["lesanciennes"] == "ok" and snapshot["progress"]["leboncoin"] == "running"
        return []
    monkeypatch.setitem(s.COLLECTORS, "leboncoin", later)
    assert s.synchronize() == 0


def test_digest_opt_in_favorites_idempotence_and_queue_merging(tmp_path):
    t.save_preferences(tmp_path, "a", {"notify_drops": True}, "2026-10-22")
    t.save_preferences(tmp_path, "a", {"id": ad()["id"], "favorite": True}, DAY1)
    one = record(tmp_path, [ad(), ad(2)])
    two = record(tmp_path, [ad(price=18000), ad(2, price=18000)], one, DAY2)
    state = {}
    queue_digest(tmp_path, state)
    pending = state["pending"]
    assert len(pending) == 1 and len(pending[0]["ad_events"]) == 1
    assert pending[0]["ad_events"][0]["id"] == ad()["id"]
    queue_digest(tmp_path, state)
    assert len(state["pending"]) == 1 and len(state["pending"][0]["ad_events"]) == 1
    record(tmp_path, [ad(price=17000), ad(2, price=18000)], two, DAY3)
    queue_digest(tmp_path, state)
    assert len(state["pending"]) == 1 and len(state["pending"][0]["ad_events"]) == 2
    state["pending"] = []  # Simulate successful delivery; cursor survives.
    queue_digest(tmp_path, state)
    assert state["pending"] == []


def test_digest_is_silent_without_opt_in_and_does_not_replay_old_ads(tmp_path):
    record(tmp_path, [ad()])
    state = {}
    queue_digest(tmp_path, state)
    assert state["pending"] == []
    t.save_preferences(tmp_path, "a", {"notify_new": True}, DAY2)
    record(tmp_path, [ad(), ad(2)], timestamp=DAY3)
    queue_digest(tmp_path, state)
    assert len(state["pending"][0]["ad_events"]) == 1
    assert state["pending"][0]["ad_events"][0]["id"] == ad(2)["id"]


def test_enabling_favorite_alerts_does_not_discard_queued_new_ads(tmp_path):
    t.save_preferences(tmp_path, "a", {"notify_new": True}, "2026-10-22")
    record(tmp_path, [ad()])
    state = {}
    queue_digest(tmp_path, state)
    assert len(state["pending"]) == 1
    t.save_preferences(tmp_path, "a", {"notify_drops": True}, DAY2)
    queue_digest(tmp_path, state)
    assert len(state["pending"]) == 1 and state["pending"][0]["ad_events"][0]["kind"] == "new"


def test_leaflet_vendor_integrity():
    root = ROOT / "static/vendor/leaflet-1.9.4"
    manifest = json.loads((root / "UPSTREAM.json").read_text())
    assert manifest["version"] == "1.9.4" and len(manifest["sha256"]) == 8
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest


def test_manual_system_action_only_starts_the_fixed_existing_unit(monkeypatch):
    from types import SimpleNamespace

    import server_control
    calls = []
    monkeypatch.setattr(server_control.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    assert server_control.handle('{"action":"refresh-annonces","unit":"evil.service"}')["ok"]
    assert calls == [["systemctl", "start", "--no-block", "portail-entraide-opel-gt-annonces-update.service"]]


def test_digest_delivery_failure_retry_and_daily_cap(tmp_path, monkeypatch):
    from app import notifications as n

    root = tmp_path / "data/annonces"
    secret = tmp_path / "secrets.json"
    secret.write_text(json.dumps({"ntfy": {"enabled": True, "server": "https://ntfy.example", "topic": "qa", "auth": "none", "interval_days": 1}}))
    monkeypatch.setattr(n, "SECRETS_PATH", secret)
    monkeypatch.setattr(n, "data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(n, "internet_available", lambda: True)
    monkeypatch.setattr(n, "observations", lambda online: {})
    monkeypatch.setattr(n, "now", lambda: DAY1)
    t.save_preferences(root, "a", {"notify_new": True}, "2026-10-22")
    first = record(root, [ad()])
    monkeypatch.setattr(n, "publish", lambda *args: False)
    assert n.run() == 0
    path = tmp_path / "data/notifications/state.json"
    assert len(t.read_json(path)["pending"]) == 1 and "last_sent_at" not in t.read_json(path)
    sent = []
    monkeypatch.setattr(n, "publish", lambda config, event: sent.append(event) or True)
    n.run()
    assert len(sent) == 1 and t.read_json(path)["pending"] == []
    record(root, [ad(), ad(2)], first, DAY2)
    monkeypatch.setattr(n, "now", lambda: "2026-10-23T12:00:00+00:00")
    n.run()
    assert len(sent) == 1 and len(t.read_json(path)["pending"]) == 1
    monkeypatch.setattr(n, "now", lambda: DAY2)
    n.run()
    assert len(sent) == 2 and t.read_json(path)["pending"] == []


def test_browser_filters_duplicate_grouping_and_geo_validation():
    script = r'''
const assert=require('node:assert/strict'), ui=require(process.argv[1]);
const a={id:'a',source_id:'lesanciennes',model:'1900',year:1969,location:'Limours',department:'91',price:19000,currency:'EUR',first_seen_at:'2026-10-24T02:00:00Z'};
const b={...a,id:'b',source_id:'leboncoin'};
const f={min:null,max:null}, prefs={favorites:['a'],hidden:['b']};
assert.equal(ui.matches(a,{...f,min:18000,max:20000},prefs,'2026-10-23'),true);
assert.equal(ui.matches({...a,price:null},{...f,min:1},prefs,'2026-10-23'),false);
assert.equal(ui.matches(a,{...f,department:'78'},prefs,'2026-10-23'),false);
assert.equal(ui.matches(b,f,prefs,'2026-10-23'),false);
assert.equal(ui.matches(b,{...f,showHidden:true},prefs,'2026-10-23'),true);
assert.equal(ui.matches(a,{...f,newOnly:true},prefs,'2026-10-25'),false);
assert.equal(ui.matches(a,{...f,newOnly:true},prefs,'2026-10-23'),true);
assert.equal(ui.matches({...a,archived:true},f,prefs,'2026-10-23'),false);
assert.equal(ui.matches({...a,archived:true},{...f,favoritesOnly:true},prefs,'2026-10-23'),true);
assert.equal(ui.groupItems([a,b],true).length,1);
for(const update of [{year:1970},{price:18000},{department:'78'},{source_id:'lesanciennes'},{location:'Paris'},{model:'Modèle non précisé'}]) assert.equal(ui.groupItems([a,{...b,...update}],true).length,2);
assert.equal(ui.groupItems([a,b],false).length,2);
assert.equal(ui.validGeo({lat:48,lon:2}),true);
assert.equal(Boolean(ui.validGeo({lat:NaN,lon:2})),false);
assert.equal(Boolean(ui.validGeo({lat:48,lon:181})),false);
'''
    done = subprocess.run(["node", "-e", script, str(ROOT / "static/annonces/app.js")], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stderr
