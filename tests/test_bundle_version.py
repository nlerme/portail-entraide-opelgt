from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from app.common.config import DEFAULTS
from app.common.version import VERSION
from app.pieces.config import Settings
from app.pieces.services.catalogs import MODULE_BY_SITE_ID

ROOT = Path(__file__).resolve().parents[1]


def test_current_bundle_version_matches_metadata_defaults_and_static_resources():
    assert VERSION == (ROOT / "VERSION").read_text().strip()
    assert VERSION == tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
    example = json.loads((ROOT / "config.example.json").read_text())
    agents = re.findall(r"PortailEntraideOpelGT/([\d.]+)", json.dumps(example) + json.dumps(DEFAULTS) + Settings().user_agent)
    assert agents and set(agents) == {VERSION}
    for page in (ROOT / "static").rglob("*.html"):
        versions = re.findall(r"[?&]v=([^\s\"'&<>]+)", page.read_text())
        assert versions and set(versions) == {VERSION}, page
    readme = (ROOT / "README.md").read_text()
    assert f"**Version {VERSION} — Linux serveur**" in readme
    assert f"portail-entraide-opelgt-{VERSION}.zip" in readme
    header = subprocess.run(
        ["bash", str(ROOT / "run_server.sh"), "--help"], env=os.environ | {"NO_COLOR": "1"},
        check=True, capture_output=True, text=True,
    ).stdout
    assert f"version {VERSION}" in header


@pytest.mark.parametrize("module", MODULE_BY_SITE_ID.values())
def test_every_scraper_cli_exposes_the_bundle_version(module):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scrapers" / f"{module}.py"), "--version"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    assert VERSION in result.stdout
    assert re.findall(r"\b\d+\.\d+\.\d+\b", result.stdout) == [VERSION]
