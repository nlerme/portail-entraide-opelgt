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


def test_close_distinct_occurrences_are_not_removed_as_multipass_duplicates():
    run = [{"text": "GT", "line": "0", "rect": [.100, .100, .108, .110]},
           {"text": "GT", "line": "0", "rect": [.110, .100, .118, .110]}]
    assert len(h.locate_words([run, run], ["GT"])) == 2


@pytest.mark.parametrize("value,expected", [("#ABCDEF", "#abcdef"), ("#00ff80", "#00ff80"),
                                           ("#fff", "#ffff00"), ("red", "#ffff00"),
                                           (None, "#ffff00"), ("var(--unsafe)", "#ffff00")])
def test_highlight_color_is_configurable_and_rejects_invalid_css(monkeypatch, value, expected):
    monkeypatch.setattr(h, "section", lambda *names: {"viewer": {"highlight_color": value}})
    assert h.highlight_color() == expected


def test_corrupt_position_cache_is_rebuilt(tmp_path, monkeypatch):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"fixture")
    result, calls = [words(("Oil", 0))], []
    monkeypatch.setattr(h.subprocess, "run", lambda *args, **kwargs: calls.append(1) or SimpleNamespace(stdout=json.dumps(result)))
    configured = settings.model_copy(update={"data_dir": tmp_path / "data"})
    assert h.page_words(path, 1, "native", configured) == result
    cache = next((configured.data_dir / "pdf-word-positions").glob("*.json"))
    cache.write_text('{"invalid": true}')
    assert h.page_words(path, 1, "native", configured) == result and len(calls) == 2


def test_ocr_coordinates_are_mapped_back_to_the_original_scan(tmp_path, monkeypatch):
    import numpy as np
    import pytesseract
    from PIL import Image

    from app.bulletins import indexer

    path = tmp_path / "scan.pdf"
    with fitz.open() as doc:
        doc.new_page(width=500, height=250)
        doc.save(path)
    image = Image.new("RGB", (1000, 500), "white")
    inverse = np.array([[0., -1., 300.], [1., 0., 0.]])
    monkeypatch.setattr(indexer, "render_page_to_image", lambda *args: image)
    monkeypatch.setattr(indexer, "preprocess_for_ocr_with_transform", lambda image: (image, inverse))
    data = {"text": ["Oil"], "left": [100], "top": [50], "width": [40], "height": [20],
            "block_num": [1], "par_num": [1], "line_num": [1]}
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *args, **kwargs: data)
    runs = h.extract_words(path, 1, "ocr", settings.model_copy(update={"ocr_lang": "eng", "ocr_multipass": False}))
    assert runs[0][0]["rect"] == pytest.approx([.23, .2, .25, .28])


def test_successful_first_ocr_pass_is_kept_if_the_second_times_out(tmp_path, monkeypatch):
    import numpy as np
    import pytesseract
    from PIL import Image

    from app.bulletins import indexer

    path = tmp_path / "scan.pdf"
    with fitz.open() as doc:
        doc.new_page(width=500, height=250)
        doc.save(path)
    image = Image.new("RGB", (1000, 500), "white")
    monkeypatch.setattr(indexer, "render_page_to_image", lambda *args: image)
    monkeypatch.setattr(indexer, "preprocess_for_ocr_with_transform", lambda image: (image, np.array([[1., 0., 0.], [0., 1., 0.]])))
    data = {"text": ["Oil"], "left": [100], "top": [50], "width": [40], "height": [20],
            "block_num": [1], "par_num": [1], "line_num": [1]}
    calls = []
    def recognize(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("Timeout")
        return data
    monkeypatch.setattr(pytesseract, "image_to_data", recognize)
    runs = h.extract_words(path, 1, "ocr", settings.model_copy(update={"ocr_lang": "eng", "ocr_multipass": True}))
    assert len(calls) == 2 and len(h.locate_words(runs, ["oil"])) == 1


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
    assert len(calls) == 1 and calls[0][1]["timeout"] == 75
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


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract absent")
@pytest.mark.parametrize("source", ["native", "ocr"])
def test_scan_does_not_highlight_a_shifted_invisible_text_layer(tmp_path, source):
    path = tmp_path / "shifted-layer.pdf"
    with fitz.open() as visible, fitz.open() as scan:
        page = visible.new_page(width=600, height=300)
        page.insert_text((200, 180), "Oil pressure", fontsize=28)
        target = scan.new_page(width=600, height=300)
        target.insert_image(target.rect, stream=page.get_pixmap(dpi=160).tobytes("png"))
        target.insert_text((40, 50), "Oil pressure", fontsize=28, render_mode=3)
        target.insert_text((40, 80), "Invisible OCR metadata copied from a scanned bulletin with deliberately displaced positions.",
                           fontsize=8, render_mode=3)
        scan.save(path)
    with fitz.open(path) as scan:
        assert len(scan[0].get_text().strip()) > settings.ocr_text_threshold
    runs = h.extract_words(path, 1, source, settings.model_copy(update={"ocr_lang": "eng", "ocr_multipass": False}))
    matches = h.locate_words(runs, ["oil"])
    assert len(matches) == 1
    assert matches[0]["rects"][0][0] > .30 and matches[0]["rects"][0][1] > .45
