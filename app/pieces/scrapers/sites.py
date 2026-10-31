from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from app.common.config import ROOT


@dataclass(frozen=True)
class SiteConfig:
    id: str
    name: str
    base_url: str
    home_url: str
    language: str
    currency_hint: str
    platform: str
    use_website_engine_search: bool
    product_selectors: tuple[str, ...] = field(default_factory=tuple)
    status_urls: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    requests_per_minute: int = 120
    respect_robots_txt: bool = True


@dataclass(frozen=True)
class _SiteMetadata:
    id: str
    name: str
    currency_hint: str
    platform: str
    product_selectors: tuple[str, ...]


_SITE_METADATA_BY_HOST: dict[str, _SiteMetadata] = {
    "opelixparts.com": _SiteMetadata(
        id="opelix_parts",
        name="Opelix Parts",
        currency_hint="EUR",
        platform="prestashop",
        product_selectors=(".product-miniature", ".js-product", ".product", "article"),
    ),
    "splenditparts.de": _SiteMetadata(
        id="splendid_parts",
        name="SplendidParts",
        currency_hint="EUR",
        platform="splendidparts",
        product_selectors=(".product-miniature", ".js-product-miniature", ".product", "article"),
    ),
    "edelschmiede.com": _SiteMetadata(
        id="edelschmiede",
        name="Edelschmiede",
        currency_hint="EUR",
        platform="jtl",
        product_selectors=(".productbox", ".product-wrapper", ".product-item", "article"),
    ),
    "pro-gt.de": _SiteMetadata(
        id="pro_gt",
        name="GT Teile",
        currency_hint="EUR",
        platform="oscommerce",
        product_selectors=(
            ".productlist-viewmode-grid .product-container",
            ".productlist-viewmode-list .product-container",
            ".productlist-item",
            ".product-container",
            ".product-box",
            ".product",
            ".productbox",
            ".product-listing",
            "article",
        ),
    ),
    "atz-online.com": _SiteMetadata(
        id="atz_online",
        name="ATZ Online",
        currency_hint="EUR",
        platform="woocommerce",
        product_selectors=("li.product", ".type-product", ".product", "article"),
    ),
    "opelgtsource.com": _SiteMetadata(
        id="opel_gt_source",
        name="Opel GT Source",
        currency_hint="USD",
        platform="opelgtsource",
        product_selectors=(".product", ".product-list-item", ".search-result", "article", "li"),
    ),
    "oldtimer-motorenteile.com": _SiteMetadata(
        id="oldtimer_motorenteile",
        name="Oldtimer Motorenteile",
        currency_hint="EUR",
        platform="oscommerce",
        product_selectors=(
            ".productlist-viewmode-grid .product-container",
            ".productlist-viewmode-list .product-container",
            ".productlist-item",
            ".productListing-data",
            ".product-container",
            ".product-box",
            ".product",
            ".product-item",
            "article",
        ),
    ),
    "shop.tw-oldtimerteile.de": _SiteMetadata(
        id="tw_oldtimerteile",
        name="TW-Oldtimerteile",
        currency_hint="EUR",
        platform="twoldtimerteile",
        product_selectors=(
            ".productlist-viewmode-grid .product-container",
            ".productlist-viewmode-list .product-container",
            ".productlist .product-container",
            ".product-container",
            ".product-box",
            ".productlist-item",
            "article.product",
        ),
    ),
}

_SUPPORTED_LANGUAGES = {"fr", "en", "de", "nl"}


def _normalized_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def _parse_bool(value: str, *, line_number: int) -> bool:
    key, separator, raw = value.partition("=")
    if separator != "=" or key.strip() != "use-website-engine-search":
        raise ValueError(f"suppliers_infos.txt ligne {line_number}: troisième champ invalide ({value!r})")
    normalized = raw.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"suppliers_infos.txt ligne {line_number}: booléen attendu, reçu {raw!r}")
    return normalized == "true"


def load_sites(path: Path | None = None) -> dict[str, SiteConfig]:
    configured_path = Path(os.getenv("SUPPLIERS_INFO_PATH", str(path or (ROOT / "suppliers_infos.txt"))))
    if not configured_path.is_file():
        raise FileNotFoundError(f"Fichier fournisseurs introuvable : {configured_path}")

    sites: dict[str, SiteConfig] = {}
    for line_number, raw_line in enumerate(configured_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) != 3:
            raise ValueError(
                f"suppliers_infos.txt ligne {line_number}: trois champs séparés par '|' sont requis"
            )
        root_url, language, search_flag = fields
        parsed = urlparse(root_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"suppliers_infos.txt ligne {line_number}: URL racine invalide ({root_url!r})")
        language = language.lower()
        if language not in _SUPPORTED_LANGUAGES:
            raise ValueError(
                f"suppliers_infos.txt ligne {line_number}: langue non prise en charge ({language!r})"
            )
        host = _normalized_host(root_url)
        metadata = _SITE_METADATA_BY_HOST.get(host)
        if metadata is None:
            raise ValueError(
                f"suppliers_infos.txt ligne {line_number}: fournisseur inconnu pour le domaine {host!r}"
            )
        if metadata.id in sites:
            raise ValueError(
                f"suppliers_infos.txt ligne {line_number}: fournisseur {metadata.name!r} dupliqué"
            )

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        use_engine = _parse_bool(search_flag, line_number=line_number)
        sites[metadata.id] = SiteConfig(
            id=metadata.id,
            name=metadata.name,
            base_url=base_url,
            home_url=root_url,
            language=language,
            currency_hint=metadata.currency_hint,
            platform=metadata.platform,
            use_website_engine_search=use_engine,
            product_selectors=metadata.product_selectors,
            status_urls=(root_url,),
        )

    missing = {metadata.id for metadata in _SITE_METADATA_BY_HOST.values()} - set(sites)
    if missing:
        raise ValueError(
            "suppliers_infos.txt incomplet, fournisseurs manquants : " + ", ".join(sorted(missing))
        )
    return sites


SITES: dict[str, SiteConfig] = load_sites()
