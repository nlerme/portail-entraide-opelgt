#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="portail-entraide-opel-gt"
BUNDLE_TITLE="Portail Entraide Opel GT"
BUNDLE_EDITION="Linux serveur"
BUNDLE_AUTHOR="Nicolas Lermé"
INSTALL_DIR="${PORTAIL_INSTALL_DIR:-/opt/${APP_NAME}}"
CONFIG_DIR="${PORTAIL_CONFIG_DIR:-/etc/${APP_NAME}}"
CONFIG_FILE="${CONFIG_DIR}/config.json"
SECRETS_FILE="${CONFIG_DIR}/secrets.json"
DATA_DIR="${PORTAIL_DATA_DIR:-/var/lib/${APP_NAME}}"
RUN_DIR="${PORTAIL_RUN_DIR:-/run/${APP_NAME}}"
SYSTEMD_UNIT_DIR="${PORTAIL_SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
TMPFILES_DIR="${PORTAIL_TMPFILES_DIR:-/etc/tmpfiles.d}"
SERVICE_USER="${PORTAIL_SERVICE_USER:-opelgt}"
SERVICE_GROUP="${PORTAIL_SERVICE_GROUP:-opelgt}"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IFS= read -r VERSION < "$SOURCE_DIR/VERSION"
SOURCE_OWNER_UID="${SUDO_UID:-}"
SOURCE_OWNER_GID="${SUDO_GID:-}"
CLOUDFLARE_TUNNEL_REQUESTED=0
CLOUDFLARE_TUNNEL_TOKEN=""
NTFY_STAGED_FILE=""
UNITS=(
  "${APP_NAME}-web.service"
  "${APP_NAME}-ocr-worker.service"
  "${APP_NAME}-catalog-worker.service"
  "${APP_NAME}-control.socket"
  "${APP_NAME}-catalog-update.timer"
  "${APP_NAME}-annonces-update.timer"
  "${APP_NAME}-notifications.timer"
  "${APP_NAME}-cleanup.timer"
)
ALL_UNIT_FILES=(
  "${APP_NAME}-web.service"
  "${APP_NAME}-ocr-worker.service"
  "${APP_NAME}-catalog-worker.service"
  "${APP_NAME}-control.socket"
  "${APP_NAME}-control@.service"
  "${APP_NAME}-catalog-update.service"
  "${APP_NAME}-catalog-update.timer"
  "${APP_NAME}-annonces-update.service"
  "${APP_NAME}-annonces-update.timer"
  "${APP_NAME}-notifications.service"
  "${APP_NAME}-notifications.timer"
  "${APP_NAME}-cleanup.service"
  "${APP_NAME}-cleanup.timer"
  "${APP_NAME}-system-update.service"
  "${APP_NAME}-system-update.timer"
  "${APP_NAME}-cloudflare-health.service"
  "${APP_NAME}-cloudflare-health.timer"
)

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_BLUE=$'\033[1;34m'
  C_CYAN=$'\033[1;36m'
  C_GREEN=$'\033[1;32m'
  C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[1;31m'
  C_DIM=$'\033[2m'
else
  C_RESET="" C_BOLD="" C_BLUE="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RED="" C_DIM=""
fi

print_header() {
  local command_label="${1:-aide}"
  printf '\n%s%s%s\n' "$C_BLUE" "$BUNDLE_TITLE" "$C_RESET"
  printf '%s%s · version %s%s\n' "$C_BOLD" "$BUNDLE_EDITION" "$VERSION" "$C_RESET"
  printf '%sAuteur : %s · Commande : %s%s\n' "$C_DIM" "$BUNDLE_AUTHOR" "$command_label" "$C_RESET"
  printf '%s────────────────────────────────────────%s\n' "$C_BLUE" "$C_RESET"
}

stage() {
  local current="$1" total="$2"
  shift 2
  printf '\n%s[%s/%s]%s %s%s%s\n' "$C_CYAN" "$current" "$total" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"
}

info() { printf '  %s•%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok() { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die() { printf '\n%sERREUR%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
require_root() { [[ ${EUID} -eq 0 ]] || die "Cette commande doit être exécutée avec sudo."; }
require_systemd() { command -v systemctl >/dev/null || die "systemd est requis."; }

restore_source_ownership() {
  if [[ -n "$NTFY_STAGED_FILE" ]]; then
    rm -f -- "$NTFY_STAGED_FILE"
  fi
  if [[ -n "$SOURCE_OWNER_UID" && -n "$SOURCE_OWNER_GID" && "$SOURCE_DIR" != "$INSTALL_DIR" && "$SOURCE_DIR" != "/" && -d "$SOURCE_DIR" ]]; then
    chown -R "$SOURCE_OWNER_UID:$SOURCE_OWNER_GID" "$SOURCE_DIR" >/dev/null 2>&1 || true
  fi
}

trap restore_source_ownership EXIT

check_platform() {
  [[ "$(uname -s)" == "Linux" ]] || die "Ce bundle prend uniquement en charge Linux."
  case "$(uname -m)" in x86_64|aarch64|arm64) ;; *) die "Architecture non prise en charge : $(uname -m)." ;; esac
  command -v apt-get >/dev/null || die "Ce bundle cible Debian, Ubuntu et Raspberry Pi OS avec apt."
}

prompt_cloudflare_tunnel() {
  [[ -t 0 ]] || die "L'installation doit être lancée dans un terminal interactif."
  printf '\nConfiguration optionnelle de Cloudflare Tunnel\n'
  printf 'Cloudflare Tunnel permet de publier le portail sans ouvrir de port entrant sur la box.\n'
  printf 'Le connecteur cloudflared sera installé comme service systemd et redémarrera automatiquement après chaque reboot.\n'
  printf 'Si un service cloudflared existe déjà sur cette machine, il sera remplacé par le tunnel dont vous saisirez le jeton.\n\n'
  local answer
  while true; do
    read -r -p "Souhaitez-vous utiliser un tunnel Cloudflare ? [o/N] " answer
    case "${answer,,}" in
      o|oui|y|yes)
        CLOUDFLARE_TUNNEL_REQUESTED=1
        break
        ;;
      ''|n|non|no)
        CLOUDFLARE_TUNNEL_REQUESTED=0
        return 0
        ;;
      *) warn "Répondez par o (oui) ou n (non)." ;;
    esac
  done

  cat <<'EOF_CLOUDFLARE_TOKEN'

Où récupérer le jeton :
  1. Connectez-vous au tableau de bord Cloudflare.
  2. Ouvrez « Networking » puis « Tunnels ».
  3. Créez un tunnel, ou ouvrez le tunnel existant destiné au portail.
  4. Dans l'onglet « Overview », choisissez « Add a replica ».
  5. Choisissez Linux et copiez la commande d'installation affichée dans un éditeur de texte.
  6. Le jeton est la longue chaîne commençant par « eyJ » placée après « service install ».

Le jeton donne le droit d'exécuter le tunnel : ne le communiquez pas et ne le conservez pas dans un historique de terminal.
EOF_CLOUDFLARE_TOKEN
  while true; do
    read -r -s -p "Jeton du tunnel Cloudflare (saisie masquée) : " CLOUDFLARE_TUNNEL_TOKEN
    printf '\n'
    if [[ "$CLOUDFLARE_TUNNEL_TOKEN" =~ ^eyJ[A-Za-z0-9._=-]{20,}$ ]]; then
      break
    fi
    warn "Le jeton semble invalide : il doit commencer par eyJ."
  done
}

install_cloudflared_package() {
  [[ "$CLOUDFLARE_TUNNEL_REQUESTED" -eq 1 ]] || return 0
  install -d -m 0755 /usr/share/keyrings
  local key_temp
  key_temp="$(mktemp)"
  if ! curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o "$key_temp"; then
    rm -f "$key_temp"
    die "Téléchargement de la clé de signature Cloudflare impossible."
  fi
  install -m 0644 "$key_temp" /usr/share/keyrings/cloudflare-main.gpg
  rm -f "$key_temp"
  printf '%s\n' 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq
  apt-get install -y -qq cloudflared >/dev/null
  command -v cloudflared >/dev/null || die "cloudflared n'a pas été installé correctement."
}

configure_cloudflare_tunnel() {
  local dropin_dir="$SYSTEMD_UNIT_DIR/cloudflared.service.d"
  if [[ "$CLOUDFLARE_TUNNEL_REQUESTED" -eq 1 ]]; then
    if systemctl list-unit-files cloudflared.service --no-legend 2>/dev/null | grep -q 'cloudflared.service'; then
      warn "Un service cloudflared existe déjà ; il va être remplacé."
      cloudflared service uninstall >/dev/null 2>&1 || systemctl disable --now cloudflared.service >/dev/null 2>&1 || true
    fi
    cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN" >/dev/null
    CLOUDFLARE_TUNNEL_TOKEN=""
    unset CLOUDFLARE_TUNNEL_TOKEN
  elif [[ ! -f "$dropin_dir/${APP_NAME}.conf" ]]; then
    return 0
  fi
  install -d -m 0755 "$dropin_dir"
  install -m 0644 "$INSTALL_DIR/systemd/cloudflared-portail.conf" "$dropin_dir/${APP_NAME}.conf"
  systemctl daemon-reload
  systemctl enable cloudflared.service >/dev/null 2>&1 || true
  systemctl enable --now "${APP_NAME}-cloudflare-health.timer" >/dev/null
  if ! systemctl restart cloudflared.service; then
    warn "Le tunnel ne se connecte pas encore ; sa surveillance automatique reste active. Consultez : journalctl -u cloudflared"
  fi
  local port
  port="$(python3 -c 'import json; print(json.load(open("'"$CONFIG_FILE"'"))["server"]["port"])' 2>/dev/null || echo 8080)"
  ok "Tunnel Cloudflare configuré en HTTP/2, avec surveillance périodique. Il redémarrera automatiquement après chaque reboot."
  printf 'Dans Cloudflare, associez la route publique du tunnel au service local : http://127.0.0.1:%s\n' "$port"
}

cloudflare_health_command() {
  require_root; require_systemd
  [[ -f "$SYSTEMD_UNIT_DIR/cloudflared.service.d/${APP_NAME}.conf" ]] || return 0
  local state="$RUN_DIR/cloudflare-health.failures" port target count=0
  # A deliberate stop of the portal or connector must remain effective.
  if ! systemctl is-active --quiet "${APP_NAME}-web.service"; then
    rm -f "$state"
    return 0
  fi
  if ! systemctl is-active --quiet cloudflared.service && ! systemctl is-failed --quiet cloudflared.service; then
    rm -f "$state"
    return 0
  fi
  port="$(python3 - "$CONFIG_FILE" <<'PY_CLOUDFLARE_PORT'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as source:
    print(int(json.load(source)["server"]["port"]))
PY_CLOUDFLARE_PORT
  )"
  # Probe the origin even without local visitors, then the actual edge
  # connection count. /healthcheck alone only proves the process is alive.
  if ! curl --noproxy '*' -fsS --connect-timeout 2 --max-time 8 "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
    target="${APP_NAME}-web.service"
  elif ! curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:20241/ready >/dev/null 2>&1; then
    target=cloudflared.service
  else
    rm -f "$state"
    return 0
  fi
  local previous_target="" previous_count=""
  if [[ -f "$state" ]]; then
    read -r previous_target previous_count < "$state" || true
    if [[ "$previous_target" == "$target" && "$previous_count" =~ ^[0-2]$ ]]; then
      count="$previous_count"
    fi
  fi
  count=$((count + 1))
  [[ -d "$RUN_DIR" ]] || install -d -m 0750 "$RUN_DIR"
  printf '%s %s\n' "$target" "$count" > "$state"
  if (( count >= 3 )); then
    warn "$target : trois contrôles de santé consécutifs en échec ; reconnexion automatique."
    rm -f "$state"
    systemctl restart "$target"
  fi
}

run_as_service() {
  runuser -u "$SERVICE_USER" -- env \
    PORTAIL_CONFIG="$CONFIG_FILE" PORTAIL_SECRETS="$SECRETS_FILE" \
    HOME="$DATA_DIR" XDG_CACHE_HOME="$DATA_DIR/pieces/cache" \
    PYTHONPATH="$INSTALL_DIR" PYTHONUNBUFFERED=1 "$@"
}

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates util-linux iputils-ping \
    tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng >/dev/null
}

ensure_account() {
  getent group "$SERVICE_GROUP" >/dev/null || groupadd --system "$SERVICE_GROUP"
  id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --gid "$SERVICE_GROUP" --home-dir "$DATA_DIR" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
}

copy_application() {
  if [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    install -d -m 0755 "$INSTALL_DIR"
    tar -C "$SOURCE_DIR" \
      --exclude='./.git' --exclude='./.pytest_cache' --exclude='./.ruff_cache' \
      --exclude='./__pycache__' --exclude='*/__pycache__' --exclude='*.pyc' \
      --exclude='./config.json' --exclude='./secrets.json' --exclude='./data/*' \
      --exclude='*.zip' --exclude='*.tar.gz' -cf - . | tar -C "$INSTALL_DIR" -xf -
  fi
  find "$INSTALL_DIR" -type d -exec chmod 0755 {} +
  find "$INSTALL_DIR" -type f -exec chmod 0644 {} +
  chmod 0755 "$INSTALL_DIR/run_server.sh"
}

create_venvs() {
  (cd "$INSTALL_DIR" && sha256sum -c requirements.lock.sha256 >/dev/null) \
    || die "Les fichiers de dépendances ne correspondent pas à leur empreinte attendue."
  python3 -m venv "$INSTALL_DIR/venv-web"
  python3 -m venv "$INSTALL_DIR/venv-ocr"
  "$INSTALL_DIR/venv-web/bin/pip" install --disable-pip-version-check -q --upgrade pip
  "$INSTALL_DIR/venv-ocr/bin/pip" install --disable-pip-version-check -q --upgrade pip
  "$INSTALL_DIR/venv-web/bin/pip" install --disable-pip-version-check -q -r "$INSTALL_DIR/requirements-web.lock"
  "$INSTALL_DIR/venv-ocr/bin/pip" install --disable-pip-version-check -q -r "$INSTALL_DIR/requirements-ocr.lock"
}

migrate_default_network_binding() {
  python3 - "$CONFIG_FILE" <<'PY_NETWORK_BINDING'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
server = payload.setdefault("server", {})
host = str(server.get("host") or "").strip().lower()
public_url = str(server.get("public_url") or "").strip()
trusted_proxies = server.get("trusted_proxies") or []

# Only migrate the untouched loopback default. Explicit reverse-proxy
# configurations remain unchanged.
if host in {"127.0.0.1", "localhost", "::1"} and not public_url and not trusted_proxies:
    server["host"] = "0.0.0.0"
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    print("Configuration réseau ajustée : écoute sur toutes les interfaces (0.0.0.0).")
PY_NETWORK_BINDING
}

migrate_login_rate_limits() {
  python3 - "$CONFIG_FILE" <<'PY_LOGIN_RATE_LIMITS'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
changed = False
for section_name in ("authentication", "admin"):
    current = payload.setdefault(section_name, {})
    if "login_rate_limit_attempts" not in current:
        current["login_rate_limit_attempts"] = 5
        changed = True
    if "login_rate_limit_window_seconds" not in current:
        current["login_rate_limit_window_seconds"] = 300
        changed = True
    if "login_rate_limit_per_minute" in current:
        current.pop("login_rate_limit_per_minute", None)
        changed = True
if changed:
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
PY_LOGIN_RATE_LIMITS
}

migrate_session_duration() {
  python3 - "$CONFIG_FILE" <<'PY_SESSION_DURATION'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
changed = False
sessions = payload.setdefault("sessions", {})
if "duration_minutes" not in sessions or sessions.get("duration_minutes") == 10:
    sessions["duration_minutes"] = 30
    changed = True
for section_name in ("authentication", "admin"):
    current = payload.setdefault(section_name, {})
    if "session_hours" in current:
        current.pop("session_hours", None)
        changed = True
if changed:
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
PY_SESSION_DURATION
}

migrate_catalog_schedule() {
  python3 - "$CONFIG_FILE" <<'PY_CATALOG_SCHEDULE'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
maintenance = payload.setdefault("maintenance", {})
changed = False
if maintenance.get("weekly_catalog_update_day") != "Monday,Wednesday,Friday":
    maintenance["weekly_catalog_update_day"] = "Monday,Wednesday,Friday"
    changed = True
if maintenance.get("weekly_catalog_update_time") != "02:00":
    maintenance["weekly_catalog_update_time"] = "02:00"
    changed = True
if changed:
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
PY_CATALOG_SCHEDULE
}

migrate_default_enabled_sites() {
  python3 - "$CONFIG_FILE" <<'PY_DEFAULT_ENABLED_SITES'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
scraping = payload.setdefault("pieces", {}).setdefault("scraping", {})
if "default_enabled_sites" not in scraping:
    scraping["default_enabled_sites"] = [
        "opelix_parts", "splendid_parts", "edelschmiede", "pro_gt",
        "atz_online", "opel_gt_source", "oldtimer_motorenteile", "tw_oldtimerteile",
    ]
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
PY_DEFAULT_ENABLED_SITES
}

migrate_package_update_schedule() {
  python3 - "$CONFIG_FILE" <<'PY_PACKAGE_SCHEDULE'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
maintenance = payload.setdefault("maintenance", {})
changed = False
defaults = {
    "weekly_package_update_enabled": True,
    "weekly_package_update_day": "Wednesday",
    "weekly_package_update_time": "00:00",
}
for key, value in defaults.items():
    if key not in maintenance:
        maintenance[key] = value
        changed = True
if changed:
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
PY_PACKAGE_SCHEDULE
}

configure_files() {
  install -d -m 0750 -o root -g "$SERVICE_GROUP" "$CONFIG_DIR"
  install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" \
    "$DATA_DIR" "$DATA_DIR/portal" "$DATA_DIR/bulletins" "$DATA_DIR/pieces" "$DATA_DIR/logs" "$DATA_DIR/backups"
  if [[ ! -f "$CONFIG_FILE" ]]; then
    install -m 0640 -o root -g "$SERVICE_GROUP" "$INSTALL_DIR/config.example.json" "$CONFIG_FILE"
  fi
  migrate_default_network_binding
  migrate_login_rate_limits
  migrate_session_duration
  migrate_catalog_schedule
  migrate_default_enabled_sites
  migrate_package_update_schedule
  if [[ ! -f "$SECRETS_FILE" ]]; then
    local secret
    secret="$(python3 -c 'import secrets; print(secrets.token_hex(48))')"
    printf '{\n  "app_secret": "%s",\n  "admin_password_hash": ""\n}\n' "$secret" > "$SECRETS_FILE"
  fi
  if [[ -n "$NTFY_STAGED_FILE" ]]; then
    python3 "$INSTALL_DIR/app/common/ntfy_setup.py" apply "$NTFY_STAGED_FILE" "$SECRETS_FILE"
    NTFY_STAGED_FILE=""
  fi
  chown root:"$SERVICE_GROUP" "$CONFIG_FILE" "$SECRETS_FILE"
  chmod 0640 "$CONFIG_FILE" "$SECRETS_FILE"
  chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$DATA_DIR"
}

install_units() {
  for unit in "${ALL_UNIT_FILES[@]}"; do
    install -d -m 0755 "$SYSTEMD_UNIT_DIR"
    install -m 0644 "$INSTALL_DIR/systemd/$unit" "$SYSTEMD_UNIT_DIR/$unit"
  done
  install -d -m 0755 "$TMPFILES_DIR"
  install -m 0644 "$INSTALL_DIR/systemd/${APP_NAME}.tmpfiles" "$TMPFILES_DIR/${APP_NAME}.conf"
  systemd-tmpfiles --create "$TMPFILES_DIR/${APP_NAME}.conf"
  systemctl daemon-reload
}

apply_system_update_schedule() {
  local enabled day time_value timezone day_abbr
  mapfile -t _package_schedule < <(python3 - "$CONFIG_FILE" <<'PY_READ_PACKAGE_SCHEDULE'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
maintenance = payload.get("maintenance", {})
print("true" if maintenance.get("weekly_package_update_enabled", True) else "false")
print(maintenance.get("weekly_package_update_day", "Wednesday"))
print(maintenance.get("weekly_package_update_time", "00:00"))
print(maintenance.get("timezone", "Europe/Paris"))
PY_READ_PACKAGE_SCHEDULE
  )
  enabled="${_package_schedule[0]:-true}"
  day="${_package_schedule[1]:-Wednesday}"
  time_value="${_package_schedule[2]:-00:00}"
  timezone="${_package_schedule[3]:-Europe/Paris}"
  [[ "$time_value" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "Heure de mise à jour système invalide : $time_value"
  case "$day" in
    Monday) day_abbr=Mon ;; Tuesday) day_abbr=Tue ;; Wednesday) day_abbr=Wed ;;
    Thursday) day_abbr=Thu ;; Friday) day_abbr=Fri ;; Saturday) day_abbr=Sat ;; Sunday) day_abbr=Sun ;;
    *) die "Jour de mise à jour système invalide : $day" ;;
  esac
  cat > "$SYSTEMD_UNIT_DIR/${APP_NAME}-system-update.timer" <<EOF_SYSTEM_UPDATE_TIMER
[Unit]
Description=Portail Entraide Opel GT - planification des mises à jour des paquets système

[Timer]
OnCalendar=${day_abbr} *-*-* ${time_value}:00 ${timezone}
Persistent=false
AccuracySec=1s
Unit=${APP_NAME}-system-update.service

[Install]
WantedBy=timers.target
EOF_SYSTEM_UPDATE_TIMER
  chmod 0644 "$SYSTEMD_UNIT_DIR/${APP_NAME}-system-update.timer"
  systemctl daemon-reload
  if [[ "$enabled" == "true" ]]; then
    systemctl enable --now "${APP_NAME}-system-update.timer" >/dev/null
    ok "Mise à jour des paquets planifiée chaque ${day} à ${time_value} (${timezone}), suivie d'un reboot."
  else
    systemctl disable --now "${APP_NAME}-system-update.timer" >/dev/null 2>&1 || true
    warn "Mise à jour hebdomadaire des paquets désactivée dans la configuration."
  fi
}

stop_current_services() {
  if systemctl list-unit-files "${APP_NAME}-web.service" --no-legend 2>/dev/null | grep -q "${APP_NAME}-web.service"; then
    systemctl stop "${APP_NAME}-catalog-update.timer" "${APP_NAME}-catalog-update.service" \
      "${APP_NAME}-annonces-update.timer" "${APP_NAME}-annonces-update.service" \
      "${APP_NAME}-notifications.timer" "${APP_NAME}-notifications.service" \
      "${APP_NAME}-cleanup.timer" "${APP_NAME}-cleanup.service" \
      "${APP_NAME}-cloudflare-health.timer" "${APP_NAME}-cloudflare-health.service" \
      "${APP_NAME}-system-update.timer" \
      "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null 2>&1 || true
  fi
}

stop_legacy_services() {
  for unit in bulletins-opel-gt.service comparateur-opel-gt.service; do
    if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "$unit"; then
      warn "Arrêt de l'ancien service ${unit} avant migration."
      systemctl disable --now "$unit" >/dev/null 2>&1 || true
    fi
  done
}

initialize_application() {
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage initialize
}

enqueue_initial_background_work() {
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage enqueue-initial-catalogs >/dev/null
}

enable_services() {
  systemctl enable "${UNITS[@]}" >/dev/null
  systemctl restart "${APP_NAME}-control.socket"
  systemctl restart "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service"
  systemctl start "${APP_NAME}-catalog-update.timer" "${APP_NAME}-cleanup.timer" "${APP_NAME}-annonces-update.timer" "${APP_NAME}-notifications.timer"
  systemctl start --no-block "${APP_NAME}-annonces-update.service"
}

set_admin_password() {
  if [[ ! -t 0 ]]; then
    die "L'installation doit être lancée dans un terminal interactif afin de définir le mot de passe administrateur."
  fi
  PORTAIL_CONFIG="$CONFIG_FILE" PORTAIL_SECRETS="$SECRETS_FILE" PYTHONPATH="$INSTALL_DIR" \
    "$INSTALL_DIR/venv-web/bin/python" -m app.manage set-admin-password --no-restart-hint
  chown root:"$SERVICE_GROUP" "$SECRETS_FILE"
  chmod 0640 "$SECRETS_FILE"
  systemctl restart "${APP_NAME}-web.service"
}

install_command() {
  stage 1 8 "Vérification de la plateforme et options d’accès"
  require_root; require_systemd; check_platform
  NTFY_STAGED_FILE="$(mktemp)"
  chmod 0600 "$NTFY_STAGED_FILE"
  python3 "$SOURCE_DIR/app/common/ntfy_setup.py" prompt "$NTFY_STAGED_FILE" "$SECRETS_FILE"
  prompt_cloudflare_tunnel

  stage 2 8 "Installation des dépendances système"
  install_packages
  install_cloudflared_package

  stage 3 8 "Préparation du compte système et arrêt des services"
  ensure_account
  stop_current_services
  stop_legacy_services

  stage 4 8 "Déploiement des fichiers de l’application"
  copy_application

  stage 5 8 "Environnements Python et configuration — cette étape peut prendre plusieurs minutes"
  create_venvs
  configure_files

  stage 6 8 "Services systemd et planifications"
  install_units
  apply_system_update_schedule

  stage 7 8 "Initialisation des données et démarrage"
  initialize_application
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage reset-catalog-schedule-state >/dev/null
  enqueue_initial_background_work
  enable_services

  stage 8 8 "Mot de passe administrateur et accès distant"
  set_admin_password
  configure_cloudflare_tunnel
  if ! run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.notifications --test; then
    warn "Le test ntfy n'a pas encore été remis ; il reste en attente et sera réessayé automatiquement."
  fi
  ok "Portail ${VERSION} installé."
  print_access
}

print_access() {
  local host port display_host
  host="$(python3 -c 'import json; print(json.load(open("'"$CONFIG_FILE"'"))["server"]["host"])' 2>/dev/null || echo 0.0.0.0)"
  port="$(python3 -c 'import json; print(json.load(open("'"$CONFIG_FILE"'"))["server"]["port"])' 2>/dev/null || echo 8080)"
  display_host="$host"
  if [[ "$host" == "0.0.0.0" || "$host" == "::" ]]; then
    display_host="$(ip -o -4 route get 1.1.2.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="src") {print $(i+1); exit}}')"
    if [[ -z "$display_host" ]]; then
      display_host="$(hostname -I 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i ~ /^[0-9]+\./) {print $i; exit}}')"
    fi
    [[ -n "$display_host" ]] || display_host="ADRESSE_IP_DU_SERVEUR"
  fi
  printf 'Adresse du portail : http://%s:%s\n' "$display_host" "$port"
  printf 'Le serveur écoute sur %s:%s. HTTP est autorisé sur le réseau local ; pour un accès depuis Internet, configurez HTTPS comme décrit dans README.md.\n' "$host" "$port"
}

status_command() {
  stage 1 1 "État des services"
  require_systemd
  for unit in "${UNITS[@]}"; do
    if systemctl is-active --quiet "$unit"; then ok "$unit : actif"; else warn "$unit : inactif"; fi
  done
  if systemctl is-active --quiet "${APP_NAME}-system-update.timer"; then
    ok "${APP_NAME}-system-update.timer : actif"
  else
    warn "${APP_NAME}-system-update.timer : inactif"
  fi
  if systemctl is-active --quiet cloudflared.service 2>/dev/null; then
    ok "cloudflared.service : actif"
  fi
  if [[ -S "$RUN_DIR/control.sock" ]]; then
    ok "Canal de contrôle : disponible"
  else
    warn "Canal de contrôle : absent"
  fi
}

logs_command() {
  stage 1 1 "Suivi des journaux applicatifs"
  local lines="${2:-120}"
  if compgen -G "$DATA_DIR/logs/*.log" >/dev/null; then tail -n "$lines" -F "$DATA_DIR"/logs/*.log; else warn "Aucun fichier de log disponible."; fi
}

health_command() {
  stage 1 1 "Contrôle de santé du portail"
  local port
  port="$(python3 -c 'import json; print(json.load(open("'"$CONFIG_FILE"'"))["server"]["port"])')"
  curl -fsS "http://127.0.0.1:${port}/api/health"; printf '\n'
}

migrate_command() {
  stage 1 4 "Vérification de l’installation"
  require_root; require_systemd
  [[ -x "$INSTALL_DIR/venv-web/bin/python" ]] || die "Le portail doit être installé avant la migration."

  stage 2 4 "Arrêt temporaire des services"
  systemctl stop "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null 2>&1 || true

  stage 3 4 "Migration des anciennes données"
  if ! run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage reset-catalog-schedule-state >/dev/null \
      || ! run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage migrate \
          --old-bulletins /var/lib/bulletins-entraide-opel-gt \
          --old-pieces /var/lib/comparateur-entraide-opel-gt \
      || ! run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage enqueue-initial-catalogs >/dev/null; then
    systemctl start "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null 2>&1 || true
    die "Migration interrompue ; les services ont été redémarrés."
  fi

  stage 4 4 "Redémarrage des services"
  systemctl restart "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null
  ok "Migration terminée ; les traitements nécessaires se poursuivent en arrière-plan."
}

backup_command() {
  stage 1 1 "Création de la sauvegarde"
  require_root
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage backup "${@:2}"
}

restore_command() {
  stage 1 3 "Vérification de la sauvegarde et arrêt des services"
  require_root; require_systemd
  local archive="${2:-}"
  [[ -n "$archive" && -f "$archive" ]] || die "Indiquez une archive de sauvegarde existante."
  archive="$(readlink -f "$archive")"
  systemctl stop "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null

  stage 2 3 "Restauration des données"
  if ! PORTAIL_CONFIG="$CONFIG_FILE" PORTAIL_SECRETS="$SECRETS_FILE" PORTAIL_DATA_DIR="$DATA_DIR" PYTHONPATH="$INSTALL_DIR" \
      "$INSTALL_DIR/venv-web/bin/python" -m app.manage restore "$archive"; then
    systemctl start "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null 2>&1 || true
    die "Restauration annulée ; les données précédentes ont été conservées."
  fi
  chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$DATA_DIR"
  chown root:"$SERVICE_GROUP" "$CONFIG_FILE" "$SECRETS_FILE"
  chmod 0640 "$CONFIG_FILE" "$SECRETS_FILE"
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage initialize

  stage 3 3 "Redémarrage du portail"
  systemctl restart "${APP_NAME}-control.socket" "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null
  ok "Sauvegarde restaurée et portail redémarré."
}

configured_data_dir() {
  if [[ -f "$CONFIG_FILE" ]]; then
    python3 - "$CONFIG_FILE" "$DATA_DIR" <<'PY_CONFIGURED_DATA'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
fallback = sys.argv[2]
try:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    value = str(payload.get("storage", {}).get("data_dir") or fallback)
except Exception:
    value = fallback
print(value)
PY_CONFIGURED_DATA
  else
    printf '%s\n' "$DATA_DIR"
  fi
}

safe_remove_tree() {
  local target="${1:-}" resolved
  [[ -n "$target" ]] || return 0
  resolved="$(readlink -m -- "$target")"
  case "$resolved" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var)
      die "Refus de supprimer un répertoire système : $resolved"
      ;;
  esac
  [[ "$resolved" == /* && ${#resolved} -gt 5 ]] || die "Répertoire de purge invalide : $resolved"
  rm -rf -- "$resolved"
}

disable_cloudflare_unit() {
  local unit="$1"
  if ! systemctl disable --now "$unit" >/dev/null 2>&1; then
    # Missing units are normal on a repeated uninstall. A running or enabled
    # connector/monitor must never be silently left behind, however.
    if systemctl is-active --quiet "$unit" || systemctl is-enabled --quiet "$unit"; then
      die "Impossible d'arrêter et de désactiver $unit ; désinstallation interrompue."
    fi
  fi
}

uninstall_command() {
  stage 1 4 "Vérification de la désinstallation"
  require_root; require_systemd
  local purge="${2:-}" configured_data
  configured_data="$(configured_data_dir)"

  stage 2 4 "Arrêt et désactivation des services"
  # Stop the timer and any in-flight health check before stopping the tunnel.
  disable_cloudflare_unit "${APP_NAME}-cloudflare-health.timer"
  disable_cloudflare_unit "${APP_NAME}-cloudflare-health.service"
  disable_cloudflare_unit "${APP_NAME}-notifications.timer"
  disable_cloudflare_unit "${APP_NAME}-notifications.service"
  systemctl disable --now "${UNITS[@]}" "${APP_NAME}-system-update.timer" >/dev/null 2>&1 || true
  systemctl stop "${APP_NAME}-annonces-update.service" >/dev/null 2>&1 || true
  if [[ "$purge" == "--purge" || -f "$SYSTEMD_UNIT_DIR/cloudflared.service.d/${APP_NAME}.conf" ]]; then
    # --purge also handles older installations without our management drop-in.
    disable_cloudflare_unit cloudflared.service
  fi

  stage 3 4 "Suppression de l’application et des unités systemd"
  for unit in "${ALL_UNIT_FILES[@]}"; do rm -f "$SYSTEMD_UNIT_DIR/$unit"; done
  rm -f "$SYSTEMD_UNIT_DIR/cloudflared.service.d/${APP_NAME}.conf"
  rmdir "$SYSTEMD_UNIT_DIR/cloudflared.service.d" 2>/dev/null || true
  rm -f "$TMPFILES_DIR/${APP_NAME}.conf"
  safe_remove_tree "$RUN_DIR"
  safe_remove_tree "$INSTALL_DIR"
  systemctl daemon-reload >/dev/null
  systemctl reset-failed >/dev/null 2>&1 || true

  stage 4 4 "Nettoyage final"
  if [[ "$purge" == "--purge" ]]; then
    safe_remove_tree "$CONFIG_DIR"
    safe_remove_tree "$DATA_DIR"
    if [[ "$(readlink -m -- "$configured_data")" != "$(readlink -m -- "$DATA_DIR")" ]]; then
      safe_remove_tree "$configured_data"
    fi
    safe_remove_tree "${PORTAIL_LOG_DIR:-/var/log/${APP_NAME}}"
    if id "$SERVICE_USER" >/dev/null 2>&1; then userdel "$SERVICE_USER" >/dev/null 2>&1 || true; fi
    if getent group "$SERVICE_GROUP" >/dev/null && ! getent passwd | awk -F: -v g="$(getent group "$SERVICE_GROUP" | cut -d: -f3)" '$4==g{found=1} END{exit !found}'; then
      groupdel "$SERVICE_GROUP" >/dev/null 2>&1 || true
    fi
    ok "Application, configuration, secrets, PDF, index, catalogues, historique, cache, tâches, logs, sauvegardes, unités et compte système supprimés."
  else
    ok "Application supprimée ; configuration et données conservées."
  fi
}

apply_config_command() {
  stage 1 3 "Validation de la configuration"
  require_root; require_systemd
  PORTAIL_CONFIG="$CONFIG_FILE" PORTAIL_SECRETS="$SECRETS_FILE" PYTHONPATH="$INSTALL_DIR" \
    "$INSTALL_DIR/venv-web/bin/python" -m app.manage validate-config

  stage 2 3 "Actualisation des planifications"
  apply_system_update_schedule

  stage 3 3 "Redémarrage du portail"
  systemctl restart "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null
  ok "Configuration appliquée, planification actualisée et portail redémarré."
}

system_update_execute_command() {
  stage 1 3 "Vérification de la planification et du verrou"
  require_root; require_systemd; check_platform
  local enabled
  enabled="$(python3 - "$CONFIG_FILE" <<'PY_PACKAGE_ENABLED'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("true" if payload.get("maintenance", {}).get("weekly_package_update_enabled", True) else "false")
PY_PACKAGE_ENABLED
)"
  [[ "$enabled" == "true" ]] || { warn "Mise à jour système désactivée ; aucune action."; return 0; }
  install -d -m 0755 /run/lock
  exec 9>"/run/lock/${APP_NAME}-system-update.lock"
  flock -n 9 || { warn "Une mise à jour système est déjà en cours."; return 0; }
  stage 2 3 "Mise à jour des paquets APT"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade --with-new-pkgs

  stage 3 3 "Redémarrage de la machine"
  ok "Mise à jour des paquets terminée."
  sync
  systemctl reboot
}

service_control_command() {
  local action="$1" action_label
  case "$action" in
    start) action_label="Démarrage" ;;
    stop) action_label="Arrêt" ;;
    restart) action_label="Redémarrage" ;;
    *) die "Action de service inconnue : $action" ;;
  esac
  stage 1 1 "${action_label} des services applicatifs"
  require_root; require_systemd
  systemctl "$action" "${APP_NAME}-web.service" "${APP_NAME}-ocr-worker.service" "${APP_NAME}-catalog-worker.service" >/dev/null
  ok "Services applicatifs : ${action_label,,} terminé."
}

set_admin_password_command() {
  stage 1 2 "Définition du mot de passe administrateur"
  require_root; require_systemd
  PORTAIL_CONFIG="$CONFIG_FILE" PORTAIL_SECRETS="$SECRETS_FILE" PYTHONPATH="$INSTALL_DIR" \
    "$INSTALL_DIR/venv-web/bin/python" -m app.manage set-admin-password --no-restart-hint
  chown root:"$SERVICE_GROUP" "$SECRETS_FILE"
  chmod 0640 "$SECRETS_FILE"

  stage 2 2 "Redémarrage du service web"
  systemctl restart "${APP_NAME}-web.service" >/dev/null
  ok "Mot de passe administrateur modifié et sessions précédentes invalidées."
}

retry_ocr_command() {
  stage 1 1 "Mise en file des PDF non indexés"
  require_root
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage enqueue-missing-ocr
}

cleanup_command() {
  stage 1 1 "Nettoyage des fichiers temporaires"
  require_root
  run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.manage cleanup
}

usage() {
  cat <<EOF_USAGE
Usage : sudo ./run_server.sh COMMANDE

  install                 Installe ou met à niveau ; configure ntfy et le mot de passe admin.
  ntfy-test               Envoie une notification de test (ou la conserve si hors ligne).
  start|stop|restart      Gère les trois services applicatifs.
  status                  Affiche l'état des services et du socket.
  health                  Interroge /api/health.
  logs [N]                Suit les logs applicatifs locaux.
  set-admin-password      Redéfinit le mot de passe administrateur.
  retry-ocr               Met en file les PDF non indexés.
  migrate                 Importe explicitement les données des anciens bundles.
  backup [--output PATH]  Sauvegarde données, configuration et secrets.
  restore ARCHIVE         Restaure transactionnellement une sauvegarde complète.
  cleanup                 Nettoie les fichiers temporaires et anciens travaux.
  apply-config            Valide la configuration, actualise les timers puis redémarre le portail.
  system-update-execute   Exécute la mise à jour APT planifiée puis redémarre la machine.
  uninstall [--purge]     Désinstalle ; --purge supprime absolument toutes les données.
EOF_USAGE
}

command="${1:-}"
print_header "${command:-aide}"
case "$command" in
  install) install_command ;;
  start|stop|restart) service_control_command "$command" ;;
  status) status_command ;;
  health) health_command ;;
  cloudflare-health) cloudflare_health_command ;;
  ntfy-test) require_root; run_as_service "$INSTALL_DIR/venv-web/bin/python" -m app.notifications --test ;;
  logs) logs_command "$@" ;;
  set-admin-password) set_admin_password_command ;;
  retry-ocr) retry_ocr_command ;;
  migrate) migrate_command ;;
  backup) backup_command "$@" ;;
  restore) restore_command "$@" ;;
  cleanup) cleanup_command ;;
  apply-config) apply_config_command ;;
  system-update-execute) system_update_execute_command ;;
  uninstall) uninstall_command "$@" ;;
  -h|--help|help|'') usage ;;
  *) usage; die "Commande inconnue : $command" ;;
esac
