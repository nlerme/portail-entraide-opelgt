from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent / ".runtime"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
TEST_ROOT.mkdir(parents=True)
CONFIG = Path(__file__).resolve().parents[1] / "config.example.json"
SECRETS = TEST_ROOT / "secrets.json"
SECRETS.write_text(json.dumps({"app_secret": "test-secret", "admin_password_hash": ""}), encoding="utf-8")
os.environ["PORTAIL_CONFIG"] = str(CONFIG)
os.environ["PORTAIL_SECRETS"] = str(SECRETS)
os.environ["PORTAIL_DATA_DIR"] = str(TEST_ROOT / "data")
