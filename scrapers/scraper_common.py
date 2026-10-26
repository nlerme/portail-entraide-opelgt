#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilitaires communs pour les scrapers du comparateur Entraide Opel GT.

Objectifs d'intégration :
- même fonction publique dans chaque script : scrape(output=None, workers=None, timeout=None)
- mêmes champs JSON produits
- même affichage terminal
- aucune trace Python si un fournisseur est down / en maintenance / en congés
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Any
import argparse
import contextlib
import io
import json
import re
import time
import traceback

from catalog_progress import report_progress, reset_progress

BUNDLE_VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()

FIELDS = ("nom", "nom_traduit", "prix", "disponibilite", "url_photo", "url_fiche")
AVAILABILITIES = {"en stock", "en rupture de stock", "réapprovisionnement", "sur demande", "inconnu"}
NUMERIC_EURO_PRICE_RE = re.compile(r"^\d(?:[\d .]*\d)?,\d{2}\s*€$")

LANG_PATTERNS = {
    "fr": (
        r"maintenance", r"en\s+maintenance", r"travaux", r"indisponible", r"temporairement",
        r"ferm[ée]", r"fermeture", r"cong[ée]s", r"vacances", r"hors\s+ligne",
        r"service\s+indisponible", r"site\s+indisponible",
    ),
    "de": (
        r"wartung", r"wartungsarbeiten", r"nicht\s+verf[uü]gbar", r"vor[uü]bergehend",
        r"geschlossen", r"betriebsferien", r"urlaub", r"ferien", r"pause", r"offline",
        r"service\s+unavailable", r"zugriff\s+verweigert",
    ),
    "en": (
        r"maintenance", r"temporarily\s+unavailable", r"currently\s+unavailable", r"closed",
        r"vacation", r"holiday", r"holidays", r"down", r"offline", r"service\s+unavailable",
        r"forbidden", r"access\s+denied",
    ),
}
HTTP_DOWN_RE = re.compile(
    r"\b(?:HTTP\s*)?(?:403|408|425|429|500|502|503|504)\b|"
    r"Max retries exceeded|NameResolutionError|Temporary failure|Connection(?:Error| refused)|"
    r"Read timed out|ConnectTimeout|Timeout|SSLError|RemoteDisconnected|"
    r"Service Unavailable|Bad Gateway|Gateway Timeout|Forbidden",
    re.IGNORECASE,
)
EMPTY_MAINTENANCE_RE = re.compile(
    r"aucun(?:e)?\s+(?:produit|pi[eè]ce|carte)|no\s+(?:product|item)|keine\s+(?:artikel|produkte)|"
    r"catalogue\s+vide|compteur.*introuvable|pagination.*introuvable",
    re.IGNORECASE,
)

@dataclass
class ScrapeResult:
    supplier: str
    status: str                  # ok | unavailable | failed
    ok: bool
    output_path: str
    status_path: str
    item_count: int
    duration_seconds: float
    message: str
    details: str = ""
    legacy_stdout_tail: str = ""
    legacy_stderr_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tail(text: str, max_chars: int = 6000) -> str:
    text = text or ""
    return text[-max_chars:] if len(text) > max_chars else text


def classify_unavailability(text: str, language: str = "fr") -> tuple[bool, str]:
    haystack = text or ""
    if HTTP_DOWN_RE.search(haystack):
        return True, "site indisponible ou accès temporairement refusé"
    langs = [language]
    if language not in {"fr", "de", "en"}:
        langs = []
    # Toujours tester les trois langues : certains sites mélangent frontend et serveur.
    for lang in (langs + [x for x in ("fr", "de", "en") if x not in langs]):
        for pattern in LANG_PATTERNS[lang]:
            if re.search(pattern, haystack, re.IGNORECASE):
                return True, f"message de maintenance/fermeture détecté ({lang})"
    if EMPTY_MAINTENANCE_RE.search(haystack):
        return True, "page catalogue vide ou remplacée par une page d'information"
    return False, ""


def validate_schema(path: Path) -> tuple[bool, str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"JSON illisible : {exc}", 0
    if not isinstance(data, list):
        return False, "la racine JSON n'est pas une liste", 0
    known_prices = 0
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict) or tuple(item.keys()) != FIELDS:
            return False, f"élément {index}: champs attendus {FIELDS}, reçus {tuple(item.keys()) if isinstance(item, dict) else type(item)}", len(data)
        if item.get("disponibilite") not in AVAILABILITIES:
            return False, f"élément {index}: disponibilité invalide {item.get('disponibilite')!r}", len(data)
        for field in FIELDS:
            if not isinstance(item.get(field), str) or not item.get(field).strip():
                return False, f"élément {index}: champ vide ou non chaîne {field}", len(data)
        if NUMERIC_EURO_PRICE_RE.fullmatch(item["prix"].strip()):
            known_prices += 1
    if data and known_prices == 0:
        return False, "aucun prix numérique extrait dans le catalogue", len(data)
    return True, "", len(data)


def write_status(path: Path, result: ScrapeResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_legacy_scraper(
    *,
    supplier: str,
    language: str,
    output_path: Path,
    status_path: Path,
    legacy_callable: Callable[[Path, int | None, float | None], Any],
    workers: int | None = None,
    timeout: float | None = None,
    quiet: bool = False,
) -> ScrapeResult:
    started = time.monotonic()
    out = Path(output_path)
    status = Path(status_path)
    reset_progress(supplier)

    if not quiet:
        print(f"[{supplier}] version harmonisée")
        print(f"[{supplier}] 1/3 Initialisation")
        print(f"[{supplier}] 2/3 Scraping fournisseur")

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    status_value = "failed"
    message = "échec non classé"
    details = ""

    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            result = legacy_callable(out, workers, timeout)
            if isinstance(result, int) and result not in (0, None):
                raise RuntimeError(f"code retour non nul : {result}")
    except SystemExit as exc:
        code = exc.code
        if code not in (0, None):
            combined = stdout_buffer.getvalue() + "\n" + stderr_buffer.getvalue() + "\n" + str(code)
            unavailable, reason = classify_unavailability(combined, language)
            status_value = "unavailable" if unavailable else "failed"
            message = reason or f"arrêt contrôlé du script : {code}"
            details = combined
        else:
            status_value = "ok"
            message = "scraping terminé"
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        combined = stdout_buffer.getvalue() + "\n" + stderr_buffer.getvalue() + "\n" + "".join(traceback.format_exception_only(type(exc), exc))
        unavailable, reason = classify_unavailability(combined, language)
        status_value = "unavailable" if unavailable else "failed"
        message = reason or "échec contrôlé sans traceback"
        details = combined
    else:
        status_value = "ok"
        message = "scraping terminé"

    ok = status_value == "ok"
    item_count = 0
    if ok:
        report_progress(97, f"{supplier} : vérification du catalogue récupéré.")
        schema_ok, schema_msg, item_count = validate_schema(out)
        if not schema_ok:
            ok = False
            status_value = "failed"
            message = schema_msg
            details = stdout_buffer.getvalue() + "\n" + stderr_buffer.getvalue()

    elapsed = time.monotonic() - started
    result = ScrapeResult(
        supplier=supplier,
        status=status_value,
        ok=ok,
        output_path=str(out),
        status_path=str(status),
        item_count=item_count,
        duration_seconds=round(elapsed, 3),
        message=message,
        details=_tail(details, 12000),
        legacy_stdout_tail=_tail(stdout_buffer.getvalue()),
        legacy_stderr_tail=_tail(stderr_buffer.getvalue()),
    )
    write_status(status, result)
    if result.ok:
        report_progress(99, f"{supplier} : {item_count} pièces vérifiées ; contrôle final avant publication.")

    if not quiet:
        print(f"[{supplier}] 3/3 Résultat")
        if result.ok:
            print(f"[{supplier}] OK — {result.item_count} pièce(s), {result.duration_seconds:.1f} s")
            print(f"[{supplier}] JSON : {result.output_path}")
        elif result.status == "unavailable":
            print(f"[{supplier}] INDISPONIBLE — {result.message}")
            print(f"[{supplier}] Ancien JSON conservé s'il existe : {result.output_path}")
            print(f"[{supplier}] Statut : {result.status_path}")
        else:
            print(f"[{supplier}] ÉCHEC CONTRÔLÉ — {result.message}")
            print(f"[{supplier}] Statut : {result.status_path}")
    return result


def scraper_cli(
    *,
    supplier: str,
    version: str,
    default_output: Path,
    scrape_func: Callable[..., ScrapeResult],
) -> int:
    parser = argparse.ArgumentParser(description=f"Scraper harmonisé {supplier}")
    parser.add_argument("-o", "--output", type=Path, default=default_output)
    parser.add_argument("-j", "--workers", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--status-file", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--strict", action="store_true", help="retourne un code non nul si le statut n'est pas ok")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(f"{supplier} {version}")
        return 0
    result = scrape_func(
        output=args.output,
        workers=args.workers,
        timeout=args.timeout,
        status_file=args.status_file,
        quiet=args.quiet,
    )
    return 0 if result.ok or not args.strict else 1
