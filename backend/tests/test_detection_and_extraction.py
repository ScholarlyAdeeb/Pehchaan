from app.modules.classification.auto_detect import decide
from app.modules.ocr.indian_extractors import extract_aadhaar_fields, extract_pan_fields
from app.modules.ocr.mrz_parser import compute_check_digit, parse_mrz
from app.modules.records import crosscheck
from app.storage import file_store

PAN_OCR = """INCOME TAX DEPARTMENT PERMANENT ACCOUNT NUMBER
Name / ary
Ritu Kumar
Father's Name / fat =r art
Anil Singh Kumar
Date of Birth (ore Tarr Signature
16/07/1961
Permanent Account Number .
ZIUBV5209Q a >"""

AADHAAR_OCR = """Govemment of nia
AADHAAR
Name (art
Anil Kumar
Date of Birth (arate Gender / tar
29/11/1958 MALE"""


def test_text_evidence_overrides_classifier_for_unknown_class():
    d = decide({"aadhar": 0.7, "pan": 0.2, "passport": 0.1}, "UNION OF INDIA DRIVING LICENCE\nMH12 20110012345")
    assert d.detected_type == "driving_license"
    assert d.method == "text"


def test_classifier_and_text_agree():
    d = decide({"aadhar": 0.01, "pan": 0.98, "passport": 0.01}, PAN_OCR)
    assert d.detected_type == "pan" and d.method == "classifier+text"


def test_low_confidence_without_text_is_flagged_for_manual_confirmation():
    d = decide({"aadhar": 0.4, "pan": 0.35, "passport": 0.25}, "illegible")
    assert "Confirm manually" in d.reason


def test_pan_fields_with_value_below_label():
    f = extract_pan_fields(PAN_OCR)
    assert f["id_number"] == "ZIUBV5209Q"
    assert f["name"] == "Ritu Kumar"
    assert f["father_name"] == "Anil Singh Kumar"
    assert f["date_of_birth"] == "1961-07-16"


def test_aadhaar_fields_skip_noise_lines():
    f = extract_aadhaar_fields(AADHAAR_OCR)
    assert f["name"] == "Anil Kumar"
    assert f["date_of_birth"] == "1958-11-29"
    assert f["gender"] == "Male"


def _td3(number="O2453770", dob="800417", expiry="330522", printed_number=None):
    doc = number.ljust(9, "<")
    personal = "<" * 14
    cds = [compute_check_digit(doc), compute_check_digit(dob), compute_check_digit(expiry), compute_check_digit(personal)]
    comp = compute_check_digit(f"{doc}{cds[0]}{dob}{cds[1]}{expiry}{cds[2]}{personal}{cds[3]}")
    shown = (printed_number or number).ljust(9, "<")
    return "P<INDSHARMA<<GEETA<<<<<<<<<<<EEDDC\n" + f"{shown}{cds[0]}IND{dob}{cds[1]}F{expiry}{cds[2]}{personal}{cds[3]}{comp}"


def test_mrz_resolves_o_zero_confusion_only_when_check_digit_confirms():
    mrz = parse_mrz(_td3(printed_number="02453770"))
    assert mrz.all_checks_pass
    assert mrz.fields[0].value.startswith("O2453770")
    assert mrz.given_names == "GEETA"  # trailing C/E/D noise treated as filler


def test_mrz_birth_and_expiry_centuries():
    mrz = parse_mrz(_td3())
    assert mrz.date_of_birth == "1980-04-17"
    assert mrz.date_of_expiry == "2033-05-22"


def test_records_crosscheck_detects_same_number_different_holder(monkeypatch):
    monkeypatch.setattr(crosscheck.get_settings(), "DATABASE_URL", None)
    file_store.save_scan({"identity": {"document_number": "TEST9001", "name": "GEETA SHARMA",
                                       "date_of_birth": "1980-04-17"}, "risk": {"verdict": "CLEAR"}})
    same = crosscheck.check_against_records("TEST9001", "Geeta Sharma", "1980-04-17")
    assert same.status == "consistent" and same.risk == 0
    clash = crosscheck.check_against_records("TEST9001", "Rakesh Verma", "1977-03-09")
    assert clash.status == "conflict" and clash.risk == 100
    assert {i.code for i in clash.issues} == {"RECORD_NAME_CONFLICT", "RECORD_DOB_CONFLICT"}
