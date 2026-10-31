from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("bulletins", "pieces", "annonces", "couples")


def test_service_footers_have_the_same_content_and_shared_style():
    footers = []
    for service in SERVICES:
        page = BeautifulSoup((ROOT / f"static/{service}/index.html").read_text(), "html.parser")
        footer = page.select_one("footer.portal-footer")
        assert footer is not None
        assert len(page.select("footer")) == 1
        assert footer.select_one("hr.footer-separator") is not None
        assert footer.select_one(".footer-bottom").get_text(" ", strip=True) == "Auteur : Nicolas Lermé — Copyright 2026 Fait avec amour ❤️"
        assert footer.select_one('[role="img"][aria-label="cœur"]').get_text() == "❤️"
        styles = [link["href"].split("?")[0] for link in page.select('link[rel="stylesheet"]')]
        assert styles[-1] == "/static/common/footer.css"
        footers.append(str(footer))
    assert len(set(footers)) == 1


def test_footer_badges_match_the_readme_and_do_not_need_an_external_service():
    readme = (ROOT / "README.md").read_text()
    expected = re.findall(r"!\[([^\]]+)\]\(https://img\.shields\.io/[^)]+\)", readme)
    page = BeautifulSoup((ROOT / "static/annonces/index.html").read_text(), "html.parser")
    images = page.select("footer.portal-footer .footer-badges img")
    assert [image["alt"] for image in images] == expected
    assert len(images) > 40
    root = ROOT / "static/common/badges"
    manifest = json.loads((root / "manifest.json").read_text())
    assets = {item["file"]: item for item in manifest["badges"]}
    assert len(assets) == len(images)
    for image in images:
        assert image["src"].startswith("/static/common/badges/")
        data = (ROOT / image["src"].lstrip("/")).read_bytes()
        assert hashlib.sha256(data).hexdigest() == assets[Path(image["src"]).name]["sha256"]
        svg = ET.fromstring(data)
        assert svg.attrib["height"] == "20"
        assert float(svg.attrib["width"]) <= 250
        for element in svg.iter():
            assert element.tag.rsplit("}", 1)[-1] not in {"script", "foreignObject", "iframe", "image"}
            assert not any(name.lower().startswith("on") for name in element.attrib)
