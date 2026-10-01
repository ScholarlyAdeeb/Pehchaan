"""
Shared registry of forged documents — without personal data.

When an officer rejects a document as forged, only its *image fingerprint*
and the tamper types are written to `pehchaan_forgery_registry`, an
append-only, hash-chained table every checkpoint reads. Each new scan's
fingerprint is compared with the registry.

Fingerprint = two perceptual hashes (DCT low-frequency signs):
  * page:     256 bits of the whole image — sensitive to the printed text,
              so two different documents of the same design differ by 14+
              bits (measured on the dataset; median 112).
  * portrait: 64 bits of the holder photo region (not a face-recognition
              template; the photo cannot be rebuilt from it).

Match rule (measured, no false matches between different documents):
  page distance <= 12                       same image, re-saved or re-sent
  portrait <= 6 and page <= 70              same document, slightly re-cropped
A document re-photographed at a clearly different angle will not match.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

PAGE_EXACT = 12
PORTRAIT_CLOSE = 6
PAGE_LOOSE = 70


def _dct_hash(gray: np.ndarray, n: int, size: int) -> str:
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    coeffs = cv2.dct(small)[:n, :n].flatten()
    bits = coeffs > np.median(coeffs[1:])
    return f"{int(''.join('1' if b else '0' for b in bits), 2):0{n * n // 4}x}"


def fingerprint(image: np.ndarray, portrait: np.ndarray | None) -> dict[str, str | None]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    por = None
    if portrait is not None and portrait.size:
        pg = cv2.cvtColor(portrait, cv2.COLOR_BGR2GRAY) if portrait.ndim == 3 else portrait
        por = _dct_hash(pg, 8, 32)
    return {"page": _dct_hash(gray, 16, 64), "portrait": por}


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def is_match(fp: dict, page: str, portrait: str | None) -> tuple[bool, int, int | None]:
    d_page = hamming(fp["page"], page)
    d_por = hamming(fp["portrait"], portrait) if fp.get("portrait") and portrait else None
    matched = d_page <= PAGE_EXACT or (d_por is not None and d_por <= PORTRAIT_CLOSE and d_page <= PAGE_LOOSE)
    return matched, d_page, d_por


@dataclass
class RegistryMatch:
    page_distance: int
    portrait_distance: int | None
    tamper_types: str | None
    doc_type: str | None
    checkpoint_id: str | None
    source_scan: str | None
    when: str | None


def find_matches(fp: dict) -> list[RegistryMatch]:
    settings = get_settings()
    if not settings.DATABASE_URL:
        return []
    try:
        import psycopg

        with psycopg.connect(settings.DATABASE_URL, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT page_hash, portrait_hash, tamper_types, doc_type, checkpoint_id, source_scan, created_at "
                "FROM pehchaan_forgery_registry"
            ).fetchall()
    except Exception as e:  # table is created by the web server on first start
        logger.info("Forgery registry unavailable: %s", e)
        return []
    out = []
    for page, por, types, doc_type, cp, src, when in rows:
        if not page:
            continue
        matched, d_page, d_por = is_match(fp, page, por)
        if matched:
            out.append(RegistryMatch(d_page, d_por, types, doc_type, cp, src, when.isoformat() if when else None))
    return sorted(out, key=lambda m: m.page_distance)
