from app.modules.ocr.mrz_parser import parse_mrz
from app.modules.validation.rules_engine import validate_generic, validate_passport

_LINE_1 = "P<UTOERIKSSON<<ANNA<MARIA".ljust(44, "<")
_LINE_2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def test_validate_passport_all_checksums_pass_only_expiry_flagged():
    """
    This document's MRZ checksums (document number, DOB, expiry, personal
    number, and the overall composite) are all internally consistent — i.e.
    nothing here looks tampered. The *only* issue should be that the
    document's expiry date (2012-04-15) is genuinely in the past relative to
    whenever this test runs, which is a real expiry, not a forgery signal.
    That distinction (tampered vs. merely expired) is exactly what the
    validation module is supposed to surface separately.
    """
    mrz = parse_mrz(_LINE_1 + "\n" + _LINE_2)
    assert mrz.all_checks_pass is True

    result = validate_passport(mrz, visual_name="ANNA MARIA ERIKSSON")
    codes = {i.code for i in result.issues}
    assert codes == {"DOCUMENT_EXPIRED", "UNRECOGNIZED_NATIONALITY_CODE"}
    assert result.critical_count == 1  # expiry only — no checksum/tamper flags


def test_validate_passport_flags_name_mismatch():
    mrz = parse_mrz(_LINE_1 + "\n" + _LINE_2)
    result = validate_passport(mrz, visual_name="JOHN COMPLETELY DIFFERENT")
    codes = {i.code for i in result.issues}
    assert "NAME_MISMATCH_MRZ_VS_VISUAL" in codes
    assert result.critical_count >= 1


def test_validate_generic_missing_required_field():
    result = validate_generic("visa", {"visa_number": "V123456"})
    codes = {i.code for i in result.issues}
    assert "MISSING_FIELD_VISA_TYPE" in codes


def test_validate_generic_issue_after_expiry_is_critical():
    result = validate_generic(
        "visa",
        {
            "visa_number": "V1",
            "visa_type": "Tourist",
            "issue_date": "2025-01-01",
            "expiry_date": "2024-01-01",
        },
    )
    codes = {i.code for i in result.issues}
    assert "ISSUE_AFTER_EXPIRY" in codes
    assert result.critical_count >= 1
