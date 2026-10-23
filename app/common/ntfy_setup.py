"""Interactive installer, using only the system Python standard library."""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def validate(settings: dict) -> dict:
    if not isinstance(settings, dict):
        raise ValueError("Les réglages ntfy doivent être un objet JSON.")
    interval = settings.get("interval_days", 1)
    if type(interval) is not int or not 1 <= interval <= 365:
        raise ValueError("L'intervalle ntfy doit être un nombre entier de jours entre 1 et 365 (au maximum un envoi par jour).")
    if settings.get("enabled") is not True:
        return {"enabled": False, "interval_days": interval}
    server = str(settings.get("server", "")).strip().rstrip("/")
    try:
        parsed = urlsplit(server)
        valid = parsed.scheme == "https" and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Le serveur ntfy doit être une URL HTTPS sans identifiants ni paramètres.")
    topic = str(settings.get("topic", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic) or topic in {"app", "docs", "static", "file", "v1"}:
        raise ValueError("Le sujet ntfy doit contenir 1 à 64 lettres, chiffres, tirets ou soulignements.")
    mode = settings.get("auth", "none")
    if mode not in {"none", "token", "basic"}:
        raise ValueError("Authentification ntfy inconnue.")
    result = {"enabled": True, "server": server, "topic": topic, "auth": mode, "interval_days": interval}
    if mode == "token":
        token = str(settings.get("token", ""))
        if not token or any(c.isspace() for c in token):
            raise ValueError("Jeton ntfy vide ou invalide.")
        result["token"] = token
    elif mode == "basic":
        username, password = str(settings.get("username", "")), str(settings.get("password", ""))
        if not username or ":" in username or not password or any(c in username + password for c in "\r\n"):
            raise ValueError("Identifiants ntfy invalides.")
        result.update(username=username, password=password)
    return result


def read(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Le fichier de secrets doit contenir un objet JSON.")
    return data


def atomic_write(path: Path, value: dict, mode: int) -> None:
    ownership = path.stat() if path.exists() else None
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if ownership is not None and os.geteuid() == 0:
            os.chown(temporary, ownership.st_uid, ownership.st_gid)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prompt(existing: dict) -> dict:
    print("\nNotifications ntfy : alertes sur les incidents et les rétablissements.")
    if existing.get("enabled"):
        if input("Conserver la configuration ntfy existante ? [O/n] ").strip().lower() not in {"n", "non", "no"}:
            return validate(existing)
    if input("Activer les notifications ntfy ? [O/n] ").strip().lower() in {"n", "non", "no"}:
        return {"enabled": False}
    print("Abonnez l'application ntfy du téléphone au même serveur et au même sujet.")
    print("Sans authentification, choisissez un sujet long et imprévisible ; un sujet public n'est pas privé.")
    while True:
        settings = {
            "enabled": True,
            "server": input("Serveur ntfy [https://ntfy.sh] : ").strip() or "https://ntfy.sh",
            "topic": input("Sujet ntfy : ").strip(),
        }
        mode = input("Authentification : aucune, jeton ou mot de passe ? [aucune/j/m] : ").strip().lower()
        if mode in {"j", "jeton", "token"}:
            settings.update(auth="token", token=getpass.getpass("Jeton ntfy (saisie masquée) : "))
        elif mode in {"m", "mot de passe", "basic"}:
            settings.update(auth="basic", username=input("Utilisateur ntfy : ").strip(), password=getpass.getpass("Mot de passe ntfy (saisie masquée) : "))
        elif mode in {"", "aucune", "none"}:
            settings["auth"] = "none"
        else:
            print("Choisissez aucune, j ou m.")
            continue
        try:
            return validate(settings)
        except ValueError as exc:
            print(exc)


def main() -> int:
    action, staged_path, secrets_path = sys.argv[1:]
    staged, secrets = Path(staged_path), Path(secrets_path)
    if action == "prompt":
        if not sys.stdin.isatty():
            raise ValueError("L'installation nécessite un terminal interactif pour configurer ntfy.")
        atomic_write(staged, prompt(read(secrets).get("ntfy", {})), 0o600)
    elif action == "apply":
        payload = read(secrets)
        payload["ntfy"] = validate(read(staged))
        atomic_write(secrets, payload, 0o640)
        staged.unlink(missing_ok=True)
    else:
        raise ValueError("Action inconnue.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyboardInterrupt, EOFError) as exc:
        print(f"Configuration ntfy interrompue : {exc}", file=sys.stderr)
        raise SystemExit(1)
