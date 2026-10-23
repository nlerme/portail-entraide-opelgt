from __future__ import annotations

import time
from pathlib import Path

from app.bulletins.crawler import BulletinLink
from app.bulletins.database import connect, init_db
from app.bulletins.sync import SyncManager
from app.common import jobs


class FakeResponseSession:
    def close(self):
        return None


class FakeCrawler:
    def __init__(self, links, fail_name=None):
        self.links = links
        self.fail_name = fail_name
        self.session = FakeResponseSession()

    def discover_bulletins(self):
        return self.links

    def download_pdf(self, url, target):
        if self.fail_name and self.fail_name in target.name:
            raise RuntimeError("échec simulé")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4\n%%EOF")
        return "hash", target.stat().st_size, None, None


def wait_finished(manager: SyncManager, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = manager.state()
        if not state["running"]:
            return state
        time.sleep(0.02)
    raise AssertionError("Synchronisation non terminée")


def test_download_failure_finishes_sync_at_100_percent(monkeypatch, tmp_path):
    from app.bulletins.config import settings

    db = tmp_path / "bulletins.sqlite3"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db(db)
    links = [
        BulletinLink("https://www.entraideopelgt.fr/ok.pdf", "OK", "ok.pdf", 1, 2025, None, verified=True),
        BulletinLink("https://www.entraideopelgt.fr/bad.pdf", "BAD", "bad.pdf", 2, 2025, None, verified=True),
    ]
    manager = SyncManager(settings, db)
    assert manager.start(FakeCrawler(links, fail_name="bad")) is True
    state = wait_finished(manager)
    assert state["phase"] == "finished-with-errors"
    assert state["completedSteps"] == state["totalSteps"]
    assert len(state["errors"]) == 1
    with connect(db) as conn:
        rows = conn.execute("SELECT filename,status FROM bulletins ORDER BY filename").fetchall()
    assert {row["status"] for row in rows} >= {"download-error", "index-pending"}


def test_ocr_enqueue_is_deduplicated(monkeypatch, tmp_path):
    from app.bulletins.config import settings

    db = tmp_path / "bulletins.sqlite3"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db(db)
    for suffix in ("", "-wal", "-shm"):
        Path(str(jobs.DB_PATH) + suffix).unlink(missing_ok=True)
    jobs.init_jobs()
    link = BulletinLink("https://www.entraideopelgt.fr/one.pdf", "One", "one.pdf", 1, 2025, None, verified=True)
    manager = SyncManager(settings, db)
    assert manager.start(FakeCrawler([link]))
    wait_finished(manager)
    first_count = len([job for job in jobs.list_jobs() if job["queue"] == "ocr"])
    assert manager.start(FakeCrawler([link]), force_reindex=True)
    wait_finished(manager)
    second_count = len([job for job in jobs.list_jobs() if job["queue"] == "ocr"])
    assert first_count == second_count == 1


def test_bulletin_crawler_rejects_external_hosts_before_request(tmp_path):
    from app.bulletins.config import settings
    from app.bulletins.crawler import CrawlError, EntraideCrawler

    class NoNetwork:
        def get(self, *args, **kwargs):
            raise AssertionError("La requête réseau ne doit pas être envoyée")

    crawler = EntraideCrawler(settings)
    crawler.session = NoNetwork()
    verified, final_url, error, metadata = crawler._probe_pdf_url("https://example.org/private.pdf")
    assert verified is False
    assert final_url == "https://example.org/private.pdf"
    assert "non autorisé" in error
    assert metadata == {}
    candidates = crawler._candidate_pdf_urls("https://example.org/private.pdf", "Bulletin 1", 1, 2026, 1)
    assert candidates
    assert all("entraideopelgt.fr" in candidate for candidate in candidates)
    try:
        crawler.download_pdf("https://example.org/private.pdf", tmp_path / "private.pdf")
    except CrawlError as exc:
        assert "non autorisée" in str(exc)
    else:
        raise AssertionError("Le téléchargement externe aurait dû être refusé")


def test_bulletin_download_rejects_announced_oversize_pdf(tmp_path):
    from app.bulletins.config import settings
    from app.bulletins.crawler import CrawlError, EntraideCrawler

    class Response:
        url = "https://www.entraideopelgt.fr/large.pdf"
        headers = {"Content-Type": "application/pdf", "Content-Length": "11"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    crawler = EntraideCrawler(settings.model_copy(update={"max_pdf_bytes": 10}))
    crawler.session = Session()
    try:
        crawler.download_pdf(Response.url, tmp_path / "large.pdf")
    except CrawlError as exc:
        assert "trop volumineux" in str(exc)
    else:
        raise AssertionError("Le PDF trop volumineux aurait dû être refusé")
    assert not (tmp_path / "large.pdf").exists()
