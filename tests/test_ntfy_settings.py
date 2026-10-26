from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import server_control
from app import main
from app import notifications as n
from app.common import auth, control_client
from app.common.ntfy_settings import public_settings, save_settings, updated_settings


def configuration(**changes):
    return {
        **dict(
            enabled=True,
            server="https://ntfy.example",
            topic="test-topic",
            auth="token",
            token="TEST_SECRET_TOKEN",
            interval_days=1,
        ),
        **changes,
    }


@pytest.fixture
def secrets(tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text(
        json.dumps({"app_secret": "KEEP_APP_SECRET", "admin_password_hash": "KEEP_HASH", "ntfy": configuration()})
    )
    path.chmod(0o640)
    return path


@pytest.mark.parametrize("value", [0, -1, True, 0.5, "1", 366])
def test_notification_frequency_never_exceeds_one_per_day(value):
    with pytest.raises(ValueError):
        updated_settings(configuration(), {"interval_days": value})


def test_secret_replacement_preservation_auth_switch_and_public_metadata(secrets):
    before = secrets.stat()
    result = save_settings(secrets, {"interval_days": 7, "token": ""})
    assert result["settings"]["has_token"] and result["settings"]["interval_days"] == 7
    assert "TEST_SECRET_TOKEN" not in json.dumps(result)
    saved = json.loads(secrets.read_text())
    assert saved["app_secret"] == "KEEP_APP_SECRET" and saved["admin_password_hash"] == "KEEP_HASH"
    assert saved["ntfy"]["token"] == "TEST_SECRET_TOKEN"
    assert secrets.stat().st_mode & 0o777 == 0o640
    assert (secrets.stat().st_uid, secrets.stat().st_gid) == (before.st_uid, before.st_gid)
    save_settings(secrets, {"auth": "basic", "username": "user", "password": "TEST_PASSWORD"})
    settings = json.loads(secrets.read_text())["ntfy"]
    assert "token" not in settings and settings["password"] == "TEST_PASSWORD"
    save_settings(secrets, {"password": "", "interval_days": 2})
    assert json.loads(secrets.read_text())["ntfy"]["password"] == "TEST_PASSWORD"
    save_settings(secrets, {"enabled": False})
    assert json.loads(secrets.read_text())["ntfy"] == {"enabled": False, "interval_days": 2}


def test_privileged_helper_accepts_only_ntfy_settings_and_preserves_other_secrets(secrets, monkeypatch):
    monkeypatch.setattr(server_control, "SECRETS_PATH", secrets)
    result = server_control.handle(json.dumps({"action": "save-ntfy", "settings": {"token": "NEW_TEST_TOKEN"}}))
    assert result["ok"] and "NEW_TEST_TOKEN" not in json.dumps(result)
    original = secrets.read_bytes()
    for patch in [{"app_secret": "EVIL"}, {"interval_days": 0}, {"password": {"bad": "TEST_SECRET"}}, None]:
        result = server_control.handle(json.dumps({"action": "save-ntfy", "settings": patch}))
        assert result["ok"] is False and secrets.read_bytes() == original
        assert "TEST_SECRET" not in json.dumps(result)


def test_daily_batch_survives_restart_does_not_drop_delayed_events(secrets, tmp_path, monkeypatch):
    clock = [datetime(2026, 10, 23, 6, tzinfo=timezone.utc)]
    monkeypatch.setattr(n, "now", lambda: clock[0].isoformat())
    monkeypatch.setattr(n, "SECRETS_PATH", secrets)
    monkeypatch.setattr(n, "data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(n, "internet_available", lambda: True)
    checks = {"catalogue:gt": (False, "Catalogue GT Teile"), "annonces:lbc": (False, "Collecte Leboncoin")}
    monkeypatch.setattr(n, "observations", lambda online: checks.copy())
    delivered = []
    monkeypatch.setattr(n, "publish", lambda settings, event: delivered.append(event) or True)
    assert n.run() == 0 and len(delivered) == 1
    assert "Catalogue GT Teile" in delivered[0]["message"] and "Collecte Leboncoin" in delivered[0]["message"]
    checks["catalogue:gt"] = (True, "Catalogue GT Teile")
    clock[0] += timedelta(hours=23, minutes=59, seconds=59)
    assert n.run() == 0 and len(delivered) == 1
    path = tmp_path / "data/notifications/state.json"
    assert len(json.loads(path.read_text())["pending"]) == 1
    clock[0] += timedelta(seconds=1)
    assert n.run() == 0 and len(delivered) == 2
    assert "rétabli" in delivered[1]["message"]
    assert not json.loads(path.read_text())["pending"]
    assert n.run(test=True) == 1 and len(delivered) == 2  # Test sends obey the same cap.
    save_settings(secrets, {"interval_days": 3})
    clock[0] += timedelta(days=2)
    assert n.run() == 0 and len(delivered) == 2
    clock[0] += timedelta(days=1)
    assert n.run() == 0 and len(delivered) == 3


def test_long_batches_remain_within_ntfy_limit_and_leave_unsent_entries():
    events = [{"title": "Incident", "message": f"{i} " + ("Échec de source. " * 25), "priority": 4} for i in range(100)]
    event, count = n.notification_batch(events)
    assert 0 < count < len(events) and len(event["message"].encode("utf-8")) < 4096
    assert events[count:] and "événements" in event["title"]


@pytest.fixture
def client(secrets, monkeypatch):
    monkeypatch.setattr(main, "SECRETS_PATH", secrets)
    monkeypatch.setattr(main, "verify_admin_password", lambda _: True)
    auth._ATTEMPTS.clear()
    with TestClient(main.app) as value:
        yield value
    auth._ATTEMPTS.clear()


def login(client):
    result = client.post("/api/admin/login", json={"username": "admin", "password": "Admin!Test12345"})
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json()["csrfToken"]}


def test_ntfy_api_admin_csrf_secrets_and_effective_update(client, secrets):
    assert client.get("/api/admin/ntfy").status_code == 401
    assert client.put("/api/admin/ntfy", json={"token": "NEW"}).status_code == 401
    headers = login(client)
    result = client.get("/api/admin/ntfy")
    assert result.status_code == 200 and result.json()["has_token"]
    assert "TEST_SECRET_TOKEN" not in result.text and "no-store" in result.headers["cache-control"]
    assert client.put("/api/admin/ntfy", json={"interval_days": 2}).status_code == 403
    result = client.put("/api/admin/ntfy", headers=headers, json={"token": "NEW_TEST_TOKEN", "interval_days": 2})
    assert result.status_code == 200 and result.json()["settings"]["interval_days"] == 2
    assert "NEW_TEST_TOKEN" not in result.text
    assert json.loads(secrets.read_text())["ntfy"]["token"] == "NEW_TEST_TOKEN"
    result = client.put("/api/admin/ntfy", headers=headers, json={"interval_days": 7})
    assert result.status_code == 200 and json.loads(secrets.read_text())["ntfy"]["token"] == "NEW_TEST_TOKEN"
    for body in [{"token": "MUST_NOT_ECHO", "interval_days": 0}, ["MUST_NOT_ECHO"], {"app_secret": "MUST_NOT_ECHO"}]:
        result = client.put("/api/admin/ntfy", headers=headers, json=body)
        assert result.status_code == 400 and "MUST_NOT_ECHO" not in result.text
    assert json.loads(secrets.read_text())["app_secret"] == "KEEP_APP_SECRET"


def test_ntfy_api_uses_root_channel_when_secrets_are_read_only(client, monkeypatch):
    headers = login(client)
    calls = []
    monkeypatch.setattr(main.os, "access", lambda *args: False)
    monkeypatch.setattr(
        main,
        "request_ntfy_write",
        lambda patch: calls.append(patch) or {"ok": True, "settings": public_settings(configuration(interval_days=3))},
    )
    result = client.put("/api/admin/ntfy", headers=headers, json={"interval_days": 3})
    assert result.status_code == 200 and calls == [{"interval_days": 3}]


def test_sensitive_control_request_is_structured_and_error_does_not_echo(monkeypatch):
    sent = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, value):
            pass

        def connect(self, path):
            pass

        def sendall(self, value):
            sent.append(value)

        def shutdown(self, value):
            pass

        def recv(self, value):
            if len(sent) == 1:
                sent.append(b"ack")
                return b'{"ok":true}\n'
            return b""

    monkeypatch.setattr(control_client.socket, "socket", lambda *args: Socket())
    result = control_client.request_ntfy_write({"token": "TEST_TOKEN"})
    assert result["ok"]
    assert json.loads(sent[0]) == {"action": "save-ntfy", "settings": {"token": "TEST_TOKEN"}}

    def fail(*args):
        raise OSError("TEST_TOKEN")

    monkeypatch.setattr(control_client.socket, "socket", fail)
    with pytest.raises(control_client.ControlChannelError, match="Canal de contrôle") as error:
        control_client.request_ntfy_write({"token": "TEST_TOKEN"})
    assert "TEST_TOKEN" not in str(error.value)
