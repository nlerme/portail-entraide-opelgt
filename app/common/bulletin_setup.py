"""Collect the club credentials needed by unattended bulletin synchronization."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from app.common.ntfy_setup import atomic_write, read


def validate(value: dict) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Identifiants de synchronisation des bulletins absents ou invalides.")
    username, password = value.get("username"), value.get("password")
    if (not isinstance(username, str) or not username.strip() or len(username) > 512
            or not isinstance(password, str) or not password or len(password) > 4096
            or any(c in username + password for c in "\x00\r\n")):
        raise ValueError("Identifiants de synchronisation des bulletins absents ou invalides.")
    return {"username": username.strip(), "password": password}


def prompt(existing: dict) -> dict[str, str]:
    print("\nBulletins : première récupération à l’installation, puis chaque dimanche à 02:00 (Europe/Paris).")
    print("Saisissez le compte membre Entraide Opel GT qui dispose de l’accès aux bulletins.")
    print("Ces identifiants seront conservés dans le fichier de secrets protégé pour les collectes sans navigateur.")
    try:
        current = validate(existing)
    except ValueError:
        current = None
    if current and input("Conserver les identifiants de synchronisation existants ? [O/n] ").strip().lower() not in {"n", "non", "no"}:
        return current
    while True:
        username = input("Identifiant membre Entraide Opel GT : ").strip()
        password = getpass.getpass("Mot de passe membre (saisie masquée) : ")
        confirmation = getpass.getpass("Confirmez le mot de passe membre : ")
        if password != confirmation:
            print("Confirmation différente : recommencez.")
            continue
        try:
            return validate({"username": username, "password": password})
        except ValueError as exc:
            print(exc)


def main() -> int:
    action, staged_path, secrets_path = sys.argv[1:]
    staged, secrets = Path(staged_path), Path(secrets_path)
    if action == "prompt":
        if not sys.stdin.isatty():
            raise ValueError("L’installation nécessite un terminal interactif pour les identifiants des bulletins.")
        atomic_write(staged, prompt(read(secrets).get("bulletins", {})), 0o600)
    elif action == "apply":
        payload = read(secrets)
        payload["bulletins"] = validate(read(staged))
        atomic_write(secrets, payload, 0o640)
        staged.unlink(missing_ok=True)
    else:
        raise ValueError("Action inconnue.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyboardInterrupt, EOFError):
        print("Configuration des bulletins interrompue. Aucun identifiant n’est affiché.", file=sys.stderr)
        raise SystemExit(1)
