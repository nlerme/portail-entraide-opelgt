from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = "portail-entraide-opel-gt"


def _function(name: str, following: str) -> str:
    script = (ROOT / "run_server.sh").read_text()
    return script[script.index(f"{name}() {{"):script.index(f"\n{following}() {{")]


@pytest.fixture
def monitor(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    units = tmp_path / "units"
    dropin = units / "cloudflared.service.d" / f"{APP}.conf"
    dropin.parent.mkdir(parents=True)
    dropin.write_text("managed")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server": {"port": 8080}}))
    command_log = tmp_path / "commands.txt"
    curl_log = tmp_path / "probes.txt"
    (fakebin / "systemctl").write_text("""#!/bin/sh
printf '%s\n' "$*" >> "$COMMAND_LOG"
case "$1" in
  is-active)
    case "$*" in
      *-web.service) test "${WEB_STATE:-active}" = active ;;
      *) test "${TUNNEL_STATE:-active}" = active ;;
    esac ;;
  is-failed) test "${TUNNEL_STATE:-active}" = failed ;;
  *) exit 0 ;;
esac
""")
    (fakebin / "curl").write_text("""#!/bin/sh
printf '%s\n' "$*" >> "$CURL_LOG"
case "$*" in
  */api/health) test "$PROBE_MODE" != origin ;;
  */ready) test "$PROBE_MODE" != tunnel ;;
  *) exit 1 ;;
esac
""")
    for path in fakebin.iterdir():
        path.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fakebin}:{os.environ['PATH']}", "COMMAND_LOG": str(command_log), "CURL_LOG": str(curl_log),
    }
    shell = (
        "set -Eeuo pipefail\n"
        f"APP_NAME={APP}\nSYSTEMD_UNIT_DIR={shlex.quote(str(units))}\n"
        f"RUN_DIR={shlex.quote(str(tmp_path / 'run'))}\nCONFIG_FILE={shlex.quote(str(config))}\n"
        "require_root(){ :; }; require_systemd(){ :; }; warn(){ :; }\n"
        + _function("cloudflare_health_command", "run_as_service") + "\ncloudflare_health_command\n"
    )

    def run(mode="healthy", **states):
        subprocess.run(["bash", "-c", shell], env=env | {"PROBE_MODE": mode} | states, check=True, capture_output=True)
        return command_log.read_text().splitlines()

    return run, tmp_path / "run/cloudflare-health.failures", curl_log


def test_tunnel_is_reconnected_after_three_failed_probes_without_local_visits(monitor):
    run, state, curl_log = monitor
    assert "restart cloudflared.service" not in run("tunnel")
    assert "restart cloudflared.service" not in run("tunnel")
    calls = run("tunnel")
    assert calls.count("restart cloudflared.service") == 1
    assert not state.exists()
    probes = curl_log.read_text()
    assert probes.count("/api/health") == 3
    assert probes.count("/ready") == 3
    assert "--noproxy *" in probes
    assert "--max-time 5" in probes


def test_healthy_tunnel_resets_consecutive_failure_count(monitor):
    run, state, _ = monitor
    run("tunnel")
    run("tunnel")
    assert "restart cloudflared.service" not in run()
    assert not state.exists()
    assert "restart cloudflared.service" not in run("tunnel")


def test_origin_failure_recovers_only_the_web_service(monitor):
    run, state, curl_log = monitor
    for _ in range(2):
        run("origin")
    calls = run("origin")
    assert calls.count(f"restart {APP}-web.service") == 1
    assert "restart cloudflared.service" not in calls
    assert "/ready" not in curl_log.read_text()
    assert not state.exists()


@pytest.mark.parametrize("states", [{"WEB_STATE": "inactive"}, {"TUNNEL_STATE": "inactive"}])
def test_deliberately_stopped_services_are_not_restarted(monitor, states):
    run, _, curl_log = monitor
    for _ in range(3):
        calls = run("tunnel", **states)
    assert not any(call.startswith("restart ") for call in calls)
    assert not curl_log.exists()


def test_failed_connector_can_be_recovered(monitor):
    run, _, _ = monitor
    for _ in range(3):
        calls = run("tunnel", TUNNEL_STATE="failed")
    assert calls.count("restart cloudflared.service") == 1


@pytest.mark.parametrize("requested, managed", [(1, False), (0, True), (0, False)])
def test_installer_adds_monitor_only_for_a_managed_tunnel(tmp_path, requested, managed):
    units = tmp_path / "units"
    dropin = units / "cloudflared.service.d" / f"{APP}.conf"
    if managed:
        dropin.parent.mkdir(parents=True)
        dropin.write_text("old")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server": {"port": 8080}}))
    log = tmp_path / "commands.txt"
    shell = (
        "set -Eeuo pipefail\n"
        f"APP_NAME={APP}\nINSTALL_DIR={shlex.quote(str(ROOT))}\nSYSTEMD_UNIT_DIR={shlex.quote(str(units))}\n"
        f"CONFIG_FILE={shlex.quote(str(config))}\nCALL_LOG={shlex.quote(str(log))}\n"
        f"CLOUDFLARE_TUNNEL_REQUESTED={requested}\nCLOUDFLARE_TUNNEL_TOKEN=eyJtest-sentinel\n"
        "warn(){ :; }; ok(){ :; }\n"
        "systemctl(){ printf '%s\\n' \"systemctl $*\" >> \"$CALL_LOG\"; }\n"
        "cloudflared(){ printf '%s\\n' \"cloudflared $1 $2\" >> \"$CALL_LOG\"; }\n"
        + _function("configure_cloudflare_tunnel", "cloudflare_health_command")
        + "\nconfigure_cloudflare_tunnel\n"
    )
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True)
    if requested or managed:
        content = dropin.read_text()
        assert "TUNNEL_TRANSPORT_PROTOCOL=http2" in content
        assert "TUNNEL_METRICS=127.0.0.1:20241" in content
        assert "Restart=always" in content
        assert "eyJtest-sentinel" not in content
        commands = log.read_text()
        assert f"enable --now {APP}-cloudflare-health.timer" in commands
        assert "restart cloudflared.service" in commands
        assert ("cloudflared service install" in commands) is bool(requested)
    else:
        assert not dropin.exists()
        assert not log.exists()
