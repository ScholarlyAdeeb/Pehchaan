"""Fill the measured image holders with real content.

``photo_regions.REGIONS`` says where each holder is; this module puts something
real in it:

* ``photo`` / ``ghost_photo`` - the harvested portrait for that person, fitted
  to the holder.  The ghost is a smaller, faded copy, as on a real Aadhaar.
* ``qr`` - a genuinely scannable code from ``cv2.QRCodeEncoder``.
* ``barcode`` - left alone; see ``codes`` for why a PDF417 is not faked.

Everything is driven off the page-relative rectangles, so a holder can be filled
at any output resolution.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import codes as codes_mod
import faces as faces_mod
from app.modules.localization.photo_regions import Region, regions_for

#: A ghost portrait is printed smaller and washed out.
GHOST_FADE = 0.55
GHOST_INSET = 0.06      # fraction of the holder to inset the ghost by


def fit_face(face: np.ndarray, width: int, height: int) -> np.ndarray:
    """Scale and centre ``face`` to cover a ``width`` x ``height`` holder.

    Cover rather than contain: a photo holder is a fixed aperture, and letter-
    boxing a portrait inside it looks pasted on.
    """
    if face is None or face.size == 0 or width <= 0 or height <= 0:
        return np.zeros((max(height, 1), max(width, 1), 3), dtype=np.uint8)
    fh, fw = face.shape[:2]
    scale = max(width / fw, height / fh)
    nw, nh = max(1, int(round(fw * scale))), max(1, int(round(fh * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    big = cv2.resize(face, (nw, nh), interpolation=interp)
    x0, y0 = (nw - width) // 2, (nh - height) // 2
    x0, y0 = max(0, x0), max(0, y0)
    return big[y0:y0 + height, x0:x0 + width].copy()


def _faded(face: np.ndarray, fade: float = GHOST_FADE) -> np.ndarray:
    """Wash a portrait out towards white, the way a ghost image is printed."""
    faded = face.astype(np.float32) * fade + 255.0 * (1.0 - fade)
    return np.clip(faded, 0, 255).astype(np.uint8)


def paste(canvas: np.ndarray, patch: np.ndarray, box: tuple[int, int, int, int]) -> None:
    """Blit ``patch`` into ``box`` on ``canvas``, clipping to both."""
    x, y, w, h = box
    ch, cw = canvas.shape[:2]
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    dx1, dy1 = min(cw, x + w), min(ch, y + h)
    if dx1 <= dx0 or dy1 <= dy0:
        return
    pw, ph = patch.shape[1], patch.shape[0]
    sw = min(pw - sx0, dx1 - dx0)
    sh = min(ph - sy0, dy1 - dy0)
    if sw <= 0 or sh <= 0:
        return
    canvas[dy0:dy0 + sh, dx0:dx0 + sw] = patch[sy0:sy0 + sh, sx0:sx0 + sw]


def fill_holders(
    canvas: np.ndarray,
    document_type: str,
    row: dict,
    bank: faces_mod.FaceBank,
    *,
    draw_boxes: bool = False,
) -> dict:
    """Put a real portrait and any real code into ``document_type``'s holders.

    Returns a per-holder report of what was actually placed, which the caller
    records in the sidecar annotation.  With ``draw_boxes`` the measured
    outlines are drawn on top as well, for reviewing the geometry.
    """
    h, w = canvas.shape[:2]
    serial = int(row.get("serial") or 0)
    face = bank.get(serial)
    report: dict[str, dict] = {}

    for region in regions_for(document_type):
        box = region.to_pixels(w, h)
        placed: dict = {"kind": region.kind, "bbox": dict(zip("xywh", box))}

        if region.is_portrait:
            if face is None:
                placed["filled"] = False
            elif region.kind == "ghost_photo":
                inset = int(min(box[2], box[3]) * GHOST_INSET)
                gw, gh = max(1, box[2] - 2 * inset), max(1, box[3] - 2 * inset)
                patch = _faded(fit_face(face, gw, gh))
                paste(canvas, patch, (box[0] + inset, box[1] + inset, gw, gh))
                placed.update(filled=True, source=f"face_{serial:04d}", faded=True)
            else:
                paste(canvas, fit_face(face, box[2], box[3]), box)
                placed.update(filled=True, source=f"face_{serial:04d}", faded=False)

        elif region.is_code:
            payload = codes_mod.payload_for(document_type, row)
            if region.kind == "qr" and payload:
                ok = codes_mod.draw_qr(canvas, box, payload, border=1)
                placed.update(filled=ok)
                if ok:
                    placed["payload"] = payload
            else:
                # no encoder for this symbology; left as a placeholder on purpose
                placed.update(filled=False, note="no encoder available")
        report[region.name] = placed

    if draw_boxes:
        from app.modules.localization.photo_regions import draw_regions

        filled = canvas
        out = draw_regions(filled, document_type, copy=False, scale=max(1.0, h / 700))
        canvas[:] = out
    return report
