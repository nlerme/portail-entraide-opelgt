from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = "portail-entraide-opel-gt"


@pytest.fixture
def installation(tmp_path):
    units = tmp_path / "units"
    dropin = units / "cloudflared.service.d" / f"{APP}.conf"
    dropin.parent.mkdir(parents=True)
    dropin.write_text("managed")
    unrelated = dropin.with_name("other.conf")
    unrelated.write_text("unrelated configuration")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({name: {"active": True, "enabled": True} for name in (
        "cloudflared.service", f"{APP}-cloudflare-health.timer", f"{APP}-cloudflare-health.service",
        f"{APP}-notifications.timer", f"{APP}-notifications.service",
    )}))
    log = tmp_path / "commands.jsonl"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    systemctl = fakebin / "systemctl"
    systemctl.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
path = Path(os.environ['TEST_UNIT_STATE'])
data = json.loads(path.read_text())
args = sys.argv[1:]
with open(os.environ['TEST_UNIT_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[0] == 'disable':
    for unit in args[2:]:
        if unit == os.getenv('TEST_FAIL_UNIT'):
            sys.exit(1)
        if unit in data:
            data[unit] = {'active': False, 'enabled': False}
    path.write_text(json.dumps(data))
elif args[0] in ('is-active', 'is-enabled'):
    key = 'active' if args[0] == 'is-active' else 'enabled'
    sys.exit(0 if data.get(args[-1], {}).get(key, False) else 1)
''')
    systemctl.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "TEST_UNIT_STATE": str(state), "TEST_UNIT_LOG": str(log),
        "PORTAIL_SYSTEMD_UNIT_DIR": str(units),
        "PORTAIL_SERVICE_USER": "portail-test-user-does-not-exist",
        "PORTAIL_SERVICE_GROUP": "portail-test-group-does-not-exist",
    }
    for key in ("INSTALL", "CONFIG", "DATA", "RUN", "TMPFILES", "LOG"):
        path = tmp_path / key.lower()
        path.mkdir()
        env[f"PORTAIL_{key}_DIR"] = str(path)

    def run(purge=True, fail_unit=""):
        return subprocess.run(
            ["bash", str(ROOT / "run_server.sh"), "uninstall", *(["--purge"] if purge else [])],
            env=env | {"TEST_FAIL_UNIT": fail_unit}, capture_output=True, text=True,
        )

    return run, state, log, dropin, unrelated


@pytest.mark.parametrize("legacy", [False, True])
def test_purge_stops_monitor_before_connector_and_disables_legacy_service(installation, legacy):
    run, state, log, dropin, unrelated = installation
    if legacy:
        dropin.unlink()
    result = run()
    assert result.returncode == 0, result.stderr
    assert all(not value["active"] and not value["enabled"] for value in json.loads(state.read_text()).values())
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    ordered = [commands.index(["disable", "--now", unit]) for unit in (
        f"{APP}-cloudflare-health.timer", f"{APP}-cloudflare-health.service", "cloudflared.service",
    )]
    assert ordered == sorted(ordered)
    assert not dropin.exists()
    assert unrelated.read_text() == "unrelated configuration"
    assert run().returncode == 0


@pytest.mark.parametrize("managed", [False, True])
def test_plain_uninstall_stops_only_the_managed_connector(installation, managed):
    run, state, _, dropin, _ = installation
    if not managed:
        dropin.unlink()
    assert run(purge=False).returncode == 0
    assert json.loads(state.read_text())["cloudflared.service"]["active"] is (not managed)


@pytest.mark.parametrize("unit", ["cloudflared.service", f"{APP}-cloudflare-health.timer"])
def test_failed_stop_aborts_before_purge_and_keeps_management_marker(installation, unit):
    run, state, _, dropin, _ = installation
    result = run(fail_unit=unit)
    assert result.returncode != 0
    assert unit in result.stderr and "désinstallation interrompue" in result.stderr
    assert json.loads(state.read_text())[unit]["active"]
    assert dropin.exists()


def test_failed_disable_is_reported_even_when_the_connector_has_already_stopped(installation):
    run, state, _, dropin, _ = installation
    data = json.loads(state.read_text())
    data["cloudflared.service"] = {"active": False, "enabled": True}
    state.write_text(json.dumps(data))
    assert run(fail_unit="cloudflared.service").returncode != 0
    assert dropin.exists()


def test_missing_legacy_service_allows_purge_even_if_disable_returns_an_error(installation):
    run, state, _, dropin, _ = installation
    state.write_text("{}")
    result = run(fail_unit="cloudflared.service")
    assert result.returncode == 0, result.stderr
    assert not dropin.exists()


def test_purge_removes_ntfy_credentials_and_pending_messages(installation):
    run, state, _, _, _ = installation
    config = state.parent / "config" / "secrets.json"
    pending = state.parent / "data" / "notifications" / "state.json"
    config.write_text(json.dumps({"ntfy": {"token": "TEST_TOKEN", "password": "TEST_PASSWORD"}}))
    pending.parent.mkdir()
    pending.write_text(json.dumps({"pending": [{"message": "Test incident"}]}))
    assert run().returncode == 0
    assert not config.exists() and not pending.exists()


def test_plain_uninstall_keeps_ntfy_settings_for_reinstallation(installation):
    run, state, _, _, _ = installation
    config = state.parent / "config" / "secrets.json"
    config.write_text(json.dumps({"ntfy": {"token": "TEST_TOKEN"}}))
    assert run(purge=False).returncode == 0
    assert json.loads(config.read_text())["ntfy"]["token"] == "TEST_TOKEN"
