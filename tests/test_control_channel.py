from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

import pytest

import server_control
from app.common import control_client


def serve_once(path: Path, response: dict) -> threading.Thread:
    ready = threading.Event()

    def target():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            os.chmod(path, 0o660)
            server.listen(1)
            ready.set()
            conn, _ = server.accept()
            with conn:
                received = b""
                while not received.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    received += chunk
                assert json.loads(received)["action"] in {"restart", "stop", "apply-config", "save-config"}
                conn.sendall(json.dumps(response).encode("utf-8") + b"\n")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    assert ready.wait(2)
    return thread


def test_control_socket_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "control.sock"
    thread = serve_once(path, {"ok": True, "message": "Redémarrage planifié."})
    monkeypatch.setenv("PORTAIL_CONTROL_SOCKET", str(path))
    result = control_client.request_system_action("restart")
    thread.join(2)
    assert result["ok"] is True


def test_privileged_helper_dispatches_apply_config(monkeypatch):
    observed = []
    monkeypatch.setattr(server_control, "schedule", lambda action: observed.append(action) or {"ok": True})
    result = server_control.handle(json.dumps({"action": "apply-config"}))
    assert result["ok"] is True
    assert observed == ["apply-config"]


def test_apply_config_control_socket_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "control.sock"
    thread = serve_once(path, {"ok": True, "message": "Configuration appliquée."})
    monkeypatch.setenv("PORTAIL_CONTROL_SOCKET", str(path))
    result = control_client.request_system_action("apply-config")
    thread.join(2)
    assert result["ok"] is True


def test_control_socket_rejects_unknown_action():
    with pytest.raises(ValueError):
        control_client.request_system_action("shell")


def test_control_socket_reports_permission_or_missing_channel(tmp_path, monkeypatch):
    path = tmp_path / "missing.sock"
    monkeypatch.setenv("PORTAIL_CONTROL_SOCKET", str(path))
    with pytest.raises(control_client.ControlChannelError) as caught:
        control_client.request_system_action("stop", timeout=0.1)
    assert str(path) in str(caught.value)
