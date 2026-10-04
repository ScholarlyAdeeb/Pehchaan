"""
Module 1 — OCR Extraction with Document Region Localization.

Pipeline:
1. Document Region Localization (Faster R-CNN) — detects semantic regions
2. Targeted OCR — runs on detected text regions for higher accuracy
3. Returns both region detection results and extracted text

Wraps whichever OCR backend is installed behind a stable interface so the
rest of the system never imports `pytesseract` directly. If Tesseract's
binary isn't installed on the host, we fail soft with a clear error the
frontend can surface, instead of crashing the whole scan.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from pytesseract import Output

    _TESSERACT_PACKAGE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TESSERACT_PACKAGE_AVAILABLE = False


def tesseract_binary_available() -> bool:
    """
    True only if the actual Tesseract *executable* is reachable — having the
    `pytesseract` Python package installed is necessary but not sufficient,
    since it's just a thin wrapper that shells out to the binary. Used by
    the health endpoint so the frontend's status badge reflects reality
    instead of a package import that always succeeds after `pip install`.
    """
    if not _TESSERACT_PACKAGE_AVAILABLE:
        return False
    _configure_tesseract()
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# Back-compat alias used elsewhere in this module for the soft-fail path below.
_TESSERACT_AVAILABLE = _TESSERACT_PACKAGE_AVAILABLE


@dataclass
class OCRWord:
    text: str
    confidence: float
    box: tuple[int, int, int, int]  # x, y, w, h


@dataclass
class OCRResult:
    raw_text: str
    # Reading of the lightly processed page (see preprocess_variants); the
    # field extractors fill in what raw_text missed from it.
    light_text: str = ""
    words: list[OCRWord] = field(default_factory=list)
    mean_confidence: float = 0.0
    engine_available: bool = True
    warning: str | None = None
    # New fields for region-aware OCR
    region_detection: Optional[dict] = None  # Serialized RegionDetectionResult
    text_regions_used: int = 0
    region_reads: list = field(default_factory=list)  # per-box Tesseract readings (region_fields.RegionRead)


def _configure_tesseract() -> None:
    settings = get_settings()
    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


def _run_localization(image: np.ndarray, document_type: str) -> Optional[dict]:
    """Run document region localization if enabled and a trained model exists."""
    settings = get_settings()
    if not settings.LOCALIZATION_ENABLED:
        return None

    from pathlib import Path
    model_path = settings.LOCALIZATION_MODEL_PATH
    if not model_path or not Path(model_path).is_file():
        logger.info("Localization skipped — no trained model at %s", model_path)
        return None
    if not _region_model_trusted(str(Path(model_path).resolve())):
        return None

    try:
        detector = _cached_detector(model_path, settings.LOCALIZATION_CONFIDENCE, settings.LOCALIZATION_DEVICE)
        # The detector is trained on raw card images, so it runs on the original
        # pixels: deskewing here would shift every box away from the image the
        # rest of the pipeline reads. Regions are not filtered by document type
        # here because in auto-detect mode the type is not final yet; the field
        # merge only uses the classes that belong to the final type.
        with _detector_lock:
            result = detector.detect(image, None)
        result.document_type = document_type
        return result.to_dict() if result.regions else None
    except Exception as e:
        logger.warning(f"Localization failed, continuing with full-image OCR only: {e}")
        return None


_detector_lock = threading.Lock()


@lru_cache(maxsize=4)
def _region_model_trusted(resolved_path: str) -> bool:
    """Refuse a default-location model whose hash differs from model_manifest.json."""
    from app.modules.provenance import MODEL_FILES, model_trusted

    if resolved_path != str(MODEL_FILES["region_detector"].resolve()):
        return True  # a custom path set by the operator is outside the manifest
    return model_trusted("region_detector")


@lru_cache(maxsize=2)
def _cached_detector(model_path: str, confidence: float, device: str):
    """One loaded model per process instead of a reload from disk on every request."""
    from app.modules.localization.detector import create_detector

    if device == "auto":
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"

    return create_detector(model_path=model_path, confidence_threshold=confidence, device=device)


def _is_mrz_word(text: str) -> bool:
    return "<" in text and len(text) >= 15


def _has_mrz_fragment(words: list[OCRWord]) -> bool:
    return any(_is_mrz_word(w.text) for w in words)


def _mrz_band(gray: np.ndarray, words: list[OCRWord]) -> np.ndarray | None:
    """Crop the horizontal band around an MRZ fragment the main pass found.

    Works wherever the MRZ sits on the page (full-page scans put it well
    above the bottom), unlike a fixed bottom-of-image crop.
    """
    import cv2

    hits = [w for w in words if _is_mrz_word(w.text)]
    if not hits:
        return None
    top = min(w.box[1] for w in hits)
    bottom = max(w.box[1] + w.box[3] for w in hits)
    line_h = max(w.box[3] for w in hits)
    y1 = max(0, int(top - 2.5 * line_h))
    y2 = min(gray.shape[0], int(bottom + 2.5 * line_h))
    band = gray[y1:y2, :]
    if band.size == 0:
        return None
    # Upscale only: binarising thin OCR-B glyphs turns '<' into C/K.
    return cv2.resize(band, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)


def _lines_text(data: dict) -> str:
    lines: dict[tuple[int, int, int], list[str]] = {}
    for i, t in enumerate(data["text"]):
        if t.strip():
            lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(t.strip())
    return "\n".join(" ".join(parts) for parts in lines.values())


def _tesseract_config(document_type: str) -> str:
    """Document-type-specific Tesseract config for better accuracy."""
    base = "--oem 3"
    if document_type in ("passport", "visa"):
        # PSM 6 = uniform block. No whitelist on main pass — visual zone
        # has mixed content (names, dates, places).
        return f"{base} --psm 6 -c preserve_interword_spaces=1"
    if document_type in ("national_id", "aadhar"):
        return f"{base} --psm 4"
    if document_type == "pan":
        return f"{base} --psm 6"
    if document_type == "driving_license":
        return f"{base} --psm 4"
    return f"{base} --psm 6"


def run_ocr(image: np.ndarray, document_type: str = "passport") -> OCRResult:
    """
    Run OCR over a BGR (OpenCV-style) image array with optional region localization.

    Pipeline:
    1. Image preprocessing (deskew, denoise, contrast enhance)
    2. Document Region Localization (Faster R-CNN) — if a trained model is configured; boxes are reported as evidence
    3. Full-image OCR (the reading the field extractors use)
    4. For passports: second MRZ-tuned pass on the bottom of the page
    """
    from app.modules.ocr.preprocessing import preprocess_for_mrz, preprocess_variants

    # Step 0: Preprocess image for better OCR (orientation detection needs Tesseract configured)
    if _TESSERACT_AVAILABLE:
        _configure_tesseract()
    preprocessed, light = preprocess_variants(image, document_type)

    # Step 1: Document region localization (if a trained model is configured).
    # Its boxes are reported as evidence alongside the full-page reading; they
    # do not replace it, because the field extractors rely on printed labels and
    # line structure that per-box crops do not carry.
    region_result = _run_localization(image, document_type)

    # Each detected text box is also read on its own; the scan route merges
    # those readings into the extracted fields (app/modules/ocr/region_fields.py).
    region_reads = []
    if region_result and _TESSERACT_AVAILABLE:
        from app.modules.ocr.region_fields import read_regions

        region_reads = read_regions(image, region_result)

    # Step 2: Full-image OCR with preprocessing

    if not _TESSERACT_AVAILABLE:
        return OCRResult(
            raw_text="",
            engine_available=False,
            warning=(
                "Tesseract OCR is not installed on this machine. Install the "
                "Tesseract binary and the `pytesseract` package (see "
                "backend/README.md) to enable real text extraction. "
                "Downstream modules will run in degraded mode."
            ),
        )

    _configure_tesseract()
    config = _tesseract_config(document_type)

    try:
        # The denoised page is the primary reading. The lightly processed one
        # is read too: on crisp, small print it succeeds where denoising has
        # blurred the text away (see preprocess_variants).
        data = pytesseract.image_to_data(preprocessed, output_type=Output.DICT, config=config)
        light_data = pytesseract.image_to_data(light, output_type=Output.DICT, config=config)
    except pytesseract.TesseractNotFoundError:
        return OCRResult(
            raw_text="",
            engine_available=False,
            warning=(
                "Tesseract binary not found on PATH. Set TESSERACT_CMD in "
                "your .env to the full path of tesseract.exe."
            ),
        )

    words: list[OCRWord] = []
    confidences: list[float] = []
    lines: dict[tuple[int, int, int], list[str]] = {}

    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 0.0
        box = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
        words.append(OCRWord(text=text, confidence=conf, box=box))
        confidences.append(conf)
        # Field extractors are label/line based, so keep Tesseract's line structure.
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(text)

    main_text = "\n".join(" ".join(parts) for parts in lines.values())
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

    # Step 3: For passports/visas, a second MRZ-tuned pass when the main pass
    # did not already return both MRZ lines.
    if document_type in ("passport", "visa"):
        import re
        mrz_like = [l for l in main_text.splitlines()
                    if "<" in l and len(re.sub(r"\s", "", l)) >= 40]
        if len(mrz_like) < 2:
            try:
                mrz_img = _mrz_band(preprocessed, words) if mrz_like or _has_mrz_fragment(words) else None
                if mrz_img is None:
                    mrz_img = preprocess_for_mrz(image)
                mrz_data = pytesseract.image_to_data(
                    mrz_img, output_type=Output.DICT,
                    config="--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<",
                )
                mrz_lines: dict[tuple[int, int, int], list[str]] = {}
                for j, t in enumerate(mrz_data["text"]):
                    if t.strip():
                        k = (mrz_data["block_num"][j], mrz_data["par_num"][j], mrz_data["line_num"][j])
                        mrz_lines.setdefault(k, []).append(t.strip())
                mrz_text = "\n".join("".join(parts) for parts in mrz_lines.values())
                if mrz_text:
                    main_text = main_text + "\n\n" + mrz_text
            except Exception as e:
                logger.warning("MRZ-specific OCR pass failed: %s", e)

    return OCRResult(
        raw_text=main_text,
        light_text=_lines_text(light_data),
        words=words,
        mean_confidence=round(mean_conf, 2),
        region_detection=region_result,
        text_regions_used=len(region_reads),
        region_reads=region_reads,
    )
