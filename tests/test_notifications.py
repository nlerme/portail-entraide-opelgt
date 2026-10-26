from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
import requests

from app import notifications as n
from app.common import ntfy_setup as setup


@pytest.fixture
def config(tmp_path, monkeypatch):
    secret = tmp_path / "secrets.json"
    secret.write_text(
        json.dumps(
            {
                "ntfy": {
                    "enabled": True,
                    "server": "https://ntfy.example",
                    "topic": "test-topic",
                    "auth": "token",
                    "token": "TEST_TOKEN",
                }
            }
        )
    )
    monkeypatch.setattr(n, "SECRETS_PATH", secret)
    monkeypatch.setattr(n, "data_root", lambda: tmp_path / "data")
    return tmp_path


def test_offline_incident_survives_restarts_and_delivers_then_recovers(config, monkeypatch):
    monkeypatch.setattr(n, "observations", lambda online: {"internet": (online, "Connexion Internet")})
    monkeypatch.setattr(n, "internet_available", lambda: False)
    delivered = []
    monkeypatch.setattr(n, "publish", lambda cfg, event: delivered.append(event) or True)
    assert n.run() == 0 and n.run() == 0 and not delivered
    state_path = config / "data/notifications/state.json"
    state = json.loads(state_path.read_text())
    assert len(state["pending"]) == 1 and state["incidents"]["internet"]["active"]
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert "TEST_TOKEN" not in state_path.read_text()
    monkeypatch.setattr(n, "internet_available", lambda: True)
    assert n.run() == 0 and len(delivered) == 1
    assert "problème détecté" in delivered[0]["message"] and "rétabli" in delivered[0]["message"]
    assert n.run() == 0 and len(delivered) == 1
    assert not json.loads(state_path.read_text())["pending"]


def test_failed_delivery_is_retained_and_acknowledged_only_after_success(config, monkeypatch):
    monkeypatch.setattr(n, "publish", lambda cfg, event: False)
    assert n.run(test=True) == 1
    path = config / "data/notifications/state.json"
    assert len(json.loads(path.read_text())["pending"]) == 1
    monkeypatch.setattr(n, "internet_available", lambda: True)
    monkeypatch.setattr(n, "observations", lambda online: {})
    monkeypatch.setattr(n, "publish", lambda cfg, event: True)
    assert n.run() == 0 and not json.loads(path.read_text())["pending"]


def test_source_failures_emit_once_and_pending_update_does_not_fake_recovery():
    state = {}
    n.transition(state, {"catalogue:gt": (False, "Catalogue GT Teile")}, "2026-10-23T02:00:00+00:00")
    n.transition(state, {"catalogue:gt": (False, "Catalogue GT Teile")}, "later")
    n.transition(state, {"catalogue:gt": (None, "Catalogue GT Teile")}, "updating")
    assert len(state["pending"]) == 1
    n.transition(state, {"catalogue:gt": (True, "Catalogue GT Teile")}, "recovered")
    assert len(state["pending"]) == 2 and not state["incidents"]["catalogue:gt"]["active"]


@pytest.mark.parametrize("mode", ["token", "basic", "none"])
def test_ntfy_json_auth_headers_unicode_and_no_redirect(monkeypatch, mode):
    settings = {
        "enabled": True,
        "server": "https://ntfy.example",
        "topic": "test",
        "auth": mode,
        "token": "SECRET",
        "username": "user",
        "password": "PASSWORD",
    }
    calls = []

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(n.requests, "post", post)
    event = {"title": "Échec du catalogue", "message": "Réessayer", "priority": 4}
    assert n.publish(settings, event)
    url, kwargs = calls[0]
    assert url == "https://ntfy.example/" and not kwargs["allow_redirects"]
    assert kwargs["json"]["topic"] == "test" and kwargs["json"]["title"] == event["title"]
    expected = {"token": "Bearer SECRET", "basic": "Basic " + base64.b64encode(b"user:PASSWORD").decode()}
    assert kwargs["headers"] == ({"Authorization": expected[mode]} if mode != "none" else {})
    assert kwargs["auth"] is None


def test_delivery_error_does_not_log_credentials(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("SECRET username PASSWORD private-topic")

    monkeypatch.setattr(n.requests, "post", fail)
    settings = {"server": "https://ntfy.example", "topic": "private-topic", "auth": "token", "token": "SECRET"}
    assert not n.publish(settings, {"title": "Test", "message": "Message"})
    assert all(value not in caplog.text for value in ("SECRET", "PASSWORD", "private-topic"))


def test_monitor_reads_catalogue_and_announcement_failures(config, monkeypatch):
    data = config / "data"
    (data / "pieces/catalogues").mkdir(parents=True)
    (data / "pieces/catalogues/sync_status.json").write_text(
        json.dumps({"suppliers": [{"site_id": "pro_gt", "site_name": "GT Teile", "status": "failed"}]})
    )
    (data / "annonces").mkdir()
    (data / "annonces/leboncoin.json").write_text(json.dumps({"status": "restricted"}))
    units = config / "units"
    (units / "cloudflared.service.d").mkdir(parents=True)
    (units / "cloudflared.service.d" / f"{n.APP}.conf").write_text("managed")
    monkeypatch.setenv("PORTAIL_SYSTEMD_UNIT_DIR", str(units))
    monkeypatch.setattr(n, "probe", lambda *args, **kwargs: False)
    monkeypatch.setattr(n, "active", lambda unit: unit != "cloudflared.service")
    monkeypatch.setattr(n.shutil, "which", lambda _: True)
    checks = n.observations(True)
    assert checks["cloudflare"][0] is False and checks["web"][0] is False
    assert checks["catalogue:pro_gt"][0] is False and checks["annonces:leboncoin"][0] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"server": "http://ntfy.example"},
        {"server": "https://user:pass@ntfy.example"},
        {"server": "https://ntfy.example/?token=secret"},
        {"topic": "bad/topic"},
        {"token": "bad\nvalue"},
        {"auth": "unknown"},
    ],
)
def test_installer_rejects_invalid_or_unsafe_destination(changes):
    with pytest.raises(ValueError):
        setup.validate(
            {
                **{
                    "enabled": True,
                    "server": "https://ntfy.example",
                    "topic": "test",
                    "auth": "token",
                    "token": "TEST",
                },
                **changes,
            }
        )


def test_installer_masks_token_and_preserves_other_secrets(tmp_path, monkeypatch, capsys):
    answers = iter(["", "https://ntfy.example", "test-topic", "j"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: "NEVER_ECHO_THIS")
    settings = setup.prompt({})
    assert settings["token"] == "NEVER_ECHO_THIS" and "NEVER_ECHO_THIS" not in capsys.readouterr().out
    staged, secrets = tmp_path / "staged.json", tmp_path / "secrets.json"
    setup.atomic_write(staged, settings, 0o600)
    secrets.write_text(json.dumps({"app_secret": "KEEP", "admin_password_hash": "HASH"}))
    monkeypatch.setattr(sys, "argv", ["ntfy_setup.py", "apply", str(staged), str(secrets)])
    assert setup.main() == 0 and not staged.exists()
    value = json.loads(secrets.read_text())
    assert value["app_secret"] == "KEEP" and value["admin_password_hash"] == "HASH"
    assert secrets.stat().st_mode & 0o777 == 0o640
    assert setup.validate({"enabled": False, "token": "REMOVE"}) == {"enabled": False, "interval_days": 1}


def test_units_monitor_independently_and_install_prompts_before_deploy():
    root = Path(__file__).resolve().parents[1]
    unit = (root / "systemd" / f"{n.APP}-notifications.service").read_text()
    timer = (root / "systemd" / f"{n.APP}-notifications.timer").read_text()
    script = (root / "run_server.sh").read_text()
    assert "Requires=" not in unit and "BindsTo=" not in unit
    assert "User=opelgt" in unit and "-m app.notifications" in unit
    assert "OnUnitInactiveSec=60s" in timer
    install = script.split("install_command() {", 1)[1].split("print_access() {", 1)[0]
    assert install.index('ntfy_setup.py" prompt') < install.index("install_packages")
    uninstall = script.split("uninstall_command() {", 1)[1].split("system_update_execute_command()", 1)[0]
    assert uninstall.index('-notifications.service"') < uninstall.index('safe_remove_tree "$CONFIG_DIR"')
