from app.modules.face.verifier import FaceMatchResult
from app.modules.records.crosscheck import RecordCheckResult
from app.modules.risk.risk_engine import OVERRIDE_FLOOR, compute_risk
from app.modules.tampering.tampering_engine import TamperingResult
from app.modules.validation.rules_engine import ValidationIssue, _finalize


def _validation(*severities):
    return _finalize([ValidationIssue(f"X{i}", "m", s) for i, s in enumerate(severities)], checks_run=5)


def _face(sim, decision):
    return FaceMatchResult(similarity=sim, is_match=decision == "match", backend="t", document_face_found=True,
                           live_face_found=True, decision=decision, match_threshold=0.30, mismatch_threshold=0.18)


def _tampering(score, verdict="clean"):
    return TamperingResult(tampering_score=score, verdict=verdict)


def test_clean_document_without_selfie_uses_only_validation_and_tampering():
    report = compute_risk(_validation(), _tampering(10))
    applicable = {c.key: c for c in report.components if c.applicable}
    assert set(applicable) == {"validation", "tampering"}
    # weights 0.30 and 0.35 renormalised over 0.65
    assert abs(applicable["validation"].effective_weight - 0.30 / 0.65) < 1e-3
    assert report.risk_score == round(10 * 0.35 / 0.65)
    assert report.verdict == "CLEAR"


def test_components_sum_to_weighted_score():
    face = _face(0.25, "uncertain")
    records = RecordCheckResult(status="consistent", source="t", document_number="X1", risk=0, summary="ok")
    report = compute_risk(_validation("warning"), _tampering(30, "suspicious"), face, records)
    total = sum(c.contribution for c in report.components if c.applicable)
    assert abs(total - report.weighted_score) < 0.05
    assert abs(sum(c.effective_weight for c in report.components if c.applicable) - 1.0) < 1e-3


def test_critical_issue_forces_floor_even_when_everything_else_is_clean():
    report = compute_risk(_validation("critical"), _tampering(0))
    assert report.risk_score == OVERRIDE_FLOOR
    assert report.verdict == "REJECT"
    assert report.overrides


def test_records_conflict_forces_floor():
    records = RecordCheckResult(status="conflict", source="t", document_number="X1", risk=100, summary="c")
    report = compute_risk(_validation(), _tampering(0), None, records)
    assert report.risk_score >= OVERRIDE_FLOOR
    assert report.verdict == "REJECT"


def test_no_history_record_check_is_left_out_of_score():
    records = RecordCheckResult(status="no_history", source="t", document_number="X1", risk=None, summary="first")
    report = compute_risk(_validation(), _tampering(0), None, records)
    rec = next(c for c in report.components if c.key == "records")
    assert rec.applicable is False and rec.contribution == 0


def test_face_mismatch_forces_high_risk_even_on_a_clean_document():
    report = compute_risk(_validation(), _tampering(5), _face(0.12, "mismatch"))
    assert report.risk_score >= 85 and report.verdict == "REJECT"


def test_face_far_below_mismatch_line_forces_90():
    report = compute_risk(_validation(), _tampering(5), _face(0.03, "mismatch"))
    assert report.risk_score >= 90


def test_inconclusive_face_cannot_be_cleared():
    report = compute_risk(_validation(), _tampering(0), _face(0.25, "uncertain"))
    assert report.verdict == "REVIEW"


def test_face_match_keeps_clean_document_clear():
    report = compute_risk(_validation(), _tampering(5), _face(0.8, "match"))
    assert report.verdict == "CLEAR"
