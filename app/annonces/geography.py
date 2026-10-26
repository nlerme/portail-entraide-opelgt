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


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
    value = re.sub(r"\bsaint\b", "st", re.sub(r"\bsainte\b", "ste", value))
    return re.sub(r"[^a-z0-9]", "", value)


class GeoResolver:
    def __init__(self, root: Path):
        self.path = root / "geography.json"
        self.cache = read_json(self.path)
        self.deadline = time.monotonic() + 30
        self.session = requests.Session()

    def fetch(self, params: dict) -> list:
        with self.session.get("https://geo.api.gouv.fr/communes", params=params, timeout=(2, 3),
                              allow_redirects=False, headers={"User-Agent": f"PortailEntraideOpelGT/{VERSION} (+https://github.com/nlerme/portail-entraide-opelgt)"}) as response:
            response.raise_for_status()
            if len(response.content) > 200000:
                return []
            value = response.json()
            return value if isinstance(value, list) else []

    def resolve(self, item: dict) -> dict | None:
        town = re.sub(r"\s*\(\d{2,5}\).*|\s+cedex.*", "", str(item.get("location") or ""), flags=re.I).strip()
        if not town or normalized(town) in {"lieunonprecise", "france", "nonprecise"}:
            return None
        department = str(item.get("department") or "")
        postal = str(item.get("postal_code") or "")
        key = hashlib.sha256(f"{normalized(town)}|{department}|{postal}".encode()).hexdigest()
        cached = self.cache.get(key, {})
        if cached.get("expires", 0) > time.time():
            return cached.get("geo")
        if time.monotonic() + 5 > self.deadline:
            return None
        params = {"nom": town, "fields": "nom,centre,codeDepartement,codesPostaux", "limit": 10}
        if re.fullmatch(r"(?:\d{2,3}|2[AB])", department):
            params["codeDepartement"] = department
        if re.fullmatch(r"\d{5}", postal):
            params["codePostal"] = postal
        geo = None
        try:
            matches = [row for row in self.fetch(params) if isinstance(row, dict) and normalized(str(row.get("nom", ""))) == normalized(town)
                       and (not department or row.get("codeDepartement") == department)]
            if not matches and "codePostal" in params and time.monotonic() + 5 <= self.deadline:
                postal_params = {key: value for key, value in params.items() if key != "nom"}
                matches = [row for row in self.fetch(postal_params) if isinstance(row, dict)
                           and postal in row.get("codesPostaux", []) and (not department or row.get("codeDepartement") == department)]
            if len(matches) == 1:
                centre = matches[0].get("centre")
                coordinates = centre.get("coordinates", [None, None]) if isinstance(centre, dict) else [None, None]
                lon, lat = coordinates
                if type(lat) in (float, int) and type(lon) in (float, int) and -90 <= lat <= 90 and -180 <= lon <= 180:
                    geo = {"lat": lat, "lon": lon, "precision": "commune", "label": "Centre de la commune de " + matches[0]["nom"]}
        except (requests.RequestException, ValueError, TypeError):
            pass
        self.cache[key] = {"geo": geo, "expires": time.time() + (31536000 if geo else 86400)}
        return geo

    def close(self) -> None:
        self.session.close()
        write_json(self.path, self.cache)
