from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image

from app.bulletins.config import Settings
from app.bulletins.signatures import ocr_index_signature

TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
elif shutil.which("tesseract"):
    pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract") or "tesseract"


@dataclass
class PageText:
    page_no: int
    text: str
    source: str
    confidence: float | None


@dataclass(frozen=True)
class OcrTask:
    page_index_zero_based: int
    page_no: int
    native_text: str
    source_mode: str


class PdfIndexer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract_pages(self, pdf_path: Path) -> list[PageText]:
        mode = self.settings.ocr_mode.lower().strip()
        if mode not in {"auto", "always", "never", "hybrid"}:
            mode = "auto"

        pages: list[PageText | None] = []
        tasks: list[OcrTask] = []
        with fitz.open(pdf_path) as doc:
            for index, page in enumerate(doc, start=1):
                native_text = clean_text(page.get_text("text") or "")
                native_len = len(native_text.strip())
                needs_ocr = mode == "always" or (mode == "auto" and native_len < self.settings.ocr_text_threshold)

                if mode == "never":
                    pages.append(PageText(index, native_text, "native", None))
                    continue

                if mode == "hybrid":
                    pages.append(None)
                    tasks.append(OcrTask(index - 1, index, native_text, "hybrid"))
                    continue

                if needs_ocr:
                    pages.append(None)
                    tasks.append(OcrTask(index - 1, index, native_text, "ocr"))
                else:
                    pages.append(PageText(index, native_text, "native", None))

        if tasks:
            workers = resolve_ocr_workers(
                self.settings.ocr_workers,
                len(tasks),
                getattr(self.settings, "ocr_workers_auto_cap", 4),
            )
            if workers <= 1:
                results = [self._ocr_task(pdf_path, task) for task in tasks]
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr") as executor:
                    futures = [executor.submit(self._ocr_task, pdf_path, task) for task in tasks]
                    results = [future.result() for future in futures]

            for task, result in zip(tasks, results):
                pages[task.page_no - 1] = result

        return [page for page in pages if page is not None]

    def _ocr_task(self, pdf_path: Path, task: OcrTask) -> PageText:
        with fitz.open(pdf_path) as doc:
            page = doc[task.page_index_zero_based]
            ocr_text, confidence = self.ocr_page(page)

        if task.source_mode == "hybrid":
            combined = combine_texts(task.native_text, ocr_text)
            source = "hybrid" if ocr_text.strip() else "native"
            return PageText(task.page_no, combined, source, confidence)

        if ocr_text.strip():
            return PageText(task.page_no, ocr_text, "ocr", confidence)
        return PageText(task.page_no, task.native_text, "native-empty", confidence)

    def ocr_page(self, page: fitz.Page) -> tuple[str, float | None]:
        image = render_page_to_image(page, self.settings.ocr_dpi)
        processed = preprocess_for_ocr(image)

        main_text, main_conf = run_tesseract(
            processed,
            lang=self.settings.ocr_lang,
            psm=self.settings.ocr_psm_main,
            timeout=self.settings.ocr_timeout_seconds,
        )

        if not self.settings.ocr_multipass:
            return clean_text(main_text), main_conf

        sparse_text, sparse_conf = run_tesseract(
            processed,
            lang=self.settings.ocr_lang,
            psm=self.settings.ocr_psm_sparse,
            timeout=self.settings.ocr_timeout_seconds,
        )
        combined = combine_texts(main_text, sparse_text)
        confidence_values = [c for c in [main_conf, sparse_conf] if c is not None]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
        return clean_text(combined), confidence


def resolve_ocr_workers(configured: int, task_count: int, auto_cap: int = 4) -> int:
    if task_count <= 1:
        return 1
    if configured and configured > 0:
        return max(1, min(int(configured), task_count))

    # Conservative auto mode: enough parallelism for a major speedup, but capped to
    # avoid exhausting RAM on machines peu puissantes when pages are
    # rendered at 300 DPI. The cap is part of the OCR signature policy and must
    # rester stable entre les lancements.
    cpus = os.cpu_count() or 2
    return max(1, min(task_count, max(1, int(auto_cap)), max(1, cpus // 2)))


def clone_settings_with_page_workers(settings: Settings, page_workers: int) -> Settings:
    # Pydantic v2. The original Settings object is immutable enough for reads, but
    # using a copy makes the batch synchronizer explicit: when several PDFs are
    # processed concurrently, each PDF processes its pages sequentially so the
    # total OCR worker count stays bounded and predictable.
    return settings.model_copy(update={"ocr_workers": int(page_workers)})


def render_page_to_image(page: fitz.Page, dpi: int) -> Image.Image:
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    gray = np.array(image.convert("L"))

    # Supprime legerement le bruit de scan sans gommer le texte dactylographie.
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

    # Redressement approximatif : utile pour les bulletins anciens scannes un peu de travers.
    deskewed = deskew(denoised)

    # Binarisation robuste. Otsu suffit souvent pour les pages machine a ecrire; on evite
    # une binarisation trop agressive qui detruirait les annotations manuscrites fines.
    _, thresholded = cv2.threshold(deskewed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(thresholded)


def deskew(gray: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(gray < 245))
    if coords.size == 0:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) < 0.25 or abs(angle) > 8:
        return gray

    height, width = gray.shape[:2]
    center = (width // 2, height // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated



def sanitize_tessdata_environment() -> None:
    """Normalize OCR data-path environment variables for child tesseract calls.

    Certaines configurations peuvent laisser des guillemets littéraux
    autour de TESSDATA_PREFIX/TESSDATA_DIR. Tesseract les interprète alors
    comme une partie du chemin et ne charge plus fra/eng.
    """
    for name in ("TESSDATA_DIR", "TESSDATA_PREFIX"):
        value = os.environ.get(name)
        if not value:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned != value:
            os.environ[name] = cleaned


def validate_tessdata_languages(lang: str) -> None:
    # Lightweight local validation used by diagnostics/tests and safe to call
    # before OCR. Tesseract also validates at runtime.
    tessdata_dir = os.environ.get("TESSDATA_DIR") or os.environ.get("TESSDATA_PREFIX")
    if not tessdata_dir:
        return
    tessdata_path = Path(tessdata_dir.strip().strip('"').strip("'"))
    if tessdata_path.name.lower() != "tessdata" and (tessdata_path / "tessdata").exists():
        tessdata_path = tessdata_path / "tessdata"
    missing = []
    for code in [part.strip() for part in lang.split("+") if part.strip()]:
        if not (tessdata_path / f"{code}.traineddata").exists():
            missing.append(f"{code}.traineddata")
    if missing:
        raise RuntimeError(
            "Données OCR introuvables dans "
            f"{tessdata_path}: {', '.join(missing)}. "
            "Installe ou corrige les paquets Tesseract OCR et les données fra/eng."
        )

def run_tesseract(image: Image.Image, lang: str, psm: int, timeout: int) -> tuple[str, float | None]:
    config_parts = ["--oem 1", f"--psm {psm}", "-c preserve_interword_spaces=1"]

    # Ne pas injecter --tessdata-dir dans la chaîne de configuration pytesseract.
    # Des chemins avec guillemets intégrés peuvent être transmis tels quels
    # à Tesseract. On s'appuie donc sur l'environnement TESSDATA_PREFIX/TESSDATA_DIR
    # normalisé par le service Linux.
    sanitize_tessdata_environment()
    validate_tessdata_languages(lang)

    config = " ".join(config_parts)
    data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=pytesseract.Output.DICT, timeout=timeout)

    words: list[str] = []
    confidences: list[float] = []
    current_line: tuple[int, int, int] | None = None
    line_words: list[str] = []
    lines: list[str] = []

    for i, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text or "").strip()
        if not text:
            continue
        conf_raw = data.get("conf", [])[i]
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            conf = -1
        if conf >= 0:
            confidences.append(conf)
        line_key = (
            int(data.get("block_num", [0])[i]),
            int(data.get("par_num", [0])[i]),
            int(data.get("line_num", [0])[i]),
        )
        if current_line is None:
            current_line = line_key
        if line_key != current_line:
            if line_words:
                lines.append(" ".join(line_words))
            line_words = []
            current_line = line_key
        line_words.append(text)
        words.append(text)

    if line_words:
        lines.append(" ".join(line_words))

    if not lines and words:
        lines = [" ".join(words)]

    confidence = sum(confidences) / len(confidences) if confidences else None
    return "\n".join(lines), confidence


def clean_text(text: str) -> str:
    # Normalize line endings and Unicode forms before FTS insertion. This avoids
    # petites différences du flux texte deviennent des jetons
    # de recherche instables.
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def combine_texts(primary: str, secondary: str) -> str:
    primary_lines = [line.strip() for line in primary.splitlines() if line.strip()]
    secondary_lines = [line.strip() for line in secondary.splitlines() if line.strip()]
    seen = {normalize_line(line) for line in primary_lines}
    combined = list(primary_lines)
    for line in secondary_lines:
        key = normalize_line(line)
        if key and key not in seen:
            combined.append(line)
            seen.add(key)
    return "\n".join(combined)


def normalize_line(line: str) -> str:
    return re.sub(r"\W+", "", line.lower())[:160]



def extract_pdf_pages(settings: Settings, bulletin: Mapping[str, Any]) -> list[PageText]:
    pdf_path = Path(str(bulletin["local_path"]))
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    indexer = PdfIndexer(settings)
    return indexer.extract_pages(pdf_path)


def store_pdf_index(
    conn: sqlite3.Connection,
    settings: Settings,
    bulletin: Mapping[str, Any],
    pages: list[PageText],
) -> int:
    # All database writes stay single-threaded and ordered by the caller. This
    # preserves deterministic rowids and therefore deterministic result ordering
    # même lorsque l'extraction OCR est effectuée en parallèle.
    bulletin_id = int(bulletin["id"])
    conn.execute("DELETE FROM pages_fts WHERE bulletin_id = ?", (bulletin_id,))
    conn.execute("DELETE FROM pages WHERE bulletin_id = ?", (bulletin_id,))

    for page in sorted(pages, key=lambda p: p.page_no):
        cur = conn.execute(
            """
            INSERT INTO pages (bulletin_id, page_no, text, text_source, ocr_confidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (bulletin_id, page.page_no, page.text, page.source, page.confidence),
        )
        page_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO pages_fts (
                rowid, text, title, filename, bulletin_id, page_no, number, year, text_source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                page_id,
                page.text,
                bulletin["title"],
                bulletin["filename"],
                bulletin_id,
                page.page_no,
                bulletin["number"],
                bulletin["year"],
                page.source,
            ),
        )

    conn.execute(
        """
        UPDATE bulletins
        SET pages = ?, indexed_at = CURRENT_TIMESTAMP, index_signature = ?, status = 'indexed'
        WHERE id = ?
        """,
        (len(pages), ocr_index_signature(settings), bulletin_id),
    )
    conn.commit()
    return len(pages)


def index_pdf(conn: sqlite3.Connection, settings: Settings, bulletin: Mapping[str, Any]) -> int:
    pages = extract_pdf_pages(settings, bulletin)
    return store_pdf_index(conn, settings, bulletin, pages)


def escape_fts_token(token: str) -> str:
    token = token.strip()
    token = token.replace('"', '""')
    return f'"{token}"'


def build_fts_query(keywords: str, mode: str) -> str:
    keywords = keywords.strip()
    mode = mode.lower().strip()
    if not keywords:
        raise ValueError("Veuillez saisir au moins un mot cle.")

    if mode == "raw":
        return keywords

    if mode == "phrase":
        return escape_fts_token(keywords)

    tokens = [t for t in re.split(r"\s+", keywords) if t.strip()]
    if not tokens:
        raise ValueError("Veuillez saisir au moins un mot cle.")

    if mode == "any":
        return " OR ".join(f"{escape_fts_token(t)}*" for t in tokens)

    # Par defaut : tous les mots, prefix-match pour trouver carburateur/carburateurs.
    return " ".join(f"{escape_fts_token(t)}*" for t in tokens)


def search_pages(
    conn: sqlite3.Connection,
    keywords: str,
    mode: str = "all",
    year_from: int | None = None,
    year_to: int | None = None,
    bulletin_from: int | None = None,
    bulletin_to: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    fts_query = build_fts_query(keywords, mode)
    where = ["pages_fts MATCH ?"]
    params: list[Any] = [fts_query]

    if year_from is not None:
        where.append("CAST(year AS INTEGER) >= ?")
        params.append(year_from)
    if year_to is not None:
        where.append("CAST(year AS INTEGER) <= ?")
        params.append(year_to)
    if bulletin_from is not None:
        where.append("CAST(number AS INTEGER) >= ?")
        params.append(bulletin_from)
    if bulletin_to is not None:
        where.append("CAST(number AS INTEGER) <= ?")
        params.append(bulletin_to)

    where_sql = " AND ".join(where)
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    count_sql = f"SELECT COUNT(*) AS count FROM pages_fts WHERE {where_sql}"
    total = int(conn.execute(count_sql, params).fetchone()["count"])

    sql = f"""
        SELECT
            rowid AS page_id,
            title,
            filename,
            bulletin_id,
            page_no,
            number,
            year,
            text_source,
            bm25(pages_fts) AS score,
            snippet(pages_fts, 0, '[[[H]]]', '[[[/H]]]', '…', 32) AS excerpt
        FROM pages_fts
        WHERE {where_sql}
        ORDER BY score ASC, CAST(number AS INTEGER) ASC, CAST(page_no AS INTEGER) ASC, filename ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "pageId": row["page_id"],
                "bulletinId": row["bulletin_id"],
                "bulletinTitle": row["title"],
                "filename": row["filename"],
                "number": row["number"],
                "year": row["year"],
                "page": row["page_no"],
                "source": row["text_source"],
                "score": row["score"],
                "excerpt": row["excerpt"] or "",
                "pdfUrl": f"/api/pdf/{row['bulletin_id']}#page={row['page_no']}",
            }
        )
    return {"total": total, "results": results, "query": fts_query}
