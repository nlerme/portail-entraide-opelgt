"""Locate FTS matches in native PDFs and scans without changing the index/PDF."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from app.bulletins.search import build_fts_query
from app.common.config import ROOT


def matched_pages(conn, bulletin_id: int, keywords: str, mode: str, page: int | None = None) -> list[dict]:
    query = build_fts_query(keywords, mode)
    clause = " AND CAST(page_no AS INTEGER)=?" if page is not None else ""
    values = [query, bulletin_id, *([page] if page is not None else [])]
    rows = conn.execute(
        "SELECT page_no,text_source,highlight(pages_fts,0,'[[[H]]]','[[[/H]]]') AS marked "
        "FROM pages_fts WHERE pages_fts MATCH ? AND CAST(bulletin_id AS INTEGER)=?" + clause +
        " ORDER BY CAST(page_no AS INTEGER)", values,
    ).fetchall()
    return [{"page": int(row["page_no"]), "source": row["text_source"],
             "terms": list(dict.fromkeys(re.findall(r"\[\[\[H\]\]\](.*?)\[\[\[/H\]\]\]", row["marked"], re.S)))}
            for row in rows]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"\s+", " ", "".join(char if char.isalnum() else " " for char in value
                                         if not unicodedata.combining(char))).strip()


def locate_words(runs: list[list[dict]], terms: list[str]) -> list[dict]:
    patterns = sorted({normalize(term) for term in terms} - {""}, key=len, reverse=True)
    matches = []
    variants = list(runs)
    for words in runs:
        if any(word["text"].endswith(("-", "\u00ad")) for word in words):
            variants.append([{**word, "line": ""} for word in words])
    for words in variants:
        text, owners = "", []
        for index, word in enumerate(words):
            join = index and words[index - 1]["text"].endswith(("-", "\u00ad")) and words[index - 1]["line"] != word["line"]
            token = normalize(word["text"])
            if text and not join:
                text += " "
                owners.append(-1)
            text += token
            owners.extend([index] * len(token))
        occupied = set()
        for pattern in patterns:
            for found in re.finditer(r"(?<!\w)" + re.escape(pattern).replace(r"\ ", r"\s+") + r"(?!\w)", text):
                indexes = sorted(set(owners[found.start():found.end()]) - {-1})
                if not indexes or occupied.intersection(range(*found.span())):
                    continue
                occupied.update(range(*found.span()))
                rects = [words[index]["rect"] for index in indexes]
                # Multipass OCR may locate the same passage more than once.
                center = ((rects[0][0] + rects[0][2]) / 2, (rects[0][1] + rects[0][3]) / 2)
                if any(abs(center[0] - item["center"][0]) < .012 and abs(center[1] - item["center"][1]) < .008
                       for item in matches):
                    continue
                matches.append({"rects": rects, "center": center})
    return [{"rects": item["rects"]} for item in sorted(matches, key=lambda item: (item["center"][1], item["center"][0]))]


def page_words(path: Path, page: int, source: str, settings) -> list[list[dict]]:
    stat = path.stat()
    options = ["v1", str(path.resolve()), stat.st_size, stat.st_mtime_ns, page, source,
               settings.ocr_lang, settings.ocr_dpi, settings.ocr_psm_main, settings.ocr_psm_sparse, settings.ocr_multipass]
    key = hashlib.sha256(json.dumps(options).encode()).hexdigest()
    directory = settings.data_dir / "pdf-word-positions"
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    cache = directory / f"{key}.json"
    with (directory / f"{key}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
        python = ROOT / "venv-ocr" / "bin" / "python"
        result = subprocess.run(
            [str(python) if python.is_file() else sys.executable, "-m", "app.bulletins.highlights",
             str(path.resolve()), str(page), source],
            cwd=ROOT, capture_output=True, text=True, timeout=50, check=True,
        )
        words = json.loads(result.stdout)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(words, stream, ensure_ascii=False)
                os.chmod(temporary, 0o640)
            os.replace(temporary, cache)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return words


def extract_words(path: Path, number: int, source: str, settings) -> list[list[dict]]:
    import fitz

    with fitz.open(path) as document:
        page = document[number - 1]
        width, height = page.rect.width, page.rect.height
        native = []
        for word in page.get_text("words"):
            rect = fitz.Rect(word[:4]) * page.rotation_matrix
            native.append({"text": word[4], "line": f"{word[5]}:{word[6]}",
                           "rect": [rect.x0 / width, rect.y0 / height, rect.x1 / width, rect.y1 / height]})
        if source not in {"ocr", "hybrid"} and native:
            return [native]
        import pytesseract
        from PIL import Image

        from app.bulletins.indexer import sanitize_tessdata_environment, validate_tessdata_languages

        sanitize_tessdata_environment()
        validate_tessdata_languages(settings.ocr_lang)
        pixmap = page.get_pixmap(dpi=min(200, max(100, settings.ocr_dpi)), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).convert("L")
        runs = [native] if native else []
        modes = [settings.ocr_psm_main, *([settings.ocr_psm_sparse] if settings.ocr_multipass else [])]
        for mode in dict.fromkeys(modes):
            data = pytesseract.image_to_data(image, lang=settings.ocr_lang, config=f"--oem 1 --psm {mode}",
                                            output_type=pytesseract.Output.DICT, timeout=min(20, settings.ocr_timeout_seconds))
            runs.append([{"text": text, "line": f"{data['block_num'][i]}:{data['par_num'][i]}:{data['line_num'][i]}",
                          "rect": [data['left'][i] / image.width, data['top'][i] / image.height,
                                   (data['left'][i] + data['width'][i]) / image.width,
                                   (data['top'][i] + data['height'][i]) / image.height]}
                         for i, text in enumerate(data["text"]) if text.strip()])
        return runs


if __name__ == "__main__":
    from app.bulletins.config import settings

    print(json.dumps(extract_words(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], settings), ensure_ascii=False))
