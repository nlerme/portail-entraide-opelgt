from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

DEFAULT_CONTROL_SOCKET = Path("/run/portail-entraide-opel-gt/control.sock")
_ALLOWED_ACTIONS = {"restart", "stop", "apply-config", "refresh-annonces"}
_MAX_RESPONSE = 65536


class ControlChannelError(RuntimeError):
    pass


def control_socket_path() -> Path:
    return Path(os.environ.get("PORTAIL_CONTROL_SOCKET", str(DEFAULT_CONTROL_SOCKET)))


def request_system_action(action: str, timeout: float = 3.0) -> dict[str, Any]:
    normalized = action.strip().lower()
    if normalized not in _ALLOWED_ACTIONS:
        raise ValueError(f"Action système non autorisée : {action}")
    path = control_socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(path))
            client.sendall(json.dumps({"action": normalized}).encode() + b"\n")
            client.shutdown(socket.SHUT_WR)
            chunks = []
            size = 0
            while size < _MAX_RESPONSE:
                chunk = client.recv(min(4096, _MAX_RESPONSE - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b"".join(chunks)
    except (OSError, TimeoutError) as exc:
        raise ControlChannelError(f"Canal de contrôle système indisponible ({path}) : {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ControlChannelError("Réponse invalide du canal de contrôle système.") from exc
    if not isinstance(payload, dict):
        raise ControlChannelError("Format de réponse inattendu du canal de contrôle système.")
    return payload


def request_config_write(content: str, timeout: float = 5.0) -> dict[str, Any]:
    if not isinstance(content, str) or not content:
        raise ValueError("Le contenu de configuration est vide.")
    if len(content.encode("utf-8")) > 512 * 1024:
        raise ValueError("Le fichier de configuration dépasse 512 Kio.")
    path = control_socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(path))
            client.sendall(json.dumps({"action": "save-config", "content": content}, ensure_ascii=False).encode("utf-8") + b"\n")
            client.shutdown(socket.SHUT_WR)
            raw = b""
            while len(raw) < _MAX_RESPONSE:
                chunk = client.recv(min(4096, _MAX_RESPONSE - len(raw)))
                if not chunk:
                    break
                raw += chunk
    except (OSError, TimeoutError) as exc:
        raise ControlChannelError(f"Canal de contrôle système indisponible ({path}) : {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ControlChannelError("Réponse invalide du canal de contrôle système.") from exc
    if not isinstance(payload, dict):
        raise ControlChannelError("Format de réponse inattendu du canal de contrôle système.")
    return payload


def request_ntfy_write(settings: dict, timeout: float = 5.0) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("Réglages ntfy invalides.")
    raw = json.dumps({"action": "save-ntfy", "settings": settings}, ensure_ascii=False).encode("utf-8") + b"\n"
    if len(raw) > 16384:
        raise ValueError("Les réglages ntfy dépassent 16 Kio.")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(control_socket_path()))
            client.sendall(raw)
            client.shutdown(socket.SHUT_WR)
            answer = b""
            while len(answer) < _MAX_RESPONSE:
                chunk = client.recv(min(4096, _MAX_RESPONSE - len(answer)))
                if not chunk:
                    break
                answer += chunk
    except (OSError, TimeoutError) as exc:
        raise ControlChannelError("Canal de contrôle indisponible pour les réglages ntfy.") from exc
    try:
        result = json.loads(answer)
    except (ValueError, UnicodeError) as exc:
        raise ControlChannelError("Réponse ntfy invalide du canal de contrôle.") from exc
    if not isinstance(result, dict):
        raise ControlChannelError("Format de réponse ntfy inattendu.")
    return result
