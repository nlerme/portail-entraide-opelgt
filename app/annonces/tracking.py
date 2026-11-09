"""Persistent observations and account preferences; no credentials are stored here."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.chmod(temporary, 0o640)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        os.chmod(path, 0o640)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def preferences_path(root: Path, account: str) -> Path:
    # Keep the authentication subject's exact spelling: distinct accounts must
    # never collide through case folding or a caller-controlled filesystem path.
    key = hashlib.sha256(account.encode("utf-8")).hexdigest()
    return root / "users" / f"{key}.json"


def preferences(root: Path, account: str) -> dict:
    value = read_json(preferences_path(root, account))
    return {"favorites": value.get("favorites", []), "hidden": value.get("hidden", []),
            "last_seen_at": value.get("last_seen_at"), "notify_new": value.get("notify_new", False),
            "notify_drops": value.get("notify_drops", False), "notify_since": value.get("notify_since"),
            "notify_new_since": value.get("notify_new_since"), "notify_drops_since": value.get("notify_drops_since")}


def save_preferences(root: Path, account: str, patch: dict, timestamp: str) -> dict:
    allowed = {"id", "favorite", "hidden", "mark_seen", "notify_new", "notify_drops"}
    if not isinstance(patch, dict) or not patch or set(patch) - allowed:
        raise ValueError("Réglages d’annonces invalides.")
    for name in allowed - {"id"}:
        if name in patch and type(patch[name]) is not bool:
            raise ValueError("Un réglage d’annonces doit être un booléen.")
    ident = patch.get("id")
    if ident is not None and (not isinstance(ident, str) or len(ident) > 500):
        raise ValueError("Identifiant d’annonce invalide.")
    if "favorite" in patch or "hidden" in patch:
        if not isinstance(ident, str) or not 1 <= len(ident) <= 500 or ":" not in ident:
            raise ValueError("Identifiant d’annonce invalide.")
    path = preferences_path(root, account)
    with locked(path.with_suffix(".lock")):
        value = preferences(root, account)
        for field, key in (("favorite", "favorites"), ("hidden", "hidden")):
            if field in patch:
                items = set(value[key])
                if patch[field]:
                    items.add(ident)
                else:
                    items.discard(ident)
                if len(items) > 1000:
                    raise ValueError("La limite de 1 000 annonces suivies ou masquées est atteinte.")
                value[key] = sorted(items)
        if patch.get("mark_seen"):
            value["last_seen_at"] = timestamp
        for name in ("notify_new", "notify_drops"):
            if name in patch:
                if patch[name] and not value[name]:
                    value[name + "_since"] = timestamp
                    if not value["notify_since"]:
                        value["notify_since"] = timestamp
                value[name] = patch[name]
        write_json(path, value)
    return value


def decorate(item: dict, entry: dict, *, archived: bool = False) -> dict:
    history = entry.get("prices", [])
    change = entry.get("last_price_change")
    return {**item, "number": entry["number"], "first_seen_at": entry["first_seen_at"],
            "observed_at": entry.get("observed_at"), "price_history": history,
            "price_change": change, "archived": archived}


def record_observations(root: Path, source_id: str, previous: dict, payload: dict,
                        observed: set[str], timestamp: str, resolver) -> None:
    """Called under the update lock. Baseline old cache before detecting changes."""
    state = read_json(root / "history.json")
    entries = state.setdefault("ads", {})
    events = state.setdefault("events", [])
    state.setdefault("next_number", 1)
    state.setdefault("next_event", 1)

    def create(item, first):
        entry = {"number": state["next_number"], "first_seen_at": first, "prices": [], "latest": item}
        state["next_number"] += 1
        entries[item["id"]] = entry
        return entry

    def event(kind, item, entry, old_price=None):
        events.append({"seq": state["next_event"], "kind": kind, "id": item["id"], "at": timestamp,
                       "number": entry["number"], "model": item.get("model"), "year": item.get("year"),
                       "price": item.get("price"), "old_price": old_price, "url": item.get("url"),
                       "location": item.get("location"), "currency": item.get("currency", "EUR")})
        state["next_event"] += 1

    for item in previous.get("items", []):
        if not isinstance(item, dict) or not item.get("id") or item["id"] in entries:
            continue
        entry = create(item, previous.get("last_success_at") or timestamp)
        if isinstance(item.get("price"), (int, float)):
            entry["prices"] = [{"at": entry["first_seen_at"], "price": item["price"], "currency": item.get("currency", "EUR")}]
    active = {item["id"] for item in payload["items"] if isinstance(item, dict) and item.get("id")}
    for ident, entry in entries.items():
        if entry.get("latest", {}).get("source_id", ident.split(":")[0]) == source_id:
            entry["active"] = ident in active
    result = []
    for original in payload["items"]:
        item = dict(original)
        ident = item.get("id")
        if not ident:
            continue
        entry = entries.get(ident)
        if entry is None:
            entry = create(item, timestamp)
            if ident in observed:
                event("new", item, entry)
        if ident in observed:
            old = entry.get("latest", {})
            price = item.get("price")
            known = entry["prices"][-1] if entry["prices"] else old
            old_price = known.get("price")
            currency = item.get("currency", "EUR")
            if isinstance(price, (int, float)):
                prices = entry["prices"]
                if not prices or prices[-1]["price"] != price or prices[-1].get("currency") != currency:
                    prices.append({"at": timestamp, "price": price, "currency": currency})
                    entry["prices"] = prices[-50:]
                if isinstance(old_price, (int, float)) and price != old_price and currency == known.get("currency", "EUR"):
                    entry["last_price_change"] = {"at": timestamp, "previous": old_price, "current": price, "delta": price - old_price}
                    if price < old_price:
                        event("drop", item, entry, old_price)
            entry["observed_at"] = timestamp
        geo = resolver.resolve(item)
        if geo:
            item["geo"] = geo
        elif entry.get("latest", {}).get("geo") and all(item.get(field) == entry["latest"].get(field)
                                                        for field in ("location", "department", "postal_code")):
            item["geo"] = entry["latest"]["geo"]
        else:
            item.pop("geo", None)
        # Keep only source fields in the archive (never recursively store the history).
        entry["latest"] = {key: value for key, value in item.items()
                           if key not in {"price_history", "price_change", "number", "first_seen_at", "observed_at", "archived"}}
        entry["active"] = True
        result.append(decorate(entry["latest"], entry))
    payload["items"] = result
    # Retain favorites in the archive; bound the remaining old observations.
    protected = set()
    for path in (root / "users").glob("*.json"):
        protected.update(read_json(path).get("favorites", []))
    removable = sorted((ident for ident, entry in entries.items() if not entry.get("active") and ident not in protected),
                       key=lambda ident: entries[ident]["first_seen_at"])
    for ident in removable[:max(0, len(entries) - 3000)]:
        del entries[ident]
    state["events"] = events[-5000:]
    write_json(root / "history.json", state)


def archived_favorites(root: Path, favorites: list[str], current: set[str]) -> list[dict]:
    entries = read_json(root / "history.json").get("ads", {})
    return [decorate(entries[ident]["latest"], entries[ident], archived=True)
            for ident in favorites if ident not in current and ident in entries]
