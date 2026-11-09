"""Search-only adapter for the pinned lbc 1.1.9 response and pagination."""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
import uuid
from datetime import datetime
from http.cookiejar import Cookie
from pathlib import Path
from typing import get_args
from zoneinfo import ZoneInfo

import lbc
from curl_cffi import requests as curl_requests
from curl_cffi.requests.impersonate import BrowserTypeLiteral
from lbc.exceptions import DatadomeError

from app.annonces.collectors import AccessRestricted, CollectionError
from app.common.config import data_root, section

SEARCH_URL = "https://api.leboncoin.fr/finder/search"
FALLBACK_DELAY_SECONDS = 10
BLOCK_COOLDOWN_SECONDS = 7200
LOGGER = logging.getLogger("portail.annonces.leboncoin")


def session_path() -> Path:
    return data_root() / "annonces" / ".leboncoin-session.json"


def read_session(path: Path) -> dict:
    try:
        if path.stat().st_size > 1024 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and isinstance(value.get("profiles"), dict) else {}
    except (OSError, ValueError):
        return {}


def write_session(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".lbc-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=True, allow_nan=False)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


class SearchClient(lbc.Client):
    """Use lbc's search/parser with stable sessions and bounded recovery."""

    def __init__(self, **kwargs):
        self._request_timeout = kwargs.get("timeout", 20)
        primary = kwargs.get("impersonate", "safari260_ios")
        fallbacks = section("annonces", "leboncoin").get("fallback_profiles", ["chrome146", "firefox147"])
        supported = set(get_args(BrowserTypeLiteral)) - {"chrome131_android", "chrome_android"}
        if not isinstance(fallbacks, list) or len(fallbacks) > 2 or any(not isinstance(p, str) or p not in supported for p in fallbacks):
            raise CollectionError("annonces.leboncoin.fallback_profiles doit contenir au plus deux profils HTTP pris en charge.")
        self._profiles = list(dict.fromkeys([primary, *fallbacks]))
        self._session_path = session_path()
        self._session_state = read_session(self._session_path)
        if self._session_state.get("primary") != primary:
            self._session_state = {"primary": primary, "profiles": {}}
        preferred = self._session_state.get("preferred")
        if preferred in self._profiles:
            self._profiles.remove(preferred)
            self._profiles.insert(0, preferred)
        choices = self._available_profiles()
        if not choices:
            until = min(self._blocked_until(p) for p in self._profiles)
            date = datetime.fromtimestamp(until, ZoneInfo("Europe/Paris")).strftime("%d/%m à %H:%M")
            raise AccessRestricted(f"Leboncoin : collecte en pause après refus HTTP 403 / DataDome ; prochain essai possible le {date}.")
        kwargs["impersonate"] = choices[0]
        self._fallback_used = False
        super().__init__(**kwargs)
        self._search_key = None
        self._next_offset = 0
        self._pivot = None
        self._owners = {}

    def _entry(self, profile):
        profiles = self._session_state.setdefault("profiles", {})
        if not isinstance(profiles.get(profile), dict):
            profiles[profile] = {}
        return profiles[profile]

    def _blocked_until(self, profile):
        value = self._entry(profile).get("blocked_until", 0)
        return float(value) if type(value) in (float, int) and math.isfinite(value) else 0

    def _available_profiles(self):
        return [profile for profile in self._profiles if self._blocked_until(profile) <= time.time()]

    def _remember_session(self, session, profile):
        entry = self._entry(profile)
        entry["cookies"] = [
            {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path,
             "secure": cookie.secure, "expires": cookie.expires}
            for cookie in session.cookies.jar
            if cookie.domain.lstrip(".") in {"leboncoin.fr", "www.leboncoin.fr", "api.leboncoin.fr"}
            and (cookie.expires is None or cookie.expires > time.time())
        ]
        write_session(self._session_path, self._session_state)

    def _send_search(self, payload):
        try:
            # lbc 1.1.9 reads the timeout from its HTTP session.
            self.session.timeout = self.timeout
            # Never let lbc recursively create new sessions after a refusal.
            return super()._fetch("POST", SEARCH_URL, payload, 0)
        except DatadomeError:
            entry = self._entry(self._active_profile)
            entry["blocked_until"] = time.time() + BLOCK_COOLDOWN_SECONDS
            # Do not reuse challenge cookies returned with a refused search.
            self.session.cookies.clear()
            raise
        finally:
            self._remember_session(self.session, self._active_profile)

    def _init_session(self, proxy=None, impersonate=None, request_verify=True, timeout=None):
        self._active_profile = impersonate
        entry = self._entry(impersonate)
        agent = entry.get("user_agent")
        if impersonate == "safari260_ios" and not (isinstance(agent, str) and agent.startswith("LBC;iOS;26.0;iPhone;")):
            # The SDK randomly pairs Android identities with Safari iOS. Keep
            # the native API format, with one coherent device for this profile.
            agent = f"LBC;iOS;26.0;iPhone;{uuid.uuid4()};wifi;101.45.0"
            entry["cookies"] = []
        if not isinstance(agent, str) or not agent.startswith("LBC;") or len(agent) > 1000 or "\r" in agent or "\n" in agent:
            agent = self._generate_user_agent()
        entry["user_agent"] = agent
        session = curl_requests.Session(impersonate=impersonate, verify=request_verify,
                                        timeout=self._request_timeout if timeout is None else timeout)
        session.headers.update({
            "User-Agent": agent,
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site",
        })
        if proxy:
            session.proxies = {"http": proxy.url, "https": proxy.url}
        try:
            cookies = entry.get("cookies", [])
            for raw in cookies if isinstance(cookies, list) else []:
                if not isinstance(raw, dict):
                    continue
                name, value, domain, path = (raw.get(k) for k in ("name", "value", "domain", "path"))
                expires = raw.get("expires")
                if not all(isinstance(v, str) for v in (name, value, domain, path)) or not name or len(name) > 256 or len(value) > 8192:
                    continue
                if domain.lstrip(".") not in {"leboncoin.fr", "www.leboncoin.fr", "api.leboncoin.fr"} or not path.startswith("/"):
                    continue
                if expires is not None and (type(expires) not in (int, float) or not math.isfinite(expires) or expires <= time.time()):
                    continue
                session.cookies.jar.set_cookie(Cookie(0, name, value, None, False, domain, True, domain.startswith("."),
                                                      path, True, bool(raw.get("secure")), expires, expires is None, None, None, {}))
            if not any(cookie.name == "datadome" for cookie in session.cookies.jar):
                session.get("https://www.leboncoin.fr/", verify=request_verify, timeout=self._request_timeout)
            self._remember_session(session, impersonate)
        except BaseException:
            session.close()
            raise
        return session

    def _fetch(self, method, url, payload=None, max_retries=-1):
        if method != "POST" or url != SEARCH_URL or not isinstance(payload, dict):
            return super()._fetch(method, url, payload, max_retries)
        # lbc's public search method does not expose these transport fields.
        # Its **kwargs become advert filters, so they cannot be passed there.
        body = dict(payload)
        # The SDK enables expanded recommendations by default. Ask for the
        # requested search only, with its own total, to avoid unrelated pages.
        body["extend"] = False
        body["disable_total"] = False
        key = json.dumps({k: body.get(k) for k in ("filters", "owner_type", "sort_by", "sort_order")},
                         sort_keys=True, ensure_ascii=True)
        if body.get("offset") == 0:
            self._search_key, self._next_offset, self._pivot = key, 0, None
        elif key != self._search_key:
            raise CollectionError("Pagination Leboncoin sans recherche initiale correspondante.")
        body["offset"] = self._next_offset
        if self._pivot is not None:
            body["pivot"] = self._pivot
        try:
            raw = self._send_search(body)
        except DatadomeError:
            alternatives = [profile for profile in self._available_profiles() if profile != self._active_profile]
            # One alternative, only before any page was received. Changing the
            # profile mid-pagination would invalidate the cursor and session.
            if self._fallback_used or self._next_offset or not alternatives:
                raise
            self._fallback_used = True
            LOGGER.warning("Leboncoin : profil %s refusé ; essai borné du profil %s après temporisation.", self._active_profile, alternatives[0])
            self.session.close()
            time.sleep(FALLBACK_DELAY_SECONDS)
            self.session = self._init_session(proxy=self._proxy, impersonate=alternatives[0], request_verify=self.request_verify)
            self._impersonate = alternatives[0]
            raw = self._send_search(body)
        if not isinstance(raw, dict) or not isinstance(raw.get("ads"), list):
            raise CollectionError("Réponse de recherche Leboncoin non reconnue.")
        owners = {}
        adverts = []
        for advert in raw["ads"]:
            if not isinstance(advert, dict):
                raise CollectionError("Annonce Leboncoin non reconnue.")
            ident = advert.get("list_id")
            if not ((type(ident) is int and ident >= 0) or (isinstance(ident, str) and ident.isdecimal())):
                raise CollectionError("Identifiant d'annonce Leboncoin non reconnu.")
            owner = advert.get("owner")
            kind = owner.get("type") if isinstance(owner, dict) else None
            owners[ident] = kind if isinstance(kind, str) and kind in {"private", "pro"} else ""
            adverts.append({**advert, "owner": owner if isinstance(owner, dict) else {}})
        pivot = raw.get("pivot")
        if pivot is not None and (not isinstance(pivot, str) or len(pivot) > 65536):
            raise CollectionError("Curseur de pagination Leboncoin non reconnu.")
        self._owners = owners
        self._pivot = pivot or None
        # Use the actual number returned if the server caps the requested size.
        self._next_offset += len(raw["ads"])
        self._session_state["preferred"] = self._active_profile
        self._entry(self._active_profile)["blocked_until"] = 0
        write_session(self._session_path, self._session_state)
        return {**raw, "ads": adverts}

    def search(self, *args, **kwargs):
        result = super().search(*args, **kwargs)
        for advert in result.ads:
            # The SDK otherwise drops owner.type. Never use advert.user here:
            # that property performs an additional request to a seller profile.
            advert.seller_type = self._owners.get(advert.id, "")
        return result
