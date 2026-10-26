from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from app.pieces.config import settings
from app.pieces.models import ConnectivityStatus, Offer, SearchRequest, SearchResponse, SiteSearchReport
from app.pieces.scrapers.base import _models_from_text
from app.pieces.scrapers.sites import SITES
from app.pieces.services.cache import cache
from app.pieces.services.catalogs import get_sync_status, load_catalog
from app.pieces.services.compatibility import keep_for_model
from app.pieces.services.connectivity import check_internet
from app.pieces.services.history import item_history_key, price_history_map
from app.pieces.services.text import extract_price, extract_reference, normalize_text, stable_id
from app.pieces.services.translation import canonical_french

_SUGGESTION_MAP: dict[str, tuple[str, ...]] = {
    "cable embrayage": (
        "câble d'embrayage",
        "câble embrayage 1900",
        '"câble embrayage"',
        "+câble +embrayage -occasion",
    ),
    "maitre cylindre": (
        "maître-cylindre de frein",
        "maître-cylindre 22,2 mm",
        "maître-cylindre GT 1900",
    ),
    "joint capot": ("joint de capot", "caoutchouc de capot", '"joint capot"'),
    "pompe eau": ("pompe à eau CIH", '"pompe à eau"'),
}
_STOPWORDS = {
    "opel",
    "gt",
    "piece",
    "pieces",
    "a",
    "au",
    "aux",
    "d",
    "de",
    "du",
    "l",
    "la",
    "le",
    "pour",
    "avec",
    "sans",
    "nouveau",
    "neuf",
    "the",
    "and",
    "for",
    "und",
    "fur",
    "fuer",
    "der",
    "die",
    "das",
    "mit",
    "van",
    "een",
    "het",
    "les",
    "des",
    "une",
    "sur",
    "chez",
    "model",
    "modele",
}

# Increment this value whenever the catalogue search pipeline changes in a way
# that can make a previously cached response invalid.
_SEARCH_CACHE_REVISION = 12

_AVAILABILITY_MAP = {
    "en stock": ("in_stock", "En stock"),
    "en rupture de stock": ("out_of_stock", "Pas de stock"),
    "réapprovisionnement": ("restocking", "Réapprovisionnement"),
    "reapprovisionnement": ("restocking", "Réapprovisionnement"),
    "sur demande": ("unknown", "Sur demande"),
    "inconnu": ("unknown", "À confirmer"),
}


def _positive_parts(keywords: str) -> list[str]:
    parts: list[str] = []
    for match in re.finditer(r'"([^"]+)"|(\S+)', keywords):
        phrase, token = match.groups()
        value = phrase if phrase is not None else (token or "")
        if phrase is None and value.startswith("-"):
            continue
        value = value.lstrip("+").strip()
        if value:
            parts.append(value)
    return parts


def _normalized_query(keywords: str) -> str:
    return normalize_text(canonical_french(" ".join(_positive_parts(keywords))))


def suggest_keywords(keywords: str, offers: list[Offer] | None = None, model: str | None = None) -> list[str]:
    normalized = _normalized_query(keywords)
    suggestions = list(_SUGGESTION_MAP.get(normalized, ()))
    words = [word for word in normalized.split() if len(word) > 2]

    if len(words) == 1:
        suggestions.extend((f"{words[0]} avant", f"{words[0]} arrière", f'"{words[0]}"'))
    elif len(words) > 1:
        suggestions.extend(" ".join(words[:i] + words[i + 1 :]) for i in range(len(words)))
        suggestions.append(f'"{" ".join(words)}"')

    if model and words:
        model_label = {"1900": "1900", "1100": "1100", "gtj": "GT/J"}.get(model, model)
        suggestions.append(f"{' '.join(words)} {model_label}")

    if offers:
        query_tokens = set(words)
        counter: Counter[str] = Counter()
        for offer in offers[:50]:
            title = normalize_text(canonical_french(offer.title))
            for token in set(title.split()):
                if (
                    len(token) > 2
                    and token not in query_tokens
                    and token not in _STOPWORDS
                    and not token.isdigit()
                ):
                    counter[token] += 1
        for token, count in counter.most_common(6):
            if count >= 2:
                suggestions.append(f"{' '.join(words)} {token}".strip())

    unique: list[str] = []
    original = normalize_text(" ".join(_positive_parts(keywords)))
    for suggestion in suggestions:
        if suggestion and normalize_text(suggestion) != original and suggestion not in unique:
            unique.append(suggestion)
    return unique[:6]


def analyze_ambiguity(keywords: str, offers: list[Offer]) -> tuple[bool, list[str]]:
    if not offers:
        return False, []
    reasons: list[str] = []
    terms = [term for term in _normalized_query(keywords).split() if len(term) > 2]
    if len(terms) <= 1:
        reasons.append("La requête ne contient qu'un terme significatif.")
    if len(offers) >= 20:
        reasons.append("La requête renvoie un grand nombre de pièces différentes.")

    confidences = [offer.query_confidence for offer in offers]
    if confidences and mean(confidences) < 0.82:
        reasons.append("Une part importante des correspondances de titre reste peu spécifique.")

    titles = {normalize_text(canonical_french(offer.title)) for offer in offers}
    if len(offers) >= 8 and len(titles) / len(offers) > 0.85:
        reasons.append("Les intitulés des résultats sont très variés.")

    by_currency: dict[str, list[float]] = {}
    for offer in offers:
        if offer.price is not None and offer.price > 0:
            by_currency.setdefault(offer.currency or "", []).append(offer.price)
    for values in by_currency.values():
        if len(values) >= 4 and min(values) > 0 and max(values) / min(values) >= 5:
            reasons.append(
                "Les prix couvrent une plage très large, signe de pièces ou variantes différentes."
            )
            break
    return bool(reasons), reasons


def _cache_key(request: SearchRequest) -> str:
    sync = get_sync_status()
    payload = {
        "revision": _SEARCH_CACHE_REVISION,
        "catalog_sync": sync.last_success_at or sync.last_completed_at,
        "model": request.model,
        "keywords": request.keywords.lower(),
        "sites": sorted(request.sites),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _ensure_requested_catalogues_ready(request: SearchRequest) -> None:
    sync = get_sync_status()
    if not sync.suppliers:
        if not sync.ready:
            raise RuntimeError(sync.detail or "Aucun catalogue fournisseur n'est prêt.")
        return
    by_id = {supplier.site_id: supplier for supplier in sync.suppliers}
    unavailable: list[str] = []
    for site_id in request.sites:
        supplier = by_id.get(site_id)
        if supplier is None or not (supplier.ok and supplier.item_count > 0):
            unavailable.append(SITES[site_id].name if site_id in SITES else site_id)
    if unavailable:
        raise RuntimeError("Catalogues fournisseurs non prêts pour la recherche : " + ", ".join(unavailable))


def _normalized_catalog_titles(record: dict[str, Any]) -> tuple[str, ...]:
    """Return canonicalized product-title variants and nothing else.

    ``nom`` is the title scraped from the supplier and ``nom_traduit`` is its
    translated title.  URLs, category paths, descriptions and surrounding page
    text are deliberately excluded: supplier category pages routinely contain
    words such as ``clutch`` or ``embrayage`` for unrelated products.
    """

    titles: list[str] = []
    for key in ("nom", "nom_traduit"):
        normalized = normalize_text(canonical_french(str(record.get(key) or "")))
        if normalized and normalized not in titles:
            titles.append(normalized)
    return tuple(titles)


def _significant_tokens(value: str) -> list[str]:
    normalized = normalize_text(canonical_french(value))
    return list(
        dict.fromkeys(
            token
            for token in normalized.split()
            if token and token not in _STOPWORDS and (len(token) > 1 or token.isdigit())
        )
    )


def _query_terms(keywords: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """Parse the documented search syntax.

    Returns ``(optional, required, phrases, excluded)``:

    * ordinary unquoted words are alternatives (OR);
    * words prefixed with ``+`` are all mandatory;
    * a quoted group is a mandatory exact canonical phrase;
    * words prefixed with ``-`` exclude a title.
    """

    optional: list[str] = []
    required: list[str] = []
    phrases: list[str] = []
    excluded: list[str] = []
    for match in re.finditer(r'"([^"]+)"|(\S+)', keywords):
        phrase, raw_token = match.groups()
        value = phrase if phrase is not None else (raw_token or "")
        is_excluded = phrase is None and value.startswith("-")
        is_required = phrase is None and value.startswith("+")
        value = value.lstrip("+-").strip()
        tokens = _significant_tokens(value)
        if not tokens:
            continue
        if is_excluded:
            excluded.extend(tokens)
        elif phrase is not None:
            phrases.append(" ".join(tokens))
        elif is_required:
            required.extend(tokens)
        else:
            optional.extend(tokens)
    return (
        list(dict.fromkeys(optional)),
        list(dict.fromkeys(required)),
        list(dict.fromkeys(phrases)),
        list(dict.fromkeys(excluded)),
    )


def _query_score(keywords: str, normalized_titles: tuple[str, ...] | list[str] | str) -> float:
    """Score the documented query syntax against product titles only.

    Eligibility is deliberately independent from URLs, category paths and page
    text.  Ordinary terms use OR semantics, ``+`` terms use AND semantics,
    quoted groups require the canonical phrase, and ``-`` terms exclude a
    product.  Canonicalization makes equivalent French, English, German and
    Dutch supplier titles comparable without widening the search to unrelated
    page content.
    """

    titles = (normalized_titles,) if isinstance(normalized_titles, str) else tuple(normalized_titles)
    titles = tuple(title for title in titles if title)
    optional, required, phrases, excluded = _query_terms(keywords)
    if not titles or not (optional or required or phrases):
        return 0.0

    # A negative concept in either the original or translated title excludes the
    # record. This avoids a bad translation hiding an explicit exclusion.
    all_title_tokens = set().union(*(set(title.split()) for title in titles))
    if any(token in all_title_tokens for token in excluded):
        return 0.0

    best = 0.0
    for title in titles:
        title_concepts = [token for token in title.split() if token not in _STOPWORDS]
        concept_title = " ".join(title_concepts)
        token_set = set(title_concepts)

        if any(token not in token_set for token in required):
            continue
        if any(phrase not in concept_title for phrase in phrases):
            continue

        matched_optional = [token for token in optional if token in token_set]
        if optional and not matched_optional:
            continue

        requested_tokens = list(
            dict.fromkeys(
                [
                    *optional,
                    *required,
                    *(token for phrase in phrases for token in phrase.split()),
                ]
            )
        )
        compact_query = " ".join(requested_tokens)

        if concept_title == compact_query:
            score = 1.0
        elif phrases:
            # All quoted phrases are present by the eligibility check. A quoted
            # query therefore remains the most selective form exposed by the UI.
            score = 0.98
        elif required:
            # Every +term is present. Optional words, when supplied as well,
            # improve the score but are not silently made mandatory.
            coverage = len(matched_optional) / len(optional) if optional else 1.0
            score = 0.90 + 0.08 * coverage
        else:
            coverage = len(matched_optional) / len(optional)
            if coverage == 1.0 and compact_query and compact_query in concept_title:
                score = 0.98
            elif coverage == 1.0:
                score = 0.95
            else:
                # A partial OR match is intentionally ranked below a title that
                # contains every ordinary keyword, while remaining eligible.
                score = 0.55 + 0.35 * coverage
        best = max(best, score)
    return round(best, 3)


def _availability(value: str) -> tuple[str, str]:
    key = normalize_text(value).replace("reapprovisionnement", "réapprovisionnement")
    return _AVAILABILITY_MAP.get(key, ("unknown", value.strip() or "À confirmer"))


def _record_to_offer(
    site_id: str,
    record: dict[str, Any],
    checked_at: str,
    confidence: float,
    history: dict[str, Any] | None = None,
) -> Offer:
    site = SITES[site_id]
    title = str(record.get("nom_traduit") or record.get("nom") or "Pièce sans nom").strip()
    original_title = str(record.get("nom") or "").strip()
    url = str(record.get("url_fiche") or site.home_url).strip() or site.home_url
    image = str(record.get("url_photo") or "").strip() or None
    price_text = str(record.get("prix") or "").strip()
    price, currency = extract_price(price_text, site.currency_hint)
    availability, availability_label = _availability(str(record.get("disponibilite") or ""))
    raw_description = " ".join(part for part in (original_title, title, price_text) if part)
    price_history = (history or {}).get(item_history_key(site_id, record))
    previous_price = price_history.previous_price if price_history is not None else None
    previous_price_date = price_history.previous_at if price_history is not None else None
    price_trend = None
    if price is not None and previous_price is not None:
        delta = price - previous_price
        price_trend = "stable" if abs(delta) < 0.005 else ("up" if delta > 0 else "down")
    return Offer(
        id=stable_id(site_id, url, title),
        site_id=site_id,
        site_name=site.name,
        title=title,
        url=url,
        image_url=image,
        reference=extract_reference(raw_description),
        price=price,
        currency=currency,
        availability=availability,  # type: ignore[arg-type]
        availability_label=availability_label,
        models=_models_from_text(raw_description + " " + url),
        query_confidence=round(min(1.0, max(0.0, confidence)), 3),
        raw_description=raw_description,
        checked_at=checked_at,
        price_source="catalogue_sync",
        availability_source="catalogue_sync",
        previous_price=previous_price,
        previous_price_date=previous_price_date,
        price_trend=price_trend,
    )


async def run_search(
    request: SearchRequest,
    connectivity: ConnectivityStatus | None = None,
) -> SearchResponse:
    _ensure_requested_catalogues_ready(request)

    key = _cache_key(request)
    cached = cache.get("search", key)
    if cached:
        response = SearchResponse.model_validate(cached)
        if connectivity is not None:
            response.connectivity = connectivity
        return response

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connectivity = connectivity or await check_internet(force=False)
    reports: list[SiteSearchReport] = []
    all_offers: list[Offer] = []
    warnings = [
        "Prix hors frais de port, consigne, éventuels frais de douane et variations de taxes selon le pays.",
        "Les résultats proviennent du dernier catalogue synchronisé ; la fiche fournisseur reste la référence avant achat.",
    ]

    for site_id in request.sites:
        if site_id not in SITES:
            continue
        try:
            records = load_catalog(site_id)
        except Exception as exc:
            reports.append(
                SiteSearchReport(
                    site_id=site_id,
                    site_name=SITES[site_id].name,
                    state="error",
                    detail=f"Catalogue local illisible : {type(exc).__name__}",
                )
            )
            continue

        histories = price_history_map(site_id)
        offers: list[Offer] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            confidence = _query_score(request.keywords, _normalized_catalog_titles(record))
            if confidence <= 0:
                continue
            offer = _record_to_offer(site_id, record, generated_at, confidence, histories)
            if keep_for_model(offer, request.model):
                offers.append(offer)

        offers.sort(
            key=lambda offer: (-offer.query_confidence, offer.price is None, offer.price or 0, offer.title)
        )
        if settings.max_results_per_site > 0:
            offers = offers[: settings.max_results_per_site]
        all_offers.extend(offers)
        reports.append(
            SiteSearchReport(
                site_id=site_id,
                site_name=SITES[site_id].name,
                state="ok" if offers else "empty",
                result_count=len(offers),
                pages_read=1,
                detail="Catalogue local synchronisé"
                if offers
                else "Aucun résultat correspondant dans le catalogue local.",
            )
        )

    all_offers.sort(
        key=lambda offer: (
            -offer.query_confidence,
            offer.price is None,
            offer.price or 0,
            offer.site_name,
            offer.title,
        )
    )
    ambiguous, ambiguity_reasons = analyze_ambiguity(request.keywords, all_offers)
    suggestions = suggest_keywords(request.keywords, all_offers, request.model)
    response = SearchResponse(
        query=request.keywords,
        model=request.model,
        generated_at=generated_at,
        offers=all_offers,
        total_offers=len(all_offers),
        reports=reports,
        warnings=warnings,
        suggestions=suggestions,
        ambiguous=ambiguous,
        ambiguity_reasons=ambiguity_reasons,
        connectivity=connectivity,
    )
    cache.set("search", key, response.model_dump(mode="json"), settings.search_cache_seconds)
    return response
