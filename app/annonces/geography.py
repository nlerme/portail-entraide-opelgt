"""Resolve advertised towns, never seller street addresses, with the public Geo API."""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from pathlib import Path

import requests

from app.annonces.tracking import read_json, write_json
from app.common.version import VERSION

NETWORK_BUDGET_SECONDS = 120.0
MAX_REQUESTS = 80
CACHE_SCHEMA = 2
REQUEST_TIMEOUT = (5, 10)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
    value = re.sub(r"\bsaint\b", "st", re.sub(r"\bsainte\b", "ste", value))
    return re.sub(r"[^a-z0-9]", "", value)


def location_parts(item: dict) -> tuple[str, str, str]:
    town = str(item.get("location") or "").strip()
    postal = str(item.get("postal_code") or "").strip()
    embedded = re.search(r"(?<!\d)\d{5}(?!\d)", town)
    if not re.fullmatch(r"\d{5}", postal):
        postal = embedded[0] if embedded else ""
    town = re.sub(r"(?<!\d)\d{5}(?!\d)", " ", town)
    town = re.sub(r"\((?:\s*|\d{2,3}|2[AB])\)|\bcedex(?:\s*\d+)?\b.*$", " ", town, flags=re.I)
    town = re.sub(r"^(?:France|FR)[\s,/-]+|[\s,/-]+(?:France|FR)$", "", town, flags=re.I)
    town = re.sub(r"\s+", " ", town).strip(" ,;-/–—")
    if normalized(town) in {"lieunonprecise", "france", "nonprecise"}:
        town = ""
    department = str(item.get("department") or "").strip().upper()
    if not re.fullmatch(r"(?:\d{2,3}|2[AB])", department):
        department = ""
    return town, department, postal


def valid_geo(value) -> bool:
    return (isinstance(value, dict) and type(value.get("lat")) in (float, int) and
            type(value.get("lon")) in (float, int) and -90 <= value["lat"] <= 90 and -180 <= value["lon"] <= 180)


class GeoResolver:
    def __init__(self, root: Path):
        self.path = root / "geography.json"
        self.cache = read_json(self.path)
        # Collection of adverts can take minutes between two geocoding calls.
        # Only the actual duration of geocoding HTTP calls consumes this budget.
        self.network_seconds = 0.0
        self.request_count = 0
        self.queries = {}
        self.session = requests.Session()

    def fetch(self, params: dict) -> list:
        with self.session.get("https://geo.api.gouv.fr/communes", params=params, timeout=REQUEST_TIMEOUT,
                              allow_redirects=False, headers={"User-Agent": f"PortailEntraideOpelGT/{VERSION} (+https://github.com/nlerme/portail-entraide-opelgt)"}) as response:
            response.raise_for_status()
            if len(response.content) > 200000:
                raise ValueError("Réponse de géolocalisation trop volumineuse.")
            value = response.json()
            if not isinstance(value, list):
                raise ValueError("Format de géolocalisation invalide.")
            return value

    def query(self, params: dict) -> tuple[list, str]:
        key = tuple(sorted(params.items()))
        if key in self.queries:
            return self.queries[key]
        if self.network_seconds + sum(REQUEST_TIMEOUT) > NETWORK_BUDGET_SECONDS or self.request_count >= MAX_REQUESTS:
            return [], "deferred"
        before = time.monotonic()
        self.request_count += 1
        try:
            result = self.fetch(params), "ok"
        except (requests.RequestException, ValueError, TypeError):
            result = [], "temporary"
        finally:
            self.network_seconds += max(0, time.monotonic() - before)
        if result[1] == "ok":
            self.queries[key] = result
        return result

    def resolve(self, item: dict) -> dict | None:
        town, department, postal = location_parts(item)
        if not town and not postal:
            return None
        key = hashlib.sha256(f"{normalized(town)}|{department}|{postal}".encode()).hexdigest()
        cached = self.cache.get(key, {})
        if cached.get("expires", 0) > time.time():
            if valid_geo(cached.get("geo")):
                return cached["geo"]
            # Old null entries do not distinguish failures from unknown towns.
            if cached.get("schema") == CACHE_SCHEMA:
                return None
        fields = {"fields": "nom,centre,codeDepartement,codesPostaux"}
        if department:
            fields["codeDepartement"] = department
        candidates = []
        status = "ok"
        if postal:
            # Some postcodes cover more than ten towns: retain all candidates.
            rows, status = self.query({**fields, "codePostal": postal})
            rows = [row for row in rows if isinstance(row, dict) and postal in row.get("codesPostaux", [])
                    and (not department or row.get("codeDepartement") == department)]
            candidates = [row for row in rows if normalized(str(row.get("nom", ""))) == normalized(town)]
            if not candidates and len(rows) == 1:
                candidates = rows
        if not candidates and town and status == "ok":
            rows, status = self.query({**fields, "nom": town, "limit": 50})
            candidates = [row for row in rows if isinstance(row, dict) and normalized(str(row.get("nom", ""))) == normalized(town)
                          and (not department or row.get("codeDepartement") == department)]
        if status == "deferred":
            return None  # A spent budget is not evidence of an unknown town.
        geo = None
        if len(candidates) == 1:
            centre = candidates[0].get("centre")
            coordinates = centre.get("coordinates") if isinstance(centre, dict) else None
            if isinstance(coordinates, (list, tuple)) and len(coordinates) == 2:
                lon, lat = coordinates
                candidate = {"lat": lat, "lon": lon, "precision": "commune", "label": "Centre de la commune de " + str(candidates[0].get("nom", town))}
                if valid_geo(candidate):
                    geo = candidate
        self.cache[key] = {"geo": geo, "schema": CACHE_SCHEMA,
                           "expires": time.time() + (31536000 if geo else 300 if status == "temporary" else 86400)}
        return geo

    def close(self) -> None:
        self.session.close()
        write_json(self.path, self.cache)

