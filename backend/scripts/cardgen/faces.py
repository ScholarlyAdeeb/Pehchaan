"""Harvest real portrait photos for the dataset, one per person.

The spreadsheet has no photo column, so the generator needs a face for each of
the 300 people from somewhere. The repository already contains it: the 902
images under ``backend/training/data`` are specimen documents
("SYNTHETIC / SPECIMEN - NOT A REAL DOCUMENT") that carry a real portrait.

``backend/training/data/aadhar/AADHARDATASET_Page_NNN.jpg`` is 1:1 with
spreadsheet serial NNN, so harvesting that folder gives exactly one face per
person, and reusing it across all four cards keeps a person's face consistent
between their Aadhaar, PAN, licence and passport - which is what a face
verification dataset needs.

Faces are located with the project's own YuNet detector rather than a new
dependency, and are cached to ``sample-data/templates/_face_cache`` (a
directory that already existed for this purpose) so the ~50 ms per page is paid
once rather than on every generation run.

Usage
-----
    python scripts/cardgen/faces.py            # harvest, then report
    python scripts/cardgen/faces.py --rebuild  # discard the cache first
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.face.detector import detect_faces, pick_portrait  # noqa: E402

TRAINING_DATA = BACKEND_ROOT / "training" / "data"
CACHE = BACKEND_ROOT.parent / "sample-data" / "templates" / "_face_cache"
MANIFEST = CACHE / "faces.json"

#: Source folder whose page numbering matches the spreadsheet serials 1..300.
SOURCE_DIR = TRAINING_DATA / "aadhar"
SOURCE_GLOB = "AADHARDATASET_Page_*.jpg"

#: An ID photo is head-and-shoulders, not a tight face crop, so the detected
#: face box is grown: more above the head than below the chin.
PAD_LEFT = 0.28      # fraction of face width to add on each side
PAD_TOP = 0.34       # above the face box (hair, forehead)
PAD_BOTTOM = 0.52    # below the face box (chin, shoulders)
MIN_FACE_PX = 60

#: The specimen photos are mounted in a frame, so growing the face box can
#: overshoot the photo and pick up the document's white margin and border rule.
#: An edge strip this uniform is card stock, not the portrait.
TRIM_MAX_FRACTION = 0.18   # never trim more than this much of a dimension
TRIM_MAX_STD = 4.0          # row/column std below which it counts as flat


class FaceBank:
    """Portrait crops for every person, loaded from the cache."""

    def __init__(self, cache: Path = CACHE) -> None:
        self.cache = cache
        self._faces: dict[int, np.ndarray] = {}

    def serial_for(self, serial: int) -> int | None:
        """Serial whose face is cached, or ``None`` if the harvest missed it."""
        return serial if (self.cache / f"face_{serial:04d}.jpg").exists() else None

    def get(self, serial: int) -> np.ndarray | None:
        """BGR portrait for ``serial``, or ``None`` when unavailable."""
        if serial in self._faces:
            return self._faces[serial]
        path = self.cache / f"face_{serial:04d}.jpg"
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is not None:
            self._faces[serial] = img
        return img

    def available(self) -> int:
        return len(list(self.cache.glob("face_*.jpg")))


#: The specimen photos are mounted in a ruled frame, so growing the face box
#: can overshoot the photo and pick up the document's margin and border rule.
#: Scanning outward for that border gives the photo's true edges.
#: The specimen pages mount every portrait at the same place, so the photo is
#: found as a colour block on near-white card stock rather than by growing a
#: box until it hits a rule - that kept landing on the document's text lines
#: instead. Measured across 33 pages the rect is identical to the pixel, so the
#: segmentation is also a cheap check that the template has not changed.
SAT_MIN = 45             # HSV saturation above which a pixel is not white stock
VAL_MAX = 195            # or clearly darker than white stock
MIN_PHOTO_AREA = 5000


def photo_rect(image: np.ndarray, face_box) -> tuple[int, int, int, int] | None:
    """Bounding box ``(x, y, w, h)`` of the mounted photo containing a face.

    A colour photograph on white card stock is either saturated or clearly
    dark, so thresholding on that and keeping the component that contains the
    face centre isolates the photo; the page's printed text is sparse and never
    joins it.  Returns ``None`` if no plausible block is found.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > SAT_MIN) | (hsv[:, :, 2] < VAL_MAX)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    fx, fy, fw, fh = face_box
    cx, cy = fx + fw // 2, fy + fh // 2
    best, best_area = None, 0
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < MIN_PHOTO_AREA:
            continue
        if x <= cx < x + w and y <= cy < y + h and w * h > best_area:
            best, best_area = (int(x), int(y), int(w), int(h)), w * h
    return best


def _portrait_crop(image: np.ndarray, box) -> np.ndarray:
    """Crop the mounted portrait the face sits in.

    Prefers the segmented photo rectangle.  If that fails, falls back to a
    head-and-shoulders expansion of the face box, which at least keeps the face.
    """
    x, y, w, h = box
    ih, iw = image.shape[:2]

    rect = photo_rect(image, box)
    if rect is not None:
        rx, ry, rw, rh = rect
        if 0.4 <= rw / rh <= 1.2:
            return image[ry:ry + rh, rx:rx + rw].copy()

    ch = int(round(h * (1.0 + PAD_TOP + PAD_BOTTOM)))
    cw = int(round(w * (1.0 + 2 * PAD_LEFT)))
    left = x + w / 2.0 - cw / 2.0
    top = y - h * PAD_TOP
    x0, y0 = max(0, int(round(left))), max(0, int(round(top)))
    x1, y1 = min(iw, int(round(left + cw))), min(ih, int(round(top + ch)))
    if x1 <= x0 or y1 <= y0:
        return image[y:y + h, x:x + w].copy()
    crop = image[y0:y1, x0:x1].copy()
    if crop.shape[1] > crop.shape[0] * 1.2:
        centre = crop.shape[1] // 2
        half = int(crop.shape[0] * 0.42)
        crop = crop[:, max(0, centre - half):min(crop.shape[1], centre + half)]
    return crop


def harvest(rebuild: bool = False, limit: int = 0) -> dict:
    """Detect and cache one portrait per person. Returns the manifest."""
    if rebuild and CACHE.is_dir():
        for f in CACHE.glob("face_*.jpg"):
            f.unlink()
    CACHE.mkdir(parents=True, exist_ok=True)

    pages = sorted(SOURCE_DIR.glob(SOURCE_GLOB))
    if limit:
        pages = pages[:limit]
    if not pages:
        raise FileNotFoundError(f"no source pages in {SOURCE_DIR}")

    manifest: dict[str, dict] = {}
    misses: list[int] = []
    digests: dict[str, int] = {}

    for page in pages:
        serial = int(page.stem.rsplit("_", 1)[1])
        out = CACHE / f"face_{serial:04d}.jpg"
        if out.exists():
            if str(serial) not in manifest:
                manifest[str(serial)] = {"source": page.name, "cached": True}
            continue
        image = cv2.imread(str(page), cv2.IMREAD_COLOR)
        if image is None:
            misses.append(serial)
            continue
        faces = detect_faces(image)
        box = pick_portrait(faces) if faces else None
        if box is None or box.w < MIN_FACE_PX:
            misses.append(serial)
            continue
        crop = _portrait_crop(image, (box.x, box.y, box.w, box.h))
        cv2.imwrite(str(out), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
        digest = hashlib.md5(crop.tobytes()).hexdigest()[:12]
        digests.setdefault(digest, serial)
        manifest[str(serial)] = {
            "source": page.name,
            "face_box": [int(box.x), int(box.y), int(box.w), int(box.h)],
            "crop_size": [int(crop.shape[1]), int(crop.shape[0])],
            "digest": digest,
        }

    # a digest shared by two serials would mean the same photo on two people
    by_digest: dict[str, list[int]] = {}
    for serial, info in manifest.items():
        if isinstance(info, dict) and "digest" in info:
            by_digest.setdefault(info["digest"], []).append(int(serial))
    repeated = {d: s for d, s in by_digest.items() if len(s) > 1}

    payload = {
        "source_dir": str(SOURCE_DIR),
        "count": len(manifest),
        "distinct_faces": len(by_digest) or len(manifest),
        "repeated_images": repeated,
        "missed": misses,
        "faces": manifest,
    }
    MANIFEST.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="discard the cache first")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    result = harvest(rebuild=args.rebuild, limit=args.limit)
    print(f"harvested {result['count']} portraits into {CACHE}")
    print(f"  distinct faces: {result['distinct_faces']}")
    if result["missed"]:
        print(f"  no face found for serials: {result['missed'][:20]}"
              f"{' ...' if len(result['missed']) > 20 else ''}")
    if result["repeated_images"]:
        print(f"  same photo reused across serials: {result['repeated_images']}")
    print(f"  manifest: {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
