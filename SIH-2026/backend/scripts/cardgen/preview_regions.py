"""Render each card background with its measured holders drawn on it.

This is the accuracy gate for ``photo_regions.REGIONS``.  Run it after any
change to the table and look at the output:

    python scripts/dataset/preview_regions.py [outdir]

The drawings land in ``scripts/dataset/preview/`` by default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.localization.photo_regions import draw_regions  # noqa: E402

SAMPLE_DATA = BACKEND_ROOT.parent / "sample-data"
TEMPLATES = SAMPLE_DATA / "templates"
OUT_DIR = Path(__file__).resolve().parent / "preview"

# background source and the crop the source PDF actually places, established by
# byte comparison in extract_layouts (r = 0.999 .. 1.000)
BACKGROUNDS: dict[str, tuple[str, tuple[int, int] | None]] = {
    "aadhaar": ("WhatsApp Image 2026-09-26 at 6.43.56 AM (1).jpeg", None),
    "pan": ("WhatsApp Image 2026-09-26 at 6.43.56 AM.jpeg", (40, 557)),
    "driving_license": ("DL.jpeg", (605, 1183)),
    "passport": ("PASSPORT.jpeg", None),
}


def main(outdir: Path | None = None) -> int:
    out = outdir or OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    for doc, (filename, crop) in BACKGROUNDS.items():
        img = cv2.imread(str(TEMPLATES / filename), cv2.IMREAD_COLOR)
        if img is None:
            print(f"  {doc}: cannot read {filename}")
            continue
        if crop:
            y0, y1 = crop
            img = img[y0:y1 + 1]
        drawn = draw_regions(img, doc, copy=True, scale=max(1.0, img.shape[0] / 700))
        path = out / f"{doc}_regions.png"
        cv2.imwrite(str(path), drawn)
        print(f"  {doc:16s} {img.shape[1]}x{img.shape[0]} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
