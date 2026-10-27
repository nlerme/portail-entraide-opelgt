from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlparse

PRICE_RE = re.compile(
    r"(?:(?P<cur1>€|EUR|USD|\$|GBP|£)\s*)?"
    r"(?P<num>\d{1,6}(?:[\s.']\d{3})*(?:[,.]\d{1,2})?)"
    r"\s*(?P<cur2>€|EUR|USD|\$|GBP|£)?",
    re.IGNORECASE,
)
REF_PATTERNS = (
    re.compile(
        r"(?:réf(?:érence)?|ref(?:erence)?|part(?:\s*no\.?|\s*number)?|artikel(?:nummer)?|art\.?\s*nr\.?|sku)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})",
        re.I,
    ),
    re.compile(r"\b([A-Z]{1,4}[-/]?\d{3,8}[A-Z0-9-]*)\b"),
)


def strip_accents(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    value = strip_accents(value).lower()
    value = value.replace("opel gt", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def stable_id(*parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()[:16]


def clean_url(url: str, base_url: str) -> str:
    url = urljoin(base_url, url.strip())
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return url


def extract_price(text: str, currency_hint: str | None = None) -> tuple[float | None, str | None]:
    candidates: list[tuple[float, str | None]] = []
    for match in PRICE_RE.finditer(text.replace("\xa0", " ")):
        raw = match.group("num").replace(" ", "").replace("'", "")
        has_currency = bool(match.group("cur1") or match.group("cur2"))
        if not has_currency:
            if currency_hint is None:
                continue
            nearby = text[max(0, match.start() - 12) : match.end() + 12].lower()
            numeric_price_shape = any(sep in match.group("num") for sep in (",", "."))
            price_context = any(word in nearby for word in ("prix", "price", "preis", "vanaf", "from"))
            compact_field = bool(
                re.fullmatch(
                    r"\s*(?:from|vanaf|ab|des|dès)?\s*[€$£]?\s*\d[\d\s.,']*\s*(?:€|eur|usd|gbp|\$|£)?\s*",
                    text,
                    re.I,
                )
            )
            if not (numeric_price_shape or price_context or compact_field):
                continue
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value <= 0 or value > 100000:
            continue
        symbol = (match.group("cur1") or match.group("cur2") or currency_hint or "").upper()
        currency = {"€": "EUR", "$": "USD", "£": "GBP"}.get(symbol, symbol or currency_hint)
        candidates.append((value, currency))
    return candidates[0] if candidates else (None, currency_hint)


def extract_reference(text: str) -> str | None:
    explicit = REF_PATTERNS[0].search(text)
    if explicit:
        ref = re.sub(r"[^A-Z0-9]", "", explicit.group(1).upper())
        if 3 <= len(ref) <= 24 and ref not in {
            "1100",
            "1900",
            "1968",
            "1969",
            "1970",
            "1971",
            "1972",
            "1973",
        }:
            return ref
    generic = REF_PATTERNS[1].search(text)
    if generic:
        ref = re.sub(r"[^A-Z0-9]", "", generic.group(1).upper())
        if 3 <= len(ref) <= 24 and any(char.isalpha() for char in ref):
            return ref
    return None
