"""
Error Level Analysis (ELA) — classic JPEG-forensics technique.

Idea: a genuine, never-edited JPEG has a roughly uniform compression error
across the whole image because every 8x8 block was quantized the same
number of times. When someone pastes in a replacement photo, retouches a
date, or stamps over a visa, that region gets re-compressed a *different*
number of times than the rest of the image — so re-saving the image at a
known quality and diffing against the original makes edited regions light
up as brighter blobs in the error map.

This doesn't require any training data and works on any JPEG-derived image,
which is why it's a staple of real digital-forensics toolkits (e.g. FotoForensics).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from app.config import get_settings


@dataclass
class ELAResult:
    mean_error: float
    max_error: float
    suspicious_region_ratio: float  # fraction of pixels above the hot threshold
    suspicious: bool
    heatmap_png: bytes | None = None  # optional visualization for the UI/report


def run_ela(image_bytes: bytes, quality: int | None = None, generate_heatmap: bool = True) -> ELAResult:
    settings = get_settings()
    quality = quality or settings.ELA_JPEG_QUALITY

    original = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    buffer = io.BytesIO()
    original.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    recompressed = Image.open(buffer).convert("RGB")

    orig_arr = np.asarray(original, dtype=np.int16)
    recompressed_arr = np.asarray(recompressed, dtype=np.int16)

    if orig_arr.shape != recompressed_arr.shape:
        # Shouldn't normally happen, but guard against odd color-mode edge cases.
        h = min(orig_arr.shape[0], recompressed_arr.shape[0])
        w = min(orig_arr.shape[1], recompressed_arr.shape[1])
        orig_arr = orig_arr[:h, :w]
        recompressed_arr = recompressed_arr[:h, :w]

    diff = np.abs(orig_arr - recompressed_arr).sum(axis=2).astype(np.float32)  # H x W

    mean_error = float(diff.mean())
    max_error = float(diff.max()) if diff.size else 0.0

    hot_threshold = max(mean_error * 4, 25.0)
    suspicious_region_ratio = float((diff > hot_threshold).mean())

    suspicious = (
        suspicious_region_ratio > 0.015  # more than 1.5% of the image is a hot outlier
        and max_error > settings.ELA_SUSPICION_THRESHOLD * 4
    )

    heatmap_bytes = None
    if generate_heatmap and diff.size:
        heatmap_bytes = _render_heatmap(diff)

    return ELAResult(
        mean_error=round(mean_error, 3),
        max_error=round(max_error, 1),
        suspicious_region_ratio=round(suspicious_region_ratio, 4),
        suspicious=suspicious,
        heatmap_png=heatmap_bytes,
    )


def _render_heatmap(diff: np.ndarray) -> bytes:
    normalized = diff - diff.min()
    max_val = normalized.max()
    if max_val > 0:
        normalized = (normalized / max_val) * 255.0
    heatmap = normalized.astype(np.uint8)
    img = Image.fromarray(heatmap, mode="L").convert("RGB")
    img.thumbnail((800, 800))  # a visual aid for the report, stored with every scan
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return out.getvalue()
