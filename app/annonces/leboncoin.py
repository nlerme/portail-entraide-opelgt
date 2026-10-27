"""Search-only adapter for the pinned lbc 1.1.7 response and pagination."""
from __future__ import annotations

import json

import lbc
from curl_cffi import requests as curl_requests

from app.annonces.collectors import CollectionError

SEARCH_URL = "https://api.leboncoin.fr/finder/search"


class SearchClient(lbc.Client):
    """Keep lbc's transport/parser, including its refusal and retry policy."""

    def __init__(self, **kwargs):
        self._request_timeout = kwargs.get("timeout", 20)
        super().__init__(**kwargs)
        self._search_key = None
        self._next_offset = 0
        self._pivot = None
        self._owners = {}

    def _init_session(self, proxy=None, impersonate=None, request_verify=True):
        # Keep the SDK's accepted API identity and cookie initialization.
        # The previous adapter replaced both without a successful live validation.
        session = curl_requests.Session(impersonate=impersonate, verify=request_verify, timeout=self._request_timeout)
        session.headers.update({
            "User-Agent": self._generate_user_agent(),
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site",
        })
        if proxy:
            session.proxies = {"http": proxy.url, "https": proxy.url}
        try:
            session.get("https://www.leboncoin.fr/", verify=request_verify, timeout=self._request_timeout)
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
        key = json.dumps({k: body.get(k) for k in ("filters", "owner_type", "sort_by", "sort_order")},
                         sort_keys=True, ensure_ascii=True)
        if body.get("offset") == 0:
            self._search_key, self._next_offset, self._pivot = key, 0, None
        elif key != self._search_key:
            raise CollectionError("Pagination Leboncoin sans recherche initiale correspondante.")
        body["offset"] = self._next_offset
        if self._pivot is not None:
            body["pivot"] = self._pivot
        raw = super()._fetch(method, url, body, max_retries)
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
        return {**raw, "ads": adverts}

    def search(self, *args, **kwargs):
        result = super().search(*args, **kwargs)
        for advert in result.ads:
            # The SDK otherwise drops owner.type. Never use advert.user here:
            # that property performs an additional request to a seller profile.
            advert.seller_type = self._owners.get(advert.id, "")
        return result
