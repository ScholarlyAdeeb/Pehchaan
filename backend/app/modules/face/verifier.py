"""
Module 4 — Face Verification.

Compares the face on the document with a live photo of the person presenting
it. Backends, strongest first, chosen at import time:

1. **OpenCV SFace** — a trained face-recognition network (128-D embedding,
   cosine similarity). Built into opencv-python; needs the model file
   `backend/models/face/face_recognition_sface_2021dec.onnx`
   (optional `face_detection_yunet_2023mar.onnx` for landmark alignment).
2. **face_recognition (dlib)** — if the package is installed.
3. **Histogram + ORB fallback** — no model, always available, weak.

Each backend has its own calibrated bands, because their scores live on
different scales:
    similarity >= match      -> "match"
    similarity <  mismatch   -> "mismatch"   (confidently a different person)
    in between               -> "uncertain"  (needs an officer's eyes)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.config import BACKEND_ROOT

try:
    import face_recognition  # type: ignore

    _DLIB = True
except ImportError:
    _DLIB = False

_MODEL_DIR = BACKEND_ROOT / "models" / "face"
_SFACE_PATH = _MODEL_DIR / "face_recognition_sface_2021dec.onnx"
_YUNET_PATH = _MODEL_DIR / "face_detection_yunet_2023mar.onnx"

_ALIGN_SIZE = (200, 200)

# (match_at_or_above, mismatch_below), measured on the passport dataset.
# SFace: 1,770 different-person pairs had median 0.20, 95th pct 0.36, 99th
# 0.44; same-person pairs ~0.90. OpenCV's generic 0.363 line let ~5% of
# different people through, so "same person" starts at 0.45 (~0.6%).
# Fallback: same person 0.40, different people 0.02-0.16.
_BANDS = {
    "sface": (0.45, 0.30),
    "dlib": (0.50, 0.35),
    "fallback": (0.30, 0.18),
}
_LABELS = {
    "sface": "OpenCV SFace face-recognition network (cosine similarity)",
    "dlib": "face_recognition / dlib 128-D embeddings",
    "fallback": "histogram + ORB keypoints (lightweight fallback, not a recognition model)",
}


@dataclass
class FaceMatchResult:
    similarity: float  # higher = more likely the same person (scale depends on backend)
    is_match: bool
    backend: str
    document_face_found: bool
    live_face_found: bool
    decision: str = "not_run"  # match | uncertain | mismatch | not_run
    match_threshold: float | None = None
    mismatch_threshold: float | None = None
    backend_key: str = "none"


class _SFace:
    def __init__(self) -> None:
        self.recognizer = cv2.FaceRecognizerSF.create(str(_SFACE_PATH), "")
        self.detector = None
        if _YUNET_PATH.is_file() and model_trusted("face_detector_yunet"):
            self.detector = cv2.FaceDetectorYN.create(str(_YUNET_PATH), "", (320, 320), 0.6)

    def _embed(self, face: np.ndarray) -> np.ndarray:
        pad = cv2.copyMakeBorder(face, *(int(face.shape[0] * 0.25),) * 2, *(int(face.shape[1] * 0.25),) * 2,
                                 cv2.BORDER_REPLICATE)
        if self.detector is not None:
            h, w = pad.shape[:2]
            self.detector.setInputSize((w, h))
            _, found = self.detector.detect(pad)
            if found is not None and len(found):
                aligned = self.recognizer.alignCrop(pad, found[0])
                return self.recognizer.feature(aligned)
        return self.recognizer.feature(cv2.resize(face, (112, 112)))

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        score = self.recognizer.match(self._embed(a), self._embed(b), cv2.FaceRecognizerSF_FR_COSINE)
        return round(max(0.0, float(score)), 4)


_sface: _SFace | None = None
from app.modules.provenance import model_trusted  # noqa: E402

if _SFACE_PATH.is_file() and model_trusted("face_recognizer_sface"):
    try:
        _sface = _SFace()
    except cv2.error:
        _sface = None

_STRONG_BACKEND = _sface is not None or _DLIB


def active_backend() -> str:
    return "sface" if _sface is not None else "dlib" if _DLIB else "fallback"


def backend_bands(key: str | None = None) -> tuple[float, float]:
    return _BANDS[key or active_backend()]


def backend_label(key: str | None = None) -> str:
    return _LABELS[key or active_backend()]


def _prep(face_img: np.ndarray) -> np.ndarray:
    resized = cv2.resize(face_img, _ALIGN_SIZE)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if resized.ndim == 3 else resized
    return cv2.equalizeHist(gray)


def _fallback_similarity(face_a: np.ndarray, face_b: np.ndarray) -> float:
    gray_a, gray_b = _prep(face_a), _prep(face_b)

    hist_a = cv2.calcHist([gray_a], [0], None, [256], [0, 256])
    hist_b = cv2.calcHist([gray_b], [0], None, [256], [0, 256])
    cv2.normalize(hist_a, hist_a)
    cv2.normalize(hist_b, hist_b)
    hist_score = max(0.0, cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))

    orb = cv2.ORB_create(nfeatures=500)
    kp_a, des_a = orb.detectAndCompute(gray_a, None)
    kp_b, des_b = orb.detectAndCompute(gray_b, None)

    orb_score = 0.0
    if des_a is not None and des_b is not None and len(kp_a) > 5 and len(kp_b) > 5:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des_a, des_b)
        good = [m for m in matches if m.distance < 50]
        orb_score = min(1.0, len(good) / max(1, min(len(kp_a), len(kp_b))))

    return round(0.5 * hist_score + 0.5 * orb_score, 4)


def _dlib_similarity(face_a: np.ndarray, face_b: np.ndarray) -> float | None:
    enc_a = face_recognition.face_encodings(cv2.cvtColor(face_a, cv2.COLOR_BGR2RGB))
    enc_b = face_recognition.face_encodings(cv2.cvtColor(face_b, cv2.COLOR_BGR2RGB))
    if not enc_a or not enc_b:
        return None
    distance = float(np.linalg.norm(enc_a[0] - enc_b[0]))
    return round(max(0.0, 1.0 - distance / 1.2), 4)


def _result(similarity: float, key: str) -> FaceMatchResult:
    match_t, mismatch_t = _BANDS[key]
    decision = "match" if similarity >= match_t else "mismatch" if similarity < mismatch_t else "uncertain"
    return FaceMatchResult(
        similarity=similarity,
        is_match=decision == "match",
        backend=_LABELS[key],
        document_face_found=True,
        live_face_found=True,
        decision=decision,
        match_threshold=match_t,
        mismatch_threshold=mismatch_t,
        backend_key=key,
    )


def compare_faces(document_face: np.ndarray | None, live_face: np.ndarray | None) -> FaceMatchResult:
    if document_face is None or live_face is None:
        return FaceMatchResult(
            similarity=0.0,
            is_match=False,
            backend="none",
            document_face_found=document_face is not None,
            live_face_found=live_face is not None,
            decision="not_run",
        )

    if _sface is not None:
        try:
            return _result(_sface.similarity(document_face, live_face), "sface")
        except cv2.error:
            pass
    if _DLIB:
        sim = _dlib_similarity(document_face, live_face)
        if sim is not None:
            return _result(sim, "dlib")
    return _result(_fallback_similarity(document_face, live_face), "fallback")
