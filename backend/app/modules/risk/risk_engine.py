"""
Risk Engine — turns the independent screening signals into one 0-100 risk
score and a verdict, and records exactly how the number was produced.

    1. Each signal produces its own risk on a 0-100 scale:
         Document validation   risk = sum of rule penalties (critical 30, warning 10, info 2), capped at 100
         Tampering forensics   risk = tampering score (ELA 50% + copy-move 35% + metadata 15%)
         Face match            risk = 100 mismatch, 60 inconclusive, (1 - similarity) x 20 match
         Records history       risk = 100 identity conflict, 50 previously flagged, 0 consistent
    2. Signals that did not run (no selfie given, no earlier screenings of this
       number) are left out, and the weights of the remaining ones are scaled
       up so they still add to 1:  effective weight = weight / sum(weights that ran)
    3. Weighted score = sum(risk x effective weight)
    4. Hard floors: a critical rule failure, a "tampered" forensics verdict or
       a records identity conflict lifts the score to at least 66, because a
       good result elsewhere must not wash out a disqualifying finding.
       A live photo that clearly belongs to someone else lifts it to at least
       85 (90 when far below the mismatch line); an inconclusive face match
       to at least 45, so it cannot be cleared automatically. So does a
       document whose holder's name or number could not be read: nothing on
       it was verified, so it cannot be cleared either.
    5. Verdict bands: 0-30 CLEAR, 31-65 REVIEW, 66-100 REJECT (shown to
       officers as HIGH RISK).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.modules.face.verifier import FaceMatchResult
from app.modules.tampering.tampering_engine import TamperingResult
from app.modules.validation.rules_engine import _SEVERITY_PENALTY, ValidationResult

OVERRIDE_FLOOR = 66
FACE_MISMATCH_FLOOR = 85
FACE_MISMATCH_FLOOR_STRONG = 90
FACE_UNCERTAIN_FLOOR = 45
UNREAD_IDENTITY_FLOOR = 45


@dataclass
class RiskComponent:
    key: str
    label: str
    applicable: bool
    risk: float | None
    weight: float
    effective_weight: float = 0.0
    contribution: float = 0.0
    explanation: str = ""


@dataclass
class RiskReport:
    risk_score: int  # 0 (low risk) - 100 (high risk)
    verdict: str  # "CLEAR" | "REVIEW" | "REJECT"
    contributing_factors: list[str] = field(default_factory=list)
    validation_score: int = 100
    tampering_score: int = 0
    face_similarity: float | None = None
    components: list[RiskComponent] = field(default_factory=list)
    weighted_score: float = 0.0
    overrides: list[str] = field(default_factory=list)
    thresholds: dict[str, int] = field(default_factory=dict)
    formula: str = ""


def _validation_component(validation: ValidationResult, weight: float) -> RiskComponent:
    counts = {s: sum(1 for i in validation.issues if i.severity == s) for s in ("critical", "warning", "info")}
    parts = [f"{n} {s} x {_SEVERITY_PENALTY[s]}" for s, n in counts.items() if n]
    penalty = sum(n * _SEVERITY_PENALTY[s] for s, n in counts.items())
    explanation = (
        f"{validation.checks_run} rule checks run. Penalties: {' + '.join(parts)} = {penalty}"
        + (" (capped at 100)" if penalty > 100 else "")
        if parts else f"{validation.checks_run} rule checks run, no rule failed."
    )
    return RiskComponent("validation", "Document validation", True, float(100 - validation.score), weight,
                         explanation=explanation)


def _tampering_component(tampering: TamperingResult, weight: float) -> RiskComponent:
    if tampering.components:
        explanation = " + ".join(
            f"{c['name']} {c['raw']:.0f} x {c['weight']}" for c in tampering.components
        ) + f" = {tampering.tampering_score} ({tampering.verdict})"
    else:
        explanation = f"Tampering score {tampering.tampering_score} ({tampering.verdict})"
    return RiskComponent("tampering", "Tampering forensics", True, float(tampering.tampering_score), weight,
                         explanation=explanation)


def _face_component(face_match: FaceMatchResult | None, weight: float, threshold: float) -> tuple[RiskComponent, str | None]:
    label = "Face match (document vs live photo)"
    if face_match is None:
        return RiskComponent("face", label, False, None, weight,
                             explanation="No live photo was provided, so face matching did not run."), None
    if not face_match.live_face_found and not face_match.document_face_found:
        return RiskComponent("face", label, True, 40.0, weight,
                             explanation="No face found in either image; fixed risk 40."), \
            "No face detected on the document or in the live photo — identity not verified."
    if not face_match.document_face_found:
        return RiskComponent("face", label, True, 40.0, weight,
                             explanation="No face found on the document photo; fixed risk 40."), \
            "No face detected on the document photo — cannot verify identity."
    if not face_match.live_face_found:
        return RiskComponent("face", label, True, 40.0, weight,
                             explanation="No face found in the live photo; fixed risk 40."), \
            "No face detected in the live photo — face verification incomplete."
    sim = face_match.similarity
    match_t = face_match.match_threshold or threshold
    mismatch_t = face_match.mismatch_threshold or match_t
    if face_match.decision == "match":
        return RiskComponent("face", label, True, round((1 - sim) * 20, 1), weight,
                             explanation=f"Similarity {sim:.0%} ≥ match line {match_t:.0%}: same person. Residual risk (1 − {sim:.2f}) × 20"), None
    if face_match.decision == "uncertain":
        return RiskComponent("face", label, True, 60.0, weight,
                             explanation=f"Similarity {sim:.0%} is between the mismatch line {mismatch_t:.0%} and the match line {match_t:.0%}: identity not confirmed. Fixed risk 60"), \
            f"Face similarity {sim:.0%} is inconclusive — an officer must compare the traveller with the document photo."
    return RiskComponent("face", label, True, 100.0, weight,
                         explanation=f"Similarity {sim:.0%} is below the mismatch line {mismatch_t:.0%}: a different person. Risk 100"), \
        f"The traveller's face does not match the document photo (similarity {sim:.0%}, same-person needs ≥ {match_t:.0%})."


def _records_component(records, weight: float) -> RiskComponent:
    label = "Records (issuing database + earlier screenings)"
    if records is None or records.risk is None:
        summary = records.summary if records is not None else "Records check did not run."
        return RiskComponent("records", label, False, None, weight, explanation=summary)
    return RiskComponent("records", label, True, float(records.risk), weight,
                         explanation=f"{records.summary} Risk {records.risk} ({records.status.replace('_', ' ')}).")


def compute_risk(
    validation: ValidationResult,
    tampering: TamperingResult,
    face_match: FaceMatchResult | None = None,
    records=None,
    unread_identity: list[str] | None = None,
) -> RiskReport:
    """`unread_identity` names the key identity details (name, document
    number) that could not be read from the document."""
    settings = get_settings()
    factors: list[str] = []

    if validation.critical_count:
        factors.append(
            f"{validation.critical_count} critical validation failure(s): "
            + "; ".join(i.message for i in validation.issues if i.severity == "critical")
        )
    if validation.warning_count:
        factors.append(f"{validation.warning_count} field(s) flagged for manual review.")
    if tampering.verdict != "clean":
        factors.extend(tampering.evidence)

    face_comp, face_factor = _face_component(face_match, settings.WEIGHT_FACE, 0.5)
    if face_factor:
        factors.append(face_factor)
    if records is not None:
        factors.extend(i.message for i in records.issues if i.severity in ("critical", "warning"))

    components = [
        _validation_component(validation, settings.WEIGHT_VALIDATION),
        _tampering_component(tampering, settings.WEIGHT_TAMPERING),
        face_comp,
        _records_component(records, settings.WEIGHT_RECORDS),
    ]

    total_weight = sum(c.weight for c in components if c.applicable) or 1.0
    weighted = 0.0
    for c in components:
        if c.applicable:
            c.effective_weight = round(c.weight / total_weight, 4)
            c.contribution = round(c.risk * c.weight / total_weight, 2)
            weighted += c.risk * c.weight / total_weight
    weighted = min(100.0, max(0.0, weighted))
    risk_score = int(round(weighted))

    overrides: list[str] = []
    floor_reasons = []
    if validation.critical_count > 0:
        floor_reasons.append(f"{validation.critical_count} critical validation failure(s)")
    if tampering.verdict == "tampered":
        floor_reasons.append("forensics verdict is 'tampered'")
    if records is not None and records.status == "conflict":
        floor_reasons.append(
            "identity conflicts with the issuing records"
            if (records.reference or {}).get("status") == "mismatch"
            else "identity conflicts with earlier screening records")
    if floor_reasons and risk_score < OVERRIDE_FLOOR:
        overrides.append(
            f"Raised from {risk_score} to {OVERRIDE_FLOOR}: " + "; ".join(floor_reasons)
            + " (disqualifying on its own)."
        )
        risk_score = OVERRIDE_FLOOR

    # A live photo, once given, is the strongest identity evidence there is:
    # a clear mismatch means the presenter is not the holder, whatever the
    # document itself looks like.
    if face_match is not None and face_match.decision == "mismatch":
        very_far = face_match.mismatch_threshold is not None and face_match.similarity < face_match.mismatch_threshold / 2
        floor = FACE_MISMATCH_FLOOR_STRONG if very_far else FACE_MISMATCH_FLOOR
        if risk_score < floor:
            overrides.append(
                f"Raised from {risk_score} to {floor}: the person presenting the document is not the person "
                f"in its photo (face similarity {face_match.similarity:.0%})."
            )
            risk_score = floor
    elif face_match is not None and face_match.decision == "uncertain" and risk_score < FACE_UNCERTAIN_FLOOR:
        overrides.append(
            f"Raised from {risk_score} to {FACE_UNCERTAIN_FLOOR}: the face match is inconclusive, so the "
            "document cannot be cleared without an officer comparing faces."
        )
        risk_score = FACE_UNCERTAIN_FLOOR

    if unread_identity and risk_score < UNREAD_IDENTITY_FLOOR:
        overrides.append(
            f"Raised from {risk_score} to {UNREAD_IDENTITY_FLOOR}: the {' and '.join(unread_identity)} could not be "
            "read, so the document cannot be checked against its records. An officer must read it by hand or rescan."
        )
        factors.append(f"Could not read the holder's {' and '.join(unread_identity)}; rescan or verify by hand.")
        risk_score = UNREAD_IDENTITY_FLOOR

    if risk_score <= settings.RISK_CLEAR_MAX:
        verdict = "CLEAR"
    elif risk_score <= settings.RISK_REVIEW_MAX:
        verdict = "REVIEW"
    else:
        verdict = "REJECT"

    if not factors:
        factors.append("No risk indicators found across validation, tampering, face or records checks.")

    return RiskReport(
        risk_score=risk_score,
        verdict=verdict,
        contributing_factors=factors,
        validation_score=validation.score,
        tampering_score=tampering.tampering_score,
        face_similarity=face_match.similarity if face_match else None,
        components=components,
        weighted_score=round(weighted, 2),
        overrides=overrides,
        thresholds={
            "clear_max": settings.RISK_CLEAR_MAX, "review_max": settings.RISK_REVIEW_MAX,
            "override_floor": OVERRIDE_FLOOR, "face_mismatch_floor": FACE_MISMATCH_FLOOR,
            "face_uncertain_floor": FACE_UNCERTAIN_FLOOR, "unread_identity_floor": UNREAD_IDENTITY_FLOOR,
        },
        formula="score = sum(component risk x weight) / sum(weights of components that ran)",
    )
