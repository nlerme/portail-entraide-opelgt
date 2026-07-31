from pathlib import Path

import pytest

from app.pieces.scrapers.sites import load_sites

EXPECTED = [
    ("opelix_parts", "https://www.opelixparts.com/9-gt-1968-73", "fr", False),
    ("splendid_parts", "https://splenditparts.de/shop/en/70-opel-gt", "en", False),
    ("edelschmiede", "https://www.edelschmiede.com/GT_1", "en", False),
    ("pro_gt", "https://www.pro-gt.de/en/", "en", True),
    ("atz_online", "https://atz-online.com/?s=%22opel+gt%22&post_type=product", "de", False),
    ("opel_gt_source", "https://www.opelgtsource.com/search?car_id=4", "en", False),
    (
        "oldtimer_motorenteile",
        "https://www.oldtimer-motorenteile.com/?cat=c898_Opel-GT--68---73-Opel-GT--68---73.html",
        "en",
        False,
    ),
    (
        "tw_oldtimerteile",
        "https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/",
        "de",
        False,
    ),
]


def test_suppliers_file_drives_urls_languages_and_search_modes():
    sites = load_sites()
    assert [
        (site.id, site.home_url, site.language, site.use_website_engine_search) for site in sites.values()
    ] == EXPECTED


def test_suppliers_file_rejects_malformed_lines(tmp_path: Path):
    malformed = tmp_path / "suppliers_infos.txt"
    malformed.write_text(
        "https://splenditparts.de/shop/en/70-opel-gt | en | maybe\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="troisième champ invalide"):
        load_sites(malformed)


def test_pro_gt_supplier_uses_public_name_gt_teile():
    sites = load_sites()
    assert sites["pro_gt"].name == "GT Teile"


def test_tw_oldtimerteile_contact_block_is_present_on_comparator_page():
    html = (Path(__file__).resolve().parents[1] / "static" / "pieces" / "index.html").read_text(encoding="utf-8")

    assert "TW-Oldtimerteile" in html
    assert "https://shop.tw-oldtimerteile.de/Opel-Typen/Opel-GT/" in html
    assert "Torsten Winter, Weidweg 2, 64823 Groß-Umstadt, Allemagne" in html
    assert 'href="tel:+49607874639"' in html
    assert 'href="mailto:opel.winter@t-online.de"' in html
    assert "logo-tw-oldtimerteile.svg" in html
