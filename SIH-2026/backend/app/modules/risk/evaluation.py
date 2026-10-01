"""
Evaluation matrix — one row per check, stating HOW it was measured, what
was found, what was expected, and a one-line plain-language result. This is
what an officer reads; the risk breakdown is what an auditor reads.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.face.verifier import FaceMatchResult
from app.modules.tampering.tampering_engine import TamperingResult
from app.modules.validation.rules_engine import ValidationResult

_LABELS = {
    "passport": "passport", "visa": "visa", "national_id": "national ID", "aadhar": "Aadhaar",
    "pan": "PAN card", "driving_license": "driving licence", "permit": "border permit",
}
_MRZ_NAMES = {
    "passport_number": "document number", "date_of_birth": "date of birth",
    "date_of_expiry": "expiry date", "personal_number": "personal number",
}


@dataclass
class EvalRow:
    check: str
    method: str
    measured: str
    expected: str
    status: str  # pass | warn | fail | skip
    sentence: str


def _issues(validation: ValidationResult, *prefixes: str):
    return [i for i in validation.issues if i.code.startswith(prefixes)]


def build_evaluation(
    *,
    document_type: str,
    classification,
    identity,
    mrz,
    validation: ValidationResult,
    tampering: TamperingResult,
    face_match: FaceMatchResult | None,
    live_photo_given: bool,
    document_face_found: bool,
    records,
    registry_matches=None,
    registry_checked: bool = False,
) -> list[EvalRow]:
    rows: list[EvalRow] = []
    label = _LABELS.get(document_type, document_type)

    # 1. Document type
    if classification is not None:
        conf = f"{classification.confidence:.0%}"
        status = "warn" if classification.mismatch or classification.confidence < 0.6 else "pass"
        sentence = (f"Looks like a {_LABELS.get(classification.detected_type, classification.detected_type)}, "
                    f"not the type selected." if classification.mismatch
                    else f"Identified as a {label} ({conf} confidence).")
        rows.append(EvalRow("Document type", "Image classifier (MobileNetV2) + printed-text markers",
                            conf, "≥ 60% and agrees with selection", status, sentence))

    # 2. Required details read
    missing = _issues(validation, "MISSING_FIELD_")
    read = [k for k in ("name", "document_number", "date_of_birth") if getattr(identity, k)]
    rows.append(EvalRow(
        "Details read", "OCR (Tesseract) + field format rules",
        f"{len(read)}/3 key fields", "name, number, date of birth",
        "warn" if missing else "pass",
        "Could not read: " + ", ".join(i.field.replace("_", " ") for i in missing) + "." if missing
        else "Name, document number and date of birth were read.",
    ))

    # 3. MRZ check digits (passport/visa)
    if document_type in ("passport", "visa"):
        if mrz is None or not mrz.detected:
            rows.append(EvalRow("MRZ check digits", "Arithmetic check (ICAO 9303, weights 7-3-1)",
                                "MRZ not found", "2 readable MRZ lines", "fail",
                                "The machine-readable zone could not be read."))
        else:
            checks = [(f.name, f.valid) for f in mrz.fields] + [("composite", mrz.composite_valid)]
            failed = [n for n, v in checks if v is False]
            unreadable = [n for n, v in checks if v is None]
            ok = sum(1 for _, v in checks if v)
            rows.append(EvalRow(
                "MRZ check digits", "Arithmetic check (ICAO 9303, weights 7-3-1)",
                f"{ok}/{len(checks)} digits correct", "all correct",
                "fail" if failed else "warn" if unreadable else "pass",
                ("Check digit wrong for " + ", ".join(_MRZ_NAMES.get(n, n) for n in failed) + " — the MRZ was altered.")
                if failed else "Some check digits could not be read." if unreadable
                else "Every MRZ check digit is correct.",
            ))
        viz = _issues(validation, "VIZ_MRZ_MISMATCH_", "NAME_MISMATCH_MRZ_VS_VISUAL")
        rows.append(EvalRow(
            "Printed page vs MRZ", "Entry comparison (name, DOB, expiry, number)",
            f"{len(viz)} mismatch(es)", "0 mismatches", "fail" if viz else "pass",
            " ".join(i.message.split(". ")[0] + "." for i in viz) if viz
            else "Printed details agree with the MRZ.",
        ))

    # 4. Number / format rules for Indian documents
    fmt = _issues(validation, "AADHAAR_CHECKSUM", "PAN_FORMAT", "DL_FORMAT")
    if document_type in ("aadhar", "national_id", "pan", "driving_license"):
        method = {"pan": "Format rule ABCDE1234F", "driving_license": "Format rule state-RTO-year-serial"}.get(
            document_type, "Verhoeff checksum (UIDAI)")
        rows.append(EvalRow(
            "Number format", method, "invalid" if fmt else "valid" if identity.document_number else "not read",
            "valid", "fail" if fmt else "pass" if identity.document_number else "skip",
            fmt[0].message if fmt else "Document number has a valid format." if identity.document_number
            else "No number to check.",
        ))

    # 5. Dates and reference data
    dated = _issues(validation, "DOCUMENT_EXPIRED", "IMPLAUSIBLE_AGE", "ISSUE_AFTER_EXPIRY")
    ref = _issues(validation, "PINCODE_STATE_MISMATCH", "UNRECOGNIZED_PSK_CODE", "EVISA_", "RARE_VISA")
    rows.append(EvalRow(
        "Dates & reference data", "Date logic + lookup in PIN / passport-office / e-Visa lists",
        f"{len(dated) + len(ref)} issue(s)", "0 issues",
        "fail" if any(i.severity == "critical" for i in dated + ref) else "warn" if dated or ref else "pass",
        " ".join(i.message.split(". ")[0] + "." for i in (dated + ref)[:2]) if dated or ref
        else "Dates are consistent and reference lookups agree.",
    ))

    # 6. Tampering
    comp = {c["name"]: c for c in tampering.components}
    ela = tampering.ela
    if ela is not None:
        pct = ela.suspicious_region_ratio * 100
        rows.append(EvalRow(
            "Pasted / edited regions", "Pixel re-compression difference (Error Level Analysis)",
            f"{pct:.2f}% pixels abnormal", "< 1% abnormal",
            "fail" if pct >= 4 else "warn" if ela.suspicious else "pass",
            f"{pct:.1f}% of the image re-compresses differently — likely edited." if ela.suspicious
            else "No area re-compresses differently from the rest.",
        ))
    cm = tampering.copy_move
    if cm is not None:
        cm_comp = comp.get("Copy-move (clone) detection", {})
        rows.append(EvalRow(
            "Cloned regions", "Keypoint displacement clustering (ORB)",
            f"{cm.match_count} matching pairs", "below alarm level (100)",
            "warn" if cm.suspicious else "pass",
            "A region appears copied to another place on the document." if cm.suspicious
            else "No copied-and-pasted region found." + (" (Printed text naturally repeats.)" if cm_comp.get("raw", 0) == 0 and cm.match_count > 30 else ""),
        ))
    md = tampering.metadata
    if md is not None:
        rows.append(EvalRow(
            "File metadata", "EXIF inspection for editing software",
            md.software_tag or ("no EXIF" if not md.has_exif else "no editor tag"), "no editor signature",
            "fail" if md.editor_signature_found else "pass",
            f"File was saved by image-editing software ({md.software_tag})." if md.editor_signature_found
            else "No sign of image-editing software.",
        ))

    # 7. Face
    if not live_photo_given:
        rows.append(EvalRow("Face match", "Face similarity (document photo vs live photo)", "not run",
                            "live photo required", "skip",
                            "No live photo given, so identity was not checked." if document_face_found
                            else "No live photo given; no face found on the document."))
    elif face_match is None or face_match.decision == "not_run":
        missing_where = "document" if face_match and not face_match.document_face_found else "live photo"
        rows.append(EvalRow("Face match", "Face similarity (document photo vs live photo)", f"no face in {missing_where}",
                            "a face in both", "warn", f"No face could be found in the {missing_where}."))
    else:
        sim = f"{face_match.similarity:.0%}"
        need = f"≥ {face_match.match_threshold:.0%} same person; < {face_match.mismatch_threshold:.0%} different"
        text = {
            "match": "The traveller matches the document photo.",
            "uncertain": "Face match is inconclusive — compare the traveller with the photo yourself.",
            "mismatch": "The traveller is NOT the person in the document photo.",
        }[face_match.decision]
        rows.append(EvalRow("Face match", f"Face similarity — {face_match.backend}", sim, need,
                            {"match": "pass", "uncertain": "warn", "mismatch": "fail"}[face_match.decision], text))

    # 8. Forged-document registry
    if registry_checked:
        if registry_matches:
            m = registry_matches[0]
            rows.append(EvalRow(
                "Known forgeries", "Image fingerprint vs registry of rejected documents (perceptual hash)",
                f"{len(registry_matches)} match(es), {m.page_distance} bits apart", "no match", "fail",
                "This exact document was rejected as forged before"
                + (f" at {m.checkpoint_id}." if m.checkpoint_id else "."),
            ))
        else:
            rows.append(EvalRow(
                "Known forgeries", "Image fingerprint vs registry of rejected documents (perceptual hash)",
                "no match", "no match", "pass", "Not seen among documents rejected as forged.",
            ))

    # 9. Issued-documents database
    ref = getattr(records, "reference", None) if records is not None else None
    if ref and ref["status"] in ("match", "mismatch", "not_found"):
        compared = [f for f in ref["fields"] if f["on_document"]]
        rows.append(EvalRow(
            "Issuing records", "Database comparison (document number -> holder name, date of birth, expiry)",
            "; ".join(f"{f['field'].replace('_', ' ')} {'=' if f['match'] else '≠'} {f['in_database']}" for f in compared)
            or ("number not in database" if ref["status"] == "not_found" else "number found"),
            "same holder details as issued",
            {"match": "pass", "mismatch": "fail", "not_found": "skip"}[ref["status"]],
            ref["summary"],
        ))

    # 10. Earlier screenings
    if records is not None:
        history = getattr(records, "history_status", "") or records.status
        status = {"conflict": "fail", "flagged_history": "warn", "consistent": "pass"}.get(history, "skip")
        history_issues = [i for i in records.issues if i.code != "ISSUING_RECORD_MISMATCH"]
        rows.append(EvalRow(
            "Earlier screenings", "Database entry comparison (same document number)",
            f"{records.prior_count} earlier record(s)", "same name and DOB every time", status,
            history_issues[0].message if history_issues and status in ("fail", "warn")
            else (getattr(records, "history_summary", "") or records.summary),
        ))
    return rows
