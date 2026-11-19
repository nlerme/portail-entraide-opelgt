from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.common.version import VERSION

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("PORTAIL_CONFIG", ROOT / "config.json")).expanduser()
SECRETS_PATH = Path(os.environ.get("PORTAIL_SECRETS", ROOT / "secrets.json")).expanduser()

DEFAULTS: dict[str, Any] = {
    "server": {"host": "0.0.0.0", "port": 8080, "public_url": "", "log_level": "info", "trusted_proxies": []},
    "sessions": {"duration_minutes": 30},
    "authentication": {
        "login_url": "https://www.entraideopelgt.fr/index.php/connexion",
        "validation_url": "https://www.entraideopelgt.fr/index.php/espace-membres/les-bulletins",
        "login_rate_limit_attempts": 5,
        "login_rate_limit_window_seconds": 300,
        "request_timeout_seconds": 30,
        "https_only_cookies": False,
        "allow_insecure_lan_http": True,
        "allow_insecure_remote_http": False,
    },
    "admin": {
        "enabled": True,
        "username": "admin",
        "login_rate_limit_attempts": 5,
        "login_rate_limit_window_seconds": 300,
        "log_tail_lines": 300,
    },
    "storage": {"data_dir": "/var/lib/portail-entraide-opel-gt"},
    "jobs": {"poll_seconds": 2, "lease_seconds": 900, "max_retries": 2},
    "bulletins": {
        "viewer": {"highlight_color": "#ffff00"},
        "remote": {"bulletins_url": "https://www.entraideopelgt.fr/index.php/espace-membres/les-bulletins"},
        "ocr": {
            "lang": "fra+eng", "dpi": 300, "mode": "auto", "text_threshold": 80,
            "multipass": True, "psm_main": 6, "psm_sparse": 11,
            "timeout_seconds": 600, "workers": 1, "workers_auto_cap": 1,
        },
        "network": {
            "http_timeout_seconds": 30,
            "user_agent": f"PortailEntraideOpelGT/{VERSION} (bulletins; https://www.entraideopelgt.fr/)",
            "max_pdf_bytes": 104857600,
        },
    },
    "pieces": {
        "scraping": {
            "request_timeout_seconds": 18, "connectivity_timeout_seconds": 4,
            "connectivity_cache_seconds": 20, "status_cache_seconds": 300,
            "status_probe_timeout_seconds": 6, "status_site_timeout_seconds": 14,
            "status_all_timeout_seconds": 20, "search_cache_seconds": 60,
            "detail_cache_seconds": 60, "translation_cache_seconds": 2592000,
            "max_pages_per_site": 0, "max_results_per_site": 0,
            "max_detail_pages_per_site": 8, "target_results_per_site": 30,
            "max_concurrent_sites": 2, "max_concurrent_pages_per_site": 2,
            "max_concurrent_details": 2, "search_site_timeout_seconds": 45,
            "search_all_timeout_seconds": 60, "circuit_breaker_failures": 3,
            "circuit_breaker_seconds": 120, "http_retries": 2,
            "default_requests_per_minute": 120, "respect_robots_txt": True,
            "robots_cache_seconds": 86400, "disabled_sites": [],
            "default_enabled_sites": [
                "opelix_parts", "splendid_parts", "edelschmiede", "pro_gt",
                "atz_online", "opel_gt_source", "oldtimer_motorenteile", "tw_oldtimerteile",
            ],
            "user_agent": f"PortailEntraideOpelGT/{VERSION} (pieces; https://www.entraideopelgt.fr/)",
        },
        "catalog_validation": {
            "min_item_ratio": 0.7, "min_known_price_ratio": 0.5,
            "reject_zero_availability": True, "min_baseline_items": 10,
        },
    },
    "annonces": {
        "default_enabled_sources": ["lesanciennes", "leboncoin", "classicnumber", "classictrader", "carandclassic", "retrocalage", "paruvendu", "autoscout24", "carjager", "plethorecars", "dyler"],
        "leboncoin": {"impersonate": "safari260_ios", "request_interval_seconds": 2.0, "fallback_profiles": ["chrome146", "firefox147"]},
    },
    "maintenance": {
        "timezone": "Europe/Paris", "weekly_catalog_update_day": "Monday,Wednesday,Friday",
        "weekly_catalog_update_time": "02:00",
        "weekly_package_update_enabled": True,
        "weekly_package_update_day": "Wednesday",
        "weekly_package_update_time": "00:00",
        "cleanup_time": "03:30", "catalog_update_timeout_seconds": 21600,
    },
}


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def read_object(path: Path, *, optional: bool = False) -> dict[str, Any]:
    if not path.exists():
        if optional:
            return {}
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON invalide dans {path} : ligne {exc.lineno}, colonne {exc.colno}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"La racine de {path} doit être un objet JSON.")
    return payload


CONFIG = deep_merge(DEFAULTS, read_object(CONFIG_PATH, optional=True))
SECRETS = read_object(SECRETS_PATH, optional=True)


def section(*names: str) -> dict[str, Any]:
    current: Any = CONFIG
    for name in names:
        current = current.get(name, {}) if isinstance(current, dict) else {}
    if not isinstance(current, dict):
        raise RuntimeError(f"La section {'.'.join(names)} doit être un objet JSON.")
    return current


def secret(name: str, default: str = "") -> str:
    value = SECRETS.get(name, default)
    return str(value or default)


def data_root() -> Path:
    override = os.environ.get("PORTAIL_DATA_DIR")
    raw = override or section("storage").get("data_dir") or DEFAULTS["storage"]["data_dir"]
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = CONFIG_PATH.parent / path
    return path.resolve()
