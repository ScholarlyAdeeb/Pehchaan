"""
The main pipeline endpoint: upload a document (+ optional live selfie) and
get back a full OCR -> validation -> tampering -> face -> risk report.

This route is deliberately a thin orchestrator — it calls each module in
turn and assembles the response. All the actual logic lives in
`app/modules/*`, which keeps this file readable as a map of the pipeline.

Performance: OCR, tampering detection, and face detection are independent
signals. They run in parallel via a thread pool, cutting wall-clock time
by ~60% compared to sequential execution.
"""
from __future__ import annotations

import asyncio
import base64
import io

import cv2
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.models.schemas import (
    BoxModel,
    ClassificationSummary,
    FaceSummary,
    IdentitySummary,
    RecordCheckSummary,
    MRZSummary,
    OCRSummary,
    RiskSummary,
    ScanListItem,
    ScanResponse,
    StatsResponse,
    TamperingSummary,
    ValidationSummary,
)
from app.modules.face.detector import detect_faces, detect_largest_face, pick_portrait
from app.modules.face.verifier import backend_bands, backend_label, compare_faces
from app.modules.classification import auto_detect
from app.modules.classification.classifier import classifier
from app.modules.ocr.engine import run_ocr
from app.modules.ocr.field_extractors import extract_fields
from app.modules.ocr.region_fields import assess_layout, merge_region_fields
from app.modules.ocr.mrz_parser import parse_mrz
from app.modules.provenance import provenance
from app.modules.records.crosscheck import apply_reference_check, check_against_records
from app.modules.records.issued_documents import check_issued_document
from app.modules.records.forgery_registry import find_matches, fingerprint
from app.modules.records.pii import hash_document_number, mask_document_number
from app.modules.risk.evaluation import build_evaluation
from app.modules.risk.risk_engine import compute_risk
from app.modules.tampering.tampering_engine import analyze_tampering
from app.modules.validation.rules_engine import ValidationIssue, _finalize, validate_generic, validate_passport
from app.modules.security.timestamping import create_scan_receipt
from app.modules.security.signed_batches import create_signed_batch
from app.storage import file_store
from app.utils.image_utils import bytes_to_bgr

_pool = ThreadPoolExecutor(max_workers=4)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

_MAX_BYTES_DEFAULT = 12 * 1024 * 1024


async def _read_upload(upload: UploadFile) -> bytes:
    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await upload.read()
    if len(data) > max_bytes:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB}MB limit.")
    if not data:
        raise HTTPException(400, "Empty file upload.")
    _check_image(data, settings.MAX_IMAGE_PIXELS)
    return data


_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}


def _check_image(data: bytes, max_pixels: int) -> None:
    """Accept only real raster images of sane size — the declared content type
    and file name are client-controlled, the bytes are not."""
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            if img.width * img.height > max_pixels:
                raise HTTPException(413, "Image resolution is too large.")
            img.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise HTTPException(400, "The file is not a readable image.")
    if fmt not in _ALLOWED_FORMATS:
        raise HTTPException(400, f"Unsupported image format '{fmt}'. Use JPG, PNG, WebP, BMP or TIFF.")


_EQUIVALENT_TYPES = [{"national_id", "aadhar"}]


def _same_family(a: str, b: str) -> bool:
    return a == b or any(a in g and b in g for g in _EQUIVALENT_TYPES)


def _tesseract_family(document_type: str) -> str:
    if document_type in ("passport", "visa"):
        return "passport"
    if document_type == "pan":
        return "pan"
    return "card"


def _build_identity(document_type: str, fields: dict, mrz) -> IdentitySummary:
    if document_type in ("passport", "visa") and mrz is not None and mrz.detected:
        mrz_number = next((f.value.replace("<", "") for f in mrz.fields if f.name == "passport_number"), None)
        mrz_name = " ".join(filter(None, [mrz.given_names, mrz.surname])) or None
        return _with_pii(IdentitySummary(
            name=mrz_name or fields.get("name"),
            document_number=mrz_number or fields.get("passport_number_visual") or fields.get("visa_number"),
            date_of_birth=mrz.date_of_birth or fields.get("date_of_birth"),
            expiry_date=mrz.date_of_expiry or fields.get("expiry_date"),
            nationality=mrz.nationality or fields.get("nationality"),
            gender=mrz.sex or fields.get("gender"),
        ))
    number_key = {
        "passport": "passport_number_visual",
        "visa": "visa_number",
        "driving_license": "license_number",
        "permit": "permit_number",
    }.get(document_type, "id_number")
    return _with_pii(IdentitySummary(
        name=fields.get("name") or fields.get("issued_to"),
        document_number=fields.get(number_key),
        date_of_birth=fields.get("date_of_birth"),
        expiry_date=fields.get("expiry_date") or fields.get("valid_till"),
        nationality=fields.get("nationality"),
        gender=fields.get("gender"),
    ))


def _with_pii(identity: IdentitySummary) -> IdentitySummary:
    identity.document_number_hash = hash_document_number(identity.document_number)
    identity.document_number_masked = mask_document_number(identity.document_number)
    return identity


def _thumb(crop) -> str | None:
    if crop is None or crop.size == 0:
        return None
    h, w = crop.shape[:2]
    scale = 128 / max(h, w)
    small = cv2.resize(crop, (max(1, int(w * scale)), max(1, int(h * scale))))
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


def _classification_mismatch(requested: str, detection) -> bool:
    if requested == "auto" or _same_family(requested, detection.detected_type):
        return False
    strong_text = detection.method in ("text", "classifier+text") and detection.confidence >= 0.8
    strong_cnn = detection.method == "classifier" and detection.confidence >= 0.85
    return strong_text or strong_cnn


@router.post("/scan", response_model=ScanResponse)
async def scan_document(
    document_type: str = Form(...),
    document: UploadFile = File(...),
    live_face: UploadFile | None = File(None),
):
    valid_types = {"passport", "visa", "national_id", "driving_license", "permit", "aadhar", "pan", "auto"}
    if document_type not in valid_types:
        raise HTTPException(400, f"document_type must be one of {sorted(valid_types)}")

    started = time.perf_counter()
    requested_type = document_type
    doc_bytes = await _read_upload(document)
    try:
        doc_image = bytes_to_bgr(doc_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    live_bytes: bytes | None = None
    if live_face is not None:
        live_bytes = await _read_upload(live_face)

    # Classifier, OCR, tampering forensics and face detection are independent — run them together.
    loop = asyncio.get_running_loop()
    first_ocr_type = "national_id" if requested_type == "auto" else requested_type
    classifier_probs, ocr_result, tampering, doc_faces = await asyncio.gather(
        loop.run_in_executor(_pool, classifier.predict_proba, doc_bytes),
        loop.run_in_executor(_pool, partial(run_ocr, doc_image, first_ocr_type)),
        loop.run_in_executor(_pool, partial(analyze_tampering, doc_bytes, doc_image)),
        loop.run_in_executor(_pool, partial(detect_faces, doc_image)),
    )
    # Pick the holder's portrait by photo quality, not size: passports also
    # print a faint ghost copy that must never be used for matching.
    portrait = pick_portrait(doc_faces)
    doc_face_crop = (
        (doc_image[portrait.y:portrait.y + portrait.h, portrait.x:portrait.x + portrait.w], portrait)
        if portrait else None
    )

    # --- Document type: auto-detect, or confirm the officer's choice ---
    detection = auto_detect.decide(classifier_probs, ocr_result.raw_text)
    if requested_type == "auto":
        document_type = detection.detected_type
        if _tesseract_family(document_type) != _tesseract_family(first_ocr_type):
            ocr_result = await loop.run_in_executor(_pool, partial(run_ocr, doc_image, document_type))

    classification = ClassificationSummary(
        requested_type=requested_type,
        detected_type=detection.detected_type,
        used_type=document_type,
        method=detection.method,
        confidence=detection.confidence,
        reason=detection.reason,
        classifier_available=classifier_probs is not None,
        classifier_probs=classifier_probs,
        text_scores=detection.text_scores,
        text_evidence=detection.text_evidence,
        mismatch=_classification_mismatch(requested_type, detection),
    )

    # --- OCR post-processing: MRZ + field extraction ---
    mrz_summary: MRZSummary | None = None
    mrz_full = None
    if document_type in ("passport", "visa"):
        mrz_full = mrz = parse_mrz(ocr_result.raw_text)
        mrz_summary = MRZSummary(
            detected=mrz.detected,
            format=mrz.format,
            issuing_country=mrz.issuing_country,
            surname=mrz.surname,
            given_names=mrz.given_names,
            nationality=mrz.nationality,
            sex=mrz.sex,
            date_of_birth=mrz.date_of_birth,
            date_of_expiry=mrz.date_of_expiry,
            composite_valid=mrz.composite_valid,
            fields=[
                {"name": f.name, "value": f.value, "valid": f.valid,
                 "check_digit_printed": f.check_digit_expected, "check_digit_computed": f.check_digit_found}
                for f in mrz.fields
            ],
            raw_lines=mrz.raw_lines,
            warnings=mrz.warnings,
        )
    extracted_fields = extract_fields(document_type, ocr_result.raw_text)
    # Fields the full-page reading missed (or got in an invalid form) are taken
    # from the boxes the region detector found.
    extracted_fields, field_sources = merge_region_fields(document_type, extracted_fields, ocr_result.region_reads)
    layout_recognised, layout_note = (
        assess_layout(document_type, ocr_result.region_reads) if ocr_result.region_reads else (False, "")
    )
    identity = _build_identity(document_type, extracted_fields, mrz_full)

    # --- Validation rules ---
    if document_type == "passport" and mrz_full is not None:
        validation = validate_passport(mrz_full, visual_name=extracted_fields.get("name"), extracted_fields=extracted_fields)
    else:
        validation = validate_generic(document_type, extracted_fields)
    if classification.mismatch:
        validation.issues.append(ValidationIssue(
            code="DOC_TYPE_MISMATCH",
            message=(f"Screened as {auto_detect.LABELS.get(requested_type, requested_type)}, but the document "
                     f"looks like a {auto_detect.LABELS.get(detection.detected_type, detection.detected_type)}. "
                     f"{detection.reason}"),
            severity="warning",
        ))
        validation = _finalize(validation.issues, validation.checks_run + 1)

    # --- Records cross-check against earlier screenings ---
    fp = fingerprint(doc_image, doc_face_crop[0] if doc_face_crop else None)
    records, registry_matches, reference = await asyncio.gather(
        loop.run_in_executor(_pool, partial(check_against_records, identity.document_number, identity.name, identity.date_of_birth)),
        loop.run_in_executor(_pool, find_matches, fp),
        loop.run_in_executor(_pool, partial(
            check_issued_document, document_type, identity.document_number, identity.name,
            identity.date_of_birth, identity.expiry_date)),
    )
    records = apply_reference_check(records, reference)
    if registry_matches:
        m = registry_matches[0]
        validation.issues.append(ValidationIssue(
            code="KNOWN_FORGERY_MATCH",
            message=(f"This image matches a document already rejected as forged"
                     f"{' at ' + m.checkpoint_id if m.checkpoint_id else ''}"
                     f"{' (' + m.tamper_types + ')' if m.tamper_types else ''} — the same forged document has been presented before."),
            severity="critical",
        ))
        validation = _finalize(validation.issues, validation.checks_run + 1)
    else:
        validation.checks_run += 1

    # --- Face verification ---
    settings = get_settings()
    face_match = None
    doc_box = None
    if doc_face_crop is not None:
        b = doc_face_crop[1]
        doc_box = BoxModel(x=b.x, y=b.y, w=b.w, h=b.h, image_w=doc_image.shape[1], image_h=doc_image.shape[0])
    match_t, mismatch_t = backend_bands()
    face_summary = FaceSummary(attempted=False, document_face_found=doc_face_crop is not None,
                               document_face_box=doc_box, threshold=match_t, mismatch_threshold=mismatch_t,
                               backend=backend_label(), document_face_candidates=len(doc_faces),
                               document_face_thumb=_thumb(doc_face_crop[0]) if doc_face_crop else None)
    if live_bytes is not None:
        try:
            live_image = bytes_to_bgr(live_bytes)
        except ValueError as e:
            raise HTTPException(400, f"Live capture: {e}") from e
        live_face_crop = await loop.run_in_executor(_pool, detect_largest_face, live_image)
        face_match = compare_faces(
            doc_face_crop[0] if doc_face_crop else None,
            live_face_crop[0] if live_face_crop else None,
        )
        face_summary = FaceSummary(
            attempted=True,
            similarity=face_match.similarity,
            is_match=face_match.is_match,
            backend=face_match.backend,
            document_face_found=face_match.document_face_found,
            live_face_found=face_match.live_face_found,
            document_face_box=doc_box,
            threshold=face_match.match_threshold,
            mismatch_threshold=face_match.mismatch_threshold,
            decision=face_match.decision,
            document_face_candidates=len(doc_faces),
            document_face_thumb=_thumb(doc_face_crop[0]) if doc_face_crop else None,
            live_face_thumb=_thumb(live_face_crop[0]) if live_face_crop else None,
        )

    # --- Risk Engine ---
    risk = compute_risk(validation, tampering, face_match, records)
    evaluation = build_evaluation(
        document_type=document_type, classification=classification, identity=identity, mrz=mrz_full,
        validation=validation, tampering=tampering, face_match=face_match,
        live_photo_given=live_bytes is not None, document_face_found=doc_face_crop is not None, records=records,
        registry_matches=registry_matches, registry_checked=bool(get_settings().DATABASE_URL),
    )

    ela_heatmap_url = None
    if tampering.ela and tampering.ela.heatmap_png:
        ela_heatmap_url = "data:image/jpeg;base64," + base64.b64encode(tampering.ela.heatmap_png).decode("ascii")

    response = ScanResponse(
        id="pending",
        timestamp="pending",
        document_type=document_type,  # type: ignore[arg-type]
        ocr=OCRSummary(
            raw_text=ocr_result.raw_text,
            mean_confidence=ocr_result.mean_confidence,
            engine_available=ocr_result.engine_available,
            warning=ocr_result.warning,
            extracted_fields=extracted_fields,
            region_detection=ocr_result.region_detection,  # type: ignore[arg-type]
            text_regions_used=ocr_result.text_regions_used,
            field_sources=field_sources,
            layout_recognised=layout_recognised,
            layout_note=layout_note,
            # the number box is reported masked: the stored record must never hold the full number
            region_reads=[
                {**r.to_dict(), "text": identity.document_number_masked or "(masked)"}
                if r.class_name == "document_number" else r.to_dict()
                for r in ocr_result.region_reads
            ],
        ),
        mrz=mrz_summary,
        validation=ValidationSummary(
            score=validation.score,
            issues=[
                {"code": i.code, "message": i.message, "severity": i.severity, "field": i.field}
                for i in validation.issues
            ],
            checks_run=validation.checks_run,
        ),
        tampering=TamperingSummary(
            tampering_score=tampering.tampering_score,
            verdict=tampering.verdict,
            evidence=tampering.evidence,
            ela_suspicious=tampering.ela.suspicious if tampering.ela else False,
            ela_max_error=tampering.ela.max_error if tampering.ela else 0.0,
            copy_move_matches=tampering.copy_move.match_count if tampering.copy_move else 0,
            ela_heatmap=ela_heatmap_url,
            components=tampering.components,
        ),
        face=face_summary,
        risk=RiskSummary(**asdict(risk)),
        classification=classification,
        identity=identity,
        records=RecordCheckSummary(**asdict(records)),
        evaluation=[asdict(r) for r in evaluation],
        image_fingerprint=fp,
        registry_matches=[asdict(m) for m in registry_matches],
        provenance=provenance(),
        processing_ms=int((time.perf_counter() - started) * 1000),
    )

    record = response.model_dump()
    scan_id = file_store.save_scan(record)
    record = file_store.get_scan(scan_id)

    # Create timestamped receipt for the scan
    try:
        if record is not None:
            receipt = create_scan_receipt(record)
            logger.info("Created receipt %s for scan %s", receipt.receipt_id, scan_id)
    except Exception as e:
        logger.warning("Failed to create scan receipt: %s", e)

    return ScanResponse(**record)


@router.get("/scans", response_model=list[ScanListItem])
async def list_scans(limit: int = 50):
    records = file_store.list_scans(limit=limit)
    return [
        ScanListItem(
            id=r["id"],
            timestamp=r["timestamp"],
            document_type=r["document_type"],
            risk_score=r["risk"]["risk_score"],
            verdict=r["risk"]["verdict"],
        )
        for r in records
    ]


@router.get("/scans/{scan_id}", response_model=ScanResponse)
async def get_scan(scan_id: str):
    record = file_store.get_scan(scan_id)
    if not record:
        raise HTTPException(404, "Scan not found.")
    return ScanResponse(**record)


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    return StatsResponse(**file_store.stats())


# --- Security & Audit Routes ---

@router.get("/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    """Retrieve a timestamped scan receipt by ID."""
    from app.modules.security.timestamping import get_receipt
    receipt = get_receipt(receipt_id)
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return receipt


@router.get("/receipts/scan/{scan_id}")
async def get_receipts_for_scan(scan_id: str):
    """Get all receipts for a given scan."""
    from app.modules.security.timestamping import get_receipts_for_scan
    return get_receipts_for_scan(scan_id)


@router.get("/receipts/{receipt_id}/verify")
async def verify_receipt(receipt_id: str):
    """Verify a scan receipt's integrity."""
    from app.modules.security.timestamping import get_receipt, verify_scan_receipt
    receipt = get_receipt(receipt_id)
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    valid, msg = verify_scan_receipt(receipt)
    return {"valid": valid, "message": msg}


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str):
    """Retrieve a signed batch by ID."""
    from app.modules.security.signed_batches import get_batch, verify_signed_batch
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    valid, msg = verify_signed_batch(batch)
    return {"batch": batch, "verified": valid, "message": msg}


@router.get("/batches/scan/{scan_id}")
async def get_batches_for_scan(scan_id: str):
    """Get all batches containing a specific scan."""
    from app.modules.security.signed_batches import get_batches_for_scan
    return get_batches_for_scan(scan_id)


@router.post("/batches")
async def create_batch(scan_ids: list[str], receipt_ids: list[str]):
    """Create a signed batch from scan IDs and receipt IDs."""
    from app.modules.security.signed_batches import create_signed_batch
    if len(scan_ids) != len(receipt_ids):
        raise HTTPException(400, "scan_ids and receipt_ids must have same length")
    batch = create_signed_batch(scan_ids, receipt_ids)
    return batch


@router.get("/batches/{batch_id}/verify")
async def verify_batch(batch_id: str):
    """Verify a signed batch's integrity."""
    from app.modules.security.signed_batches import get_batch, verify_signed_batch
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    valid, msg = verify_signed_batch(batch)
    return {"valid": valid, "message": msg}


@router.get("/incidents")
async def list_incidents(
    limit: int = 50,
    severity: str | None = None,
    type: str | None = None,
):
    """List incident reports."""
    from app.modules.security.incident import get_incident_reports, IncidentSeverity, IncidentType
    sev = IncidentSeverity(severity) if severity else None
    typ = IncidentType(type) if type else None
    return get_incident_reports(limit=limit, severity=sev, type=typ)


@router.post("/incidents")
async def create_incident(
    type: str,
    severity: str,
    title: str,
    description: str,
    checkpoint_id: str | None = None,
    officer_id: str | None = None,
    related_scan_ids: list[str] | None = None,
    metadata: dict | None = None,
    created_by: str = "api",
):
    """Create an incident report."""
    from app.modules.security.incident import create_incident_report, IncidentSeverity, IncidentType
    try:
        sev = IncidentSeverity(severity)
        typ = IncidentType(type)
    except ValueError as e:
        raise HTTPException(400, f"Invalid type or severity: {e}")
    report = create_incident_report(
        type=typ,
        severity=sev,
        title=title,
        description=description,
        checkpoint_id=checkpoint_id,
        officer_id=officer_id,
        related_scan_ids=related_scan_ids,
        metadata=metadata,
        created_by=created_by,
    )
    return report


@router.get("/insider-alerts")
async def list_insider_alerts(
    limit: int = 50,
    status: str | None = None,
    severity: str | None = None,
):
    """List insider threat alerts."""
    from app.modules.security.insider_threat import get_insider_alerts
    return get_insider_alerts(limit=limit, status=status, severity=severity)


@router.post("/insider-alerts/detect")
async def run_insider_detection(lookback_days: int = 7):
    """Run insider threat detection on recent scans."""
    from app.modules.security.insider_threat import detect_insider_threats
    alerts = detect_insider_threats(lookback_days=lookback_days)
    return {"alerts_generated": len(alerts), "alerts": alerts}


@router.get("/retention/stats")
async def get_retention_stats():
    """Get statistics about data age for retention planning."""
    from app.modules.security.retention import get_retention_stats
    return get_retention_stats()


@router.post("/retention/apply")
async def apply_retention(dry_run: bool = False):
    """Apply the retention policy (cleanup expired records)."""
    from app.modules.security.retention import apply_retention_policy
    return apply_retention_policy(dry_run=dry_run)


@router.get("/provenance")
async def get_provenance():
    """Get model and rules provenance information."""
    from app.modules.provenance import provenance, integrity_report
    return {"provenance": provenance(), "integrity": integrity_report()}


@router.post("/admin/bootstrap")
async def bootstrap_admin(
    email: str = Form(...),
    password: str = Form(...),
    bootstrap_code: str = Form(...),
):
    """Create the first admin account using one-time bootstrap code."""
    from app.modules.security.auth import bootstrap_admin
    return bootstrap_admin(email=email, password=password, bootstrap_code=bootstrap_code)


@router.get("/health/security")
async def security_health():
    """Security health check: engine key, auth secret, audit key, checkpoint config."""
    settings = get_settings()
    return {
        "engine_key_configured": bool(settings.ENGINE_API_KEY),
        "auth_secret_configured": bool(settings.AUTH_SECRET_KEY),
        "audit_signing_key_configured": bool(settings.AUDIT_SIGNING_KEY),
        "pii_hash_key_configured": bool(settings.PII_HASH_KEY),
        "admin_bootstrap_available": bool(settings.ADMIN_BOOTSTRAP_CODE) and not (settings.UPLOAD_DIR / ".admin_bootstrap").exists(),
        "checkpoint_access_configured": bool(settings.ENGINE_CHECKPOINT_IDS),
        "allowed_checkpoints": settings.ENGINE_CHECKPOINT_IDS,
    }
