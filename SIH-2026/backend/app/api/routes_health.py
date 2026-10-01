"""System status endpoints — the frontend uses these to show which engines
are live and what each model actually is, so a demo never silently degrades
and nobody has to take a model's specs on faith."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
from fastapi import APIRouter

from app.config import BACKEND_ROOT, get_settings
from app.modules.face.verifier import _STRONG_BACKEND, active_backend, backend_bands, backend_label
from app.modules.ocr.engine import tesseract_binary_available

router = APIRouter(prefix="/api", tags=["system"])

_CLASSIFIER_WEIGHTS = BACKEND_ROOT / "training" / "document_classifier.pth"
_CLASSIFIER_METRICS = BACKEND_ROOT / "training" / "document_classifier_metrics.json"
_YUNET = BACKEND_ROOT / "models" / "face" / "face_detection_yunet_2023mar.onnx"
_SFACE = BACKEND_ROOT / "models" / "face" / "face_recognition_sface_2021dec.onnx"


def _file_info(path: Path) -> dict:
    if not path.is_file():
        return {"present": False}
    stat = path.stat()
    return {
        "present": True,
        "size_mb": round(stat.st_size / 1e6, 1),
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _tesseract_info() -> dict:
    if not tesseract_binary_available():
        return {"available": False}
    import pytesseract

    try:
        return {
            "available": True,
            "version": str(pytesseract.get_tesseract_version()),
            "languages": sorted(l for l in pytesseract.get_languages(config="") if l in ("eng", "hin", "nep", "osd")),
        }
    except Exception as e:
        return {"available": True, "error": str(e)}


@router.get("/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "engines": {
            "ocr": "tesseract" if tesseract_binary_available() else "unavailable",
            "face_verification": backend_label(),
        },
    }


@router.get("/system/models")
async def models():
    settings = get_settings()
    metrics = json.loads(_CLASSIFIER_METRICS.read_text()) if _CLASSIFIER_METRICS.is_file() else None
    loc_path = Path(settings.LOCALIZATION_MODEL_PATH) if settings.LOCALIZATION_MODEL_PATH else None
    loc_weights = loc_path or BACKEND_ROOT / "models" / "localization" / "region_detector.pt"
    loc_metrics_path = BACKEND_ROOT / "training" / "region_detector_metrics.json"
    loc_metrics = json.loads(loc_metrics_path.read_text()) if loc_metrics_path.is_file() else None
    ocr_eval_path = BACKEND_ROOT / "training" / "region_ocr_eval.json"
    ocr_eval = json.loads(ocr_eval_path.read_text()) if ocr_eval_path.is_file() else None
    from app.modules.records.issued_documents import DB_PATH as issued_db

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": [
            {
                "key": "document_classifier",
                "name": "Document-type classifier",
                "kind": "Trained neural network",
                "architecture": "MobileNetV2 (ImageNet-pretrained, final layer retrained)",
                "purpose": "Tells Aadhaar, PAN, driving licence and passport images apart for auto-detection.",
                "status": "active" if _CLASSIFIER_WEIGHTS.is_file() else "missing",
                "weights": _file_info(_CLASSIFIER_WEIGHTS),
                "classes": metrics["classes"] if metrics else ["aadhar", "pan", "passport"],
                "training": None if not metrics else {
                    "train_images": metrics["train_images"],
                    "validation_images": metrics["validation_images"],
                    "validation_accuracy": metrics["validation_accuracy"],
                    "validation_accuracy_photo_style": metrics.get("validation_accuracy_photo_style"),
                    "split": metrics.get("split"),
                    "epochs": metrics["epochs"],
                    "optimizer": metrics["optimizer"],
                    "input_size": metrics["input_size"],
                    "per_class": metrics["per_class"],
                    "confusion_matrix": metrics["confusion_matrix"],
                },
                "caveat": "Held-out images are other people's cards from the same generated templates, so "
                          "accuracy on real-world documents and other layouts is not yet measured.",
            },
            {
                "key": "region_detector",
                "name": "Document region detector",
                "kind": "Trained neural network",
                "architecture": "Faster R-CNN, ResNet-50 FPN backbone",
                "purpose": "Locates each field (name, dates, document number, address, photo, MRZ, QR, barcode); "
                           "every text box is then read on its own and merged into the extracted fields.",
                "status": "active" if (settings.LOCALIZATION_ENABLED and loc_path and loc_path.is_file()) else "disabled",
                "weights": _file_info(loc_weights),
                "training": None if not loc_metrics else {
                    "split": loc_metrics["split"],
                    "best_epoch": loc_metrics["best_epoch"],
                    "held_out_photo_style": {k: loc_metrics["photo_style"][k] for k in ("map50", "map75", "mean_iou")},
                    "held_out_clean": {k: loc_metrics["clean"][k] for k in ("map50", "map75", "mean_iou")},
                    "per_class": loc_metrics["photo_style"]["per_class"],
                },
                "field_extraction": None if not ocr_eval else {
                    "held_out_cards": ocr_eval["cards"],
                    "fields_checked": ocr_eval["fields_checked"],
                    "accuracy_full_page_only": ocr_eval["page_only"],
                    "accuracy_with_regions": ocr_eval["with_regions"],
                    "per_document": ocr_eval["per_document"],
                },
                "caveat": "Trained on one generated template per document type. On any other layout its boxes are "
                          "not reliable, so region readings are used only when the detections pass a layout check; "
                          "otherwise the full-page reading is used alone.",
            },
            {
                "key": "issued_documents",
                "name": "Issued-documents database",
                "kind": "Reference database",
                "architecture": "Local SQLite; document numbers stored as keyed hashes",
                "purpose": "Holds the name, date of birth and expiry each document number was issued with; "
                           "a scanned document that disagrees is flagged as an identity conflict.",
                "status": "active" if issued_db.is_file() else "missing",
                "weights": _file_info(issued_db),
                "caveat": "Built from the generated identity dataset (300 people, 1200 documents). A number that is "
                          "not in it is reported as 'not found' and does not affect the risk score.",
            },
            {
                "key": "ocr",
                "name": "Text recognition (OCR)",
                "kind": "OCR engine",
                "architecture": "Tesseract LSTM",
                "purpose": "Reads printed text and the passport MRZ; fields are then parsed by format-aware extractors.",
                "status": "active" if tesseract_binary_available() else "missing",
                "details": _tesseract_info(),
            },
            {
                "key": "face_detector",
                "name": "Face detector",
                "kind": "Trained neural network" if _YUNET.is_file() else "Classical computer vision",
                "architecture": "OpenCV YuNet face detector (Haar cascade as fallback)" if _YUNET.is_file()
                else "OpenCV Haar cascade (frontal face)",
                "purpose": "Finds every face on the document and picks the holder's portrait by photo quality "
                           "(contrast, tonal range, sharpness) so ghost images and watermarks are skipped.",
                "status": "active",
                "weights": _file_info(_YUNET),
                "details": {"opencv_version": cv2.__version__},
            },
            {
                "key": "face_matcher",
                "name": "Face matcher",
                "kind": "Trained neural network" if _STRONG_BACKEND else "Classical computer vision",
                "architecture": backend_label(),
                "purpose": "Compares the document portrait with the live photo: match / inconclusive / different person.",
                "status": "active",
                "weights": _file_info(_SFACE) if _SFACE.is_file() else None,
                "details": {
                    "backend": active_backend(),
                    "match_at_or_above": backend_bands()[0],
                    "different_person_below": backend_bands()[1],
                },
                "caveat": None if _STRONG_BACKEND else (
                    "Not a face-recognition model; bands measured on dataset portraits only. Put OpenCV's "
                    "face_recognition_sface_2021dec.onnx in backend/models/face/ to switch to a real recognition network."
                ),
            },
            {
                "key": "tampering",
                "name": "Tampering forensics",
                "kind": "Classical image forensics",
                "architecture": "Error Level Analysis + copy-move (ORB displacement clustering) + metadata",
                "purpose": "Looks for pasted, cloned or re-edited regions.",
                "status": "active",
                "details": {
                    "ela_jpeg_quality": settings.ELA_JPEG_QUALITY,
                    "copy_move_alarm_pairs": settings.COPY_MOVE_MATCH_THRESHOLD,
                    "weights": {"ela": 0.7, "copy_move": 0.15, "metadata": 0.15},
                },
            },
        ],
        "risk_engine": {
            "weights": {
                "validation": settings.WEIGHT_VALIDATION,
                "tampering": settings.WEIGHT_TAMPERING,
                "face": settings.WEIGHT_FACE,
                "records": settings.WEIGHT_RECORDS,
            },
            "clear_max": settings.RISK_CLEAR_MAX,
            "review_max": settings.RISK_REVIEW_MAX,
        },
        "records_database": "configured" if settings.DATABASE_URL else "in-process only",
    }
