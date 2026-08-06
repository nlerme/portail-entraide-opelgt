from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.pieces.config import settings
from app.pieces.services.cache import cache
from app.pieces.services.text import normalize_text

# Lexique volontairement ciblé sur les pièces d'Opel GT. Les expressions longues
# sont traitées avant les mots isolés afin de préserver leur sens technique.
LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "fr": {
        "maitre cylindre": ("master cylinder", "hauptbremszylinder", "hoofdremcilinder"),
        "cylindre de roue": ("wheel cylinder", "radbremszylinder", "wielremcilinder"),
        "pompe a eau": ("water pump", "wasserpumpe", "waterpomp"),
        "pompe a essence": ("fuel pump", "kraftstoffpumpe", "brandstofpomp"),
        "joint de culasse": ("head gasket", "zylinderkopfdichtung", "koppakking"),
        "joint spi": ("shaft seal", "wellendichtring", "keerring"),
        "roulement de roue": ("wheel bearing", "radlager", "wiellager"),
        "rotule de direction": ("tie rod end", "spurstangenkopf", "stuurkogel"),
        "silentbloc": ("bushing", "gummibuchse", "rubber bus"),
        "durite radiateur": ("radiator hose", "kuhlerschlauch", "radiateurslang"),
        "cable embrayage": ("clutch cable", "kupplungszug", "koppelingskabel"),
        "cable accelerateur": ("throttle cable", "gaszug", "gaskabel"),
        "essuie glace": ("wiper blade", "scheibenwischerblatt", "ruitenwisserblad"),
        "feu arriere": ("tail light", "ruckleuchte", "achterlicht"),
        "feu avant": ("headlight", "scheinwerfer", "koplamp"),
        "clignotant": ("turn signal", "blinker", "richtingaanwijzer"),
        "echappement": ("exhaust", "auspuff", "uitlaat"),
        "embrayage": ("clutch", "kupplung", "koppeling"),
        "frein": ("brake", "bremse", "rem"),
        "disque": ("disc", "scheibe", "schijf"),
        "plaquette": ("brake pad", "bremsbelag", "remblok"),
        "machoire": ("brake shoe", "bremsbacke", "remschoen"),
        "etrier": ("caliper", "bremssattel", "remklauw"),
        "amortisseur": ("shock absorber", "stossdampfer", "schokdemper"),
        "ressort": ("spring", "feder", "veer"),
        "alternateur": ("alternator", "lichtmaschine", "dynamo"),
        "demarreur": ("starter", "anlasser", "startmotor"),
        "allumeur": ("distributor", "zundverteiler", "verdeler"),
        "bougie": ("spark plug", "zundkerze", "bougie"),
        "carburateur": ("carburetor", "vergaser", "carburateur"),
        "radiateur": ("radiator", "kuhler", "radiateur"),
        "thermostat": ("thermostat", "thermostat", "thermostaat"),
        "filtre a huile": ("oil filter", "olfilter", "oliefilter"),
        "filtre a air": ("air filter", "luftfilter", "luchtfilter"),
        "filtre essence": ("fuel filter", "kraftstofffilter", "brandstoffilter"),
        "capot": ("hood", "motorhaube", "motorkap"),
        "aile": ("fender", "kotflugel", "spatbord"),
        "pare choc": ("bumper", "stossstange", "bumper"),
        "porte": ("door", "tur", "deur"),
        "poignee": ("handle", "griff", "handgreep"),
        "serrure": ("lock", "schloss", "slot"),
        "retroviseur": ("mirror", "spiegel", "spiegel"),
        "pare brise": ("windshield", "windschutzscheibe", "voorruit"),
        "joint": ("gasket seal", "dichtung", "pakking afdichting"),
        "tableau de bord": ("dashboard", "armaturenbrett", "dashboard"),
        "compteur": ("speedometer", "tachometer", "snelheidsmeter"),
        "volant": ("steering wheel", "lenkrad", "stuurwiel"),
        "siege": ("seat", "sitz", "stoel"),
        "moquette": ("carpet", "teppich", "tapijt"),
        "reservoir": ("fuel tank", "kraftstofftank", "brandstoftank"),
        "ligne essence": ("fuel line", "kraftstoffleitung", "brandstofleiding"),
        "boite de vitesse": ("gearbox transmission", "getriebe", "versnellingsbak"),
        "arbre de transmission": ("driveshaft", "kardanwelle", "aandrijfas"),
        "pont arriere": ("rear axle", "hinterachse", "achteras"),
        "neuf": ("new", "neu", "nieuw"),
        "occasion": ("used", "gebraucht", "gebruikt"),
        "gauche": ("left", "links", "links"),
        "droite": ("right", "rechts", "rechts"),
        "avant": ("front", "vorne", "voor"),
        "arriere": ("rear", "hinten", "achter"),
    }
}

REVERSE: dict[str, str] = {}
for french, variants in LEXICON["fr"].items():
    REVERSE[normalize_text(french)] = french
    for variant in variants:
        REVERSE[normalize_text(variant)] = french
REVERSE[normalize_text("kupplungsseil")] = "cable embrayage"
for _cable_variant in (
    "cable",
    "cables",
    "bowden cable",
    "bowden cables",
    "kabel",
    "kabelsatz",
    "bowdenzug",
    "kabels",
    "kabelboom",
):
    REVERSE[normalize_text(_cable_variant)] = "cable"
for _wiper_variant in (
    "wiper arm set",
    "wiper arm sets",
    "wiper arm",
    "wiper arms",
    "wiper blades",
    "windscreen wiper",
    "windscreen wipers",
    "windshield wiper",
    "windshield wipers",
    "scheibenwischer",
    "scheibenwischerarm",
    "scheibenwischerarme",
    "scheibenwischerblatter",
    "wischerarm",
    "wischerarme",
    "ruitenwisser",
    "ruitenwissers",
):
    REVERSE[normalize_text(_wiper_variant)] = "essuie glace"


@dataclass(frozen=True)
class QueryVariants:
    fr: str
    en: str
    de: str
    nl: str


class TranslationError(RuntimeError):
    """Raised when a non-French supplier query cannot be translated safely."""


_LANGUAGE_INDEX = {"en": 0, "de": 1, "nl": 2}
_FRENCH_GRAMMAR = {"a", "au", "aux", "d", "de", "des", "du", "l", "la", "le", "les", "pour"}
_SAFE_UNTRANSLATED = {
    "opel",
    "gt",
    "gtj",
    "cih",
    "ohv",
    "getrag",
    "weber",
    "solex",
    "bosch",
    "delco",
    "kadett",
    "manta",
    "ascona",
    "rekord",
    "commodore",
}
_TRANSLATION_CACHE: dict[tuple[str, str], str] = {}

# Variantes de recherche réellement employées par les catalogues. Certains sites
# utilisent un synonyme différent de la traduction littérale (par exemple
# « Kupplungszug » plutôt que « Kupplungsseil »).
_SEARCH_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("cable embrayage", "en"): ("clutch cable",),
    ("cable embrayage", "de"): ("kupplungszug", "kupplungsseil"),
    ("cable embrayage", "nl"): ("koppelingskabel",),
    ("cable embrayage", "fr"): ("câble embrayage", "cable embrayage"),
    ("essuie glace", "en"): (
        "wiper arms",
        "wiper arm",
        "wiper blades",
        "wiper blade",
        "windshield wiper",
        "wiper",
    ),
    ("essuie glace", "de"): (
        "wischerarme",
        "wischerarm",
        "scheibenwischerarme",
        "scheibenwischerblatt",
        "scheibenwischer",
        "wischer",
    ),
    ("essuie glace", "nl"): ("ruitenwisserblad", "ruitenwisser"),
    ("essuie glace", "fr"): ("essuie-glace", "essuie glace"),
}


def _positive_query_text(text: str) -> str:
    """Return only the positive terms entered by the user, without search operators."""
    parts: list[str] = []
    for match in re.finditer(r'"([^"]+)"|(\S+)', text):
        phrase, token = match.groups()
        value = phrase if phrase is not None else (token or "")
        if phrase is None and value.startswith("-"):
            continue
        value = value.lstrip("+").strip()
        if value:
            parts.append(value)
    return " ".join(parts)


def _normalize_french_query(text: str) -> str:
    tokens = normalize_text(_positive_query_text(text)).split()
    return " ".join(token for token in tokens if token not in _FRENCH_GRAMMAR)


def _lexical_translation(text: str, language: str) -> tuple[str, list[str]]:
    """Translate known automotive phrases and return untranslated significant tokens."""
    normalized = _normalize_french_query(text)
    if language == "fr":
        return " ".join(_positive_query_text(text).strip().split()), []
    if language not in _LANGUAGE_INDEX:
        raise TranslationError(f"Langue de boutique non prise en charge : {language}")

    translated = normalized
    remaining = normalized
    language_index = _LANGUAGE_INDEX[language]
    items = sorted(
        LEXICON["fr"].items(),
        key=lambda item: len(_normalize_french_query(item[0]).split()),
        reverse=True,
    )
    for source, targets in items:
        source_normalized = _normalize_french_query(source)
        if not source_normalized:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(source_normalized)}(?![a-z0-9])"
        if re.search(pattern, translated):
            translated = re.sub(pattern, targets[language_index], translated)
            remaining = re.sub(pattern, " ", remaining)

    unknown = []
    for token in remaining.split():
        if token.isdigit() or token in _SAFE_UNTRANSLATED or re.fullmatch(r"[a-z]*\d+[a-z0-9]*", token):
            continue
        unknown.append(token)
    return " ".join(translated.split()), unknown


def _replace_phrases(text: str, language_index: int) -> str:
    language = ("en", "de", "nl")[language_index]
    translated, _ = _lexical_translation(text, language)
    return translated


def query_variants(keywords_fr: str) -> QueryVariants:
    return QueryVariants(
        fr=" ".join(keywords_fr.strip().split()),
        en=_replace_phrases(keywords_fr, 0),
        de=_replace_phrases(keywords_fr, 1),
        nl=_replace_phrases(keywords_fr, 2),
    )


def _with_model_terms(translated: str, models: list[str]) -> str:
    model_terms: list[str] = ["Opel GT"]
    if len(models) == 1:
        if models[0] == "gtj":
            model_terms.extend(["GT/J", "GTJ"])
        elif models[0] == "1100":
            model_terms.extend(["1100", "1.1", "OHV"])
        elif models[0] == "1900":
            model_terms.extend(["1900", "1.9", "CIH"])
    return " ".join(dict.fromkeys([translated, *model_terms]))


def query_for_language(keywords_fr: str, language: str, models: list[str]) -> str:
    """Build the deterministic lexicon-based query used for known automotive terms."""
    variants = query_variants(keywords_fr)
    translated = getattr(variants, language, None)
    if translated is None:
        raise TranslationError(f"Langue de boutique non prise en charge : {language}")
    return _with_model_terms(translated, models)


async def _verified_translation_only(
    keywords_fr: str,
    language: str,
    client: httpx.AsyncClient,
) -> str:
    """Translate the user terms without adding vehicle-model qualifiers."""
    translated, unknown = _lexical_translation(keywords_fr, language)
    if language == "fr" or not unknown:
        return translated

    cache_key = (normalize_text(keywords_fr), language)
    remote = _TRANSLATION_CACHE.get(cache_key)
    if remote is None:
        persistent = cache.get("translation", f"{cache_key[0]}::{language}")
        remote = str(persistent) if persistent else None
    if remote is None:
        try:
            response = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": keywords_fr, "langpair": f"fr|{language}"},
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            remote = str(payload.get("responseData", {}).get("translatedText") or "").strip()
        except Exception as exc:
            raise TranslationError(
                f"Traduction française vers {language} impossible pour : {', '.join(unknown)}"
            ) from exc
        if not remote:
            raise TranslationError(f"Traduction française vers {language} vide pour : {', '.join(unknown)}")
        _TRANSLATION_CACHE[cache_key] = remote
        cache.set("translation", f"{cache_key[0]}::{language}", remote, settings.translation_cache_seconds)
    return remote


async def verified_query_for_language(
    keywords_fr: str,
    language: str,
    models: list[str],
    client: httpx.AsyncClient,
) -> str:
    """Return only the verified translation of the user's positive keywords."""
    return await _verified_translation_only(keywords_fr, language, client)


async def verified_query_candidates_for_language(
    keywords_fr: str,
    language: str,
    models: list[str],
    client: httpx.AsyncClient,
) -> list[str]:
    """Build supplier-language queries containing only the user's positive terms.

    The selected vehicle model is deliberately not appended: it is context for
    the interface, not an extra keyword silently imposed on the supplier search.
    Known catalogue synonyms remain allowed because they are translations of the
    exact requested part name.
    """
    translated = await _verified_translation_only(keywords_fr, language, client)
    canonical_query = _normalize_french_query(keywords_fr)
    bases = list(_SEARCH_ALIASES.get((canonical_query, language), (translated,)))
    if translated not in bases:
        bases.insert(0, translated)

    # The alias table explicitly defines the broad supplier semantics. Keeping
    # this expansion declarative avoids turning arbitrary phrases into unsafe
    # one-word searches (for example ``glace`` or ``arm``).
    return list(dict.fromkeys(" ".join(query.split()) for query in bases if query.strip()))


def canonical_french(title: str) -> str:
    normalized = normalize_text(title)
    # Remplace les synonymes connus par la forme française canonique.
    for variant, french in sorted(REVERSE.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(variant, french)
    return " ".join(normalized.split())
