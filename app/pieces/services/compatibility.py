from __future__ import annotations

import re

from app.pieces.models import Offer
from app.pieces.services.text import strip_accents

_UNIVERSAL_MARKERS = (
    "all opel gt",
    "all gt models",
    "tous modeles opel gt",
    "tous les modeles opel gt",
    "alle opel gt",
    "alle opel gt modelle",
    "fits 1100 and 1900",
    "1100 1900",
    "1 1 1 9",
)

# The supplier catalogues also contain parts for other classic Opel families.
# Those names must never be interpreted as an Opel GT merely because the
# engine displacement (for example 1.9 CIH) happens to be the same.
_OTHER_OPEL_MODEL_RE = re.compile(
    r"\b(?:"
    r"kadett(?:\s+[a-e])?|"
    r"manta(?:\s+[a-b])?|"
    r"ascona(?:\s+[a-c])?|"
    r"rekord(?:\s+[a-e])?|"
    r"commodore|olympia|kapitan|admiral|diplomat|"
    r"monza|senator|omega|vectra|calibra|corsa|astra|tigra|meriva|zafira|insignia|"
    r"agila|antara|cascada|combo|crossland|frontera|grandland|karl|movano|signum|"
    r"sintra|speedster|vivaro|ampera|adam|campo|monterey|blitz"
    r")\b"
)
_GT_RE = re.compile(r"\b(?:opel\s+gt|gt\s*/\s*j|gt\s+j|gtj|gt\s+(?:1100|1900|1\s*[.,]?\s*[19]))\b")


def _vehicle_text(offer: Offer) -> str:
    """Normalize compatibility text without deleting the words ``Opel GT``.

    ``normalize_text`` deliberately removes ``Opel GT`` for keyword matching,
    which is useful for search relevance but incorrect for vehicle filtering.
    """

    value = strip_accents(f"{offer.title} {offer.raw_description} {offer.url}").lower()
    value = re.sub(r"[^a-z0-9/.,]+", " ", value)
    return " ".join(value.split())


def assess_compatibility(offer: Offer, selected_model: str) -> str:
    text = _vehicle_text(offer)
    models = set(offer.models)
    explicitly_gt = bool(_GT_RE.search(text))
    explicitly_other_opel = bool(_OTHER_OPEL_MODEL_RE.search(text))

    # A Manta/Rekord/Kadett/etc. result is not an Opel GT result, even when it
    # shares a 1.9 CIH engine and therefore carries the same engine marker.
    if explicitly_other_opel and not explicitly_gt:
        return "incompatible"

    if any(marker in text for marker in _UNIVERSAL_MARKERS):
        return "universal"
    if selected_model in models:
        return "compatible"
    if not models:
        return "uncertain"

    if selected_model == "1900" and models <= {"1100"}:
        return "incompatible"
    if selected_model == "1100" and models.isdisjoint({"1100"}):
        return "incompatible"
    if selected_model == "gtj":
        if models <= {"1100"}:
            return "incompatible"
        if models & {"gtj", "1900"}:
            return "compatible"
    return "uncertain"


def keep_for_model(offer: Offer, selected_model: str) -> bool:
    offer.compatibility = assess_compatibility(offer, selected_model)  # type: ignore[assignment]
    return offer.compatibility != "incompatible"
