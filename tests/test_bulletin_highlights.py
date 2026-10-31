from __future__ import annotations

import json
import shutil
import sqlite3
from types import SimpleNamespace

import fitz
import pytest

from app.bulletins import highlights as h
from app.bulletins.config import settings


def words(*values):
    return [{"text": text, "line": str(line), "rect": [index / 10, .1 + line / 10, (index + 1) / 10, .15 + line / 10]}
            for index, (text, line) in enumerate(values)]


def test_fts_match_passages_follow_prefix_phrase_and_raw_queries_across_all_pages():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(text,bulletin_id UNINDEXED,page_no UNINDEXED,text_source UNINDEXED)")
    for page, text in [(1, "Réglage du carburateur. Réglages moteur."), (2, "Pompe à eau."), (3, "Pompe à essence. Eau.")]:
        conn.execute("INSERT INTO pages_fts VALUES(?,?,?,?)", (text, 7, page, "native"))
    conn.execute("INSERT INTO pages_fts VALUES('Réglage secret',8,1,'native')")
    assert h.matched_pages(conn, 7, "régl", "all") == [{"page": 1, "source": "native", "terms": ["Réglage", "Réglages"]}]
    assert [page["page"] for page in h.matched_pages(conn, 7, "pompe eau", "all")] == [2, 3]
    assert [page["page"] for page in h.matched_pages(conn, 7, "pompe à eau", "phrase")] == [2]
    assert [page["page"] for page in h.matched_pages(conn, 7, 'pompe NOT essence', "raw")] == [2]
    assert not h.matched_pages(conn, 7, "régl", "all", 2)
    with pytest.raises(sqlite3.OperationalError):
        h.matched_pages(conn, 7, '"', "raw")
    conn.close()


def test_positions_handle_accents_ligatures_apostrophes_hyphenated_lines_and_repeated_terms():
    run = words(("L’huile", 0), ("distribution", 0), ("distribu-", 1), ("tion", 2), ("Réglage", 2), ("ﬁltre", 2))
    assert len(h.locate_words([run], ["huile", "réglage", "filtre"])) == 3
    matches = h.locate_words([run], ["distribution"])
    assert len(matches) == 2 and sorted(len(match["rects"]) for match in matches) == [1, 2]
    assert len(h.locate_words([run], ["distribu"])) == 1
    assert not h.locate_words([run], ["distrib", "réglage|huile"])


def test_phrases_span_words_and_multipass_ocr_does_not_duplicate_occurrences():
    run = words(("pompe", 0), ("à", 0), ("eau", 0), ("pompe", 1), ("à", 1), ("eau", 1))
    matches = h.locate_words([run, run], ["pompe à eau", "pompe"])
    assert len(matches) == 2 and all(len(match["rects"]) == 3 for match in matches)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_native_positions_align_with_rotated_pdf_coordinates(tmp_path, rotation):
    path = tmp_path / "native.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=300)
        page.insert_text((80, 100), "Oil pressure. Oil filter.", fontsize=20)
        page.set_rotation(rotation)
        doc.save(path)
    runs = h.extract_words(path, 1, "native", settings)
    matches = h.locate_words(runs, ["Oil"])
    assert len(matches) == 2
    for match in matches:
        for x0, y0, x1, y1 in match["rects"]:
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_word_position_cache_reuses_results_and_invalidates_when_pdf_changes(tmp_path, monkeypatch):
    path = tmp_path / "native.pdf"
    path.write_bytes(b"fixture")
    calls = []
    result = [words(("Oil", 0))]
    monkeypatch.setattr(h.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(stdout=json.dumps(result)))
    configured = settings.model_copy(update={"data_dir": tmp_path / "data"})
    assert h.page_words(path, 1, "native", configured) == result
    assert h.page_words(path, 1, "native", configured) == result
    assert len(calls) == 1 and calls[0][1]["timeout"] == 50
    cache = list((configured.data_dir / "pdf-word-positions").glob("*.json"))
    assert len(cache) == 1 and cache[0].stat().st_mode & 0o777 == 0o640
    path.write_bytes(b"changed fixture")
    assert h.page_words(path, 1, "native", configured) == result and len(calls) == 2


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract absent")
def test_scan_positions_use_real_ocr_and_leave_original_pdf_unchanged(tmp_path):
    path = tmp_path / "scan.pdf"
    with fitz.open() as original, fitz.open() as scan:
        page = original.new_page(width=600, height=300)
        page.insert_text((60, 100), "Oil pressure and oil filter", fontsize=28)
        raster = page.get_pixmap(dpi=160).tobytes("png")
        scan.new_page(width=600, height=300).insert_image(fitz.Rect(0, 0, 600, 300), stream=raster)
        scan.save(path)
    before = path.read_bytes()
    configured = settings.model_copy(update={"ocr_lang": "eng", "ocr_multipass": False})
    runs = h.extract_words(path, 1, "ocr", configured)
    assert len(h.locate_words(runs, ["oil"])) == 2
    assert len(h.locate_words(runs, ["Oil pressure"])) == 1
    assert before == path.read_bytes()
