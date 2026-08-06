from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.bulletins.config import settings as bulletin_settings
from app.bulletins.database import init_db
from app.common.auth import hash_admin_password, password_policy_errors
from app.common.config import CONFIG_PATH, SECRETS_PATH, data_root, read_object, section
from app.common.jobs import DB_PATH, cancel_active_queue, enqueue, init_jobs
from app.pieces.config import settings as pieces_settings


def validate_config() -> int:
    if not 1 <= int(section("server").get("port", 0)) <= 65535:
        raise RuntimeError("server.port doit être compris entre 1 et 65535.")
    if str(section("maintenance").get("timezone")) != "Europe/Paris":
        raise RuntimeError('maintenance.timezone doit valoir "Europe/Paris".')
    if str(section("maintenance").get("weekly_catalog_update_day")) != "Monday,Wednesday,Friday":
        raise RuntimeError('maintenance.weekly_catalog_update_day doit valoir "Monday,Wednesday,Friday".')
    if str(section("maintenance").get("weekly_catalog_update_time")) != "02:00":
        raise RuntimeError('maintenance.weekly_catalog_update_time doit valoir "02:00".')
    maintenance = section("maintenance")
    if not isinstance(maintenance.get("weekly_package_update_enabled"), bool):
        raise RuntimeError("maintenance.weekly_package_update_enabled doit être un booléen.")
    valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    package_day = str(maintenance.get("weekly_package_update_day", ""))
    if package_day not in valid_days:
        raise RuntimeError("maintenance.weekly_package_update_day doit être un jour anglais de Monday à Sunday.")
    package_time = str(maintenance.get("weekly_package_update_time", ""))
    try:
        datetime.strptime(package_time, "%H:%M")
    except ValueError as exc:
        raise RuntimeError("maintenance.weekly_package_update_time doit respecter le format HH:MM sur 24 heures.") from exc
    if not str(section("authentication").get("login_url", "")).startswith("https://"):
        raise RuntimeError("authentication.login_url doit utiliser HTTPS.")
    if not str(section("authentication").get("validation_url", "")).startswith("https://"):
        raise RuntimeError("authentication.validation_url doit utiliser HTTPS.")
    if not str(section("bulletins", "remote").get("bulletins_url", "")).startswith("https://"):
        raise RuntimeError("bulletins.remote.bulletins_url doit utiliser HTTPS.")
    duration_minutes = int(section("sessions").get("duration_minutes", 0))
    if not 1 <= duration_minutes <= 1440:
        raise RuntimeError("sessions.duration_minutes doit être compris entre 1 et 1440.")
    for name in ("authentication", "admin"):
        limits = section(name)
        if int(limits.get("login_rate_limit_attempts", 0)) < 1:
            raise RuntimeError(f"{name}.login_rate_limit_attempts doit être supérieur ou égal à 1.")
        if int(limits.get("login_rate_limit_window_seconds", 0)) < 1:
            raise RuntimeError(f"{name}.login_rate_limit_window_seconds doit être supérieur ou égal à 1.")
    supplier_ids = {
        "opelix_parts", "splendid_parts", "edelschmiede", "pro_gt", "atz_online",
        "opel_gt_source", "oldtimer_motorenteile", "tw_oldtimerteile",
    }
    default_enabled = section("pieces", "scraping").get("default_enabled_sites", [])
    if not isinstance(default_enabled, list) or any(not isinstance(item, str) for item in default_enabled):
        raise RuntimeError("pieces.scraping.default_enabled_sites doit être une liste d’identifiants fournisseurs.")
    unknown_suppliers = sorted(set(default_enabled) - supplier_ids)
    if unknown_suppliers:
        raise RuntimeError("Fournisseurs inconnus dans pieces.scraping.default_enabled_sites : " + ", ".join(unknown_suppliers))
    print(f"Configuration valide : {CONFIG_PATH}")
    print(f"Données : {data_root()}")
    print(f"Bulletins : {bulletin_settings.db_path}")
    print(f"Catalogues : {pieces_settings.data_dir / 'catalogues'}")
    return 0


def _write_json_atomic(path: Path, payload: dict[str, Any], mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def set_admin_password(username: str | None = None, no_restart_hint: bool = False) -> int:
    print("Le mot de passe doit contenir au moins 16 caractères, une minuscule, une majuscule, un chiffre et un caractère spécial.")
    while True:
        try:
            password = getpass.getpass("Nouveau mot de passe admin : ")
        except (EOFError, KeyboardInterrupt):
            print("\nSaisie annulée.", file=sys.stderr)
            return 1
        errors = password_policy_errors(password)
        if errors:
            print("Mot de passe refusé : " + ", ".join(errors) + ".", file=sys.stderr)
            continue
        confirm = getpass.getpass("Confirmation : ")
        if password != confirm:
            print("Confirmation différente : recommencez.", file=sys.stderr)
            continue
        break
    secrets_payload = read_object(SECRETS_PATH, optional=True)
    secrets_payload.setdefault("app_secret", os.urandom(48).hex())
    secrets_payload["admin_password_hash"] = hash_admin_password(password)
    _write_json_atomic(SECRETS_PATH, secrets_payload)
    if username:
        config_payload = read_object(CONFIG_PATH, optional=True)
        config_payload.setdefault("admin", {})["username"] = username
        _write_json_atomic(CONFIG_PATH, config_payload)
    print(f"Mot de passe administrateur enregistré dans {SECRETS_PATH}.")
    if not no_restart_hint:
        print("Redémarrez le portail pour invalider les anciennes sessions : sudo /opt/portail-entraide-opel-gt/run_server.sh restart")
    return 0


def initialize() -> int:
    root = data_root()
    for path in (
        root / "portal", root / "bulletins" / "pdf", root / "bulletins" / "incoming",
        root / "bulletins" / "failed", root / "bulletins" / "work",
        root / "pieces" / "catalogues", root / "pieces" / "catalogues" / "history",
        root / "pieces" / "cache", root / "logs", root / "backups",
    ):
        path.mkdir(parents=True, exist_ok=True)
    init_jobs()
    init_db(bulletin_settings.db_path)
    print("Répertoires et bases initialisés.")
    return 0


def enqueue_catalogs() -> int:
    from app.pieces.services.catalogs import MODULE_BY_SITE_ID
    job_id = enqueue("catalogs", "catalog_sync", {}, deduplication_key="catalog-sync", items=MODULE_BY_SITE_ID.keys(), max_retries=0)
    print(job_id)
    return 0


def enqueue_initial_catalogs() -> int:
    from app.pieces.services.catalogs import get_sync_status

    status = get_sync_status()
    usable = sum(1 for supplier in status.suppliers if supplier.ok and supplier.item_count > 0)
    if usable > 0:
        print(f"Initialisation des catalogues inutile : {usable} catalogue(s) exploitable(s) déjà présent(s).")
        return 0
    print("Aucun catalogue exploitable : récupération initiale mise en arrière-plan.")
    return enqueue_catalogs()


def reset_catalog_schedule_state() -> int:
    from app.pieces.services.catalogs import reset_unscheduled_catalog_state

    cancelled = cancel_active_queue(
        "catalogs",
        "Tâche annulée lors de la mise à niveau ; prochaine récupération planifiée les lundi, mercredi et vendredi à 02:00.",
    )
    reset_unscheduled_catalog_state()
    print(f"État catalogues normalisé : {cancelled} tâche(s) active(s) annulée(s).")
    return 0


def enqueue_missing_ocr() -> int:
    init_db(bulletin_settings.db_path)
    count = 0
    with closing(sqlite3.connect(bulletin_settings.db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id,filename FROM bulletins WHERE local_path IS NOT NULL AND local_path<>'' AND (indexed_at IS NULL OR pages<=0)"
        ).fetchall()
    for row in rows:
        enqueue("ocr", "bulletin_index", {"bulletin_id": int(row["id"])}, deduplication_key=f"bulletin-index:{row['id']}", items=[row["filename"]])
        count += 1
    print(f"{count} tâche(s) OCR mise(s) en file.")
    return 0


def _copytree_merge(source: Path, destination: Path) -> int:
    copied = 0
    if not source.exists():
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1
    return copied


def migrate(old_bulletins: Path, old_pieces: Path) -> int:
    initialize()
    marker = data_root() / "portal" / "migration-v1.json"
    report: dict[str, Any] = {"time": datetime.now(timezone.utc).isoformat(), "sources": {}, "copied": {}}
    if old_bulletins.exists():
        old_db_candidates = [old_bulletins / "search.db", old_bulletins / "bulletins.sqlite3"]
        for old_db in old_db_candidates:
            if old_db.is_file():
                destination_has_data = False
                if bulletin_settings.db_path.exists():
                    try:
                        with closing(sqlite3.connect(bulletin_settings.db_path)) as current, current:
                            destination_has_data = current.execute("SELECT COUNT(*) FROM bulletins").fetchone()[0] > 0
                    except sqlite3.Error:
                        destination_has_data = False
                if not destination_has_data:
                    shutil.copy2(old_db, bulletin_settings.db_path)
                    report["copied"]["bulletin_database"] = str(old_db)
                break
        report["copied"]["bulletin_pdfs"] = _copytree_merge(old_bulletins / "pdfs", bulletin_settings.pdf_dir)
        report["sources"]["bulletins"] = str(old_bulletins)
    if old_pieces.exists():
        catalog_source = old_pieces / "catalogues"
        report["copied"]["piece_catalogues"] = _copytree_merge(catalog_source, pieces_settings.data_dir / "catalogues")
        report["copied"]["piece_cache"] = _copytree_merge(old_pieces / "cache", pieces_settings.data_dir / "cache")
        report["sources"]["pieces"] = str(old_pieces)
    _write_json_atomic(marker, report, mode=0o640)
    enqueue_missing_ocr()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def backup(output: Path | None) -> int:
    root = data_root()
    destination = output or root / "backups" / f"portail-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        if root.exists():
            archive.add(root, arcname="data", recursive=True, filter=lambda info: None if "/backups/" in info.name else info)
        if CONFIG_PATH.exists():
            archive.add(CONFIG_PATH, arcname="config/config.json")
        if SECRETS_PATH.exists():
            archive.add(SECRETS_PATH, arcname="config/secrets.json")
    os.chmod(destination, 0o600)
    print(destination)
    return 0



def _safe_extract_backup(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise RuntimeError("La sauvegarde est vide.")
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise RuntimeError(f"Chemin interdit dans la sauvegarde : {member.name}")
            if relative.parts[0] not in {"data", "config"}:
                raise RuntimeError(f"Entrée inattendue dans la sauvegarde : {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeError(f"Type d'entrée interdit dans la sauvegarde : {member.name}")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise RuntimeError(f"Type d'entrée non pris en charge : {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"Lecture impossible dans la sauvegarde : {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, member.mode & 0o777 or 0o600)


def restore(archive_path: Path) -> int:
    archive_path = archive_path.expanduser().resolve(strict=True)
    root = data_root()
    if root == Path("/") or len(root.parts) < 3:
        raise RuntimeError(f"Répertoire de données dangereux : {root}")
    root.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{root.name}.restore-", dir=root.parent) as raw_staging:
        staging = Path(raw_staging)
        _safe_extract_backup(archive_path, staging)
        restored_data = staging / "data"
        restored_config = staging / "config" / "config.json"
        restored_secrets = staging / "config" / "secrets.json"
        if not restored_data.is_dir() or not restored_config.is_file() or not restored_secrets.is_file():
            raise RuntimeError("La sauvegarde doit contenir data/, config/config.json et config/secrets.json.")

        secrets_payload = read_object(restored_secrets)
        if len(str(secrets_payload.get("app_secret") or "")) < 32:
            raise RuntimeError("La sauvegarde ne contient pas de secret d'application valide.")
        if not str(secrets_payload.get("admin_password_hash") or ""):
            raise RuntimeError("La sauvegarde ne contient pas de mot de passe administrateur configuré.")

        validation_env = os.environ.copy()
        validation_env.update({
            "PORTAIL_CONFIG": str(restored_config),
            "PORTAIL_SECRETS": str(restored_secrets),
            "PORTAIL_DATA_DIR": str(restored_data),
        })
        validation = subprocess.run(
            [sys.executable, "-m", "app.manage", "validate-config"],
            env=validation_env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if validation.returncode:
            raise RuntimeError((validation.stderr or validation.stdout or "Configuration de sauvegarde invalide.").strip())

        rollback_data = root.parent / f".{root.name}.restore-rollback"
        rollback_config = CONFIG_PATH.with_name(f".{CONFIG_PATH.name}.restore-rollback")
        rollback_secrets = SECRETS_PATH.with_name(f".{SECRETS_PATH.name}.restore-rollback")
        for path in (rollback_data, rollback_config, rollback_secrets):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

        had_data = root.exists()
        had_config = CONFIG_PATH.exists()
        had_secrets = SECRETS_PATH.exists()
        try:
            if had_data:
                os.replace(root, rollback_data)
            shutil.move(str(restored_data), str(root))
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
            if had_config:
                shutil.copy2(CONFIG_PATH, rollback_config)
            if had_secrets:
                shutil.copy2(SECRETS_PATH, rollback_secrets)
            shutil.copy2(restored_config, CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".restore-new"))
            os.replace(CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".restore-new"), CONFIG_PATH)
            shutil.copy2(restored_secrets, SECRETS_PATH.with_suffix(SECRETS_PATH.suffix + ".restore-new"))
            os.replace(SECRETS_PATH.with_suffix(SECRETS_PATH.suffix + ".restore-new"), SECRETS_PATH)
            os.chmod(CONFIG_PATH, 0o640)
            os.chmod(SECRETS_PATH, 0o640)
        except Exception:
            if root.exists():
                shutil.rmtree(root)
            if rollback_data.exists():
                os.replace(rollback_data, root)
            if rollback_config.exists():
                os.replace(rollback_config, CONFIG_PATH)
            elif not had_config:
                CONFIG_PATH.unlink(missing_ok=True)
            if rollback_secrets.exists():
                os.replace(rollback_secrets, SECRETS_PATH)
            elif not had_secrets:
                SECRETS_PATH.unlink(missing_ok=True)
            raise
        finally:
            if rollback_data.exists():
                shutil.rmtree(rollback_data)
            rollback_config.unlink(missing_ok=True)
            rollback_secrets.unlink(missing_ok=True)

    print(f"Sauvegarde restaurée : {archive_path}")
    return 0


def cleanup() -> int:
    root = data_root()
    removed = 0
    cutoff = datetime.now().timestamp() - 7 * 86400
    for directory in (root / "bulletins" / "incoming", root / "bulletins" / "work", root / "pieces" / "cache"):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and (path.suffix in {".tmp", ".part"} or path.stat().st_mtime < cutoff):
                path.unlink(missing_ok=True)
                removed += 1
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            "DELETE FROM jobs WHERE state IN ('succeeded','failed','completed_with_warnings','cancelled') "
            "AND finished_at IS NOT NULL AND finished_at < datetime('now','-90 days')"
        )
    print(f"Nettoyage terminé : {removed} fichier(s) temporaire(s) supprimé(s).")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(description="Administration du portail Entraide Opel GT")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-config")
    sub.add_parser("initialize")
    password = sub.add_parser("set-admin-password")
    password.add_argument("--username")
    password.add_argument("--no-restart-hint", action="store_true")
    sub.add_parser("enqueue-catalogs")
    sub.add_parser("enqueue-initial-catalogs")
    sub.add_parser("enqueue-missing-ocr")
    sub.add_parser("reset-catalog-schedule-state")
    migration = sub.add_parser("migrate")
    migration.add_argument("--old-bulletins", type=Path, default=Path("/var/lib/bulletins-entraide-opel-gt"))
    migration.add_argument("--old-pieces", type=Path, default=Path("/var/lib/comparateur-entraide-opel-gt"))
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--output", type=Path)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("archive", type=Path)
    sub.add_parser("cleanup")
    args = parser.parse_args()
    try:
        return {
            "validate-config": lambda: validate_config(),
            "initialize": lambda: initialize(),
            "set-admin-password": lambda: set_admin_password(args.username, args.no_restart_hint),
            "enqueue-catalogs": lambda: enqueue_catalogs(),
            "enqueue-initial-catalogs": lambda: enqueue_initial_catalogs(),
            "enqueue-missing-ocr": lambda: enqueue_missing_ocr(),
            "reset-catalog-schedule-state": lambda: reset_catalog_schedule_state(),
            "migrate": lambda: migrate(args.old_bulletins, args.old_pieces),
            "backup": lambda: backup(args.output),
            "restore": lambda: restore(args.archive),
            "cleanup": lambda: cleanup(),
        }[args.command]()
    except Exception as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
