"""OCR misreads in the MRZ should ask for a rescan, not flag the traveller
(invented holder throughout)."""
from app.modules.ocr.mrz_parser import compute_check_digit, parse_mrz, reconcile_name_with_print
from app.modules.records.crosscheck import PriorRecord
from app.modules.records import crosscheck
from app.modules.validation.rules_engine import validate_passport


def _line2(number="K1234567<", dob="900215", expiry="320614", personal="20481937551203") -> str:
    head = f"{number}{compute_check_digit(number)}IND{dob}{compute_check_digit(dob)}M{expiry}{compute_check_digit(expiry)}"
    body = f"{personal}{compute_check_digit(personal)}"
    line = head + body
    composite = line[0:10] + line[13:20] + line[21:43]
    return line + str(compute_check_digit(composite))


LINE1 = "P<INDMEHRA<<ROHAN<VIKRAM" + "<" * 20
GOOD = _line2()
VISUAL = {"date_of_birth": "1990-02-15", "expiry_date": "2032-06-14", "passport_number_visual": "K1234567"}


def _scan(line2: str, line1: str = LINE1, printed: dict | None = None):
    return parse_mrz(f"REPUBLIC OF INDIA\n{line1}\n{line2}", printed)


def test_genuine_mrz_still_passes():
    assert _scan(GOOD).all_checks_pass


def test_misread_date_digit_is_repaired_when_the_printed_date_agrees():
    # second digit of the birth year (0) read as 6.
    bad = GOOD[:14] + "6" + GOOD[15:]
    mrz = _scan(bad, printed={"date_of_birth": "1990-02-15"})
    assert mrz.all_checks_pass and mrz.date_of_birth == "1990-02-15"
    assert any("matches the printed date of birth" in w for w in mrz.warnings)


def test_no_repair_without_an_agreeing_printed_date():
    # Check digits alone accept a wrong 'fix' for many misreads.
    bad = GOOD[:14] + "6" + GOOD[15:]
    assert not _scan(bad).all_checks_pass
    assert not _scan(bad, printed={"date_of_birth": "1996-02-15"}).all_checks_pass


def test_unrepairable_optional_field_asks_for_rescan_not_high_risk():
    # Two characters garbled: no single fix exists, so the line is left as read.
    bad = GOOD[:30] + "77" + GOOD[32:]
    mrz = _scan(bad)
    assert not mrz.all_checks_pass
    v = validate_passport(mrz, visual_name="ROHAN VIKRAM MEHRA", extracted_fields=VISUAL)
    assert v.critical_count == 0
    codes = {i.code for i in v.issues}
    assert {"MRZ_CHECKSUM_PERSONAL_NUMBER", "MRZ_COMPOSITE_CHECKSUM"} <= codes


def test_altered_date_of_birth_stays_critical():
    bad = GOOD[:13] + "910215" + GOOD[19:]  # year changed, check digit not recomputed
    mrz = _scan(bad)
    v = validate_passport(mrz, visual_name="ROHAN VIKRAM MEHRA", extracted_fields=VISUAL)
    assert v.critical_count >= 1


def test_doubled_letter_in_mrz_name_follows_the_printed_page():
    assert reconcile_name_with_print("ROHAN VVIKRAM MEHRA", "MEHRA ROHAN VIKRAM") == "ROHAN VIKRAM MEHRA"
    assert reconcile_name_with_print("ROHAN VIKRAM MEHRA", "SURESH NAIR") == "ROHAN VIKRAM MEHRA"


def test_unreviewed_system_flags_do_not_count_as_history(monkeypatch):
    prior = [PriorRecord("SCN-1", "ROHAN VIKRAM MEHRA", "1990-02-15", "HIGH RISK", None, None)]
    monkeypatch.setattr(crosscheck, "_fetch_from_memory", lambda doc: prior)
    monkeypatch.setattr(crosscheck.get_settings(), "DATABASE_URL", "", raising=False)
    r = crosscheck.check_against_records("K1234567", "ROHAN VIKRAM MEHRA", "1990-02-15")
    assert r.status == "consistent" and r.risk == 0
    assert any(i.code == "RECORD_PRIOR_UNREVIEWED_FLAG" for i in r.issues)

    prior[0].officer_decision = "reject"
    r = crosscheck.check_against_records("K1234567", "ROHAN VIKRAM MEHRA", "1990-02-15")
    assert r.status == "flagged_history" and r.risk == 50


def test_edited_date_is_never_repaired_even_when_the_print_agrees():
    # Forger changed the birth year on both the page and the MRZ but left the check digit.
    bad = GOOD[:13] + "91" + GOOD[15:]
    mrz = _scan(bad, printed={"date_of_birth": "1991-02-15"})
    assert not mrz.all_checks_pass
