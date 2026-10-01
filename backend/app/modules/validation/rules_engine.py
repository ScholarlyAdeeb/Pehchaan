"""
Module 2 — Document Validation.

Runs a battery of explainable rules over the OCR/MRZ output and reports each
as a `ValidationIssue`. We deliberately never produce a single opaque
pass/fail — every finding carries a human-readable reason, because an
officer (or an auditor reviewing the digital trail later) needs to know
*why* a document was flagged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher

from app.modules.ocr.mrz_parser import MRZResult
from app.modules.reference.lookup import (
    check_visa_plausibility,
    is_evisa_eligible,
    validate_pincode_state,
    validate_psk_code,
)
from app.modules.validation.schemas import KNOWN_COUNTRY_CODES

Severity = str  # "info" | "warning" | "critical"

_SEVERITY_PENALTY = {"info": 2, "warning": 10, "critical": 30}


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: Severity
    field: str | None = None


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    score: int = 100  # 100 = fully valid, 0 = fails everything checked
    checks_run: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


def _parse_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return datetime.fromisoformat(d).date()
    except ValueError:
        return None


def _name_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 1.0  # nothing to compare, don't penalize
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def validate_passport(
    mrz: MRZResult,
    visual_name: str | None = None,
    extracted_fields: dict | None = None,
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    checks = 0

    if not mrz.detected:
        issues.append(ValidationIssue(
            code="MRZ_NOT_FOUND",
            message="No machine-readable zone detected — cannot cryptographically verify document number, date of birth, or expiry.",
            severity="critical",
        ))
        return _finalize(issues, checks_run=1)

    for f in mrz.fields:
        checks += 1
        if f.valid is False:
            issues.append(ValidationIssue(
                code=f"MRZ_CHECKSUM_{f.name.upper()}",
                message=f"MRZ check digit for '{f.name}' does not match (expected {f.check_digit_expected}, computed {f.check_digit_found}). This field may have been altered.",
                severity="critical",
                field=f.name,
            ))
        elif f.valid is None:
            issues.append(ValidationIssue(
                code=f"MRZ_CHECKSUM_UNREADABLE_{f.name.upper()}",
                message=f"Could not compute a check digit for '{f.name}' — OCR text may be too noisy.",
                severity="warning",
                field=f.name,
            ))

    checks += 1
    if mrz.composite_valid is False:
        issues.append(ValidationIssue(
            code="MRZ_COMPOSITE_CHECKSUM",
            message="MRZ composite (overall) check digit failed. Strong indicator of tampering or a fraudulent document.",
            severity="critical",
        ))

    checks += 1
    expiry = _parse_iso(mrz.date_of_expiry)
    if expiry and expiry < date.today():
        issues.append(ValidationIssue(
            code="DOCUMENT_EXPIRED",
            message=f"Passport expired on {expiry.isoformat()}.",
            severity="critical",
            field="date_of_expiry",
        ))
    elif not expiry:
        issues.append(ValidationIssue(
            code="EXPIRY_UNREADABLE",
            message="Could not parse a valid expiry date from the MRZ.",
            severity="warning",
            field="date_of_expiry",
        ))

    checks += 1
    dob = _parse_iso(mrz.date_of_birth)
    if dob:
        age_days = (date.today() - dob).days
        age_years = age_days / 365.25
        if age_years < 0 or age_years > 120:
            issues.append(ValidationIssue(
                code="IMPLAUSIBLE_AGE",
                message=f"Date of birth implies an implausible age ({age_years:.0f} years).",
                severity="critical",
                field="date_of_birth",
            ))
    else:
        issues.append(ValidationIssue(
            code="DOB_UNREADABLE",
            message="Could not parse a valid date of birth from the MRZ.",
            severity="warning",
            field="date_of_birth",
        ))

    checks += 1
    if mrz.nationality and mrz.nationality not in KNOWN_COUNTRY_CODES:
        issues.append(ValidationIssue(
            code="UNRECOGNIZED_NATIONALITY_CODE",
            message=f"Nationality code '{mrz.nationality}' is not in the recognized reference set (prototype uses a partial ISO 3166-1 alpha-3 list — verify manually).",
            severity="info",
            field="nationality",
        ))

    checks += 1
    mrz_full_name = " ".join(filter(None, [mrz.given_names, mrz.surname]))
    similarity = _name_similarity(mrz_full_name, visual_name)
    if similarity < 0.55:
        issues.append(ValidationIssue(
            code="NAME_MISMATCH_MRZ_VS_VISUAL",
            message=f"Name in the MRZ ('{mrz_full_name}') does not closely match the printed name elsewhere on the document ('{visual_name}'). Possible substitution.",
            severity="critical",
            field="name",
        ))

    # --- Printed (visual zone) vs MRZ consistency ---
    # A forger who edits the printed page rarely re-computes the MRZ as well,
    # so disagreement between the two is one of the strongest alteration signals.
    visual = extracted_fields or {}
    mrz_number = next((f.value.replace("<", "") for f in mrz.fields if f.name == "passport_number"), None)
    comparisons = [
        ("date_of_birth", visual.get("date_of_birth"), mrz.date_of_birth, "date of birth"),
        ("date_of_expiry", visual.get("expiry_date"), mrz.date_of_expiry, "expiry date"),
        ("passport_number", visual.get("passport_number_visual"), mrz_number, "passport number"),
    ]
    for field_name, printed, machine, label in comparisons:
        if not printed or not machine:
            continue
        checks += 1
        norm = (lambda v: v.upper().replace("O", "0").replace("I", "1")) if field_name == "passport_number" else str
        if norm(printed) != norm(machine):
            issues.append(ValidationIssue(
                code=f"VIZ_MRZ_MISMATCH_{field_name.upper()}",
                message=f"Printed {label} '{printed}' does not match the MRZ ({machine}). "
                        f"One of them has been altered.",
                severity="critical",
                field=field_name,
            ))

    # --- Reference data checks (data.gov.in DS-004: PSK Directory) ---
    checks += 1
    if mrz.issuing_country and mrz.issuing_country == "IND" and extracted_fields:
        issuing_office = extracted_fields.get("issuing_office")
        if issuing_office:
            psk = validate_psk_code(issuing_office)
            if psk is None:
                issues.append(ValidationIssue(
                    code="UNRECOGNIZED_PSK_CODE",
                    message=f"Passport issuing office code '{issuing_office}' not found in the Passport Seva Kendra directory — verify manually.",
                    severity="warning",
                    field="issuing_office",
                ))

    return _finalize(issues, checks_run=checks)


def validate_generic(document_type: str, extracted_fields: dict) -> ValidationResult:
    """Rule pass for documents without an MRZ — with Indian document-specific validation."""
    issues: list[ValidationIssue] = []
    checks = 0

    required_by_type = {
        "visa": ["visa_number", "visa_type"],
        "national_id": ["name", "id_number"],
        "aadhar": ["name", "id_number"],
        "pan": ["name", "id_number"],
        "driving_license": ["name", "license_number"],
        "permit": ["permit_number"],
    }
    for required_field in required_by_type.get(document_type, []):
        checks += 1
        if not extracted_fields.get(required_field):
            issues.append(ValidationIssue(
                code=f"MISSING_FIELD_{required_field.upper()}",
                message=f"Could not extract required field '{required_field}' from the document.",
                severity="warning",
                field=required_field,
            ))

    # --- Aadhaar-specific validation ---
    if document_type in ("national_id", "aadhar"):
        if extracted_fields.get("id_number"):
            checks += 1
            if extracted_fields.get("aadhaar_valid") is False:
                issues.append(ValidationIssue(
                    code="AADHAAR_CHECKSUM_FAILED",
                    message="Aadhaar number fails Verhoeff checksum validation — number may be fabricated.",
                    severity="critical",
                    field="id_number",
                ))
            elif extracted_fields.get("aadhaar_valid") is True:
                pass  # valid, no issue

        if extracted_fields.get("date_of_birth"):
            checks += 1
            dob = _parse_iso(extracted_fields["date_of_birth"])
            if dob:
                age_days = (date.today() - dob).days
                age_years = age_days / 365.25
                if age_years < 0 or age_years > 120:
                    issues.append(ValidationIssue(
                        code="IMPLAUSIBLE_AGE",
                        message=f"Date of birth implies an implausible age ({age_years:.0f} years).",
                        severity="critical",
                        field="date_of_birth",
                    ))

    # --- PAN-specific validation ---
    if document_type == "pan":
        if extracted_fields.get("id_number"):
            checks += 1
            if extracted_fields.get("pan_valid") is False:
                issues.append(ValidationIssue(
                    code="PAN_FORMAT_INVALID",
                    message="PAN number does not match the expected ABCDE1234F format.",
                    severity="critical",
                    field="id_number",
                ))

    # --- Indian DL-specific validation ---
    if document_type == "driving_license":
        if extracted_fields.get("license_number"):
            checks += 1
            if extracted_fields.get("dl_format_valid") is False:
                issues.append(ValidationIssue(
                    code="DL_FORMAT_INVALID",
                    message="Driving licence number does not match Indian state-RTO format.",
                    severity="warning",
                    field="license_number",
                ))

    # Expiry-in-the-past check, wherever an expiry-like field exists.
    for key in ("expiry_date", "valid_till"):
        if key in extracted_fields:
            checks += 1
            d = _parse_iso(extracted_fields.get(key))
            if d and d < date.today():
                issues.append(ValidationIssue(
                    code="DOCUMENT_EXPIRED",
                    message=f"Document expired on {d.isoformat()}.",
                    severity="critical",
                    field=key,
                ))

    # --- Reference data checks ---

    # DS-045: Pincode validation
    pincode = extracted_fields.get("pincode") or extracted_fields.get("pin_code")
    claimed_state = extracted_fields.get("state")
    if pincode and claimed_state:
        checks += 1
        match, actual_state = validate_pincode_state(pincode, claimed_state)
        if not match and actual_state:
            issues.append(ValidationIssue(
                code="PINCODE_STATE_MISMATCH",
                message=f"Pincode {pincode} belongs to {actual_state}, not '{claimed_state}' as printed on document.",
                severity="critical",
                field="pincode",
            ))

    # DS-010: E-visa eligibility check
    if document_type == "visa":
        visa_subtype = extracted_fields.get("visa_type", "").lower()
        nationality = extracted_fields.get("nationality", "")
        if "e-visa" in visa_subtype or "evisa" in visa_subtype or "e-tourist" in visa_subtype:
            checks += 1
            if nationality and not is_evisa_eligible(nationality):
                issues.append(ValidationIssue(
                    code="EVISA_INELIGIBLE_NATIONALITY",
                    message=f"Nationality '{nationality}' is not in the e-Visa eligible countries list — document may be forged.",
                    severity="critical",
                    field="visa_type",
                ))

        # DS-006: Visa type plausibility
        if nationality and visa_subtype:
            checks += 1
            plausibility = check_visa_plausibility(nationality, visa_subtype)
            if plausibility == "rare":
                issues.append(ValidationIssue(
                    code="RARE_VISA_NATIONALITY_COMBO",
                    message=f"Visa type '{visa_subtype}' is uncommonly issued to '{nationality}' nationals — manual review recommended.",
                    severity="warning",
                    field="visa_type",
                ))

    # Issue date after expiry date is a logical impossibility.
    if "issue_date" in extracted_fields and "expiry_date" in extracted_fields:
        checks += 1
        issue_d = _parse_iso(extracted_fields.get("issue_date"))
        expiry_d = _parse_iso(extracted_fields.get("expiry_date"))
        if issue_d and expiry_d and issue_d > expiry_d:
            issues.append(ValidationIssue(
                code="ISSUE_AFTER_EXPIRY",
                message="Issue date is after the expiry date — internally inconsistent document.",
                severity="critical",
            ))

    return _finalize(issues, checks_run=max(checks, 1))


def _finalize(issues: list[ValidationIssue], checks_run: int) -> ValidationResult:
    penalty = sum(_SEVERITY_PENALTY[i.severity] for i in issues)
    score = max(0, 100 - penalty)
    return ValidationResult(issues=issues, score=score, checks_run=checks_run)
