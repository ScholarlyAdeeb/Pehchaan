"""
Copy-move forgery detection via ORB keypoint self-matching.

Classic "copy-move" forgery: someone clones a region of the *same* image
(a clean stamp, a hologram patch, a signature) and pastes it elsewhere to
cover an alteration. Because the cloned region is pixel-identical (or
near-identical after light blending) to somewhere else in the image, we
can detect it by matching the image's ORB keypoints against *itself* and
looking for clusters of strong matches between two distant regions.

This runs in milliseconds with OpenCV alone — no external models needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import get_settings

_MIN_KEYPOINT_DISTANCE = 24  # px; matches closer than this are just noise/texture repetition
_DISPLACEMENT_BIN = 6  # px; offsets within one bin count as the same shift
_SAME_LINE_DY = 4  # px
_TEXT_REPEAT_DX = 250  # px (on the <=1000px working image)


@dataclass
class CopyMoveResult:
    match_count: int
    suspicious: bool
    matched_regions: list[tuple[int, int, int, int]] = field(default_factory=list)  # x,y,w,h boxes


def detect_copy_move(image: np.ndarray) -> CopyMoveResult:
    settings = get_settings()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    # Downscale large images before feature detection — copy-move doesn't
    # need pixel-level precision, and 750px is enough for document forgery.
    h, w = gray.shape[:2]
    if max(h, w) > 1000:
        scale = 1000 / max(h, w)
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    orb = cv2.ORB_create(nfeatures=4000)
    keypoints, descriptors = orb.detectAndCompute(gray, None)

    if descriptors is None or len(keypoints) < 10:
        return CopyMoveResult(match_count=0, suspicious=False)

    # Passports legitimately print the holder's portrait twice (main photo +
    # "ghost" image); matches between face regions are not a clone forgery.
    from app.modules.face.detector import detect_faces

    face_boxes = [
        (f.x - f.w * 0.2, f.y - f.h * 0.2, f.x + f.w * 1.2, f.y + f.h * 1.2) for f in detect_faces(gray)
    ]

    def _on_face(pt: tuple[float, float]) -> bool:
        return any(x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2 for x1, y1, x2, y2 in face_boxes)

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(descriptors, descriptors, k=3)

    # A cloned patch moves every one of its keypoints by the SAME offset,
    # whereas repeated glyphs in printed text match at scattered offsets.
    # So group matches by displacement vector and keep the largest group.
    clusters: dict[tuple[int, int], set[tuple[int, int]]] = {}
    seen: set[tuple[int, int]] = set()
    for match_group in matches:
        # k=3 because the top match of a descriptor against itself is always
        # itself (distance 0) — skip it and look at the next-best matches.
        for m in match_group[1:]:
            if m.distance >= 35:
                continue
            a, b = sorted((m.queryIdx, m.trainIdx))
            if (a, b) in seen:
                continue
            seen.add((a, b))
            (x1, y1), (x2, y2) = keypoints[a].pt, keypoints[b].pt
            dx, dy = x2 - x1, y2 - y1
            if float(np.hypot(dx, dy)) <= _MIN_KEYPOINT_DISTANCE:
                continue
            if abs(dy) < _SAME_LINE_DY and abs(dx) < _TEXT_REPEAT_DX:
                continue  # same letter repeated along a text line / MRZ filler
            if face_boxes and _on_face((x1, y1)) and _on_face((x2, y2)):
                continue
            if dx < 0 or (dx == 0 and dy < 0):
                dx, dy = -dx, -dy
            key = (int(round(dx / _DISPLACEMENT_BIN)), int(round(dy / _DISPLACEMENT_BIN)))
            clusters.setdefault(key, set()).add((a, b))

    strong_pairs = list(max(clusters.values(), key=len)) if clusters else []
    match_count = len(strong_pairs)
    suspicious = match_count >= settings.COPY_MOVE_MATCH_THRESHOLD

    regions: list[tuple[int, int, int, int]] = []
    if suspicious:
        pts = np.array([keypoints[i].pt for pair in strong_pairs for i in pair])
        if len(pts):
            x, y = pts[:, 0], pts[:, 1]
            regions.append((int(x.min()), int(y.min()), int(x.max() - x.min()), int(y.max() - y.min())))

    return CopyMoveResult(match_count=match_count, suspicious=suspicious, matched_regions=regions)
