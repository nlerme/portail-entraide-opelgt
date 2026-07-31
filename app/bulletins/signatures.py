from __future__ import annotations

from app.bulletins.config import Settings


def ocr_index_signature(settings: Settings) -> str:
    return "|".join(
        [
            "ocr-v3-crossplatform-parallel",
            f"mode={settings.ocr_mode}",
            f"lang={settings.ocr_lang}",
            f"dpi={settings.ocr_dpi}",
            f"threshold={settings.ocr_text_threshold}",
            f"multipass={settings.ocr_multipass}",
            f"psm={settings.ocr_psm_main}/{settings.ocr_psm_sparse}",
            f"workers_auto_cap={getattr(settings, 'ocr_workers_auto_cap', 1)}",
            "preprocess=denoise-deskew-otsu",
            "text_normalization=NFKC-lf",
            "tessdata=tessdata_fast_fra_eng",
        ]
    )
