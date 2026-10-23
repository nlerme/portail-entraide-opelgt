"""Optional, bounded name translation for the ATZ and Opel GT Source catalogues."""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from catalog_progress import advance_phase

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATE_TIMEOUT = (3, 6)
MAX_WORKERS = 2


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def translate_names(
    names: list[str], *, language: str, cache_file: Path, previous_output: Path, workers: int,
) -> dict[str, str]:
    """Keep prices updateable when translation is throttled or unavailable.

    Only successful translations enter the persistent cache. Original names
    used as a fallback will therefore be retried on the next catalogue update.
    """
    unique = list(dict.fromkeys(names))
    raw_cache = _read_json(cache_file)
    cache = {
        key: _text(value) for key, value in (raw_cache.items() if isinstance(raw_cache, dict) else [])
        if isinstance(key, str) and key.strip() and _text(value)
    }
    previous = _read_json(previous_output)
    if isinstance(previous, list):
        for item in previous:
            if not isinstance(item, dict):
                continue
            original, translated = _text(item.get("nom")), _text(item.get("nom_traduit"))
            if original and translated and original != translated:
                cache.setdefault(original, translated)

    missing = [name for name in unique if name not in cache]
    advance_phase("translations", completed=len(unique) - len(missing), total=len(unique), amount=0)
    batches: list[list[str]] = []
    for name in missing:
        if not batches or len(batches[-1]) >= 24 or sum(len(n) + 12 for n in batches[-1]) + len(name) > 1800:
            batches.append([])
        batches[-1].append(name)
    print(f"    Traductions : {len(unique) - len(missing)} en cache, {len(missing)} à compléter.")
    unavailable = threading.Event()

    def request(batch: list[str]) -> dict[str, str]:
        if unavailable.is_set():
            return {}
        text = batch[0] if len(batch) == 1 else "\n".join(
            f"{i:04d}|||{name}" for i, name in enumerate(batch, 1)
        )
        # No transport retries: a failure stops queued batches for this run.
        try:
            with requests.Session() as session:
                response = session.get(
                    TRANSLATE_URL,
                    params={"client": "gtx", "sl": language, "tl": "fr", "dt": "t", "q": text},
                    timeout=TRANSLATE_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
                    raise ValueError("réponse de traduction invalide")
                translated = "".join(segment[0] for segment in payload[0] if segment and isinstance(segment[0], str))
                if not translated.strip():
                    raise ValueError("traduction vide")
        except (requests.RequestException, ValueError, TypeError, IndexError, KeyError):
            unavailable.set()
            return {}

        if len(batch) == 1:
            return {batch[0]: _text(translated)}
        markers = list(re.finditer(r"(?<!\d)(\d{4})\s*\|\|\|\s*", translated))
        values = [
            _text(translated[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(translated)])
            for i, m in enumerate(markers)
        ]
        if len(markers) == len(batch) and all(values) and [int(m[1]) for m in markers] == list(range(1, len(batch) + 1)):
            return dict(zip(batch, values, strict=True))
        # Subdivide only a successful response with damaged separators, never
        # a throttled service (the previous code multiplied 429 requests).
        middle = len(batch) // 2
        return {**request(batch[:middle]), **request(batch[middle:])}

    if batches:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, workers), len(batches))) as executor:
            futures = {executor.submit(request, batch): len(batch) for batch in batches}
            for future in as_completed(futures):
                cache.update(future.result())
                advance_phase("translations", amount=futures[future])
    # Cache persistence is an optimization, not a condition for publishing
    # an otherwise valid catalogue. Never cache untranslated fallback names.
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_suffix(cache_file.suffix + ".tmp")
        temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(cache_file)
    except OSError:
        print("    Cache de traduction non enregistrable ; catalogue conservé.")
    fallback_count = sum(name not in cache for name in unique)
    if fallback_count:
        print(
            f"    Traduction indisponible pour {fallback_count} nom(s) : désignations originales conservées, "
            "prix et disponibilités actualisés. Nouvelle tentative à la prochaine mise à jour."
        )
    return {name: cache.get(name, name) for name in unique}
