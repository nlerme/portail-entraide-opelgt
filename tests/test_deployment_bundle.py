from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repository_has_no_runtime_secrets_or_data():
    forbidden_names = {"config.json", "secrets.json"}
    forbidden_suffixes = {".db", ".sqlite", ".sqlite3", ".log", ".zip", ".tar.gz"}
    bundled_documents = ROOT / "resources" / "documents"
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".runtime" in path.parts:
            continue
        assert path.name not in forbidden_names
        assert not any(path.name.endswith(suffix) for suffix in forbidden_suffixes)
        if path.suffix.lower() == ".pdf":
            assert path.is_relative_to(bundled_documents)


def test_examples_are_valid_and_secret_free():
    config = json.loads((ROOT / "config.example.json").read_text())
    secrets = json.loads((ROOT / "secrets.example.json").read_text())
    assert config["server"]["host"] == "0.0.0.0"
    assert config["authentication"]["allow_insecure_lan_http"] is True
    assert config["authentication"]["allow_insecure_remote_http"] is False
    assert config["sessions"]["duration_minutes"] == 30
    assert config["maintenance"]["weekly_catalog_update_day"] == "Monday,Wednesday,Friday"
    assert config["maintenance"]["weekly_catalog_update_time"] == "02:00"
    assert config["maintenance"]["weekly_package_update_enabled"] is True
    assert config["maintenance"]["weekly_package_update_day"] == "Wednesday"
    assert config["maintenance"]["weekly_package_update_time"] == "00:00"
    assert secrets == {
        "app_secret": "", "admin_password_hash": "",
        "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": "", "auth": "none", "interval_days": 1},
    }


def test_scripts_and_javascript_syntax():
    subprocess.run(["bash", "-n", str(ROOT / "run_server.sh")], check=True)
    for script in ROOT.rglob("*.js"):
        subprocess.run(["node", "--check", str(script)], check=True, capture_output=True)




def test_run_server_header_and_numbered_steps_are_always_available():
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    result = subprocess.run(
        ["bash", str(ROOT / "run_server.sh"), "--help"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Portail Entraide Opel GT" in result.stdout
    assert "Linux serveur · version 1.1.27" in result.stdout
    assert "Auteur : Nicolas Lermé · Commande : --help" in result.stdout
    script = (ROOT / "run_server.sh").read_text(encoding="utf-8")
    assert 'stage 1 8 "Vérification de la plateforme et options d’accès"' in script
    assert 'stage 5 8 "Environnements Python et configuration — cette étape peut prendre plusieurs minutes"' in script
    assert 'stage 8 8 "Mot de passe administrateur et accès distant"' in script
    assert 'read -r -p "Souhaitez-vous utiliser un tunnel Cloudflare ? [o/N] "' in script
    assert 'read -r -s -p "Jeton du tunnel Cloudflare (saisie masquée) : "' in script


def test_session_timer_counts_down_warns_and_expires_once():
    script_path = ROOT / "static/common/session_timer.js"
    node_script = f"""
let nowMs = 1_000_000;
let tick = null;
let expired = 0;
const classes = {{}};
global.Date.now = () => nowMs;
global.window = {{
  clearInterval: () => {{}},
  setInterval: (callback) => {{ tick = callback; return 1; }},
}};
require({json.dumps(str(script_path))});
const element = {{
  textContent: '',
  classList: {{ toggle: (name, enabled) => {{ classes[name] = Boolean(enabled); }} }},
}};
window.SessionTimer.start({{
  expiresAt: 1600,
  serverTime: 1000,
  durationMinutes: 10,
  element,
  onExpire: () => {{ expired += 1; }},
}});
if (element.textContent !== 'Temps restant avant déconnexion : 10:00' || !classes['session-safe']) throw new Error('safe');
nowMs = 1_301_000;
tick();
if (element.textContent !== 'Temps restant avant déconnexion : 4:59' || !classes['session-middle']) throw new Error('middle');
nowMs = 1_541_000;
tick();
if (element.textContent !== 'Temps restant avant déconnexion : 0:59' || !classes['session-critical']) throw new Error('critical');
nowMs = 1_601_000;
tick();
if (element.textContent !== 'Temps restant avant déconnexion : 0:00' || !classes['session-expired'] || expired !== 1) throw new Error('expiry');
tick();
if (expired !== 1) throw new Error('expiry repeated');
"""
    subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)


def test_systemd_units_have_required_security_and_socket_permissions():
    web = (ROOT / "systemd/portail-entraide-opel-gt-web.service").read_text()
    socket = (ROOT / "systemd/portail-entraide-opel-gt-control.socket").read_text()
    tmpfiles = (ROOT / "systemd/portail-entraide-opel-gt.tmpfiles").read_text()
    for directive in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true"):
        assert directive in web
    assert "SocketGroup=opelgt" in socket
    assert "SocketMode=0660" in socket
    assert "DirectoryMode=0750" in socket
    assert "0750 root opelgt" in tmpfiles


def test_install_script_contains_two_venvs_and_complete_purge():
    script = (ROOT / "run_server.sh").read_text()
    assert "venv-web" in script and "venv-ocr" in script
    assert "sha256sum -c requirements.lock.sha256" in script
    assert "iputils-ping" in script
    assert "set-admin-password --no-restart-hint" in script
    assert 'PYTHONPATH="$INSTALL_DIR"' in script
    assert 'migrate_default_network_binding' in script
    assert 'migrate_login_rate_limits' in script
    assert 'migrate_session_duration' in script
    assert 'migrate_catalog_schedule' in script
    assert 'migrate_package_update_schedule' in script
    assert 'reset-catalog-schedule-state' in script
    assert '"${APP_NAME}-catalog-update.service"' in script
    install_body = script.split("install_command()", 1)[1].split("print_access()", 1)[0]
    assert 'app.manage migrate' not in install_body
    assert 'enqueue_initial_background_work' in install_body
    assert 'enqueue-initial-catalogs' in script
    assert 'login_rate_limit_attempts' in script
    assert 'login_rate_limit_window_seconds' in script
    assert 'server["host"] = "0.0.0.0"' in script
    assert 'Adresse du portail' in script
    assert 'systemctl restart "${APP_NAME}-web.service"' in script
    assert 'prompt_cloudflare_tunnel' in script
    assert 'https://pkg.cloudflare.com/cloudflare-main.gpg' in script
    assert 'cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN"' in script
    assert 'system-update-execute' in script
    assert 'upgrade --with-new-pkgs' in script
    assert 'safe_remove_tree "$CONFIG_DIR"' in script
    assert 'safe_remove_tree "$DATA_DIR"' in script
    assert 'configured_data_dir' in script
    assert 'migrate_command()' in script
    assert 'reset-catalog-schedule-state' in script.split('migrate_command()', 1)[1].split('backup_command()', 1)[0]
    assert "PDF, index, catalogues, historique, cache, tâches, logs, sauvegardes" in script


def test_uninstall_purge_removes_every_test_path(tmp_path):
    install = tmp_path / "opt"
    config = tmp_path / "etc"
    data = tmp_path / "var"
    run = tmp_path / "run"
    units = tmp_path / "units"
    tmpfiles = tmp_path / "tmpfiles"
    logs = tmp_path / "logs"
    custom_data = tmp_path / "custom/data-root"
    for directory in (install, config, data, run, units, tmpfiles, logs, custom_data):
        directory.mkdir(parents=True)
        if directory not in (units, tmpfiles):
            (directory / "sentinel").write_text("x")
    for unit in (ROOT / "systemd").glob("portail-entraide-opel-gt-*.*"):
        if unit.suffix in {".service", ".socket", ".timer"}:
            (units / unit.name).write_text("unit")
    (tmpfiles / "portail-entraide-opel-gt.conf").write_text("tmpfiles")
    (config / "config.json").write_text(json.dumps({"storage": {"data_dir": str(custom_data)}}), encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for command in ("systemctl",):
        target = fakebin / command
        target.write_text("#!/bin/sh\nexit 0\n")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env.update({
        "PATH": f"{fakebin}:{env['PATH']}", "PORTAIL_INSTALL_DIR": str(install),
        "PORTAIL_CONFIG_DIR": str(config), "PORTAIL_DATA_DIR": str(data), "PORTAIL_RUN_DIR": str(run),
        "PORTAIL_SYSTEMD_UNIT_DIR": str(units), "PORTAIL_TMPFILES_DIR": str(tmpfiles),
        "PORTAIL_LOG_DIR": str(logs), "PORTAIL_SERVICE_USER": "portail-test-user-does-not-exist",
        "PORTAIL_SERVICE_GROUP": "portail-test-group-does-not-exist",
    })
    result = subprocess.run(["bash", str(ROOT / "run_server.sh"), "uninstall", "--purge"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    for directory in (install, config, data, run, logs, custom_data):
        assert not directory.exists()
    assert not any(units.iterdir())
    assert not any(tmpfiles.iterdir())


def test_readme_references_all_current_screenshots():
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    for name in (
        "connexion-membres.png", "liste-services.png", "recherche-bulletins.png",
        "comparateur-pieces.png", "couples-serrage.png", "connexion-administration.png",
        "administration.png",
    ):
        assert name in readme


def test_bundled_reference_resources_are_complete_and_consistent():
    data_path = ROOT / "resources/couples/couples_serrage.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 61
    assert len(payload["rows"]) == 61
    assert payload["sections"] == ["Moteur", "Direction", "Suspension avant", "Suspension arrière", "Freins"]
    assert payload["views"][0]["pdf"] == "/documents/vue-eclatee-1.pdf"
    assert any(row["views"]["1"] == "23" for row in payload["rows"])
    assert any(row["views"]["2"] == "19" for row in payload["rows"])
    assert any(row["views"]["3"] == "41" for row in payload["rows"])
    assert next(row for row in payload["rows"] if row["id"] == 27)["views"]["1"] == "5, 4"
    assert next(row for row in payload["rows"] if row["id"] == 17)["views"]["3"] == "44+"
    for view in payload["views"]:
        assert view["markers"], f"Aucun marqueur pour la vue {view['id']}"
        marker_refs = {str(marker["reference"]) for marker in view["markers"]}
        assert view["image_width"] > 0 and view["image_height"] > 0
        for marker in view["markers"]:
            assert 0 <= float(marker["x_percent"]) <= 100
            assert 0 <= float(marker["y_percent"]) <= 100
            assert 0 <= int(marker["x_px"]) <= int(view["image_width"])
            assert 0 <= int(marker["y_px"]) <= int(view["image_height"])
        row_refs = set()
        for row in payload["rows"]:
            raw = str(row["views"].get(str(view["id"]), ""))
            for chunk in raw.split(","):
                match = re.search(r"\d+\s*\+?", chunk)
                if match:
                    row_refs.add(re.sub(r"\s+", "", match.group(0)))
        assert row_refs <= marker_refs
    expected = {
        "fiche-intervention.pdf", "inventaire-avant-deplacement.pdf", "liste-visserie-opel-gt.pdf",
        "couples-serrage-opel-gt.pdf",
        "vue-eclatee-1.pdf", "vue-eclatee-2.pdf", "vue-eclatee-3.pdf",
        "vue-eclatee-1.jpg", "vue-eclatee-2.jpg", "vue-eclatee-3.jpg",
    }
    documents = ROOT / "resources/documents"
    assert expected == {path.name for path in documents.iterdir() if path.is_file()}
    for name in expected:
        content = (documents / name).read_bytes()
        if name.endswith(".pdf"):
            assert content.startswith(b"%PDF-")
        else:
            assert content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9")
    assert (ROOT / "resources/couples/couples_serrage.xlsx").read_bytes().startswith(b"PK")


def test_shop_availability_wait_message_is_emphasized():
    html = (ROOT / "static/pieces/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/pieces/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/pieces/styles.css").read_text(encoding="utf-8")
    assert "sites-state-checking" in html
    assert "<strong>Vérification de la disponibilité des boutiques…</strong>" in html
    assert "Merci de patienter quelques secondes." in html
    assert "sites-state-checking" in script
    assert ".sites-state-checking" in css and "color: var(--danger)" in css


def test_couples_markers_target_numbers_and_use_category_colours():
    payload = json.loads((ROOT / "resources/couples/couples_serrage.json").read_text(encoding="utf-8"))
    script = (ROOT / "static/couples/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/couples/styles.css").read_text(encoding="utf-8")
    html = (ROOT / "static/couples/index.html").read_text(encoding="utf-8")
    assert "Chaque petit cercle est centré sur le numéro imprimé" in payload["source_note"]
    assert len(payload["views"][0]["markers"]) == 19
    assert len(payload["views"][1]["markers"]) == 10
    assert len(payload["views"][2]["markers"]) == 5
    assert "SECTION_CLASS_NAMES" in script
    assert "MARKER_RADIUS = 27" in script
    assert "MARKER_HIT_RADIUS = 45" in script
    assert "markerSegmentsMarkup" in script
    assert "marker.x_px" in script and "marker.y_px" in script
    assert 'transform="translate(' in script
    assert 'style="' not in script
    assert "marker-segment" in script and "marker-halo" in script
    assert "--section-steering" in css and "--section-front-suspension" in css and "--section-brakes" in css
    assert ".marker-segment.section-steering" in css
    assert ".part-card.section-engine" in css and ".part-card.section-brakes" in css
    assert '<svg id="diagramMarkers"' in html
    assert 'id="categoryLegend"' in html


def test_couples_page_has_bidirectional_visual_mapping_and_dynamic_views():
    html = (ROOT / "static/couples/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/couples/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/couples/styles.css").read_text(encoding="utf-8")
    services = (ROOT / "static/common/services.html").read_text(encoding="utf-8")
    assert '<h2>Fiche d’inventaire</h2>' in services
    assert 'class="reference-workspace split-38"' in html
    assert 'id="partsList"' in html
    assert 'id="viewSelect"' in html
    assert 'id="diagramMarkers"' in html
    assert 'id="selectedPartDetail"' in html
    assert 'id="markerMatches"' in html
    assert 'href="/documents/liste-visserie-opel-gt.pdf"' in html
    assert 'href="/documents/couples-serrage-opel-gt.pdf"' in html
    assert 'href="/documents/couples-serrage-opel-gt.xlsx"' in html
    assert "Conversion N·m → m·kg" in html
    assert "Documentation pratique" not in html
    assert "Version vérifiée sur les vues" not in html
    assert "Télécharger le PDF des couples" in html
    assert "Télécharger le fichier Excel des couples" in html
    assert "Télécharger le PDF de visserie" in html
    assert html.count('target="_blank"') >= 4
    assert 'value="1"' not in html and 'value="2"' not in html and 'value="3"' not in html
    for token in (
        "rowMappings", "referencesForRowInView", "rowsForReference", "renderPartsList",
        "renderView", "selectPart", "selectMarker", "centerSelectedMarker",
        "state.payload.views", "view.markers", "marker-match-button",
    ):
        assert token in script
    assert 'id="workspaceSplitter"' in html
    assert 'id="togglePartsPane"' in html
    assert 'role="separator"' in html
    assert ".reference-workspace" in css
    assert ".workspace-splitter" in css
    assert ".reference-workspace.is-parts-collapsed" in css
    assert ".reference-workspace.split-38" in css
    assert "applySplitPercent" in script
    assert "setPartsPaneCollapsed" in script
    assert "resizeFromPointer" in script
    assert "setPointerCapture" in script
    assert "SPLIT_STORAGE_KEY" in script
    assert ".part-card.is-selected" in css
    assert ".mapping-marker.is-selected" in css
    assert ".marker-selected-ring" in css
    assert ".marker-hit-area" in css
    assert ".portal-footer .footer-bottom{display:grid" in (ROOT / "static/common/footer.css").read_text()
    assert "height:var(--workspace-height)" in css


def test_all_web_pages_load_common_responsive_baseline():
    pages = list((ROOT / "static").rglob("*.html"))
    assert len(pages) == 7
    for page in pages:
        assert '/static/common/responsive.css?v=1.1.27' in page.read_text(encoding="utf-8")
    css = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8")
    assert "overflow-x:hidden" in css
    assert ".portal-nav" in css and "overflow-x:auto" in css


def test_repository_is_ready_for_github_ci():
    assert (ROOT / ".gitattributes").is_file()
    assert (ROOT / "CONTRIBUTING.md").is_file()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.11"' in workflow
    assert "python -W error -m pytest -q" in workflow
    assert "ruff check ." in workflow
    assert "shellcheck run_server.sh" in workflow
    assert "*.pdf binary" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_service_pages_use_common_session_and_namespaced_apis():
    bulletin_html = (ROOT / "static/bulletins/index.html").read_text(encoding="utf-8")
    pieces_html = (ROOT / "static/pieces/index.html").read_text(encoding="utf-8")
    couples_html = (ROOT / "static/couples/index.html").read_text(encoding="utf-8")
    bulletin_js = (ROOT / "static/bulletins/app.js").read_text(encoding="utf-8")
    pieces_js = (ROOT / "static/pieces/app.js").read_text(encoding="utf-8")
    couples_js = (ROOT / "static/couples/app.js").read_text(encoding="utf-8")
    for html in (bulletin_html, pieces_html, couples_html):
        assert 'id="loginDialog"' not in html
        assert 'id="sessionRemaining"' in html
    assert "/api/bulletins/" in bulletin_js
    assert "/api/pieces/connectivity" in pieces_js
    assert "/api/pieces/sites" in pieces_js
    assert "/api/couples" in couples_js
    assert "/api/connectivity" not in pieces_js.replace("/api/pieces/connectivity", "")
    assert "/api/sites" not in pieces_js.replace("/api/pieces/sites", "")


def _isolated_manage_environment(tmp_path: Path) -> dict[str, str]:
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config["server"]["port"] = 18181
    config["storage"]["data_dir"] = str(tmp_path / "data")
    config_path = tmp_path / "etc/config.json"
    secrets_path = tmp_path / "etc/secrets.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    secrets_path.write_text(
        json.dumps({"app_secret": "a" * 48, "admin_password_hash": "$argon2id$test"}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "PORTAIL_CONFIG": str(config_path),
        "PORTAIL_SECRETS": str(secrets_path),
        "PORTAIL_DATA_DIR": str(tmp_path / "data"),
    })
    return env


def test_backup_restore_is_transactional(tmp_path):
    env = _isolated_manage_environment(tmp_path)
    subprocess.run(["python", "-m", "app.manage", "initialize"], cwd=ROOT, env=env, check=True, capture_output=True)
    sentinel = tmp_path / "data/sentinel.txt"
    sentinel.write_text("original", encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"
    subprocess.run(
        ["python", "-m", "app.manage", "backup", "--output", str(archive)],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    sentinel.write_text("modified", encoding="utf-8")
    config_path = Path(env["PORTAIL_CONFIG"])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["server"]["port"] = 19191
    config_path.write_text(json.dumps(config), encoding="utf-8")
    Path(env["PORTAIL_SECRETS"]).write_text(
        json.dumps({"app_secret": "b" * 48, "admin_password_hash": "changed"}),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["python", "-m", "app.manage", "restore", str(archive)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text(encoding="utf-8") == "original"
    assert json.loads(config_path.read_text(encoding="utf-8"))["server"]["port"] == 18181
    restored_secrets = json.loads(Path(env["PORTAIL_SECRETS"]).read_text(encoding="utf-8"))
    assert restored_secrets["app_secret"] == "a" * 48
    assert restored_secrets["admin_password_hash"] == "$argon2id$test"
    assert not list(tmp_path.rglob("*restore-rollback*"))
    assert not list(tmp_path.rglob("*.restore-new"))


def test_restore_rejects_path_traversal(tmp_path):
    import io
    import tarfile

    env = _isolated_manage_environment(tmp_path)
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escape")
        payload = b"forbidden"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    result = subprocess.run(
        ["python", "-m", "app.manage", "restore", str(archive)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Chemin interdit" in result.stderr
    assert not (tmp_path.parent / "escape").exists()


def _network_binding_function() -> str:
    script = (ROOT / "run_server.sh").read_text(encoding="utf-8")
    start = script.index("migrate_default_network_binding() {")
    end = script.index("\n\nconfigure_files() {", start)
    return script[start:end]


def test_upgrade_migrates_only_the_untouched_loopback_binding(tmp_path):
    default_config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    default_config["server"]["host"] = "127.0.0.1"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config), encoding="utf-8")
    shell = f'''set -Eeuo pipefail
CONFIG_FILE={str(config_path)!r}
{_network_binding_function()}
migrate_default_network_binding
'''
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    assert json.loads(config_path.read_text(encoding="utf-8"))["server"]["host"] == "0.0.0.0"

    explicit_proxy = default_config
    explicit_proxy["server"]["host"] = "127.0.0.1"
    explicit_proxy["server"]["public_url"] = "https://portail.example.test"
    explicit_proxy["server"]["trusted_proxies"] = ["127.0.0.1/32"]
    config_path.write_text(json.dumps(explicit_proxy), encoding="utf-8")
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    assert json.loads(config_path.read_text(encoding="utf-8"))["server"]["host"] == "127.0.0.1"


def test_real_server_is_reachable_on_a_non_loopback_ipv4_address(tmp_path):
    import socket
    import sys
    import time
    import urllib.error
    import urllib.request

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        server_ip = probe.getsockname()[0]
    finally:
        probe.close()
    assert not server_ip.startswith("127."), f"Aucune adresse IPv4 non loopback disponible : {server_ip}"

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("0.0.0.0", 0))
    port = listener.getsockname()[1]
    listener.close()

    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config["server"]["host"] = "0.0.0.0"
    config["server"]["port"] = port
    config["authentication"]["login_url"] = "https://127.0.0.1:9/login"
    config["authentication"]["validation_url"] = "https://127.0.0.1:9/member"
    config["authentication"]["request_timeout_seconds"] = 1
    config["storage"]["data_dir"] = str(tmp_path / "data")
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    secrets_path.write_text(json.dumps({"app_secret": "x" * 96, "admin_password_hash": ""}), encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "PORTAIL_CONFIG": str(config_path),
        "PORTAIL_SECRETS": str(secrets_path),
        "PORTAIL_DATA_DIR": str(tmp_path / "data"),
        "NO_PROXY": "*",
        "no_proxy": "*",
    })
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "server_entry.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://{server_ip}:{port}/api/health"
    try:
        last_error = None
        for _ in range(80):
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(f"Le serveur s'est arrêté prématurément.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
            try:
                with opener.open(url, timeout=0.5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                assert payload["ok"] is True
                assert payload["version"] == "1.1.27"
                login_request = urllib.request.Request(
                    f"http://{server_ip}:{port}/api/login",
                    data=json.dumps({"login": "test-local", "password": "test-local"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    opener.open(login_request, timeout=3)
                except urllib.error.HTTPError as login_error:
                    assert login_error.code != 403, "La connexion HTTP depuis le LAN ne doit pas être bloquée."
                break
            except Exception as exc:  # noqa: BLE001 - polling startup
                last_error = exc
                time.sleep(0.1)
        else:
            raise AssertionError(f"Le portail n'est pas joignable via {url}: {last_error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def test_catalog_timer_runs_monday_wednesday_friday_at_2am_without_catchup():
    timer = (ROOT / "systemd/portail-entraide-opel-gt-catalog-update.timer").read_text(encoding="utf-8")
    assert "OnCalendar=Mon,Wed,Fri *-*-* 02:00:00 Europe/Paris" in timer
    assert "Persistent=false" in timer
    assert "AccuracySec=1s" in timer
    assert "RandomizedDelaySec" not in timer


def test_weekly_system_update_timer_is_configurable_and_reboots(tmp_path):
    timer = (ROOT / "systemd/portail-entraide-opel-gt-system-update.timer").read_text(encoding="utf-8")
    service = (ROOT / "systemd/portail-entraide-opel-gt-system-update.service").read_text(encoding="utf-8")
    assert "OnCalendar=Wed *-*-* 00:00:00 Europe/Paris" in timer
    assert "Persistent=false" in timer
    assert "AccuracySec=1s" in timer
    assert "User=root" in service
    assert "run_server.sh system-update-execute" in service
    assert "TimeoutStartSec=6h" in service

    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config["maintenance"]["weekly_package_update_enabled"] = True
    config["maintenance"]["weekly_package_update_day"] = "Friday"
    config["maintenance"]["weekly_package_update_time"] = "23:45"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    units = tmp_path / "units"
    units.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake_systemctl = fakebin / "systemctl"
    fake_systemctl.write_text(f"#!/bin/sh\nprintf '%s\n' \"$*\" >> {str(systemctl_log)!r}\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    shell = (
        "set -Eeuo pipefail\n"
        f"PATH={str(fakebin)!r}:$PATH\n"
        "APP_NAME=portail-entraide-opel-gt\n"
        f"CONFIG_FILE={str(config_path)!r}\n"
        f"SYSTEMD_UNIT_DIR={str(units)!r}\n"
        "die(){ echo \"$*\" >&2; exit 1; }\n"
        "ok(){ :; }\nwarn(){ :; }\n"
        f"{_shell_function('apply_system_update_schedule', 'stop_current_services')}\n"
        "apply_system_update_schedule\n"
    )
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    generated = (units / "portail-entraide-opel-gt-system-update.timer").read_text(encoding="utf-8")
    assert "OnCalendar=Fri *-*-* 23:45:00 Europe/Paris" in generated
    assert "enable --now portail-entraide-opel-gt-system-update.timer" in systemctl_log.read_text(encoding="utf-8")

    config["maintenance"]["weekly_package_update_enabled"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    assert "disable --now portail-entraide-opel-gt-system-update.timer" in systemctl_log.read_text(encoding="utf-8")


def test_system_update_command_runs_apt_with_new_packages_then_reboots(tmp_path):
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    command_log = tmp_path / "commands.log"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name in ("apt-get", "systemctl", "sync"):
        command = fakebin / name
        command.write_text(f"#!/bin/sh\nprintf '{name} %s\n' \"$*\" >> {str(command_log)!r}\n", encoding="utf-8")
        command.chmod(0o755)
    shell = (
        "set -Eeuo pipefail\n"
        f"PATH={str(fakebin)!r}:$PATH\n"
        "APP_NAME=portail-entraide-opel-gt-test-system-update\n"
        f"CONFIG_FILE={str(config_path)!r}\n"
        "require_root(){ :; }\nrequire_systemd(){ :; }\ncheck_platform(){ :; }\n"
        "info(){ :; }\nok(){ :; }\nwarn(){ :; }\nstage(){ :; }\n"
        f"{_shell_function('system_update_execute_command', 'usage')}\n"
        "system_update_execute_command\n"
    )
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    logged = command_log.read_text(encoding="utf-8")
    assert "apt-get update" in logged
    assert "apt-get -y" in logged and "upgrade --with-new-pkgs" in logged
    assert "systemctl reboot" in logged

    command_log.write_text("", encoding="utf-8")
    config["maintenance"]["weekly_package_update_enabled"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    assert command_log.read_text(encoding="utf-8") == ""
    Path("/run/lock/portail-entraide-opel-gt-test-system-update-system-update.lock").unlink(missing_ok=True)


def test_cloudflare_tunnel_installer_uses_official_service_flow_and_hidden_token():
    script = (ROOT / "run_server.sh").read_text(encoding="utf-8")
    prompt = script[script.index("prompt_cloudflare_tunnel()") : script.index("install_cloudflared_package()")]
    install = script[script.index("install_cloudflared_package()") : script.index("run_as_service()")]
    assert "Networking" in prompt and "Tunnels" in prompt and "Add a replica" in prompt
    assert 'read -r -s -p "Jeton du tunnel Cloudflare' in prompt
    assert "commençant par « eyJ »" in prompt
    assert "https://pkg.cloudflare.com/cloudflare-main.gpg" in install
    assert "https://pkg.cloudflare.com/cloudflared any main" in install
    assert 'cloudflared service install "$CLOUDFLARE_TUNNEL_TOKEN"' in install
    assert "systemctl restart cloudflared.service" in install
    assert "redémarrera automatiquement après chaque reboot" in install


def test_admin_can_apply_package_schedule_after_editing_configuration():
    html = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    helper = (ROOT / "server_control.py").read_text(encoding="utf-8")
    control = (ROOT / "app/common/control_client.py").read_text(encoding="utf-8")
    assert "maintenance.weekly_package_update_*" in html
    assert 'data-control="apply-config"' in html
    assert '"apply-config"' in helper
    assert 'action in {"restart", "stop", "apply-config"}' in helper
    assert '"apply-config"' in control


def test_services_api_contains_no_catalog_enqueue_trigger():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    start = source.index('@app.get("/api/services")')
    end = source.index("# Bulletins", start)
    endpoint = source[start:end]
    assert "enqueue(" not in endpoint
    assert "start_catalog_sync" not in endpoint
    assert "_ensure_automatic_catalog_sync" not in source


def test_installation_restores_extracted_directory_ownership(tmp_path):
    if os.geteuid() != 0:
        return
    source = tmp_path / "portail-entraide-opel-gt"
    source.mkdir()
    script = source / "run_server.sh"
    script.write_text((ROOT / "run_server.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (source / "VERSION").write_text((ROOT / "VERSION").read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    nested = source / "nested"
    nested.mkdir()
    (nested / "file.txt").write_text("x", encoding="utf-8")
    os.chown(source, 0, 0)
    os.chown(script, 0, 0)
    os.chown(nested, 0, 0)
    os.chown(nested / "file.txt", 0, 0)
    env = os.environ.copy()
    env.update({"SUDO_UID": "65534", "SUDO_GID": "65534"})
    result = subprocess.run(["bash", str(script), "help"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert source.stat().st_uid == 65534
    assert (nested / "file.txt").stat().st_uid == 65534
    os.chown(source, 0, 0)
    os.chown(script, 0, 0)
    os.chown(nested, 0, 0)
    os.chown(nested / "file.txt", 0, 0)

def _shell_function(name: str, following: str) -> str:
    script = (ROOT / "run_server.sh").read_text(encoding="utf-8")
    start = script.index(f"{name}() {{")
    end = script.index(f"\n{following}() {{", start)
    return script[start:end]


def test_upgrade_migrates_session_catalog_and_package_update_settings(tmp_path):
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config["sessions"]["duration_minutes"] = 10
    config["authentication"]["session_hours"] = 8
    config["admin"]["session_hours"] = 2
    config["maintenance"]["weekly_catalog_update_day"] = "Wednesday"
    config["maintenance"]["weekly_catalog_update_time"] = "14:30"
    for key in ("weekly_package_update_enabled", "weekly_package_update_day", "weekly_package_update_time"):
        config["maintenance"].pop(key, None)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    custom = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    custom["maintenance"]["weekly_package_update_enabled"] = False
    custom["maintenance"]["weekly_package_update_day"] = "Friday"
    custom["maintenance"]["weekly_package_update_time"] = "23:45"
    custom_path = tmp_path / "custom.json"
    custom_path.write_text(json.dumps(custom), encoding="utf-8")

    shell = (
        "set -Eeuo pipefail\n"
        f"{_shell_function('migrate_session_duration', 'migrate_catalog_schedule')}\n"
        f"{_shell_function('migrate_catalog_schedule', 'migrate_package_update_schedule')}\n"
        f"{_shell_function('migrate_package_update_schedule', 'configure_files')}\n"
        f"CONFIG_FILE={str(config_path)!r}\n"
        "migrate_session_duration\n"
        "migrate_catalog_schedule\n"
        "migrate_package_update_schedule\n"
        f"CONFIG_FILE={str(custom_path)!r}\n"
        "migrate_package_update_schedule\n"
    )
    subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    migrated = json.loads(config_path.read_text(encoding="utf-8"))
    assert migrated["sessions"]["duration_minutes"] == 30
    assert "session_hours" not in migrated["authentication"]
    assert "session_hours" not in migrated["admin"]
    assert migrated["maintenance"]["weekly_catalog_update_day"] == "Monday,Wednesday,Friday"
    assert migrated["maintenance"]["weekly_catalog_update_time"] == "02:00"
    assert migrated["maintenance"]["weekly_package_update_enabled"] is True
    assert migrated["maintenance"]["weekly_package_update_day"] == "Wednesday"
    assert migrated["maintenance"]["weekly_package_update_time"] == "00:00"
    preserved = json.loads(custom_path.read_text(encoding="utf-8"))["maintenance"]
    assert preserved["weekly_package_update_enabled"] is False
    assert preserved["weekly_package_update_day"] == "Friday"
    assert preserved["weekly_package_update_time"] == "23:45"


def test_services_javascript_hides_progress_and_enables_links_when_idle():
    script_path = ROOT / "static/common/services.js"
    node_script = rf"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(script_path))}, 'utf8').replace(/initialize\(\)\.catch[\s\S]*$/, '');
function element() {{
  const classes = new Set(['hidden']);
  return {{
    textContent: '', value: 0, tabIndex: -1, innerHTML: '', className: '',
    attributes: {{}},
    classList: {{
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
      contains: name => classes.has(name),
    }},
    setAttribute: function(name, value) {{ this.attributes[name] = String(value); }},
    addEventListener: () => {{}},
  }};
}}
const selectors = [
  '#bulletinsStatus','#bulletinsDetail','#bulletinsFrequency','#bulletinsProgress',
  '#bulletinsDownloadBar','#bulletinsDownloadPercent','#bulletinsIndexBar','#bulletinsIndexPercent',
  '#bulletinsCurrent','#bulletinsOpen','#piecesStatus','#piecesDetail','#piecesFrequency',
  '#piecesProgress','#piecesGlobalBar','#piecesGlobalPercent','#piecesCurrent','#piecesSuppliers',
  '#piecesOpen','#logout','#sessionRemaining',
];
const nodes = Object.fromEntries(selectors.map(selector => [selector, element()]));
const context = {{
  console,
  window: {{setTimeout: () => 1, clearTimeout: () => {{}}, SessionTimer: {{start: () => {{}}, stop: () => {{}}}}, location: {{replace: () => {{}}}}}},
  document: {{
    querySelector: selector => nodes[selector],
    querySelectorAll: selector => selector === '.service-card .button' ? [nodes['#bulletinsOpen'], nodes['#piecesOpen']] : [],
  }},
  fetch: async () => {{ throw new Error('fetch not expected'); }},
  setTimeout: () => 1,
}};
vm.createContext(context);
vm.runInContext(source, context);
context.renderBulletins({{running:false, ready:false, available:true, localPdfCount:0, indexedBulletins:0, indexedPages:0, downloadProgressPercent:0, indexProgressPercent:0}});
context.renderPieces({{running:false, ready:false, available:true, availableCatalogs:0, globalProgressPercent:0, suppliers:[]}});
if (!nodes['#bulletinsProgress'].classList.contains('hidden')) throw new Error('bulletins progress visible while idle');
if (!nodes['#piecesProgress'].classList.contains('hidden')) throw new Error('pieces progress visible while idle');
if (nodes['#bulletinsOpen'].attributes['aria-disabled'] !== 'false') throw new Error('bulletins link disabled while idle');
if (nodes['#piecesOpen'].attributes['aria-disabled'] !== 'false') throw new Error('pieces link disabled while idle');
context.renderBulletins({{running:true, downloadRunning:true, indexingRunning:false, ready:true, available:false, localPdfCount:10, indexedBulletins:9, indexedPages:90, downloadProgressPercent:70, indexProgressPercent:0}});
context.renderPieces({{running:true, ready:true, available:false, availableCatalogs:6, globalProgressPercent:0, suppliers:[{{site_name:'Fournisseur',status:'pending',progress_percent:0}}]}});
if (nodes['#bulletinsProgress'].classList.contains('hidden')) throw new Error('bulletins progress hidden while active');
if (nodes['#piecesProgress'].classList.contains('hidden')) throw new Error('pieces progress hidden while active');
if (nodes['#bulletinsOpen'].attributes['aria-disabled'] !== 'true') throw new Error('bulletins link enabled while active');
if (nodes['#piecesOpen'].attributes['aria-disabled'] !== 'true') throw new Error('pieces link enabled while active');
if (nodes['#bulletinsDownloadBar'].className !== 'progress-meter progress-running') throw new Error('download should be blue while running');
if (!nodes['#piecesSuppliers'].innerHTML.includes('progress-pending') || nodes['#piecesSuppliers'].innerHTML.includes('progress-failed')) throw new Error('supplier should be pending before retrieval starts');
context.renderBulletins({{running:true, downloadRunning:false, indexingRunning:true, ready:true, available:false, localPdfCount:10, indexedBulletins:9, indexedPages:90, downloadProgressPercent:100, indexProgressPercent:40, indexTotal:10}});
if (nodes['#bulletinsDownloadBar'].className !== 'progress-meter progress-ok') throw new Error('download should be green at 100 percent');
if (nodes['#bulletinsIndexBar'].className !== 'progress-meter progress-running') throw new Error('index should be blue while running');
"""
    subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)


def test_clean_install_sequence_does_not_import_legacy_catalogues(tmp_path):
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    data_dir = tmp_path / "portal-data"
    config["storage"]["data_dir"] = str(data_dir)
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    secrets_path.write_text(json.dumps({"app_secret": "x" * 96, "admin_password_hash": ""}), encoding="utf-8")
    legacy = tmp_path / "legacy-comparator/catalogues"
    legacy.mkdir(parents=True)
    (legacy / "splendidparts.json").write_text('[{"nom":"Ancienne pièce"}]', encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "PORTAIL_CONFIG": str(config_path),
        "PORTAIL_SECRETS": str(secrets_path),
        "PORTAIL_DATA_DIR": str(data_dir),
    })
    for command in ("initialize", "reset-catalog-schedule-state", "enqueue-initial-catalogs"):
        subprocess.run(
            ["python", "-m", "app.manage", command],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    assert not (data_dir / "pieces/catalogues/splendidparts.json").exists()
    connection = sqlite3.connect(data_dir / "portal/jobs.sqlite3")
    try:
        row = connection.execute("SELECT state,queue FROM jobs WHERE queue='catalogs'").fetchone()
    finally:
        connection.close()
    assert row == ("pending", "catalogs")


def test_bulletin_individual_progress_turns_green_at_completion():
    script_path = ROOT / "static/bulletins/app.js"
    node_script = f"""
const fs = require('fs');
const vm = require('vm');
const full = fs.readFileSync({json.dumps(str(script_path))}, 'utf8');
const source = full.slice(full.indexOf('function renderSyncStatus'), full.indexOf('function renderLastSync'));
function classList() {{
  const values = new Set();
  return {{
    toggle: (name, enabled) => enabled ? values.add(name) : values.delete(name),
    contains: name => values.has(name),
    remove: name => values.delete(name),
    add: name => values.add(name),
  }};
}}
const progressBar = {{style: {{}}, classList: classList()}};
const context = {{
  lastSyncStatus: null,
  lastReadiness: null,
  renderLastSync: () => {{}},
  updateSearchAvailability: () => {{}},
  estimatedRemainingLabel: () => '',
  escapeHtml: value => String(value || ''),
  t: () => '',
  els: {{
    syncProgressPanel: {{classList: classList()}},
    readinessMessage: {{className:'', classList: classList(), textContent:'', innerHTML:''}},
    syncMessage: null,
    progressBar,
    progressText: {{textContent:''}},
    etaText: {{textContent:''}},
    currentFileText: {{textContent:''}},
    syncCounters: {{innerHTML:''}},
  }},
}};
vm.createContext(context);
vm.runInContext(source, context);
context.renderSyncStatus({{
  running: true,
  indexingRunning: false,
  totalSteps: 1,
  completedSteps: 1,
  processingRunning: true,
  readiness: {{ready:false}},
  errors: [],
}});
if (!progressBar.classList.contains('is-complete')) throw new Error('completed bulletin progress is not green');
if (progressBar.classList.contains('is-active')) throw new Error('completed bulletin progress still animated');
"""
    subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)


def test_pieces_individual_progress_starts_pending_instead_of_failed():
    script_path = ROOT / "static/pieces/app.js"
    node_script = f"""
const fs = require('fs');
const vm = require('vm');
const full = fs.readFileSync({json.dumps(str(script_path))}, 'utf8');
const source = full.slice(full.indexOf('function renderCatalogProgress'), full.indexOf('async function loadCatalogSyncStatus'));
const panelClasses = new Set(['hidden']);
const context = {{
  escapeHtml: value => String(value || ''),
  els: {{
    catalogProgressPanel: {{classList: {{toggle: (name, enabled) => enabled ? panelClasses.add(name) : panelClasses.delete(name)}}}},
    catalogGlobalPercent: {{textContent:''}},
    catalogGlobalBar: {{value:0, textContent:'', className:''}},
    catalogCurrentSupplier: {{textContent:''}},
    catalogSupplierProgress: {{innerHTML:''}},
  }},
}};
vm.createContext(context);
vm.runInContext(source, context);
context.renderCatalogProgress(
  {{running:true, queued:false, global_progress_percent:0}},
  [{{site_name:'Fournisseur', status:'pending', progress_percent:0}}],
);
if (panelClasses.has('hidden')) throw new Error('pieces progress hidden while active');
if (context.els.catalogGlobalBar.className !== 'catalog-progress-meter progress-running') throw new Error('global progress not blue while running');
if (!context.els.catalogSupplierProgress.innerHTML.includes('progress-pending')) throw new Error('supplier not pending');
if (context.els.catalogSupplierProgress.innerHTML.includes('progress-failed')) throw new Error('supplier incorrectly failed');
"""
    subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)


def test_correct_inventory_pdf_and_compact_responsive_rules_are_bundled():
    inventory = ROOT / "resources/documents/inventaire-avant-deplacement.pdf"
    assert hashlib.sha256(inventory.read_bytes()).hexdigest() == "5eab6b1845f0a6ce73114da9c95d1a4d0802e9ec1d751f31cce7cd1c022af55f"
    assert b"/AcroForm" in inventory.read_bytes()

    common_css = (ROOT / "static/common/base.css").read_text(encoding="utf-8")
    bulletins_css = (ROOT / "static/bulletins/styles.css").read_text(encoding="utf-8")
    couples_css = (ROOT / "static/couples/styles.css").read_text(encoding="utf-8")
    pieces_css = (ROOT / "static/pieces/styles.css").read_text(encoding="utf-8")
    assert "Sur écran étroit" in common_css
    assert "grid-auto-flow:column" in common_css
    for css in (bulletins_css, couples_css, pieces_css):
        assert "Sur écran étroit" in css
        assert "overflow-x:auto" in css
        assert "position:sticky" in css

    bulletin_html = (ROOT / "static/bulletins/index.html").read_text(encoding="utf-8")
    couples_html = (ROOT / "static/couples/index.html").read_text(encoding="utf-8")
    pieces_html = (ROOT / "static/pieces/index.html").read_text(encoding="utf-8")
    for html in (bulletin_html, couples_html, pieces_html):
        assert 'role="region"' in html
        assert 'tabindex="0"' in html
        assert "défilement horizontal" in html



def test_shared_interface_controls_titles_and_navigation_labels():
    pages = {
        "login": (ROOT / "static/common/login.html").read_text(encoding="utf-8"),
        "services": (ROOT / "static/common/services.html").read_text(encoding="utf-8"),
        "bulletins": (ROOT / "static/bulletins/index.html").read_text(encoding="utf-8"),
        "pieces": (ROOT / "static/pieces/index.html").read_text(encoding="utf-8"),
        "couples": (ROOT / "static/couples/index.html").read_text(encoding="utf-8"),
        "admin": (ROOT / "static/admin/index.html").read_text(encoding="utf-8"),
    }
    assert "<title>Page de connexion membre - Portail Entraide Opel GT</title>" in pages["login"]
    assert "<title>Liste des services - Portail Entraide Opel GT</title>" in pages["services"]
    assert "<title>Recherche bulletins - Portail Entraide Opel GT</title>" in pages["bulletins"]
    assert "<title>Comparateur de pièces - Portail Entraide Opel GT</title>" in pages["pieces"]
    assert "<title>Couples de serrage - Portail Entraide Opel GT</title>" in pages["couples"]
    assert "<title>Page de connexion administrateur - Portail Entraide Opel GT</title>" in pages["admin"]

    assert "Retour à la liste des services" in pages["bulletins"]
    assert "Retour à la liste des services" in pages["pieces"]
    assert "Retour à la liste des services" in pages["couples"]
    assert "Accès à la page d’administration" in pages["bulletins"]
    assert "Accès à la page d’administration" in pages["pieces"]
    assert "Accès à la page d’administration" in pages["couples"]
    assert '<a href="/bulletins" aria-current="page">' not in pages["bulletins"]
    assert '<a href="/pieces" aria-current="page">' not in pages["pieces"]
    assert '<a href="/couples"' not in pages["couples"]
    for name in ("bulletins", "pieces", "couples"):
        nav = pages[name].split('class="portal-nav panel"', 1)[1].split('</nav>', 1)[0]
        assert nav.count('<a ') == 2
        assert 'href="/services"' in nav
        assert 'href="/admin"' in nav

    for name in pages:
        assert 'data-theme="light" data-font="normal"' in pages[name]
        assert '/static/common/portal_ui.js?v=1.1.27' in pages[name]


def test_login_services_and_admin_pages_expose_requested_common_controls():
    login = (ROOT / "static/common/login.html").read_text(encoding="utf-8")
    services = (ROOT / "static/common/services.html").read_text(encoding="utf-8")
    admin = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    for html in (login, services, admin):
        assert "data-connectivity-status" in html
        assert "data-ui-theme" in html
        assert "data-ui-font-decrease" in html
        assert "data-ui-font-increase" in html
    assert "Temps restant avant déconnexion" not in login
    assert 'class="login-controls login-controls-inline"' in login
    assert "Temps restant avant déconnexion" in services
    assert "Temps restant avant déconnexion" in admin
    assert "session inactive" not in admin
    assert 'id="adminLoginSessionState"' not in admin
    assert 'class="login-controls admin-login-controls admin-login-controls-inline"' in admin
    assert "Se déconnecter" in services
    assert "services-actions" not in services
    assert "Opel GT 1968-1973 : « Seul le vol procure plus de sensations »." in services
    assert "Sélection d'un service" in services
    assert "Choisissez un service lorsque ses données sont prêtes." in services
    assert "Page d'administration du portail" in admin
    assert "Supervision du portail, des bulletins, des catalogues et des tâches de fond." in admin
    assert 'id="refresh"' not in admin
    assert ">Actualiser<" not in admin


def test_display_preferences_and_session_lifecycle_are_shared_and_persistent():
    ui = (ROOT / "static/common/portal_ui.js").read_text(encoding="utf-8")
    lifecycle = (ROOT / "static/common/session_timer.js").read_text(encoding="utf-8")
    responsive = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8")
    assert "opelgt-theme" in ui
    assert "opelgt-font" in ui
    assert "localStorage.setItem" in ui
    assert "document.documentElement.dataset.theme" in ui
    assert "document.documentElement.dataset.font" in ui
    assert "pagehide" in lifecycle
    assert "/api/session/closing" in lifecycle
    assert "/api/admin/session/closing" in lifecycle
    assert "/api/session/keepalive" in lifecycle
    assert "/api/admin/session/keepalive" in lifecycle
    assert "window.location.replace(target.login)" in lifecycle
    assert 'html[data-theme="light"] body{background:#f3f5fb!important' in responsive
    assert "session-safe" in lifecycle and "session-middle" in lifecycle and "session-critical" in lifecycle
    assert "durationMinutes" in lifecycle
    assert ".connectivity-badge.online" in responsive and "background:#198754!important" in responsive
    assert ".connectivity-badge.offline" in responsive and "background:#c62828!important" in responsive
    assert ".session-timer.session-middle" in responsive and "background:#f59e0b!important" in responsive
    assert 'html[data-theme="dark"] .page-services .service-frequency' in responsive
    assert 'html[data-theme="dark"] .page-services .service-progress' in responsive
    assert '--common-control-bg:#26364a' in responsive
    assert 'html[data-theme="dark"] .display-controls .icon-button' in responsive
    assert "window.removeEventListener('online', connectivityUpdate)" in ui
    assert "const targetLabel = dark ? 'Mode clair' : 'Mode sombre'" in ui
    assert "button.title = `Activer le ${targetLabel.toLowerCase()}`" in ui



def test_member_login_controls_are_single_row_without_inactive_session_box():
    login = (ROOT / "static/common/login.html").read_text(encoding="utf-8")
    responsive = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8")
    assert 'class="login-controls login-controls-inline"' in login
    assert "session inactive" not in login
    assert 'id="loginSessionState"' not in login
    assert login.count("data-connectivity-status") == 1
    assert login.count("data-ui-theme") == 1
    assert login.count("data-ui-font-decrease") == 1
    assert login.count("data-ui-font-increase") == 1
    assert ".page-login .login-controls-inline" in responsive
    assert "flex-wrap:nowrap!important" in responsive
    assert "border:0!important" in responsive



def test_admin_login_controls_are_single_row_without_inactive_session_box():
    admin = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")
    responsive = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8")
    assert 'class="login-controls admin-login-controls admin-login-controls-inline"' in admin
    assert "session inactive" not in admin
    assert "adminLoginSessionState" not in admin
    assert "adminLoginSessionState" not in script
    assert admin.count("data-connectivity-status") == 2  # connexion et en-tête authentifié
    login_block = admin.split('admin-login-controls-inline', 1)[1].split('</div>', 1)[0]
    assert login_block.count("data-ui-theme") == 1
    assert login_block.count("data-ui-font-decrease") == 1
    assert login_block.count("data-ui-font-increase") == 1
    assert ".page-admin .admin-login-controls-inline" in responsive
    assert "flex-wrap:nowrap!important" in responsive


def test_service_selector_is_wider_and_keeps_slogan_on_one_line_on_desktop():
    services = (ROOT / "static/common/services.html").read_text(encoding="utf-8")
    responsive = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8")
    assert 'class="services-shell services-shell-wide"' in services
    assert ".page-services .services-shell-wide{width:min(1440px,100%)}" in responsive
    assert ".page-services .services-slogan{white-space:nowrap" in responsive

def test_couples_marker_and_document_button_adjustments():
    html = (ROOT / "static/couples/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/couples/styles.css").read_text(encoding="utf-8").replace(" ", "")
    for label in (
        "Télécharger le PDF des couples",
        "Télécharger le fichier Excel des couples",
        "Télécharger le PDF de visserie",
    ):
        assert label in html
    assert ".secondary-document-link,.document-download-link{color:#fff;background:var(--brand);border-color:var(--brand)}" in css
    assert ".marker-halo{stroke-width:5.5px}" in css
    assert ".marker-segment{stroke-width:3px}" in css
    assert ".marker-selected-ring{stroke-width:2px}" in css
    assert "animation:selected-marker-blink" in css
    assert "@keyframesselected-marker-blink" in css


def test_bulletin_and_admin_header_specific_adjustments():
    bulletin_html = (ROOT / "static/bulletins/index.html").read_text(encoding="utf-8")
    admin_html = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    css = "".join((ROOT / "static/bulletins/styles.css").read_text(encoding="utf-8").split())
    assert 'class="bulletins-header-title"' in bulletin_html
    assert ".page-bulletins.bulletins-header-title{white-space:nowrap" in css
    assert ".page-bulletins#logoutButton{background:#fff!important" in css
    assert 'id="systemMetricsChart"' in admin_html
    assert "Utilisation des ressources" in admin_html
    assert ".page-admin.admin-tabs{justify-content:center" in css
    assert ".system-metrics-card" in css


def test_admin_metrics_frontend_is_dynamic_and_interactive():
    script = (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")
    for token in (
        "/api/admin/metrics",
        "window.setInterval(loadMetrics, state.metricsRefreshMs)",
        "metricsRefreshInterval",
        "handleMetricsPointerMove",
        "systemMetricsTooltip",
        "drawMetricsChart",
        "cpuPercents",
        "memoryPercent",
    ):
        assert token in script


def test_shared_display_preferences_default_to_normal_and_persist():
    script_path = ROOT / "static/common/portal_ui.js"
    node_script = f"""
const values = new Map();
global.localStorage = {{
  getItem: key => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: key => values.delete(key),
}};
global.CustomEvent = class {{ constructor(name, options) {{ this.name = name; this.detail = options?.detail; }} }};
global.document = {{
  readyState: 'complete',
  documentElement: {{dataset: {{theme: 'light', font: 'normal'}}}},
  querySelectorAll: () => [],
}};
global.navigator = {{onLine: true}};
global.window = {{
  dispatchEvent: () => {{}},
  addEventListener: () => {{}},
  clearInterval: () => {{}},
  setInterval: () => 1,
}};
require({json.dumps(str(script_path))});
if (document.documentElement.dataset.font !== 'normal') throw new Error(`font par défaut: ${{document.documentElement.dataset.font}}`);
window.PortalUI.applyFont('large');
window.PortalUI.applyTheme('dark');
if (values.get('opelgt-font') !== 'large') throw new Error('taille non persistée');
if (values.get('opelgt-theme') !== 'dark') throw new Error('thème non persisté');
"""
    subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)


def test_connectivity_indicator_uses_server_probes_and_not_browser_online_flag():
    ui = (ROOT / "static/common/portal_ui.js").read_text(encoding="utf-8")
    backend = (ROOT / "app/pieces/services/connectivity.py").read_text(encoding="utf-8")
    assert "navigator.onLine" not in ui
    for token in ("_tcp_probes", "_dns_probes", "_http_probes", "_ping_probes", "_FAILURES_BEFORE_OFFLINE"):
        assert token in backend
    assert "status?.conclusive !== false" in ui


def test_default_supplier_selection_is_configurable_and_documented():
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    expected = {
        "opelix_parts", "splendid_parts", "edelschmiede", "pro_gt", "atz_online",
        "opel_gt_source", "oldtimer_motorenteile", "tw_oldtimerteile",
    }
    assert set(config["pieces"]["scraping"]["default_enabled_sites"]) == expected
    assert "site.default_enabled !== false" in (ROOT / "static/pieces/app.js").read_text(encoding="utf-8")
    assert "default_enabled_sites" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_service_cards_use_only_requested_descriptions():
    html = (ROOT / "static/common/services.html").read_text(encoding="utf-8")
    for removed in (
        "Recherche locale plein texte, consultation des PDF",
        "Comparaison des prix, disponibilités et évolutions",
        "Consultation des valeurs de serrage",
        "Fiche mécanique à compléter",
        "Liste de préparation du véhicule",
    ):
        assert removed not in html
    assert "Fiche A4 recto/verso à compléter" in html
    assert "Fiche A4 recto/verso de préparation du véhicule" in html


def test_admin_metrics_are_per_cpu_and_refresh_is_configurable():
    html = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")
    backend = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert 'id="metricsRefreshInterval"' in html
    assert "cpuPercents" in script and "cpuLabels" in script
    assert 'Path("/proc/cpuinfo")' in backend
    assert 'Path("/proc/stat")' in backend
    assert "cpuPercents" in backend and "cpuLabels" in backend


def test_release_1114_requested_layout_and_admin_readability_adjustments():
    services = (ROOT / "static/common/services.html").read_text(encoding="utf-8")
    base = (ROOT / "static/common/base.css").read_text(encoding="utf-8").replace(" ", "")
    responsive = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8").replace(" ", "")
    couples = (ROOT / "static/couples/index.html").read_text(encoding="utf-8")
    couples_css = (ROOT / "static/couples/styles.css").read_text(encoding="utf-8").replace(" ", "")
    login = (ROOT / "static/common/login.html").read_text(encoding="utf-8")
    admin = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")

    assert services.count('class="service-card"') == 6
    assert ".page-services.service-grid{align-items:start;grid-auto-rows:auto}" in base
    assert ".page-services.service-meta{min-height:0;margin-bottom:0}" in base
    assert ".page-services.service-card.button{margin-top:.8rem!important;background:#174ea6" in base
    assert ".page-services.service-cardh2{text-align:center}" in base

    downloads = couples.split('class="reference-downloads"', 1)[1].split('</div>', 1)[0]
    assert downloads.count('document-download-link') == 3
    assert ".page-couples.reference-downloads{width:100%;justify-content:center" in couples_css

    assert '<h1>Page de connexion membre</h1>' in login
    assert ".page-login.cardh1{text-align:center}" in base
    assert '<h1>Page de connexion administrateur</h1>' in admin
    assert "Les identifiants sont vérifiés directement auprès du site membre" in admin
    assert 'id="adminSessionDuration"' in admin
    assert ".page-admin#loginDialog.dialog-cardh1{" in responsive
    assert "font-size:clamp(1.7rem,4vw,2.35rem)" in responsive

    for page in (ROOT / "static/bulletins/index.html", ROOT / "static/pieces/index.html", ROOT / "static/couples/index.html"):
        html = page.read_text(encoding="utf-8")
        nav = html.split('class="portal-nav panel"', 1)[1].split('</nav>', 1)[0]
        assert nav.count('<a ') == 2
    assert "body:is(.page-bulletins,.page-pieces,.page-couples).portal-nav.panela" in responsive
    assert "background:#174ea6!important" in responsive

    assert ".page-admin.code-editor.code-input::-webkit-scrollbar{width:14px;height:14px}" in responsive
    assert "overflow-y:scroll!important" in responsive
    assert "grid-template-rows:minmax(0,1fr)!important" in responsive
    assert "code-log-viewer" in (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")
    assert "job-state-badge" in admin_js and "job-row-" in admin_js
    assert 'status-card-${tone}' in admin_js
    assert ".page-admin.status-card-blue" in responsive


def test_release_1115_login_titles_and_subtitle_order():
    login = (ROOT / "static/common/login.html").read_text(encoding="utf-8")
    admin = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    base = (ROOT / "static/common/base.css").read_text(encoding="utf-8").replace(" ", "")

    assert "<title>Page de connexion membre - Portail Entraide Opel GT</title>" in login
    assert login.index("<h1>Page de connexion membre</h1>") < login.index("Accès réservé aux membres")
    assert 'class="eyebrow login-subtitle">Accès réservé aux membres</p>' in login

    assert "<title>Page de connexion administrateur - Portail Entraide Opel GT</title>" in admin
    assert admin.index("<h1>Page de connexion administrateur</h1>") < admin.index("Administration locale")
    assert 'class="eyebrow login-subtitle">Administration locale</p>' in admin

    assert ".login-subtitle{text-align:center" in base


def test_release_1117_logo_is_transparent_and_used_everywhere():
    logo = ROOT / "static/common/logo.png"
    pieces_logo = ROOT / "static/pieces/assets/logo-entraide-opel-gt.png"
    for path in (logo, pieces_logo):
        payload = path.read_bytes()
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        # IHDR colour type 6 = truecolour with alpha.
        assert payload[25] == 6
    assert not (ROOT / "static/common/logo.jpg").exists()
    assert not (ROOT / "static/pieces/assets/logo-entraide-opel-gt.jpg").exists()
    for page in (
        ROOT / "static/common/login.html",
        ROOT / "static/common/services.html",
        ROOT / "static/admin/index.html",
        ROOT / "static/bulletins/index.html",
        ROOT / "static/pieces/index.html",
        ROOT / "static/couples/index.html",
    ):
        html = page.read_text(encoding="utf-8")
        assert "logo.jpg" not in html
        assert "logo-entraide-opel-gt.jpg" not in html
        assert ".png" in html


def test_release_1117_admin_login_matches_member_layout_without_control_scrollbars():
    member = (ROOT / "static/common/login.html").read_text(encoding="utf-8")
    admin = (ROOT / "static/admin/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")
    css = re.sub(r"\s+", "", (ROOT / "static/common/responsive.css").read_text(encoding="utf-8"))

    assert "Page de connexion membre" in member
    assert "Page de connexion administrateur" in admin
    assert "Ce compte est indépendant du compte membre du site du club. Les identifiants sont vérifiés directement" in admin
    assert "La session locale expire automatiquement après 30 minutes. Une fois ce délai écoulé, vous serez automatiquement redirigé vers cette page." not in admin
    assert admin.count("Vous pouvez utiliser le portail en HTTP depuis un autre poste du réseau local.") == 1
    assert 'class="primary">Se connecter</button>' in admin
    assert 'id="adminSessionDuration"' in admin
    assert "adminSessionPolicy" not in admin and "adminSessionPolicy" not in script
    assert ".page-login.card,.page-admin#loginDialog{width:min(100%,34rem)!important" in css
    assert ".page-login.login-controls-inline,.page-admin.admin-login-controls-inline{overflow:visible!important" in css
    assert ".page-admin.admin-login-controls-inline::-webkit-scrollbar{display:none!important" in css
    assert ".page-admin#loginDialog.primary,.page-login.primary{" in css
    assert "background:#1d4ed8!important" in css


def test_release_1117_admin_badges_are_uniform_or_semantic_and_country_has_flag():
    script = (ROOT / "static/admin/admin.js").read_text(encoding="utf-8")
    css = (ROOT / "static/common/responsive.css").read_text(encoding="utf-8")
    status_block = script.split("$('generalStatus').innerHTML", 1)[1].split("].join('');", 1)[0]
    assert status_block.count("'blue'") == 6
    for token in (
        "positiveTone(indexCoverage)",
        "inverseTone(bulletinFailureRate",
        "supplierAvailability",
        "connectionSuccessRate",
        "connectionBlockedRate",
        'class="metric-percent"',
        "function countryFlag(countryCode)",
        "countryLabel(row)",
    ):
        assert token in script
    assert ".page-admin #generalStatus .status-card" in css
    assert ".page-admin .status-card-neutral" in css
    assert ".page-admin .status-card-red" in css


def test_bundled_pdf_renderer_integrity_and_offline_support_files():
    import hashlib

    vendor = ROOT / "static" / "vendor" / "pdfjs-6.4.299"
    metadata = json.loads((vendor / "UPSTREAM.json").read_text())
    assert metadata["name"] == "pdfjs-dist" and metadata["version"] == "6.4.299"
    assert metadata["npm_integrity"].startswith("sha512-")
    for relative, digest in metadata["files"].items():
        path = vendor / relative
        assert path.resolve().is_relative_to(vendor.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative
    for relative in ["pdf.min.mjs", "pdf.worker.min.mjs", "LICENSE",
                     "cmaps/Adobe-Japan1-UCS2.bcmap", "standard_fonts/FoxitSerif.pfb",
                     "wasm/openjpeg.wasm", "wasm/jbig2.wasm"]:
        assert relative in metadata["files"]
