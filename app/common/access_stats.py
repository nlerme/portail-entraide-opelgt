from __future__ import annotations

import ipaddress
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Request

from app.common.auth import client_key
from app.common.config import data_root

LOGGER = logging.getLogger("portail.access")
_LOOKUP_LOCK = threading.RLock()
_LOOKUPS_IN_PROGRESS: set[str] = set()

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    country TEXT NOT NULL,
    country_code TEXT,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_created ON login_attempts(created_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address, created_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_area ON login_attempts(area, created_at);
"""


def database_path() -> Path:
    return data_root() / "portal" / "statistics.sqlite3"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.commit()


def _initial_country(ip_text: str) -> tuple[str, str | None, bool]:
    normalized = ip_text.strip().lower().split("%", 1)[0]
    if normalized in {"localhost", "testclient", "unknown", ""}:
        return "Machine locale", None, False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return "Inconnu", None, False
    if address.is_loopback:
        return "Machine locale", None, False
    if address.is_private or address.is_link_local:
        return "Réseau local", None, False
    return "Identification en cours", None, True


def _resolve_public_country(ip_text: str) -> None:
    try:
        response = httpx.get(
            f"https://ipwho.is/{ip_text}",
            params={"fields": "success,country,country_code"},
            timeout=3.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        country = str(payload.get("country") or "Inconnu") if payload.get("success") else "Inconnu"
        country_code = str(payload.get("country_code") or "").upper() or None
    except Exception:
        country, country_code = "Inconnu", None
    try:
        with connect() as connection:
            connection.execute(
                "UPDATE login_attempts SET country=?, country_code=? WHERE ip_address=? AND country='Identification en cours'",
                (country, country_code, ip_text),
            )
            connection.commit()
    except sqlite3.Error:
        LOGGER.exception("Impossible de mettre à jour le pays de l'adresse IP.")
    finally:
        with _LOOKUP_LOCK:
            _LOOKUPS_IN_PROGRESS.discard(ip_text)


def _schedule_country_lookup(ip_text: str) -> None:
    with _LOOKUP_LOCK:
        if ip_text in _LOOKUPS_IN_PROGRESS:
            return
        _LOOKUPS_IN_PROGRESS.add(ip_text)
    threading.Thread(
        target=_resolve_public_country,
        args=(ip_text,),
        daemon=True,
        name="login-country-lookup",
    ).start()


def record_login_attempt(request: Request, area: str, outcome: str) -> None:
    ip_text = client_key(request)
    country, country_code, needs_lookup = _initial_country(ip_text)
    try:
        with connect() as connection:
            connection.execute(
                "INSERT INTO login_attempts(area,ip_address,country,country_code,outcome) VALUES (?,?,?,?,?)",
                (area, ip_text, country, country_code, outcome),
            )
            connection.commit()
    except sqlite3.Error:
        LOGGER.exception("Impossible d'enregistrer une tentative de connexion.")
        return
    if needs_lookup:
        _schedule_country_lookup(ip_text)


def statistics(limit: int = 100) -> dict[str, Any]:
    initialize()
    with connect() as connection:
        summary = connection.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(DISTINCT ip_address) AS unique_ips,
                      SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successful,
                      SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN outcome='rate-limited' THEN 1 ELSE 0 END) AS blocked,
                      SUM(CASE WHEN outcome NOT IN ('success','failed','rate-limited') THEN 1 ELSE 0 END) AS other
                 FROM login_attempts"""
        ).fetchone()
        by_area = connection.execute(
            """SELECT area, COUNT(*) AS attempts,
                      SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successful,
                      SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN outcome='rate-limited' THEN 1 ELSE 0 END) AS blocked
                 FROM login_attempts GROUP BY area ORDER BY area"""
        ).fetchall()
        by_ip = connection.execute(
            """SELECT area, ip_address, country, country_code, COUNT(*) AS attempts,
                      SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successful,
                      SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN outcome='rate-limited' THEN 1 ELSE 0 END) AS blocked,
                      MAX(created_at) AS last_attempt
                 FROM login_attempts
                GROUP BY area, ip_address, country, country_code
                ORDER BY last_attempt DESC LIMIT ?""",
            (max(1, min(500, int(limit))),),
        ).fetchall()
        recent = connection.execute(
            """SELECT area, ip_address, country, country_code, outcome, created_at
                 FROM login_attempts ORDER BY id DESC LIMIT ?""",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    return {
        "summary": dict(summary),
        "byArea": [dict(row) for row in by_area],
        "byIp": [dict(row) for row in by_ip],
        "recent": [dict(row) for row in recent],
    }
