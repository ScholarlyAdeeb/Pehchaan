"""
Exercises the face-comparison logic directly with synthetic crops (rather
than relying on the Haar cascade to find a real face in a generated test
image, which is unreliable). `compare_faces` operates on already-cropped
face regions, so this validates the actual similarity math independent of
detection.
"""
import numpy as np

from app.modules.face.verifier import compare_faces


def _solid_face(color: tuple[int, int, int], size: int = 160) -> np.ndarray:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :] = color
    # add a few structural features so ORB has something to key on
    img[40:60, 40:120] = (color[0] // 2, color[1] // 2, color[2] // 2)
    img[100:120, 30:130] = (255 - color[0], 255 - color[1], 255 - color[2])
    return img


def test_identical_faces_score_high_similarity_and_match():
    face = _solid_face((180, 150, 120))
    result = compare_faces(face, face.copy())
    assert result.document_face_found is True
    assert result.live_face_found is True
    assert result.similarity > 0.75  # identical images should score strongly, even via the lightweight fallback
    assert result.is_match is True


def test_missing_document_face_is_reported_and_not_a_match():
    face = _solid_face((180, 150, 120))
    result = compare_faces(None, face)
    assert result.document_face_found is False
    assert result.is_match is False


def test_missing_live_face_is_reported_and_not_a_match():
    face = _solid_face((180, 150, 120))
    result = compare_faces(face, None)
    assert result.live_face_found is False
    assert result.is_match is False
