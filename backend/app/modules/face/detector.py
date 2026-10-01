"""
Face detection using OpenCV's bundled Haar cascade (no downloads, works on
Windows without native build tools).

Documents often carry more than one face-like region: passports print a
faint "ghost" copy of the portrait as a security feature, and watermarks or
holograms can also trigger the detector. So we collect every candidate and
pick the portrait by *quality* — a real printed photo has strong contrast, a
full tonal range and sharp edges; a ghost image is washed-out and soft.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_local = threading.local()


def _cascade() -> cv2.CascadeClassifier:
    # CascadeClassifier is not thread-safe and the scan pipeline runs face
    # detection and copy-move analysis in parallel threads: one per thread.
    if not hasattr(_local, "cascade"):
        _local.cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _local.cascade

_YUNET_PATH = Path(__file__).resolve().parents[3] / "models" / "face" / "face_detection_yunet_2023mar.onnx"
_YUNET_MAX_SIDE = 1280
_YUNET_MIN_SCORE = 0.7


def _yunet():
    # Neural face detector (OpenCV YuNet) when its model file is present;
    # far fewer false faces on guilloche patterns and watermarks than Haar.
    from app.modules.provenance import model_trusted

    if not _YUNET_PATH.is_file() or not model_trusted("face_detector_yunet"):
        return None
    if not hasattr(_local, "yunet"):
        _local.yunet = cv2.FaceDetectorYN.create(str(_YUNET_PATH), "", (320, 320), _YUNET_MIN_SCORE)
    return _local.yunet


# Tonal range (5th-95th percentile of grey levels) below which a region is
# treated as a ghost / watermark rather than the holder's photograph.
_MIN_TONAL_RANGE = 70


@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int
    quality: float = 0.0  # 0..1, higher = more like a real photograph
    tonal_range: float = 0.0
    sharpness: float = 0.0


def _gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def _iou(a: FaceBox, b: FaceBox) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / float(a.w * a.h + b.w * b.h - inter or 1)


def _score(gray: np.ndarray, box: FaceBox) -> FaceBox:
    crop = gray[box.y:box.y + box.h, box.x:box.x + box.w]
    if crop.size == 0:
        return box
    p5, p95 = np.percentile(crop, (5, 95))
    box.tonal_range = float(p95 - p5)
    box.sharpness = float(cv2.Laplacian(cv2.resize(crop, (128, 128)), cv2.CV_64F).var())
    box.quality = round(min(1.0, box.tonal_range / 160) * 0.6 + min(1.0, box.sharpness / 400) * 0.4, 3)
    return box


def detect_faces(image: np.ndarray) -> list[FaceBox]:
    """All face candidates from a plain and a contrast-equalised pass,
    de-duplicated and scored. Equalisation helps dark captures but flattens
    a portrait on a mostly-blank page, so both passes are kept."""
    gray = _gray(image)
    found: list[FaceBox] = []
    detector = _yunet() if image.ndim == 3 else None
    if detector is not None:
        h, w = image.shape[:2]
        scale = min(1.0, _YUNET_MAX_SIDE / max(h, w))
        small = cv2.resize(image, (int(w * scale), int(h * scale))) if scale < 1 else image
        detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = detector.detect(small)
        for row in faces if faces is not None else []:
            x, y, bw, bh = (row[:4] / scale).astype(int)
            box = FaceBox(max(0, int(x)), max(0, int(y)), int(bw), int(bh))
            if box.w >= 40 and box.h >= 40:
                found.append(box)
        if found:
            return [_score(gray, f) for f in found]
    for candidate in (gray, cv2.equalizeHist(gray)):
        for (x, y, w, h) in _cascade().detectMultiScale(candidate, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)):
            box = FaceBox(int(x), int(y), int(w), int(h))
            if not any(_iou(box, f) > 0.4 for f in found):
                found.append(box)
    return [_score(gray, f) for f in found]


def pick_portrait(faces: list[FaceBox]) -> FaceBox | None:
    """The holder's photo: among candidates that look like a real photograph,
    the best combination of quality and size. Falls back to the best-quality
    candidate if every region looks washed-out."""
    if not faces:
        return None
    real = [f for f in faces if f.tonal_range >= _MIN_TONAL_RANGE] or faces
    biggest = max(f.w * f.h for f in real)
    return max(real, key=lambda f: f.quality * 0.7 + (f.w * f.h / biggest) * 0.3)


def detect_largest_face(image: np.ndarray) -> tuple[np.ndarray, FaceBox] | None:
    """Returns the chosen portrait crop and its box, or None if no face found."""
    chosen = pick_portrait(detect_faces(image))
    if chosen is None:
        return None
    crop = image[chosen.y:chosen.y + chosen.h, chosen.x:chosen.x + chosen.w]
    return crop, chosen
