"""Standalone face-verification endpoint — lets the frontend offer a quick
"does this selfie match this ID photo" check independent of a full document
scan (e.g. a kiosk re-check at a gate)."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import FaceSummary
from app.modules.face.detector import detect_largest_face
from app.modules.face.verifier import compare_faces
from app.utils.image_utils import bytes_to_bgr

router = APIRouter(prefix="/api/face", tags=["face"])


@router.post("/verify", response_model=FaceSummary)
async def verify_face(document_photo: UploadFile = File(...), live_photo: UploadFile = File(...)):
    doc_bytes = await document_photo.read()
    live_bytes = await live_photo.read()

    try:
        doc_image = bytes_to_bgr(doc_bytes)
        live_image = bytes_to_bgr(live_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    doc_face = detect_largest_face(doc_image)
    live_face = detect_largest_face(live_image)

    result = compare_faces(doc_face[0] if doc_face else None, live_face[0] if live_face else None)

    return FaceSummary(
        attempted=True,
        similarity=result.similarity,
        is_match=result.is_match,
        backend=result.backend,
        document_face_found=result.document_face_found,
        live_face_found=result.live_face_found,
    )
