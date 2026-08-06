#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Récupère le catalogue Opel GT 1900 d'Oldtimer-Motorenteile depuis les
pages de catégorie uniquement, puis écrit oldtimermotorenteile.json.

Dépendances :
    python -m pip install requests beautifulsoup4

Le script n'utilise ni le moteur de recherche du site, ni Playwright,
ni Selenium, et ne télécharge jamais les fiches individuelles.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except ImportError as exc:  # message explicite plutôt qu'une trace obscure
    raise SystemExit(
        "Dépendances manquantes. Exécutez : "
        "python -m pip install requests beautifulsoup4"
    ) from exc


VERSION = "2026.07.03-oldtimermotorenteile-v1"
URL_RACINE = (
    "https://www.oldtimer-motorenteile.com/"
    "?cat=c380_Opel-GT-1900--68---73-Opel-GT-1900--68---73.html"
)
FICHIER_SORTIE = "oldtimermotorenteile.json"
DEVISE_VOULUE = "EUR"
NB_THREADS_DEFAUT = 8
TIMEOUT_DEFAUT = 30.0
NB_TENTATIVES = 4

# Une session par thread : connexions persistantes sans partager un objet Session
# entre threads.
_ETAT_THREAD = threading.local()
_TAUX_EUR: dict[str, Decimal] = {"EUR": Decimal("1")}
_VERROU_TAUX = threading.Lock()


class ErreurScraping(RuntimeError):
    """Erreur contrôlée du scraper."""


def texte_propre(valeur: str | None) -> str:
    """Normalise espaces, espaces insécables et retours à la ligne."""
    return re.sub(r"\s+", " ", (valeur or "").replace("\xa0", " ")).strip()


def session_thread() -> requests.Session:
    """Retourne une session HTTP propre au thread courant."""
    session = getattr(_ETAT_THREAD, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/149.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Referer": URL_RACINE,
            }
        )
        _ETAT_THREAD.session = session
    return session


def modifier_requete(url: str, **parametres: Any) -> str:
    """Ajoute/remplace des paramètres GET en conservant l'URL existante."""
    parties = urlsplit(url)
    requete = dict(parse_qsl(parties.query, keep_blank_values=True))
    for cle, valeur in parametres.items():
        if valeur is None:
            requete.pop(cle, None)
        else:
            requete[cle] = str(valeur)
    return urlunsplit(
        (parties.scheme, parties.netloc, parties.path, urlencode(requete), "")
    )


def url_page(numero: int, langue: str) -> str:
    """Construit une URL de page catalogue en imposant langue et euro."""
    params: dict[str, Any] = {
        "language": langue,
        "currency": DEVISE_VOULUE,
    }
    if numero > 1:
        params["page"] = numero
    else:
        params["page"] = None
    return modifier_requete(URL_RACINE, **params)


def telecharger_page_catalogue(url: str, timeout: float) -> str:
    """Télécharge exclusivement une page catalogue avec reprises sur erreur."""
    if "product_info.php" in url.lower():
        raise ErreurScraping(
            "Refus de télécharger une fiche individuelle : " + url
        )

    derniere_erreur: Exception | None = None
    for tentative in range(1, NB_TENTATIVES + 1):
        try:
            reponse = session_thread().get(url, timeout=timeout, allow_redirects=True)
            reponse.raise_for_status()
            type_contenu = reponse.headers.get("Content-Type", "").lower()
            if "html" not in type_contenu and not reponse.text.lstrip().startswith("<"):
                raise ErreurScraping(
                    f"Réponse non HTML pour {url} : {type_contenu or 'type inconnu'}"
                )
            return reponse.text
        except (requests.RequestException, ErreurScraping) as exc:
            derniere_erreur = exc
            if tentative < NB_TENTATIVES:
                time.sleep(0.7 * (2 ** (tentative - 1)))

    raise ErreurScraping(
        f"Échec du téléchargement après {NB_TENTATIVES} tentatives : {url} "
        f"({derniere_erreur})"
    )


def entier_localise(texte: str) -> int:
    """Convertit '1.234' ou '1 234' en entier."""
    chiffres = re.sub(r"[^0-9]", "", texte)
    return int(chiffres) if chiffres else 0


def detecter_pagination(html: str) -> tuple[int, int | None]:
    """
    Détermine d'abord le nombre de pages depuis les liens de pagination, puis
    le recoupe avec l'indication « 1 bis N (von insgesamt T) » du catalogue.
    """
    soup = BeautifulSoup(html, "html.parser")
    pages = {1}

    for lien in soup.select(".pagination a[href], a.page-link[href]"):
        href = lien.get("href", "")
        numero = dict(parse_qsl(urlsplit(href).query)).get("page")
        if numero and numero.isdigit():
            pages.add(int(numero))
        texte = texte_propre(lien.get_text(" ", strip=True))
        if texte.isdigit():
            pages.add(int(texte))

    texte_page = texte_propre(soup.get_text(" ", strip=True))
    total: int | None = None
    par_page: int | None = None

    # Forme allemande observée sur le site :
    # « 1 bis 16 (von insgesamt 16) ».
    motifs = (
        r"([\d. ]+)\s+bis\s+([\d. ]+)\s*\(\s*von\s+insgesamt\s+([\d. ]+)\s*\)",
        r"([\d, .]+)\s+to\s+([\d, .]+)\s*\([^)]*total[^0-9]*([\d, .]+)\)",
        r"([\d, .]+)\s+(?:à|au)\s+([\d, .]+)\s*\([^)]*total[^0-9]*([\d, .]+)\)",
    )
    for motif in motifs:
        correspondance = re.search(motif, texte_page, flags=re.IGNORECASE)
        if correspondance:
            debut = entier_localise(correspondance.group(1))
            fin = entier_localise(correspondance.group(2))
            total = entier_localise(correspondance.group(3))
            if debut == 1 and fin >= debut:
                par_page = fin - debut + 1
            break

    if total is not None and par_page:
        pages.add(max(1, math.ceil(total / par_page)))

    return max(pages), total


def choisir_conteneur_produits(soup: BeautifulSoup) -> list[Tag]:
    """Retourne les cartes produit de la liste centrale, sans les sliders."""
    selecteurs = (
        ".product-filter-target.productlist .product-container",
        ".productlist.productlist-viewmode .product-container",
        "main .productlist .product-container",
        "#content .productlist .product-container",
        ".productlist .product-container",
    )
    for selecteur in selecteurs:
        cartes = [x for x in soup.select(selecteur) if isinstance(x, Tag)]
        if cartes:
            return cartes
    return []


def lien_produit(carte: Tag, base_url: str) -> tuple[str, str] | None:
    """Extrait nom et URL de fiche sans jamais ouvrir cette URL."""
    selecteurs = (
        "a.product-url[href*='product_info.php']",
        ".title a[href*='product_info.php']",
        ".product-name a[href*='product_info.php']",
        "h2 a[href*='product_info.php']",
        "h3 a[href*='product_info.php']",
        "a[href*='product_info.php']",
    )
    lien: Tag | None = None
    for selecteur in selecteurs:
        candidat = carte.select_one(selecteur)
        if isinstance(candidat, Tag):
            lien = candidat
            break
    if lien is None:
        return None

    href = texte_propre(lien.get("href"))
    nom = texte_propre(lien.get("title")) or texte_propre(lien.get_text(" ", strip=True))
    if not href or not nom:
        return None
    return nom, urljoin(base_url, href)


def cle_produit(url: str) -> str:
    """Clé stable commune aux variantes allemande et française d'une fiche."""
    parties = urlsplit(url)
    params = dict(parse_qsl(parties.query, keep_blank_values=True))
    info = params.get("info", "")
    numero = re.match(r"p(\d+)", info, flags=re.IGNORECASE)
    if numero:
        return "p" + numero.group(1)

    # Repli : URL canonique sans paramètres de présentation/session.
    a_retirer = {
        "language",
        "currency",
        "page",
        "sort",
        "view_mode",
        "xtcsid",
        "gxsid",
    }
    filtres = [
        (k, v)
        for k, v in parse_qsl(parties.query, keep_blank_values=True)
        if k.lower() not in a_retirer
    ]
    return urlunsplit(
        (parties.scheme.lower(), parties.netloc.lower(), parties.path, urlencode(filtres), "")
    )


def url_photo(carte: Tag, base_url: str) -> str:
    """Choisit l'image principale de la carte et ignore les icônes de livraison."""
    images: list[Tag] = []
    for selecteur in (
        "figure img",
        ".product-image img",
        ".image img",
        "img",
    ):
        images = [x for x in carte.select(selecteur) if isinstance(x, Tag)]
        if images:
            break

    for image in images:
        classes = " ".join(image.get("class", []))
        contexte = " ".join(
            [
                classes,
                texte_propre(image.get("alt")),
                texte_propre(image.get("title")),
            ]
        ).lower()
        if any(mot in contexte for mot in ("shipping", "liefer", "icon", "sofort")):
            continue

        source = ""
        for attribut in ("data-src", "data-original", "data-lazy-src", "src"):
            valeur = texte_propre(image.get(attribut))
            if valeur and not valeur.startswith("data:image/"):
                source = valeur
                break
        if not source:
            srcset = texte_propre(image.get("data-srcset") or image.get("srcset"))
            if srcset:
                source = texte_propre(srcset.split(",")[-1].split()[0])
        if source:
            return urljoin(base_url, source)
    return "inconnu"


def texte_livraison(carte: Tag) -> str:
    """Rassemble texte et attributs d'image du bloc de livraison."""
    zones: list[Tag] = []
    for selecteur in (
        ".shipping-info-short",
        ".shipping",
        "[class*='shipping']",
        "[class*='delivery']",
    ):
        zones = [x for x in carte.select(selecteur) if isinstance(x, Tag)]
        if zones:
            break

    morceaux: list[str] = []
    for zone in zones:
        morceaux.append(texte_propre(zone.get_text(" ", strip=True)))
        for image in zone.select("img"):
            morceaux.extend(
                [texte_propre(image.get("alt")), texte_propre(image.get("title"))]
            )

    # Repli limité à la ligne contenant Lieferzeit/Shipping time.
    if not any(morceaux):
        texte = texte_propre(carte.get_text(" ", strip=True))
        correspondance = re.search(
            r"(?:Lieferzeit|Shipping\s*time|Délai\s*de\s*livraison)\s*:\s*"
            r"(.{0,80}?)(?=\b(?:Art\.?Nr|Product\s*No|Réf|\d+[,.]\d{2}\s*(?:EUR|€))\b|$)",
            texte,
            flags=re.IGNORECASE,
        )
        if correspondance:
            morceaux.append(correspondance.group(1))

    return texte_propre(" ".join(morceaux))


def disponibilite_depuis_texte(texte: str) -> str:
    """Ramène le libellé fournisseur aux cinq valeurs imposées."""
    t = texte_propre(texte).casefold()
    if not t:
        return "inconnu"

    if any(
        mot in t
        for mot in (
            "auf anfrage",
            "sur demande",
            "on request",
            "upon request",
            "preis auf anfrage",
        )
    ):
        return "sur demande"

    if any(
        mot in t
        for mot in (
            "ausverkauft",
            "vergriffen",
            "nicht lieferbar",
            "nicht verfügbar",
            "out of stock",
            "sold out",
            "unavailable",
            "rupture de stock",
            "épuisé",
            "indisponible",
        )
    ):
        return "en rupture de stock"

    if any(
        mot in t
        for mot in (
            "nachbestellt",
            "wieder lieferbar",
            "bald lieferbar",
            "im zulauf",
            "backorder",
            "back order",
            "restocking",
            "available soon",
            "réapprovisionnement",
            "bientôt disponible",
        )
    ):
        return "réapprovisionnement"

    if any(
        mot in t
        for mot in (
            "sofort",
            "auf lager",
            "lagernd",
            "in stock",
            "immediately",
            "immédiatement",
            "en stock",
            "disponible immédiatement",
        )
    ):
        return "en stock"

    # Un délai chiffré non immédiat correspond ici à un approvisionnement.
    if re.search(
        r"\b\d+\s*(?:-|–|bis|to|à)?\s*\d*\s*"
        r"(?:tag|tage|werktag|day|days|jour|jours|woche|wochen|week|weeks|semaine|semaines)\b",
        t,
    ):
        return "réapprovisionnement"

    return "inconnu"


def decimal_localise(nombre: str) -> Decimal:
    """Convertit un nombre de prix allemand, français ou anglais en Decimal."""
    s = nombre.replace("\xa0", " ").replace(" ", "").strip()
    if not s:
        raise InvalidOperation

    if "," in s and "." in s:
        # Le dernier séparateur est le séparateur décimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")

    return Decimal(s)


def taux_vers_euro(devise: str, timeout: float) -> Decimal:
    """Récupère une fois le taux courant vers EUR si le site ignore currency=EUR."""
    devise = devise.upper()
    with _VERROU_TAUX:
        deja = _TAUX_EUR.get(devise)
    if deja is not None:
        return deja

    url = f"https://api.frankfurter.app/latest?from={devise}&to=EUR"
    derniere_erreur: Exception | None = None
    for tentative in range(1, NB_TENTATIVES + 1):
        try:
            reponse = session_thread().get(url, timeout=timeout)
            reponse.raise_for_status()
            taux = Decimal(str(reponse.json()["rates"]["EUR"]))
            with _VERROU_TAUX:
                _TAUX_EUR[devise] = taux
            return taux
        except (requests.RequestException, KeyError, ValueError, InvalidOperation) as exc:
            derniere_erreur = exc
            if tentative < NB_TENTATIVES:
                time.sleep(0.5 * tentative)

    raise ErreurScraping(
        f"Impossible de convertir {devise} vers EUR ({derniere_erreur})"
    )


def formater_euros(valeur: Decimal) -> str:
    """Formate exactement sous la forme AB,CD€."""
    arrondi = valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{arrondi:.2f}".replace(".", ",") + "€"


def prix_depuis_carte(carte: Tag, timeout: float) -> str:
    """Extrait le prix affiché; convertit en euro seulement si nécessaire."""
    zones = carte.select(
        ".current-price-container, .price, [class*='price']"
    ) or [carte]

    symboles = {"€": "EUR", "$": "USD", "£": "GBP"}
    motif = re.compile(
        r"(?P<nombre>\d[\d\s.]*?(?:[,.]\d{1,2})?)\s*"
        r"(?P<devise>EUR|USD|GBP|CHF|CAD|AUD|JPY|€|\$|£)",
        flags=re.IGNORECASE,
    )

    for zone in zones:
        texte = texte_propre(zone.get_text(" ", strip=True))
        for correspondance in motif.finditer(texte):
            try:
                montant = decimal_localise(correspondance.group("nombre"))
            except InvalidOperation:
                continue
            devise_brute = correspondance.group("devise")
            devise = symboles.get(devise_brute, devise_brute.upper())
            if devise != "EUR":
                try:
                    montant *= taux_vers_euro(devise, timeout)
                except ErreurScraping:
                    return "inconnu"
            return formater_euros(montant)

    return "inconnu"


def parser_catalogue(html: str, page_url: str, timeout: float) -> list[dict[str, str]]:
    """Parse une page de catégorie et uniquement ses cartes produit."""
    soup = BeautifulSoup(html, "html.parser")
    cartes = choisir_conteneur_produits(soup)
    produits: list[dict[str, str]] = []

    for carte in cartes:
        resultat_lien = lien_produit(carte, page_url)
        if resultat_lien is None:
            continue
        nom, fiche = resultat_lien
        produits.append(
            {
                "cle": cle_produit(fiche),
                "nom": nom,
                "prix": prix_depuis_carte(carte, timeout),
                "disponibilite": disponibilite_depuis_texte(
                    texte_livraison(carte)
                ),
                "url_photo": url_photo(carte, page_url),
                "url_fiche": fiche,
            }
        )

    if not produits:
        raise ErreurScraping(
            "Aucune carte produit reconnue sur la page catalogue : " + page_url
        )
    return produits


def recuperer_et_parser(
    numero_page: int,
    langue: str,
    timeout: float,
    html_deja_charge: str | None = None,
) -> tuple[int, str, list[dict[str, str]]]:
    """Unité de travail indépendante exécutée dans le pool de threads."""
    adresse = url_page(numero_page, langue)
    html = html_deja_charge if html_deja_charge is not None else telecharger_page_catalogue(
        adresse, timeout
    )
    return numero_page, langue, parser_catalogue(html, adresse, timeout)


def assembler_page(
    allemands: list[dict[str, str]],
    francais: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Associe la traduction française par identifiant produit, puis par position."""
    noms_fr = {produit["cle"]: produit["nom"] for produit in francais}
    sortie: list[dict[str, str]] = []

    for position, produit in enumerate(allemands):
        traduction = noms_fr.get(produit["cle"])
        if not traduction and position < len(francais):
            traduction = francais[position]["nom"]
        traduction = texte_propre(traduction) or "inconnu"

        sortie.append(
            {
                "nom": produit["nom"],
                "nom_traduit": traduction,
                "prix": produit["prix"],
                "disponibilite": produit["disponibilite"],
                "url_photo": produit["url_photo"],
                "url_fiche": produit["url_fiche"],
            }
        )
    return sortie


def scraper(sortie: Path, nb_threads: int, timeout: float) -> list[dict[str, str]]:
    """Orchestre pagination, téléchargements parallèles, appariement et JSON."""
    print(f"oldtimermotorenteile.py version {VERSION}")
    print(f"1/4 Initialisation depuis {URL_RACINE}")

    premiere_url = url_page(1, "de")
    premier_html = telecharger_page_catalogue(premiere_url, timeout)
    nombre_pages, total_annonce = detecter_pagination(premier_html)
    print(
        f"    {nombre_pages} page(s) catalogue détectée(s)"
        + (f", {total_annonce} pièce(s) annoncée(s)." if total_annonce else ".")
    )

    print("2/4 Téléchargement et parsing des pages allemandes et françaises")
    travailleurs = max(1, min(nb_threads, nombre_pages * 2))
    resultats: dict[tuple[int, str], list[dict[str, str]]] = {}

    with ThreadPoolExecutor(max_workers=travailleurs) as executant:
        taches = {}
        for numero_page in range(1, nombre_pages + 1):
            for langue in ("de", "fr"):
                html_reutilise = (
                    premier_html if numero_page == 1 and langue == "de" else None
                )
                futur = executant.submit(
                    recuperer_et_parser,
                    numero_page,
                    langue,
                    timeout,
                    html_reutilise,
                )
                taches[futur] = (numero_page, langue)

        for futur in as_completed(taches):
            numero_page, langue = taches[futur]
            try:
                page, langue_retour, produits = futur.result()
            except Exception as exc:
                raise ErreurScraping(
                    f"Échec page {numero_page}, langue {langue} : {exc}"
                ) from exc
            resultats[(page, langue_retour)] = produits
            libelle = "allemande" if langue_retour == "de" else "française"
            print(f"    Page {page}/{nombre_pages} {libelle} : {len(produits)} pièce(s).")

    print("3/4 Appariement des noms originaux et des traductions françaises")
    catalogue: list[dict[str, str]] = []
    for numero_page in range(1, nombre_pages + 1):
        catalogue.extend(
            assembler_page(
                resultats[(numero_page, "de")],
                resultats[(numero_page, "fr")],
            )
        )

    # Déduplication strictement par URL de fiche, en conservant l'ordre catalogue.
    uniques: list[dict[str, str]] = []
    deja_vues: set[str] = set()
    for produit in catalogue:
        cle = cle_produit(produit["url_fiche"])
        if cle not in deja_vues:
            deja_vues.add(cle)
            uniques.append(produit)
    catalogue = uniques

    if total_annonce is not None and len(catalogue) != total_annonce:
        print(
            "    AVERTISSEMENT : "
            f"{len(catalogue)} pièce(s) extraite(s), {total_annonce} annoncée(s) par le site.",
            file=sys.stderr,
        )

    print("4/4 Écriture du fichier JSON")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"    {len(catalogue)} pièce(s) écrite(s) dans {sortie}")
    return catalogue


def arguments() -> argparse.Namespace:
    parseur = argparse.ArgumentParser(
        description=(
            "Récupère le catalogue Opel GT 1900 d'Oldtimer-Motorenteile "
            "sans consulter les fiches individuelles."
        )
    )
    parseur.add_argument(
        "-o",
        "--sortie",
        default=FICHIER_SORTIE,
        help=f"fichier JSON de sortie (défaut : {FICHIER_SORTIE})",
    )
    parseur.add_argument(
        "-j",
        "--threads",
        type=int,
        default=NB_THREADS_DEFAUT,
        help=f"nombre maximal de requêtes parallèles (défaut : {NB_THREADS_DEFAUT})",
    )
    parseur.add_argument(
        "--timeout",
        type=float,
        default=TIMEOUT_DEFAUT,
        help=f"timeout HTTP en secondes (défaut : {TIMEOUT_DEFAUT:g})",
    )
    return parseur.parse_args()


def main() -> None:
    args = arguments()
    if args.threads < 1:
        raise SystemExit("--threads doit être supérieur ou égal à 1")
    if args.timeout <= 0:
        raise SystemExit("--timeout doit être strictement positif")

    try:
        scraper(Path(args.sortie), args.threads, args.timeout)
    except KeyboardInterrupt:
        raise SystemExit("Interruption demandée par l'utilisateur.")
    except ErreurScraping as exc:
        raise SystemExit(f"ERREUR : {exc}") from exc


# ---------------------------------------------------------------------------
# Couche d'intégration homogénéisée pour le bundle comparateur Entraide Opel GT
# ---------------------------------------------------------------------------
import sys as _scraper_sys
from pathlib import Path as _ScraperPath
from scraper_common import ScrapeResult as ScrapeResult, run_legacy_scraper as _run_legacy_scraper, scraper_cli as _scraper_cli

_LEGACY_MAIN = main
_SUPPLIER_NAME = 'Oldtimer-Motorenteile'
_SUPPLIER_LANG = 'de'
_DEFAULT_OUTPUT = _ScraperPath(__file__).resolve().with_name('oldtimermotorenteile.json')
_HARMONIZED_VERSION = "2026.07.10-harmonized-v1"


def _set_legacy_output(output: _ScraperPath) -> None:
    """Adapte les constantes de sortie historiques sans changer le parsing."""
    global OUTPUT_FILE, OUTPUT, FICHIER_SORTIE
    if "OUTPUT_FILE" in globals():
        OUTPUT_FILE = output
    if "OUTPUT" in globals():
        OUTPUT = output
    if "FICHIER_SORTIE" in globals():
        FICHIER_SORTIE = str(output)


def _run_legacy(output: _ScraperPath, workers: int | None, timeout: float | None) -> object:
    _set_legacy_output(output)
    old_argv = _scraper_sys.argv[:]
    # Les anciens scripts avaient des interfaces CLI hétérogènes. Pour garantir
    # une entrée homogène, on neutralise leurs argparse et on pilote les constantes.
    _scraper_sys.argv = [old_argv[0]]
    try:
        return _LEGACY_MAIN()
    finally:
        _scraper_sys.argv = old_argv


def scrape(
    output: str | _ScraperPath | None = None,
    workers: int | None = None,
    timeout: float | None = None,
    status_file: str | _ScraperPath | None = None,
    quiet: bool = False,
) -> ScrapeResult:
    """Point d'entrée homogène attendu par le bundle.

    Retourne toujours un ScrapeResult. En cas de site down, maintenance ou
    congés fournisseur, aucune exception n'est propagée et l'ancien JSON n'est
    pas écrasé.
    """
    out = _ScraperPath(output) if output is not None else _DEFAULT_OUTPUT
    status = _ScraperPath(status_file) if status_file is not None else out.with_suffix(".status.json")
    return _run_legacy_scraper(
        supplier=_SUPPLIER_NAME,
        language=_SUPPLIER_LANG,
        output_path=out,
        status_path=status,
        legacy_callable=_run_legacy,
        workers=workers,
        timeout=timeout,
        quiet=quiet,
    )


def main() -> int:
    return _scraper_cli(
        supplier=_SUPPLIER_NAME,
        version=_HARMONIZED_VERSION,
        default_output=_DEFAULT_OUTPUT,
        scrape_func=scrape,
    )


if __name__ == "__main__":
    raise SystemExit(main())
