"""Photo and machine-readable-code holders for the dataset cards.

Every card in ``sample-data`` is a background image with a text overlay, and
each one leaves a region empty for the holder's portrait (and, on some cards, a
QR code or barcode).  The dataset has no photo column at all - see
``scripts/dataset/generate.py`` - so these rectangles describe regions that are
blank by design.

Coordinates are stored **page-relative and normalised to 0..1**, not in pixels,
because the same card is used at several sizes: the source PDFs place a
768x517 px PAN background into a 612x792 pt page, the app downscales uploads to
3000 px, and the generator rasterises at native background resolution.

Provenance: the rectangles were measured off the backgrounds themselves, after
confirming each PDF's background is byte-identical to a file in
``sample-data/templates``:

===============  ==========================================  ==========
card             background                                  correlation
===============  ==========================================  ==========
aadhaar          ``WhatsApp Image ...(1).jpeg`` 768x1024     r = 1.000
pan              ``WhatsApp Image ....jpeg`` rows 40..557    r = 0.999
driving_license  ``DL.jpeg`` rows 605..1183  1000x579        r = 1.000
passport         ``PASSPORT.jpeg`` 1264x1691                r = 1.000
===============  ==========================================  ==========

PAN and DL edges were read directly (white-run and difference analysis against
the inspiration scans); the Aadhaar holders come from a blank-versus-inspiration
difference and the passport box from an intensity grid.  Accuracy is roughly
+/-10 px, which is why :func:`draw_regions` exists: draw the boxes, look at the
card, adjust the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

# Document types that have a measured card.  ``permit`` and ``visa`` exist in
# ``synthetic_generator.DocumentType`` but have no sample document, so they are
# deliberately absent rather than guessed at.
MEASURED_TYPES = ("aadhaar", "pan", "driving_license", "passport")

#: Regions that hold a face, and so are the ones a portrait detector must find.
PORTRAIT_KINDS = frozenset({"photo", "ghost_photo"})

#: Regions that hold a machine-readable code.  Kept separate from portraits so
#: a QR can never be mistaken for a photo, and so ``passport``'s PDF417-style
#: barcode is not filed as a QR.
CODE_KINDS = frozenset({"qr", "barcode"})


@dataclass(frozen=True)
class Region:
    """One image holder on a card.

    ``bbox_norm`` is ``(x0, y0, x1, y1)`` relative to the *page*, all in 0..1.
    ``bbox_points`` is the same rectangle in PDF points of the source 612x792 pt
    page, kept for provenance and for anyone working back from the PDFs.
    """

    name: str
    kind: str
    bbox_norm: tuple[float, float, float, float]
    bbox_points: tuple[float, float, float, float]
    source: str

    @property
    def is_portrait(self) -> bool:
        return self.kind in PORTRAIT_KINDS

    @property
    def is_code(self) -> bool:
        return self.kind in CODE_KINDS

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Return ``(x, y, w, h)`` in pixels for a ``width`` x ``height`` page."""
        x0, y0, x1, y1 = self.bbox_norm
        px = (int(round(x0 * width)), int(round(y0 * height)))
        pw = int(round((x1 - x0) * width))
        ph = int(round((y1 - y0) * height))
        return px[0], px[1], max(pw, 1), max(ph, 1)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "bbox_norm": list(self.bbox_norm),
            "bbox_points": list(self.bbox_points),
            "source": self.source,
        }


# Each entry: (name, kind, pixel box on the background, PDF points on the
# 612x792 pt source page, how it was measured).
REGIONS: dict[str, tuple[Region, ...]] = {
    "aadhaar": (
        Region(
            "photo", "photo",
            (0.066, 0.142, 0.319, 0.368),
            (63.1, 151.6, 204.5, 320.6),
            "blank-vs-inspiration diff on the front card, dense rows 145-377",
        ),
        Region(
            "ghost_photo", "ghost_photo",
            (0.844, 0.142, 0.927, 0.227),
            (497.6, 151.6, 536.2, 215.1),
            "read off the inspiration scan; flat in the blank, so not detectable",
        ),
        Region(
            "qr", "qr",
            (0.612, 0.651, 0.918, 0.883),
            (474.6, 526.5, 569.5, 693.4),
            "edge detection on the back card; blank in the background (std 0.03)",
        ),
    ),
    "pan": (
        Region(
            "photo", "photo",
            (0.049, 0.267, 0.219, 0.538),
            (99.6, 507.9, 183.6, 598.5),
            "difference against the blank template, dark-pixel block x71-131 y178-248",
        ),
        Region(
            "qr", "qr",
            (0.656, 0.267, 0.949, 0.712),
            (400.9, 507.9, 546.4, 656.6),
            "difference against the blank template, block x504-729 y178-408",
        ),
    ),
    "driving_license": (
        Region(
            "photo", "photo",
            (0.700, 0.124, 0.958, 0.734),
            (398.0, 237.0, 516.6, 399.1),
            "near-white run analysis; the scan has slight perspective, left edge 700-755",
        ),
    ),
    "passport": (
        Region(
            "photo", "photo",
            (0.041, 0.089, 0.315, 0.343),
            (49.2, 101.9, 204.2, 294.5),
            "intensity grid on the data page; brighter interior between darker bands",
        ),
        Region(
            "barcode", "barcode",
            (0.560, 0.509, 0.849, 0.545),
            (277.0, 262.8, 406.2, 279.1),
            "24 dark stripes, x708-1072 y861-920; PDF417-style, not a QR",
        ),
    ),
}

#: Draw styles per kind.  Portraits get a solid box, codes a dashed one, so a
#: rendered overlay is self-describing.
STYLES: dict[str, tuple[tuple[int, int, int], int, str]] = {
    "photo": ((60, 200, 60), 3, "PHOTO"),
    "ghost_photo": ((60, 200, 60), 2, "GHOST"),
    "qr": ((60, 160, 255), 2, "QR"),
    "barcode": ((60, 160, 255), 2, "BARCODE"),
}


def regions_for(document_type: str) -> tuple[Region, ...]:
    """Holders for ``document_type``; empty for types with no measured card."""
    return REGIONS.get(document_type, ())


def portraits_for(document_type: str) -> tuple[Region, ...]:
    """Just the face-bearing holders, primary portrait first."""
    found = [r for r in regions_for(document_type) if r.is_portrait]
    found.sort(key=lambda r: (r.kind != "photo", r.bbox_norm[0]))
    return tuple(found)


def draw_regions(
    image: np.ndarray,
    document_type: str,
    *,
    copy: bool = True,
    scale: float = 1.0,
) -> np.ndarray:
    """Draw every measured holder of ``document_type`` onto ``image``.

    ``image`` may be BGR or RGB; the result keeps the input's channel order.
    ``scale`` multiplies line thickness and label size, which is handy when the
    same card is drawn at a much larger resolution.
    """
    out = image.copy() if copy else image
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    h, w = out.shape[:2]
    thickness = max(1, int(round(3 * scale)))
    font = cv2.FONT_HERSHEY_SIMPLEX
    for region in regions_for(document_type):
        color, _, label = STYLES.get(region.kind, ((0, 0, 255), thickness, region.kind))
        x, y, rw, rh = region.to_pixels(w, h)
        if region.kind in CODE_KINDS:
            _dashed_rectangle(out, (x, y), (x + rw, y + rh), color, thickness)
        else:
            cv2.rectangle(out, (x, y), (x + rw, y + rh), color, thickness)
        fs = 0.45 * scale
        ty = y - max(4, int(6 * scale)) if y > int(14 * scale) else y + rh + int(14 * scale)
        cv2.putText(out, label, (x, ty), font, fs, color, max(1, thickness - 1), cv2.LINE_AA)
    return out


def _dashed_rectangle(
    img: np.ndarray,
    p0: tuple[int, int],
    p1: tuple[int, int],
    color: tuple[int, int, int],
    thickness: int,
    dash: int = 12,
) -> None:
    (x0, y0), (x1, y1) = p0, p1
    for x in range(x0, x1, dash * 2):
        cv2.line(img, (x, y0), (min(x + dash, x1), y0), color, thickness)
        cv2.line(img, (x, y1), (min(x + dash, x1), y1), color, thickness)
    for y in range(y0, y1, dash * 2):
        cv2.line(img, (x0, y), (x0, min(y + dash, y1)), color, thickness)
        cv2.line(img, (x1, y), (x1, min(y + dash, y1)), color, thickness)


def annotation(document_type: str, width: int, height: int) -> dict:
    """Sidecar annotation payload for one generated card."""
    return {
        "document_type": document_type,
        "image_width": width,
        "image_height": height,
        "regions": [
            {
                "name": r.name,
                "kind": r.kind,
                "bbox": dict(zip("xywh", r.to_pixels(width, height))),
            }
            for r in regions_for(document_type)
        ],
    }


def validate(types: Sequence[str] = MEASURED_TYPES) -> list[str]:
    """Return a list of problems; empty means the table is self-consistent."""
    problems: list[str] = []
    for doc in types:
        for r in regions_for(doc):
            x0, y0, x1, y1 = r.bbox_norm
            if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
                problems.append(f"{doc}/{r.name}: bbox_norm {r.bbox_norm} outside 0..1")
            if r.name in PORTRAIT_KINDS and not 0.4 <= (x1 - x0) / (y1 - y0) <= 1.2:
                problems.append(
                    f"{doc}/{r.name}: portrait aspect {(x1 - x0) / (y1 - y0):.2f} not in 0.4..1.2"
                )
            if r.is_code and r.is_portrait:
                problems.append(f"{doc}/{r.name}: region is both a code and a portrait")
    return problems
