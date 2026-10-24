from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.bulletins.database import connect, init_db
from app.common import auth


class DummySession:
    def close(self) -> None:
        return None


class DummyCrawler:
    def __init__(self, settings):
        self.settings = settings
        self.session = DummySession()

    def login(self, login: str, password: str) -> None:
        if password == "bad":
            raise main.AuthenticationError("Identifiants invalides")


@pytest.fixture(scope="module")
def portal_client():
    original = main.EntraideCrawler
    main.EntraideCrawler = DummyCrawler
    with TestClient(main.app) as value:
        value.app.state.sync_manager.start = lambda crawler, force_reindex=False: False
        yield value
    main.EntraideCrawler = original


@pytest.fixture()
def client(portal_client):
    portal_client.cookies.clear()
    auth._ATTEMPTS.clear()
    yield portal_client
    portal_client.cookies.clear()
    auth._ATTEMPTS.clear()


def member_login(client: TestClient) -> str:
    response = client.post("/api/login", json={"login": "membre", "password": "Valide!123"})
    assert response.status_code == 200
    return response.json()["csrfToken"]


def admin_login(client: TestClient, monkeypatch) -> str:
    monkeypatch.setattr(main, "verify_admin_password", lambda password: password == "Admin!Correct12345")
    response = client.post("/api/admin/login", json={"username": "admin", "password": "Admin!Correct12345"})
    assert response.status_code == 200
    return response.json()["csrfToken"]


def test_public_pages_and_redirects(client):
    assert client.get("/").status_code == 200
    assert client.get("/services", follow_redirects=False).headers["location"] == "/"
    assert client.get("/bulletins", follow_redirects=False).headers["location"] == "/"
    assert client.get("/pieces", follow_redirects=False).headers["location"] == "/"
    assert client.get("/couples", follow_redirects=False).headers["location"] == "/"
    assert client.get("/documents/fiche-intervention.pdf").status_code == 401
    assert client.get("/documents/liste-visserie-opel-gt.pdf").status_code == 401
    assert client.get("/documents/couples-serrage-opel-gt.pdf").status_code == 401
    assert client.get("/documents/couples-serrage-opel-gt.xlsx").status_code == 401
    assert client.get("/admin").status_code == 200


def test_common_login_then_service_selector(client):
    member_login(client)
    assert client.get("/services").status_code == 200
    assert client.get("/bulletins").status_code == 200
    assert client.get("/pieces").status_code == 200
    assert client.get("/couples").status_code == 200
    session = client.get("/api/session").json()
    assert session["authenticated"] is True
    assert session["user"] == "membre"


def test_security_headers_and_hidden_api_docs(client):
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "noindex" in response.headers["x-robots-tag"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"].startswith("no-store")
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert "Disallow: /" in client.get("/robots.txt").text


def test_health_exposes_no_paths(client):
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert payload["version"] == "1.1.24"
    assert "path" not in json.dumps(payload).lower()


def test_member_login_rejects_bad_credentials(client):
    response = client.post("/api/login", json={"login": "membre", "password": "bad"})
    assert response.status_code == 401
    assert response.json()["ok"] is False


def _request_from(client_host: str, *, scheme: str = "http") -> Request:
    scope = {
        "type": "http", "method": "POST", "path": "/api/login", "headers": [],
        "scheme": scheme, "server": ("192.168.1.10", 8080), "client": (client_host, 1234),
        "query_string": b"",
    }
    return Request(scope)


def test_plain_http_is_allowed_from_local_network():
    for host in ("127.0.0.1", "192.168.1.25", "10.0.0.8", "172.16.4.2", "fe80::1", "fd00::42"):
        assert main._remote_http_forbidden(_request_from(host)) is False


def test_plain_http_is_rejected_from_public_network():
    assert main._remote_http_forbidden(_request_from("8.8.8.8")) is True


def test_https_is_allowed_from_public_network():
    assert main._remote_http_forbidden(_request_from("8.8.8.8", scheme="https")) is False


def test_member_logout_requires_csrf(client):
    token = member_login(client)
    assert client.post("/api/logout").status_code == 403
    assert client.post("/api/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/session").json()["authenticated"] is False


def test_admin_cookie_reaches_api_and_is_separate(client, monkeypatch):
    token = admin_login(client, monkeypatch)
    second_login = client.post(
        "/api/admin/login", json={"username": "admin", "password": "Admin!Correct12345"}
    )
    set_cookie = second_login.headers["set-cookie"]
    token = second_login.json()["csrfToken"]
    assert "Path=/" in set_cookie
    assert auth.ADMIN_COOKIE in client.cookies
    assert client.get("/api/admin/config").status_code == 200
    assert client.post("/api/admin/logout", headers={"X-CSRF-Token": token}).status_code == 200


def test_admin_remote_plain_http_is_rejected(client, monkeypatch):
    monkeypatch.setattr(main, "_remote_http_forbidden", lambda request: True)
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "Admin!Correct12345"},
    )
    assert response.status_code == 403
    assert "HTTPS" in response.json()["message"]


def test_admin_actions_require_admin_csrf(client, monkeypatch):
    admin_login(client, monkeypatch)
    assert client.post("/api/admin/control", json={"action": "status"}).status_code == 403


def test_admin_cleanup_returns_human_message(client, monkeypatch):
    token = admin_login(client, monkeypatch)
    response = client.post("/api/admin/control", json={"action": "cleanup"}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200
    assert response.json()["message"].startswith("Nettoyage terminé (")


def test_admin_apply_config_uses_system_control_channel(client, monkeypatch):
    token = admin_login(client, monkeypatch)
    observed = []
    monkeypatch.setattr(main, "request_system_action", lambda action: observed.append(action) or {"ok": True, "message": "planifié"})
    response = client.post(
        "/api/admin/control",
        json={"action": "apply-config"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert observed == ["apply-config"]


def test_admin_config_never_returns_secrets(client, monkeypatch):
    admin_login(client, monkeypatch)
    payload = client.get("/api/admin/config").json()
    assert "admin_password_hash" not in payload["content"]
    assert "app_secret" not in payload["content"]


def test_services_and_jobs_require_authentication(client):
    assert client.get("/api/services").status_code == 401
    assert client.get("/api/couples").status_code == 401
    assert client.get("/documents/vue-eclatee-1.pdf").status_code == 401
    assert client.get("/documents/liste-visserie-opel-gt.pdf").status_code == 401
    assert client.get("/documents/couples-serrage-opel-gt.pdf").status_code == 401
    assert client.get("/documents/couples-serrage-opel-gt.xlsx").status_code == 401
    assert client.get("/api/jobs").status_code == 401


def test_couples_api_and_bundled_documents(client):
    member_login(client)
    payload = client.get("/api/couples").json()
    assert payload["row_count"] == 61
    assert len(payload["rows"]) == 61
    assert payload["rows"][0]["item"] == "Chapeaux de bielles"
    assert payload["rows"][0]["torque_mkg"] == 5.0
    assert next(row for row in payload["rows"] if row["id"] == 27)["views"]["1"] == "5, 4"
    assert client.get("/documents/fiche-intervention.pdf").headers["content-type"].startswith("application/pdf")
    assert client.get("/documents/inventaire-avant-deplacement.pdf").headers["content-type"].startswith("application/pdf")
    assert client.get("/documents/liste-visserie-opel-gt.pdf").headers["content-type"].startswith("application/pdf")
    assert client.get("/documents/couples-serrage-opel-gt.pdf").headers["content-type"].startswith("application/pdf")
    excel = client.get("/documents/couples-serrage-opel-gt.xlsx")
    assert excel.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "attachment" in excel.headers.get("content-disposition", "")
    assert client.get("/documents/vue-eclatee-1.jpg").headers["content-type"].startswith("image/jpeg")
    assert client.get("/documents/inconnu.pdf").status_code == 404


def test_pdf_path_traversal_is_rejected(client):
    member_login(client)
    assert client.get("/api/bulletins/pdf-file/..%2Fsecrets.json").status_code == 404
    assert client.get("/documents/..%2Fsecrets.json").status_code == 404


def test_bulletin_search_is_blocked_during_download_even_with_existing_index(client, monkeypatch, tmp_path):
    member_login(client)
    db_path = main.bulletin_settings.db_path
    init_db(db_path)
    pdf = main.bulletin_settings.pdf_dir / "bulletin-1.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO bulletins(url,title,filename,number,year,local_path,pages,indexed_at,status) VALUES (?,?,?,?,?,?,1,CURRENT_TIMESTAMP,'indexed')",
            ("https://example.invalid/1.pdf", "Bulletin 1", pdf.name, 1, 2026, str(pdf)),
        )
        bulletin_id = cur.lastrowid
        conn.execute("INSERT INTO pages(bulletin_id,page_no,text,text_source) VALUES (?,?,?,?)", (bulletin_id, 1, "embrayage Opel GT", "text"))
        conn.execute(
            "INSERT INTO pages_fts(text,title,filename,bulletin_id,page_no,number,year,text_source) VALUES (?,?,?,?,?,?,?,?)",
            ("embrayage Opel GT", "Bulletin 1", pdf.name, bulletin_id, 1, 1, 2026, "text"),
        )
        conn.commit()
    monkeypatch.setattr(client.app.state.sync_manager, "state", lambda: {"running": True, "phase": "download", "errors": []})
    response = client.post("/api/bulletins/search", json={"keywords": "embrayage", "mode": "all"})
    assert response.status_code == 409
    assert "récupération" in response.json()["message"].lower()


def test_admin_password_policy_all_classes():
    assert auth.password_policy_errors("Abcdefghijklmn1!") == []
    assert auth.password_policy_errors("short1!A")
    assert auth.password_policy_errors("ABCDEFGHIJKLMNOP1!")
    assert auth.password_policy_errors("abcdefghijklmnop1!")
    assert auth.password_policy_errors("Abcdefghijklmnop!")
    assert auth.password_policy_errors("Abcdefghijklmnop1")


def test_service_selector_exposes_dynamic_progress_and_disabled_links():
    html = (main.STATIC / "common" / "services.html").read_text(encoding="utf-8")
    script = (main.STATIC / "common" / "services.js").read_text(encoding="utf-8")
    assert "Opel GT 1968-1973 : « Seul le vol procure plus de sensations »." in html
    assert "Portail privé" not in html
    assert "Documentation" not in html
    assert "Pièces détachées" not in html
    assert 'id="bulletinsProgress"' in html
    assert 'id="piecesSuppliers"' in html
    assert 'aria-disabled="true"' in html
    assert 'id="bulletinsFrequency"' in html
    assert 'id="piecesFrequency"' in html
    assert 'id="couplesCard"' in html and 'href="/couples"' in html
    assert 'id="interventionCard"' in html and 'href="/documents/fiche-intervention.pdf"' in html
    assert 'id="inventoryCard"' in html and 'href="/documents/inventaire-avant-deplacement.pdf"' in html
    assert '<h2>Fiche d’inventaire</h2>' in html
    assert "automaticFrequency" in script
    assert "/api/pieces/catalog-sync" not in script
    assert "setTimeout(refreshServices, 2000)" in script
    assert "classList.toggle('hidden', !processing)" in script
    assert "setServiceLink('#bulletinsOpen', Boolean(status.available))" in script
    assert "setServiceLink('#piecesOpen', Boolean(status.available))" in script
    assert '<progress id="piecesGlobalBar"' in html
    assert 'style="width:' not in script
    assert "progress-${supplier.status}" in script
    assert "'unavailable'" in script and "'ok'" in script
    css = (main.STATIC / "pieces" / "styles.css").read_text(encoding="utf-8")
    assert ".catalog-progress-meter.progress-ok" in css and "#198754" in css
    assert ".catalog-progress-meter.progress-unavailable" in css and "#c62828" in css
    css = (main.STATIC / "common" / "base.css").read_text(encoding="utf-8")
    assert ".progress-meter.progress-ok" in css and "#198754" in css
    assert ".progress-meter.progress-unavailable" in css and "#c62828" in css


def test_individual_service_pages_use_terminal_and_running_progress_colours():
    bulletin_script = (main.STATIC / "bulletins" / "app.js").read_text(encoding="utf-8")
    bulletin_css = (main.STATIC / "bulletins" / "styles.css").read_text(encoding="utf-8")
    pieces_script = (main.STATIC / "pieces" / "app.js").read_text(encoding="utf-8")
    pieces_css = (main.STATIC / "pieces" / "styles.css").read_text(encoding="utf-8")
    assert 'classList.toggle("is-complete", complete)' in bulletin_script
    assert ".progress-bar.is-complete" in bulletin_css
    assert "globalPercent >= 100 ? 'progress-ok' : 'progress-running'" in pieces_script
    assert ".catalog-progress-meter.progress-running" in pieces_css


def test_bulletin_page_has_common_navigation_connectivity_and_no_language_menu():
    html = (main.STATIC / "bulletins" / "index.html").read_text(encoding="utf-8")
    script = (main.STATIC / "bulletins" / "app.js").read_text(encoding="utf-8")
    assert 'id="languageSelect"' not in html
    assert 'id="connectivityBadge"' in html
    assert 'id="currentFileText"' in html
    assert '<a href="/bulletins" aria-current="page">Recherche bulletins</a>' not in html
    assert '<a href="/services">Retour à la liste des services</a>' in html
    assert "window.PortalUI.startConnectivity()" in script
    assert "status.indexingRunning" in script
    assert "status.processingRunning || status.running || status.indexingRunning" in script
    assert "forceSyncButton" not in script
    assert "Vérifier les bulletins" not in html


def test_pieces_page_has_common_navigation_and_catalog_progress():
    html = (main.STATIC / "pieces" / "index.html").read_text(encoding="utf-8")
    script = (main.STATIC / "pieces" / "app.js").read_text(encoding="utf-8")
    assert html.index("</header>") < html.index('class="portal-nav panel"')
    assert '<a href="/pieces" aria-current="page">Comparateur de pièces</a>' not in html
    assert '<a href="/services">Retour à la liste des services</a>' in html
    assert 'id="catalogGlobalBar"' in html
    assert 'id="catalogSupplierProgress"' in html
    assert "state.catalogRunning" in script
    assert "Recherche désactivée pendant la récupération des catalogues" in script
    assert 'id="catalogSyncButton"' not in html
    assert "Mettre à jour les catalogues" not in html
    assert "requestCatalogUpdate" not in script
    assert '<progress id="catalogGlobalBar"' in html
    assert 'style="width:' not in script
    assert "progress-${supplier.status}" in script
    assert "'unavailable'" in script and "'ok'" in script


def test_static_pages_do_not_display_member_identity():
    static_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in main.STATIC.rglob("*") if path.is_file())
    assert "Connecté :" not in static_text


def test_bulletin_search_is_blocked_while_indexing(client, monkeypatch):
    member_login(client)
    monkeypatch.setattr(
        main,
        "_bulletin_processing_status",
        lambda request: {"indexingRunning": True, "readiness": {"ready": True, "message": "Index prêt."}},
    )
    response = client.post("/api/bulletins/search", json={"keywords": "embrayage", "mode": "all"})
    assert response.status_code == 409
    assert "indexation" in response.json()["message"].lower()


def test_parts_search_is_blocked_while_catalogs_are_running(client, monkeypatch):
    member_login(client)
    monkeypatch.setattr(main, "_catalog_status_for_api", lambda: main.CatalogSyncStatus(running=True))
    site_id = next(iter(main.SITES))
    response = client.post(
        "/api/pieces/search",
        json={"model": "1900", "keywords": "câble embrayage", "sites": [site_id]},
    )
    assert response.status_code == 409
    assert "catalogues" in response.json()["message"].lower()


def test_member_login_is_limited_to_five_failures_over_five_minutes(client):
    auth._ATTEMPTS.clear()
    for _ in range(5):
        response = client.post("/api/login", json={"login": "membre", "password": "bad"})
        assert response.status_code == 401
    blocked = client.post("/api/login", json={"login": "membre", "password": "bad"})
    assert blocked.status_code == 429
    assert "5 minute" in blocked.json()["message"]
    auth._ATTEMPTS.clear()


def test_admin_login_is_limited_to_five_failures_over_five_minutes(client, monkeypatch):
    auth._ATTEMPTS.clear()
    monkeypatch.setattr(main, "verify_admin_password", lambda password: False)
    for _ in range(5):
        response = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "incorrect"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "incorrect"},
    )
    assert blocked.status_code == 429
    assert "5 minute" in blocked.json()["message"]
    auth._ATTEMPTS.clear()


def test_login_limits_are_independently_configurable():
    authentication = main.section("authentication")
    admin = main.section("admin")
    assert authentication["login_rate_limit_attempts"] == 5
    assert authentication["login_rate_limit_window_seconds"] == 300
    assert admin["login_rate_limit_attempts"] == 5
    assert admin["login_rate_limit_window_seconds"] == 300


def test_admin_statistics_include_connection_details(client, monkeypatch):
    auth._ATTEMPTS.clear()
    token = admin_login(client, monkeypatch)
    payload = client.get("/api/admin/statistics").json()
    assert payload["connections"]["summary"]["total"] >= 1
    assert payload["connections"]["summary"]["unique_ips"] >= 1
    assert payload["connections"]["byIp"]
    row = payload["connections"]["byIp"][0]
    for key in ("ip_address", "country", "attempts", "successful", "failed", "blocked", "last_attempt"):
        assert key in row
    client.post("/api/admin/logout", headers={"X-CSRF-Token": token})


def test_services_expose_automatic_retrieval_frequencies(client, monkeypatch):
    member_login(client)
    payload = client.get("/api/services").json()
    assert "chaque connexion membre" in payload["bulletins"]["automaticFrequency"]
    assert "Mise à jour automatique" in payload["pieces"]["automaticFrequency"]
    assert client.post("/api/pieces/catalog-sync").status_code == 405


def test_service_slogan_uses_the_same_font_size_on_all_four_pages():
    common_css = (main.STATIC / "common" / "base.css").read_text(encoding="utf-8")
    bulletins_css = (main.STATIC / "bulletins" / "styles.css").read_text(encoding="utf-8")
    pieces_css = (main.STATIC / "pieces" / "styles.css").read_text(encoding="utf-8")
    couples_css = (main.STATIC / "couples" / "styles.css").read_text(encoding="utf-8")
    expected = "font-size:clamp(0.82rem,1.1vw,1.02rem)"
    assert expected in common_css
    assert expected in bulletins_css.replace(" ", "")
    assert expected in pieces_css.replace(" ", "")
    assert expected in couples_css.replace(" ", "")


def test_catalog_api_preserves_live_worker_supplier_progress(monkeypatch):
    site_id, site = next(iter(main.SITES.items()))
    monkeypatch.setattr(
        main,
        "read_sync_status_snapshot",
        lambda: main.CatalogSyncStatus(
            running=True,
            suppliers=[
                {
                    "site_id": site_id,
                    "site_name": site.name,
                    "status": "running",
                    "ok": False,
                    "item_count": 0,
                    "progress_percent": 5,
                }
            ],
        ),
    )
    monkeypatch.setattr(main, "_active_jobs", lambda queue: [{"state": "running"}])

    status = main._catalog_status_for_api()

    assert status.running is True
    assert status.global_progress_percent == 5
    assert status.suppliers[0].status == "running"
    assert status.suppliers[0].progress_percent == 5


def test_catalog_api_shows_pending_zero_before_worker_initializes_status(monkeypatch):
    suppliers = [
        {
            "site_id": site_id,
            "site_name": site.name,
            "status": "failed",
            "ok": False,
            "item_count": 0,
            "progress_percent": 100,
        }
        for site_id, site in main.SITES.items()
    ]
    monkeypatch.setattr(
        main,
        "read_sync_status_snapshot",
        lambda: main.CatalogSyncStatus(running=False, suppliers=suppliers, global_progress_percent=100),
    )
    monkeypatch.setattr(
        main,
        "_active_jobs",
        lambda queue: [{"state": "running"}] if queue == "catalogs" else [],
    )

    status = main._catalog_status_for_api()

    assert status.running is True
    assert status.global_progress_percent == 0
    assert all(item.status == "pending" for item in status.suppliers)
    assert all(item.progress_percent == 0 for item in status.suppliers)
    assert "prépare" in status.detail.lower()


def test_services_enable_comparator_with_six_valid_catalogues(client, monkeypatch):
    member_login(client)
    suppliers = []
    site_ids = list(main.SITES)
    for index, site_id in enumerate(site_ids):
        site = main.SITES[site_id]
        usable = index < 6
        suppliers.append(
            {
                "site_id": site_id,
                "site_name": site.name,
                "status": "ok" if usable else "unavailable",
                "ok": usable,
                "item_count": 100 if usable else 0,
                "progress_percent": 100,
            }
        )
    monkeypatch.setattr(
        main,
        "_catalog_status_for_api",
        lambda: main.CatalogSyncStatus(
            running=False,
            ready=False,
            global_progress_percent=100,
            detail="6/8 catalogue(s) prêt(s).",
            suppliers=suppliers,
        ),
    )
    monkeypatch.setattr(
        main,
        "_bulletin_processing_status",
        lambda request: {
            "readiness": {"ready": False},
            "processingRunning": False,
            "running": False,
            "indexingRunning": False,
        },
    )

    payload = client.get("/api/services").json()["pieces"]

    assert payload["availableCatalogs"] == 6
    assert payload["ready"] is True
    assert payload["available"] is True
    assert payload["running"] is False



def test_services_buttons_follow_processing_state_only(client, monkeypatch):
    member_login(client)
    monkeypatch.setattr(
        main,
        "_bulletin_processing_status",
        lambda request: {
            "readiness": {"ready": False, "indexedBulletins": 0, "indexedPages": 0, "localPdfCount": 0},
            "processingRunning": False, "running": False, "indexingRunning": False,
        },
    )
    monkeypatch.setattr(
        main,
        "_catalog_status_for_api",
        lambda: main.CatalogSyncStatus(running=False, ready=False, suppliers=[]),
    )
    idle = client.get("/api/services").json()
    assert idle["bulletins"]["available"] is True
    assert idle["pieces"]["available"] is True
    assert idle["bulletins"]["running"] is False
    assert idle["pieces"]["running"] is False

    monkeypatch.setattr(
        main,
        "_bulletin_processing_status",
        lambda request: {
            "readiness": {"ready": True, "indexedBulletins": 10, "indexedPages": 100, "localPdfCount": 10},
            "processingRunning": True, "running": True, "indexingRunning": False,
        },
    )
    monkeypatch.setattr(
        main,
        "_catalog_status_for_api",
        lambda: main.CatalogSyncStatus(running=True, ready=True, suppliers=[]),
    )
    active = client.get("/api/services").json()
    assert active["bulletins"]["available"] is False
    assert active["pieces"]["available"] is False
    assert active["bulletins"]["running"] is True
    assert active["pieces"]["running"] is True


def test_services_polling_never_enqueues_catalog_jobs(client):
    member_login(client)
    before = {job["id"] for job in main.list_jobs(500) if job["queue"] == "catalogs"}
    for _ in range(4):
        response = client.get("/api/services")
        assert response.status_code == 200
    after = {job["id"] for job in main.list_jobs(500) if job["queue"] == "catalogs"}
    assert after == before


def test_services_polling_never_starts_bulletin_sync(client, monkeypatch):
    member_login(client)
    starts = []
    monkeypatch.setattr(client.app.state.sync_manager, "start", lambda *args, **kwargs: starts.append((args, kwargs)))
    for _ in range(4):
        response = client.get("/api/services")
        assert response.status_code == 200
    assert starts == []


def test_session_duration_is_thirty_minutes_and_exposed(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    assert response.json()["durationMinutes"] == 30
    login_response = client.post("/api/login", json={"login": "membre", "password": "Valide!123"})
    payload = login_response.json()
    assert payload["durationMinutes"] == 30
    assert 1795 <= payload["expiresAt"] - payload["serverTime"] <= 1805


def test_admin_session_duration_is_thirty_minutes_and_exposed(client, monkeypatch):
    monkeypatch.setattr(main, "verify_admin_password", lambda password: True)
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "Admin!Correct12345"},
    )
    payload = response.json()
    assert payload["durationMinutes"] == 30
    assert 1795 <= payload["expiresAt"] - payload["serverTime"] <= 1805


def test_all_authenticated_pages_display_dynamic_session_timer():
    pages = [
        main.STATIC / "common" / "services.html",
        main.STATIC / "bulletins" / "index.html",
        main.STATIC / "pieces" / "index.html",
        main.STATIC / "admin" / "index.html",
    ]
    for path in pages:
        html = path.read_text(encoding="utf-8")
        assert 'id="sessionRemaining"' in html
        assert "Temps restant avant déconnexion : --:--" in html
        assert "session_timer.js" in html
    assert "SessionTimer.start" in (main.STATIC / "common" / "services.js").read_text(encoding="utf-8")
    assert "SessionTimer.start" in (main.STATIC / "bulletins" / "app.js").read_text(encoding="utf-8")
    assert "SessionTimer.start" in (main.STATIC / "pieces" / "app.js").read_text(encoding="utf-8")
    assert "SessionTimer.start" in (main.STATIC / "admin" / "admin.js").read_text(encoding="utf-8")


def test_login_pages_explain_configured_session_duration():
    member_html = (main.STATIC / "common" / "login.html").read_text(encoding="utf-8")
    admin_html = (main.STATIC / "admin" / "index.html").read_text(encoding="utf-8")
    assert 'id="sessionDuration"' in member_html
    assert 'id="adminSessionDuration"' in admin_html
    assert "automatiquement redirigé vers la page de connexion" in member_html
    assert "automatiquement redirigé vers la page de connexion" in admin_html


def test_member_and_admin_sessions_expire_after_configured_duration(client, monkeypatch):
    auth._MEMBER_SESSIONS.clear()
    auth._ADMIN_SESSIONS.clear()
    clock = [1_000.0]
    monkeypatch.setattr(auth.time, "time", lambda: clock[0])

    member = client.post("/api/login", json={"login": "membre", "password": "Valide!123"})
    assert member.status_code == 200
    assert member.json()["expiresAt"] == 2_800.0

    monkeypatch.setattr(main, "verify_admin_password", lambda password: True)
    admin = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "Admin!Correct12345"},
    )
    assert admin.status_code == 200
    assert admin.json()["expiresAt"] == 2_800.0

    clock[0] = 2_801.0
    assert client.get("/api/session").json()["authenticated"] is False
    assert client.get("/api/admin/session").json()["authenticated"] is False
    assert client.get("/services", follow_redirects=False).status_code == 303


def test_member_session_close_signal_and_navigation_keepalive(client):
    token = member_login(client)
    sid = client.cookies.get(auth.MEMBER_COOKIE)
    assert sid
    login_response = client.post("/api/logout", headers={"X-CSRF-Token": token})
    assert login_response.status_code == 200
    assert "max-age=0" in login_response.headers["set-cookie"].lower()

    token = member_login(client)
    sid = client.cookies.get(auth.MEMBER_COOKIE)
    login_session = auth._MEMBER_SESSIONS[sid]
    response = client.post("/api/session/closing", json={"csrfToken": token})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert login_session.closing_at is not None
    keepalive = client.post("/api/session/keepalive", headers={"X-CSRF-Token": token})
    assert keepalive.status_code == 200
    assert login_session.closing_at is None


def test_member_close_signal_ends_session_after_grace(client, monkeypatch):
    token = member_login(client)
    sid = client.cookies.get(auth.MEMBER_COOKIE)
    response = client.post("/api/session/closing", json={"csrfToken": token})
    assert response.status_code == 200
    closing_at = auth._MEMBER_SESSIONS[sid].closing_at
    assert closing_at is not None
    monkeypatch.setattr(auth.time, "time", lambda: closing_at + 0.1)
    status = client.get("/api/session").json()
    assert status["authenticated"] is False
    assert sid not in auth._MEMBER_SESSIONS


def test_admin_close_signal_and_metrics_endpoint(client, monkeypatch):
    token = admin_login(client, monkeypatch)
    sid = client.cookies.get(auth.ADMIN_COOKIE)
    assert sid
    response = client.post("/api/admin/session/closing", json={"csrfToken": token})
    assert response.status_code == 200
    assert auth._ADMIN_SESSIONS[sid].closing_at is not None
    keepalive = client.post("/api/admin/session/keepalive", headers={"X-CSRF-Token": token})
    assert keepalive.status_code == 200
    assert auth._ADMIN_SESSIONS[sid].closing_at is None

    metrics = client.get("/api/admin/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert 0 <= payload["cpuPercent"] <= 100
    assert 0 <= payload["memoryPercent"] <= 100
    assert payload["memoryUsedBytes"] >= 0
    assert payload["memoryTotalBytes"] >= payload["memoryUsedBytes"]
    assert payload["cpuCount"] >= 1


def test_admin_metrics_require_admin_session(client):
    assert client.get("/api/admin/metrics").status_code == 401


def test_public_connectivity_is_available_on_login_pages(client, monkeypatch):
    async def fake_check_internet(force=False):
        return main.ConnectivityStatus(
            online=True,
            detail="Connexion Internet disponible (test)",
            checked_at="2026-07-23T00:00:00+00:00",
            response_ms=1,
        )

    monkeypatch.setattr(main, "check_internet", fake_check_internet)
    response = client.get("/api/connectivity")
    assert response.status_code == 200
    assert response.json()["online"] is True


def test_login_cookies_are_browser_session_cookies(client, monkeypatch):
    member = client.post("/api/login", json={"login": "membre", "password": "Valide!123"})
    assert member.status_code == 200
    member_cookie = member.headers["set-cookie"].lower()
    assert "max-age=" not in member_cookie
    assert "expires=" not in member_cookie

    client.cookies.clear()
    monkeypatch.setattr(main, "verify_admin_password", lambda password: password == "Admin!Correct12345")
    admin = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "Admin!Correct12345"},
    )
    assert admin.status_code == 200
    admin_cookie = admin.headers["set-cookie"].lower()
    assert "max-age=" not in admin_cookie
    assert "expires=" not in admin_cookie


def test_annonces_authenticated_no_network_and_hidden_during_update(client, monkeypatch, tmp_path):
    import fcntl

    from app.annonces import service

    monkeypatch.setattr(service, 'directory', lambda: tmp_path)
    monkeypatch.setattr(service.PublicClient, 'get', lambda *args: pytest.fail('GET page must not collect ads'))
    assert client.get('/annonces', follow_redirects=False).headers['location'] == '/'
    assert client.get('/api/annonces').status_code == 401
    member_login(client)
    service.write_json(tmp_path / 'lesanciennes.json', {'items': [{'id': 'fixture'}], 'status': 'ok'})
    page = client.get('/annonces')
    assert page.status_code == 200 and 'Petites annonces' in page.text
    assert 'no-store' in page.headers['cache-control']
    assert client.get('/api/annonces').json()['items'] == [{'id': 'fixture'}]
    with (tmp_path / 'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        payload = client.get('/api/annonces').json()
        assert payload['running'] and payload['items'] == []
        assert client.get('/api/services').json()['annonces']['running']
    assert not client.get('/api/annonces').json()['running']
    payload = client.get('/api/services').json()['annonces']
    assert payload['count'] == 1 and payload['items'] == []
    assert '02:00' in payload['automaticFrequency']


def test_bulletin_pdf_remains_private_with_authenticated_range_reads(client, monkeypatch, tmp_path):
    settings = main.bulletin_settings.model_copy(update={"data_dir": tmp_path})
    monkeypatch.setattr(main, "bulletin_settings", settings)
    init_db(settings.db_path)
    settings.pdf_dir.mkdir()
    document = (main.RESOURCES / "documents" / "fiche-intervention.pdf").read_bytes()
    path = settings.pdf_dir / "bulletin-viewer-test.pdf"
    path.write_bytes(document)
    with connect(settings.db_path) as conn:
        row = conn.execute(
            "INSERT INTO bulletins(url,title,filename,local_path) VALUES (?,?,?,?)",
            ("https://example.invalid/viewer.pdf", "Test visionneuse", path.name, str(path)),
        )
        bulletin_id = row.lastrowid
        conn.commit()
    urls = [f"/api/bulletins/pdf/{bulletin_id}", f"/api/bulletins/pdf-file/{path.name}"]
    for url in urls:
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"Range": "bytes=0-63"}).status_code == 401
    member_login(client)
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200 and response.content == document
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.headers["cache-control"].startswith("no-store")
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        partial = client.get(url, headers={"Range": "bytes=0-63"})
        assert partial.status_code == 206 and partial.content == document[:64]
        assert partial.headers["content-range"] == f"bytes 0-63/{len(document)}"
        assert partial.headers["cache-control"].startswith("no-store")
    client.cookies.clear()
    assert client.get(urls[0]).status_code == 401


def test_pdf_renderer_modules_and_decoders_have_local_mime_types_and_scoped_csp(client):
    member_login(client)
    page = client.get("/bulletins")
    csp = page.headers["content-security-policy"]
    assert "'wasm-unsafe-eval'" in csp and "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp and "worker-src 'self'" in csp
    assert page.headers["x-frame-options"] == "DENY"
    for path in [
        "/static/bulletins/pdf_viewer.mjs",
        "/static/vendor/pdfjs-6.4.299/pdf.min.mjs",
        "/static/vendor/pdfjs-6.4.299/pdf.worker.min.mjs",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].split(";")[0] in {"text/javascript", "application/javascript"}
    decoder = client.get("/static/vendor/pdfjs-6.4.299/wasm/openjpeg.wasm")
    assert decoder.status_code == 200 and decoder.content.startswith(b"\x00asm")
    assert decoder.headers["content-type"].startswith("application/wasm")
    for other_page in ["/", "/services", "/pieces", "/couples", "/annonces", "/admin"]:
        assert "'wasm-unsafe-eval'" not in client.get(other_page).headers["content-security-policy"]
