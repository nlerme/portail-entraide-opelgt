"""Persistent, independent incident monitor and ntfy delivery queue."""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import logging
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from app.common.config import SECRETS_PATH, data_root, read_object, section
from app.common.ntfy_setup import atomic_write, validate
from app.common.version import VERSION

LOGGER = logging.getLogger("portail.notifications")
APP = "portail-entraide-opel-gt"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M:%S (Europe/Paris)")
    except (ValueError, TypeError):
        return value


def read_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def probe(url: str, *, local: bool = False, health: bool = False) -> bool:
    try:
        with requests.Session() as session:
            session.trust_env = not local
            with session.get(url, timeout=(3, 5), headers={"User-Agent": f"PortailEntraideOpelGT/{VERSION} (monitoring)"}, stream=True, allow_redirects=False) as response:
                if health:
                    if response.status_code != 200:
                        return False
                    raw = response.raw.read(8192, decode_content=True)
                    payload = json.loads(raw)
                    return payload.get("ok") is True and payload.get("service") == APP
                return 200 <= response.status_code < 500
    except (requests.RequestException, OSError, ValueError, AttributeError):
        return False


def internet_available() -> bool:
    targets = ("https://www.debian.org/", "https://www.python.org/", "https://www.cloudflare.com/cdn-cgi/trace")
    with ThreadPoolExecutor(max_workers=3) as pool:
        return any(list(pool.map(probe, targets)))


def active(unit: str) -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", unit], timeout=5, capture_output=True).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def observations(online: bool) -> dict[str, tuple[bool | None, str]]:
    port = int(section("server").get("port", 8080))
    checks: dict[str, tuple[bool | None, str]] = {
        "internet": (online, "Connexion Internet du serveur"),
        "web": (probe(f"http://127.0.0.1:{port}/api/health", local=True, health=True), "Réponse du portail local"),
    }
    if shutil.which("systemctl"):
        for suffix, name in (("ocr-worker", "Traitement des bulletins"), ("catalog-worker", "Traitement des catalogues")):
            checks[suffix] = (active(f"{APP}-{suffix}.service"), name)
    units = Path(os.getenv("PORTAIL_SYSTEMD_UNIT_DIR", "/etc/systemd/system"))
    if (units / "cloudflared.service.d" / f"{APP}.conf").is_file():
        checks["cloudflare"] = (active("cloudflared.service") and probe("http://127.0.0.1:20241/ready", local=True), "Connexion du tunnel Cloudflare")
        public = str(section("server").get("public_url") or "").rstrip("/")
        if public and online:
            checks["public-url"] = (probe(public + "/api/health", health=True), "Accès à l'URL publique du portail")
    status = read_state(data_root() / "pieces/catalogues/sync_status.json")
    for supplier in status.get("suppliers", []):
        name, ident, value = supplier.get("site_name"), supplier.get("site_id"), supplier.get("status")
        if ident and name:
            healthy = True if value == "ok" else False if value in {"failed", "unavailable"} else None
            checks[f"catalogue:{ident}"] = (healthy, f"Mise à jour du catalogue {name}")
    if status.get("running") and status.get("started_at"):
        try:
            started = datetime.fromisoformat(status["started_at"].replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            maximum = int(section("maintenance").get("catalog_update_timeout_seconds", 21600))
            checks["catalogue-duration"] = (elapsed < maximum + 300, "Durée maximale de mise à jour des catalogues")
        except (ValueError, TypeError):
            pass
    else:
        checks["catalogue-duration"] = (True, "Durée maximale de mise à jour des catalogues")
    from app.annonces.collectors import SOURCES
    for source in SOURCES:
        payload = read_state(data_root() / "annonces" / f"{source.id}.json")
        value = payload.get("status")
        if value:
            checks[f"annonces:{source.id}"] = (value == "ok", f"Collecte des annonces {source.name}")
    return checks


def transition(state: dict, checks: dict, timestamp: str) -> None:
    incidents = state.setdefault("incidents", {})
    pending = state.setdefault("pending", [])
    for key, (healthy, label) in checks.items():
        if healthy is None:
            continue
        previous = incidents.setdefault(key, {"active": False, "failures": 0})
        previous["failures"] = 0 if healthy else previous.get("failures", 0) + 1
        # Network/process probes require two consecutive failures. A persisted
        # source failure already represents a complete, bounded update attempt.
        threshold = 1 if key.startswith(("catalogue:", "annonces:")) else 2
        failed = not healthy and previous["failures"] >= threshold
        if failed and not previous["active"]:
            previous.update(active=True, since=timestamp)
            pending.append({"title": "Portail Opel GT : incident", "message": f"{label} : problème détecté le {local_time(timestamp)}. Les dernières données valides sont conservées lorsqu'elles existent.", "priority": 4, "tags": ["warning"]})
        elif healthy and previous["active"]:
            pending.append({"title": "Portail Opel GT : rétablissement", "message": f"{label} : rétabli le {local_time(timestamp)}. Incident détecté le {local_time(previous.get('since', timestamp))}.", "priority": 3, "tags": ["white_check_mark"]})
            previous["active"] = False
    # Coalesce backlog overflow explicitly instead of allowing unbounded growth.
    if len(pending) > 200:
        state["pending"] = [{"title": "Portail Opel GT : historique regroupé", "message": "Plus de 200 événements en attente : les plus anciens ont été regroupés. Consultez les journaux du serveur.", "priority": 3, "tags": ["warning"]}] + pending[-199:]


def publish(settings: dict, event: dict) -> bool:
    headers = {}
    auth = None
    if settings["auth"] == "token":
        headers["Authorization"] = "Bearer " + settings["token"]
    elif settings["auth"] == "basic":
        credentials = f"{settings['username']}:{settings['password']}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
    try:
        with requests.post(settings["server"] + "/", json={"topic": settings["topic"], **event}, headers=headers, auth=auth, timeout=(3, 8), allow_redirects=False) as response:
            if 200 <= response.status_code < 300:
                return True
            LOGGER.warning("Envoi ntfy refusé (HTTP %s) ; message conservé en attente.", response.status_code)
    except requests.RequestException:
        # Exception URLs and request headers may contain private configuration.
        LOGGER.warning("Envoi ntfy impossible ; message conservé en attente.")
    return False


def delivery_due(state: dict, interval_days: int, timestamp: str) -> bool:
    try:
        previous = datetime.fromisoformat(state["last_sent_at"].replace("Z", "+00:00"))
        current = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return current >= previous + timedelta(days=max(1, interval_days))
    except (KeyError, ValueError, TypeError):
        return True


def notification_batch(events: list[dict]) -> tuple[dict, int]:
    if len(events) == 1:
        return events[0], 1
    lines = []
    selected = []
    for event in events:
        message = str(event.get("message", ""))
        message = message.replace(" Les dernières données valides sont conservées lorsqu'elles existent.", "")
        candidate = "\n\n".join([*lines, "• " + message])
        if len(candidate.encode("utf-8")) > 3400:
            break
        lines.append("• " + message)
        selected.append(event)
    if not selected:
        # Existing queue entries are generated locally and normally much
        # shorter. Bound a legacy entry so it cannot block the whole backlog.
        message = str(events[0].get("message", "" )).encode("utf-8")[:3300].decode("utf-8", errors="ignore")
        return {**events[0], "message": message}, 1
    count = len(selected)
    priority = max(int(event.get("priority", 3)) for event in selected)
    return {
        "title": f"Portail Opel GT : {count} événements",
        "message": f"Incidents et rétablissements enregistrés ({count}) :\n\n" + "\n\n".join(lines),
        "priority": priority,
        "tags": ["warning" if priority >= 4 else "white_check_mark"],
    }, count


def run(*, test: bool = False) -> int:
    settings = validate(read_object(SECRETS_PATH, optional=True).get("ntfy", {}))
    if not settings.get("enabled"):
        return 0
    root = data_root() / "notifications"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "monitor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        path = root / "state.json"
        state = read_state(path)
        if test:
            state.setdefault("pending", []).append({"title": "Portail Opel GT : test ntfy", "message": f"Notifications configurées pour le portail {VERSION}. Les incidents et rétablissements seront signalés ici.", "priority": 3, "tags": ["white_check_mark"]})
            online = True
        else:
            online = internet_available()
            transition(state, observations(online), now())
        # Persist before attempting delivery: offline incidents survive reboots.
        atomic_write(path, state, 0o600)
        if online and state.get("pending") and delivery_due(state, settings["interval_days"], now()):
            event, count = notification_batch(state["pending"])
            if publish(settings, event):
                del state["pending"][:count]
                state["last_sent_at"] = now()
                atomic_write(path, state, 0o600)
        return 1 if test and state.get("pending") else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Surveillance et notifications ntfy du portail")
    parser.add_argument("--test", action="store_true")
    try:
        raise SystemExit(run(test=parser.parse_args().test))
    except (ValueError, OSError, RuntimeError):
        LOGGER.error("Surveillance ntfy interrompue : vérifier la configuration et les permissions des fichiers.")
        raise SystemExit(1)
