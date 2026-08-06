from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("PORTAIL_CONFIG", "/etc/portail-entraide-opel-gt/config.json"))
SERVICES = (
    "portail-entraide-opel-gt-web.service",
    "portail-entraide-opel-gt-ocr-worker.service",
    "portail-entraide-opel-gt-catalog-worker.service",
)
RUN_SERVER = Path("/opt/portail-entraide-opel-gt/run_server.sh")
MAX_CONFIG_BYTES = 512 * 1024


def response(ok: bool, message: str) -> dict[str, Any]:
    return {"ok": ok, "message": message}


def schedule(action: str) -> dict[str, Any]:
    if action not in {"restart", "stop", "apply-config"}:
        return response(False, "Action système non autorisée.")
    systemd_run = shutil.which("systemd-run")
    systemctl = shutil.which("systemctl")
    if not systemd_run or not systemctl:
        return response(False, "systemd-run ou systemctl est introuvable.")
    unit = f"portail-opel-gt-admin-{action}-{uuid.uuid4().hex[:10]}"
    if action == "apply-config":
        command = [
            systemd_run, "--quiet", "--collect", f"--unit={unit}", "--on-active=2s",
            "--property=Type=oneshot", str(RUN_SERVER), "apply-config",
        ]
        success_message = "Application de la configuration et redémarrage du portail planifiés dans 2 secondes."
    else:
        command = [
            systemd_run, "--quiet", "--collect", f"--unit={unit}", "--on-active=2s",
            "--property=Type=oneshot", systemctl, "--no-block", action, *SERVICES,
        ]
        success_message = f"{'Redémarrage' if action == 'restart' else 'Arrêt'} du portail planifié dans 2 secondes."
    done = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    if done.returncode:
        return response(False, (done.stderr or done.stdout or "Action systemd impossible.").strip())
    return response(True, success_message)


def save_config(content: Any) -> dict[str, Any]:
    if not isinstance(content, str) or not content:
        return response(False, "Le contenu de configuration est vide.")
    if len(content.encode("utf-8")) > MAX_CONFIG_BYTES:
        return response(False, "Le fichier de configuration dépasse 512 Kio.")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return response(False, f"JSON invalide : {exc}")
    if not isinstance(payload, dict):
        return response(False, "La configuration doit être un objet JSON.")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    formatted = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=CONFIG_PATH.parent, prefix=".config.", suffix=".tmp", delete=False) as temp:
            temp_name = temp.name
            temp.write(formatted)
            temp.flush()
            os.fsync(temp.fileno())
        temp_path = Path(temp_name)
        env = os.environ.copy()
        env["PORTAIL_CONFIG"] = str(temp_path)
        check = subprocess.run([sys.executable, "-m", "app.manage", "validate-config"], env=env, text=True, capture_output=True, timeout=15, check=False)
        if check.returncode:
            return response(False, (check.stderr or check.stdout or "Configuration invalide.").strip())
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, CONFIG_PATH)
        temp_name = None
    except Exception as exc:
        return response(False, f"Écriture de la configuration impossible : {exc}")
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink()
            except OSError:
                pass
    return response(True, "Configuration enregistrée. Utilisez « Appliquer et redémarrer » pour activer les nouveaux réglages.")


def handle(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return response(False, "Requête JSON invalide.")
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
        return response(False, "Requête invalide.")
    action = payload["action"].strip().lower()
    if action in {"restart", "stop", "apply-config"}:
        return schedule(action)
    if action == "save-config":
        return save_config(payload.get("content"))
    return response(False, "Action non autorisée.")


def main() -> int:
    raw = sys.stdin.readline(MAX_CONFIG_BYTES + 8192)
    sys.stdout.write(json.dumps(handle(raw), ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
