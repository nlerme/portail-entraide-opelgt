"""Credential-safe ntfy settings, shared by the API and privileged helper."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

from app.common.ntfy_setup import atomic_write, read, validate

ALLOWED_FIELDS = {"enabled", "server", "topic", "auth", "username", "token", "password", "interval_days"}


def public_settings(settings: dict) -> dict:
    return {
        "enabled": settings.get("enabled") is True,
        "server": settings.get("server", "https://ntfy.sh"),
        "topic": settings.get("topic", ""),
        "auth": settings.get("auth", "none"),
        "username": settings.get("username", ""),
        "has_token": bool(settings.get("token")),
        "has_password": bool(settings.get("password")),
        "interval_days": settings.get("interval_days", 1),
    }


def updated_settings(current: dict, patch: dict) -> dict:
    if not isinstance(patch, dict) or set(patch) - ALLOWED_FIELDS:
        raise ValueError("Réglages ntfy inconnus ou invalides.")
    if "enabled" in patch and type(patch["enabled"]) is not bool:
        raise ValueError("L'activation ntfy doit être un booléen.")
    for name in ALLOWED_FIELDS - {"enabled", "interval_days"}:
        if name in patch and (not isinstance(patch[name], str) or len(patch[name]) > 4096):
            raise ValueError("Un champ ntfy est invalide ou trop long.")
    merged = {**current, **patch}
    for name in ("token", "password"):
        # Empty password fields preserve the stored secret, never a masked
        # placeholder sent back by the server. Switching auth removes old keys.
        if name in patch and patch[name] == "":
            if current.get("auth") == merged.get("auth") and current.get(name):
                merged[name] = current[name]
            else:
                merged.pop(name, None)
    return validate(merged)


def save_settings(path: Path, patch: dict) -> dict:
    if not path.is_file():
        raise ValueError("Le fichier de secrets du portail est absent ; lancez d'abord l'installation.")
    # Serialize two simultaneous administrator saves and merge only ntfy into
    # the latest file; application/admin secrets must stay untouched.
    with path.with_name(".ntfy-settings.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        payload = read(path)
        settings = updated_settings(payload.get("ntfy", {}), patch)
        payload["ntfy"] = settings
        atomic_write(path, payload, 0o640)
    return {"ok": True, "message": "Réglages ntfy enregistrés. Ils seront utilisés au prochain contrôle, sans redémarrage.", "settings": public_settings(settings)}
