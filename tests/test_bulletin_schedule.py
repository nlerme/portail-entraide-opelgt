from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz
import pytest

from app import worker
from app.bulletins import maintenance, service
from app.bulletins.crawler import AuthenticationError, BulletinLink
from app.bulletins.database import connect, init_db
from app.common import bulletin_setup, jobs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def unattended(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "data_dir", tmp_path / "bulletins")
    monkeypatch.setattr(service.settings, "ocr_mode", "never")
    original_connect = jobs.connect
    monkeypatch.setattr(jobs, "connect", lambda path=None: original_connect(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(maintenance, "_lock_pid_matches_bundle", lambda pid: True)
    secret = tmp_path / "secrets.json"
    secret.write_text(json.dumps({"bulletins": {"username": "scheduled-member", "password": "TEST_ONLY_PASSWORD"}}))
    monkeypatch.setattr(service, "SECRETS_PATH", secret)
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 550, 700), "Opel GT bulletin: gearbox maintenance and engine lubrication. " * 10)
    pdf = document.tobytes()
    document.close()
    state = {"versions": {1: "v1", 2: "v1"}, "logins": 0, "downloads": [], "closed": 0, "pdf": pdf}

    class Crawler:
        def __init__(self, settings):
            self.session = self

        def close(self):
            state["closed"] += 1

        def login(self, username, password):
            assert (username, password) == ("scheduled-member", "TEST_ONLY_PASSWORD")
            state["logins"] += 1
            if state.get("hook"):
                state["hook"]()
            if state.get("refuse"):
                raise AuthenticationError("scheduled-member TEST_ONLY_PASSWORD must never be persisted")

        def discover_bulletins(self):
            return [BulletinLink(
                f"https://www.entraideopelgt.fr/{n}.pdf", f"Bulletin {n}", f"{n}.pdf", n, 2026, 1,
                verified=True, remote_etag=version, remote_content_length=len(pdf),
            ) for n, version in state["versions"].items()]

        def download_pdf(self, url, target):
            number = int(target.stem)
            state["downloads"].append(number)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pdf)
            return hashlib.sha256(pdf).hexdigest(), len(pdf), state["versions"][number], None

    monkeypatch.setattr(service, "EntraideCrawler", Crawler)
    return state


def test_initial_download_index_and_next_week_only_process_changed_or_new_bulletins(unattended):
    now = datetime.now(timezone.utc)
    assert service.synchronize(now) == 0  # No browser, login API or web application.
    assert unattended["logins"] == unattended["closed"] == 1
    assert unattended["downloads"] == [1, 2]
    for _ in range(2):
        assert worker.run("ocr", once=True) == 0
    with connect(service.settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bulletins WHERE indexed_at IS NOT NULL AND pages>0").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH 'gearbox'").fetchone()[0] == 2
    assert service.synchronize(now) == 0
    assert unattended["logins"] == 1 and len(jobs.list_jobs()) == 2
    with connect(service.settings.db_path) as conn:
        previous = service.latest_weekly_update(now) - timedelta(days=1)
        conn.execute("UPDATE sync_runs SET finished_at=?", (previous.isoformat(),))
    unattended["versions"].update({2: "v2", 3: "v1"})
    assert service.synchronize(now) == 0
    assert unattended["downloads"] == [1, 2, 2, 3]
    assert unattended["logins"] == unattended["closed"] == 2
    active = [job for job in jobs.list_jobs() if job["state"] == "pending"]
    assert len(active) == 2 and all(job["queue"] == "ocr" for job in active)
    for _ in active:
        assert worker.run("ocr", once=True) == 0
    with connect(service.settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bulletins WHERE indexed_at IS NOT NULL AND pages>0").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH 'gearbox'").fetchone()[0] == 3


def test_parallel_launch_is_coalesced_and_progress_is_visible_in_another_manager(unattended):
    def observe():
        assert service.synchronize() == 0
        state = maintenance.augment_sync_state(service.settings, {"running": False, "phase": "idle"})
        assert state["running"] and state["phase"] == "authentication"
    unattended["hook"] = observe
    assert service.synchronize() == 0
    assert unattended["logins"] == 1
    final = maintenance.augment_sync_state(service.settings, {"running": False})
    assert not final["running"] and final["phase"] == "finished"
    assert not maintenance.sync_lock_path(service.settings).exists()


def test_failed_authentication_does_not_store_credentials_and_can_be_retried(unattended, caplog):
    unattended["refuse"] = True
    assert service.synchronize() == 1
    assert not unattended["downloads"] and not jobs.list_jobs()
    saved = (service.settings.data_dir / "sync_state.json").read_text()
    assert '"phase": "error"' in saved
    for value in ("scheduled-member", "TEST_ONLY_PASSWORD"):
        assert value not in saved and value not in caplog.text
        with connect(service.settings.db_path) as conn:
            assert value not in conn.execute("SELECT message FROM sync_runs").fetchone()[0]
    unattended["refuse"] = False
    assert service.synchronize() == 0 and unattended["downloads"] == [1, 2]


def test_stale_external_progress_cannot_keep_the_service_locked(unattended):
    init_db(service.settings.db_path)
    state = service.settings.data_dir / "sync_state.json"
    state.write_text(json.dumps({"running": True, "phase": "download", "message": "old"}))
    result = maintenance.augment_sync_state(service.settings, {"running": False, "phase": "idle"})
    assert not result["running"] and result["phase"] == "idle"


@pytest.mark.parametrize(("now", "expected"), [
    ("2026-10-24T23:59:59+00:00", "2026-10-18T00:00:00+00:00"),
    ("2026-10-25T00:00:00+00:00", "2026-10-25T00:00:00+00:00"),
    ("2026-10-25T01:00:00+00:00", "2026-10-25T00:00:00+00:00"),
    ("2026-11-01T00:59:59+00:00", "2026-10-25T00:00:00+00:00"),
    ("2026-11-01T01:00:00+00:00", "2026-11-01T01:00:00+00:00"),
    ("2027-03-28T01:00:00+00:00", "2027-03-28T01:00:00+00:00"),
])
def test_sunday_two_oclock_is_computed_in_paris_including_clock_changes(now, expected):
    assert service.latest_weekly_update(datetime.fromisoformat(now)).astimezone(timezone.utc) == datetime.fromisoformat(expected)


def test_installer_launches_the_service_without_waiting_and_enables_the_weekly_timer(tmp_path):
    script = (ROOT / "run_server.sh").read_text()
    function = "enable_services() {" + script.split("enable_services() {", 1)[1].split("\nset_admin_password() {", 1)[0]
    command_log = tmp_path / "commands"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    command = fakebin / "systemctl"
    command.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n')
    command.chmod(0o755)
    subprocess.run(["bash", "-c", 'set -Eeuo pipefail\nAPP_NAME=portail-entraide-opel-gt\nUNITS=("${APP_NAME}-bulletins-update.timer")\n' + function + "\nenable_services"],
                   env=os.environ | {"PATH": f"{fakebin}:{os.environ['PATH']}", "COMMAND_LOG": str(command_log)}, check=True)
    calls = command_log.read_text().splitlines()
    assert "enable portail-entraide-opel-gt-bulletins-update.timer" in calls
    assert "start --no-block portail-entraide-opel-gt-bulletins-update.service" in calls
    timer = (ROOT / "systemd/portail-entraide-opel-gt-bulletins-update.timer").read_text()
    assert "OnCalendar=Sun *-*-* 02:00:00 Europe/Paris" in timer and "Persistent=true" in timer
    assert "OnCalendar=Sun *-03-25..31 03:00:00 Europe/Paris" in timer
    assert "python3 -m app.common.bulletin_setup prompt" in script
    assert '"${APP_NAME}-bulletins-update.service"' in script.split("uninstall_command()", 1)[1]


def test_setup_reuses_credentials_and_replaces_them_without_touching_other_secrets(tmp_path, monkeypatch, capsys):
    credentials = {"username": "member", "password": "TEST_PASSWORD"}
    monkeypatch.setattr("builtins.input", lambda label: "")
    assert bulletin_setup.prompt(credentials) == credentials
    staged, secret = tmp_path / "staged", tmp_path / "secrets.json"
    staged.write_text(json.dumps(credentials))
    others = {"app_secret": "existing", "admin_password_hash": "hash", "ntfy": {"token": "TEST_TOKEN"}}
    secret.write_text(json.dumps(others))
    monkeypatch.setattr(sys, "argv", ["bulletin_setup", "apply", str(staged), str(secret)])
    assert bulletin_setup.main() == 0
    assert json.loads(secret.read_text()) == others | {"bulletins": credentials}
    assert secret.stat().st_mode & 0o777 == 0o640 and not staged.exists()
    assert "TEST_PASSWORD" not in capsys.readouterr().out
    staged.write_text(json.dumps(credentials))
    result = subprocess.run(
        [sys.executable, "-S", "-m", "app.common.bulletin_setup", "apply", str(staged), str(secret)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0 and "TEST_PASSWORD" not in result.stdout + result.stderr


def test_setup_new_account_reads_the_password_only_through_getpass(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda label: "new-member")
    prompts = []
    def hidden(label):
        prompts.append(label)
        return "TEST_MASKED_PASSWORD"
    monkeypatch.setattr(bulletin_setup.getpass, "getpass", hidden)
    assert bulletin_setup.prompt({}) == {"username": "new-member", "password": "TEST_MASKED_PASSWORD"}
    assert len(prompts) == 2 and "masquée" in prompts[0]
    assert "TEST_MASKED_PASSWORD" not in capsys.readouterr().out


def test_background_service_pid_is_recognized_but_unrelated_reused_pid_is_rejected(monkeypatch):
    monkeypatch.setattr(maintenance, "_pid_cmdline", lambda pid: "/opt/portail/venv/bin/python -m app.bulletins.service")
    assert maintenance._lock_pid_matches_bundle(123)
    monkeypatch.setattr(maintenance, "_pid_cmdline", lambda pid: "/usr/bin/python unrelated.py")
    assert not maintenance._lock_pid_matches_bundle(123)
