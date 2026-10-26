"""Merge subscribed ad changes into the existing, globally rate-limited ntfy queue."""
from __future__ import annotations

import fcntl
from pathlib import Path

from app.annonces.collectors import safe_url
from app.annonces.tracking import read_json


def queue_digest(root: Path, state: dict) -> None:
    if not (root / "history.json").is_file():
        return
    with (root / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        history = read_json(root / "history.json")
        subscriptions = [read_json(path) for path in (root / "users").glob("*.json")]
    cursor = state.get("annonces_cursor", 0)
    pending = state.setdefault("pending", [])
    former = next((event for event in pending if event.get("kind") == "annonces_digest"), {})
    candidates = {event["seq"]: event for event in former.get("ad_events", [])}
    candidates.update({event["seq"]: event for event in history.get("events", []) if event.get("seq", 0) > cursor})
    selected = []
    for event in candidates.values():
        if not safe_url(event.get("url"), str(event.get("url") or "")):
            continue
        for prefs in subscriptions:
            since_key = "notify_new_since" if event["kind"] == "new" else "notify_drops_since"
            if event["at"] < (prefs.get(since_key) or prefs.get("notify_since") or "9999"):
                continue
            if ((event["kind"] == "new" and prefs.get("notify_new")) or
                    (event["kind"] == "drop" and prefs.get("notify_drops") and event["id"] in prefs.get("favorites", []))):
                selected.append(event)
                break
    pending[:] = [event for event in pending if event.get("kind") != "annonces_digest"]
    state["annonces_cursor"] = max(cursor, history.get("next_event", 1) - 1)
    if not selected:
        return
    selected = sorted(selected, key=lambda event: event["seq"])[-5000:]
    new = sum(event["kind"] == "new" for event in selected)
    drops = len(selected) - new
    lines = [f"Petites annonces : {new} nouveauté(s), {drops} baisse(s) de prix de favoris."]
    for event in selected:
        price = f"{event['price']:,.0f} {event.get('currency', 'EUR')}".replace(",", " ") if isinstance(event.get("price"), (int, float)) else "prix non précisé"
        label = "Nouvelle annonce" if event["kind"] == "new" else "Baisse de prix"
        line = f"{label} #{event['number']} — Opel GT {event.get('model') or ''}, {event.get('year') or '?'} — {price}, {event.get('location') or 'lieu non précisé'}\n{event['url']}"
        if len(("\n\n".join([*lines, line])).encode("utf-8")) > 2900:
            lines.append("Autres changements à consulter sur la page Petites annonces.")
            break
        lines.append(line)
    pending.append({"kind": "annonces_digest", "ad_events": selected, "title": "Portail Opel GT : petites annonces",
                    "message": "\n\n".join(lines), "priority": 3, "tags": ["car"]})
