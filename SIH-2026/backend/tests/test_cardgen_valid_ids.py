import copy
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

CARDGEN = Path(__file__).resolve().parents[1] / "scripts" / "cardgen"
sys.path.insert(0, str(CARDGEN))

import generate  # noqa: E402
import valid_ids  # noqa: E402
from app.modules.ocr.indian_extractors import verhoeff_checksum  # noqa: E402
from app.modules.ocr.mrz_parser import parse_mrz  # noqa: E402

TODAY = date(2026, 9, 28)


def _d(s: str) -> date:
    return datetime.strptime(s, "%d/%m/%Y").date()


@pytest.fixture(scope="module")
def people():
    if not generate.XLSX.is_file():
        pytest.skip("workbook not present")
    rows = generate.build_people(generate.load_workbook_data(generate.XLSX))
    for p in rows:
        valid_ids.normalise_identifiers(p, today=TODAY)
    return rows


def test_aadhaar_numbers_are_verhoeff_valid_and_never_start_with_0_or_1(people):
    nums = [p["Aadhaar_Number"] for p in people if "Aadhaar_Number" in p]
    assert nums and all(len(n) == 12 and n[0] in "23456789" and verhoeff_checksum(n) for n in nums)


def test_pan_follows_individual_and_surname_rules(people):
    for p in people:
        pan = p.get("PAN_Number")
        if not pan:
            continue
        surname = p.get("Passport_Surname") or p.get("Last Name")
        assert re.fullmatch(r"[A-Z]{3}P[A-Z]\d{4}[A-Z]", pan)
        assert pan[4] == surname[0].upper()


def test_every_mrz_passes_all_check_digits_and_no_passport_is_expired(people):
    for p in people:
        if "Passport_MRZ_Line_2" not in p:
            continue
        mrz = parse_mrz(p["Passport_MRZ_Line_1"] + "\n" + p["Passport_MRZ_Line_2"])
        assert mrz.all_checks_pass, p["serial"]
        assert _d(p["Passport_Date_Of_Expiry"]) > TODAY
        assert mrz.date_of_expiry == _d(p["Passport_Date_Of_Expiry"]).isoformat()


def test_driving_licences_issued_at_18_or_later_and_number_matches_year(people):
    for p in people:
        if "DL_Number" not in p:
            continue
        issue, dob = _d(p["Date_Of_Issue"]), _d(p["DOB"])
        assert issue >= valid_ids._add_years(dob, 18)
        assert _d(p["Validity_NT"]) > issue
        assert p["DL_Number"][5:9] == str(issue.year)
        assert re.fullmatch(r"DL-\d{2}(19|20)\d{2}\d{7}", p["DL_Number"])


def test_generation_is_deterministic(people):
    raw = generate.build_people(generate.load_workbook_data(generate.XLSX))[0]
    a, b = copy.deepcopy(raw), copy.deepcopy(raw)
    valid_ids.normalise_identifiers(a, today=TODAY)
    valid_ids.normalise_identifiers(b, today=TODAY)
    assert a == b
