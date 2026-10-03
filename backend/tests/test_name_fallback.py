"""Finding the holder's name wherever it sits on a card (invented people throughout)."""
from app.modules.ocr.field_extractors import extract_fields
from app.modules.ocr.name_finder import find_name

# OCR text shaped like a real Aadhaar front: garbled Hindi, then the English
# name with a stray mark in front of it, then the date of birth.
AADHAAR_NOISY = """BTUs
a mere oréta arA
x Rahul Kumar Verma
S WA FfVDOB: 01/06/2006
3 qev MALE
Aadhaar Is proof of identity, not of citizenship"""

# A college identity card: no "Name" label, organisation lines around the name.
STUDENT_CARD = """(Formerly Delhi College of Engineering)
(Govt of NCT of Delhi)
RAHUL KUMAR VERMA
DTU/24/A17/045
B.Tech(EE)
Valid Upto :Jul 2024 to May 2028"""


def test_aadhaar_name_with_stray_mark_is_read():
    fields = extract_fields("aadhar", AADHAAR_NOISY)
    assert fields["name"] == "Rahul Kumar Verma"
    assert fields["date_of_birth"] == "2006-06-01"
    assert fields["gender"] == "Male"


def test_unlabelled_name_on_an_id_card_is_found():
    assert extract_fields("driving_license", STUDENT_CARD)["name"] == "RAHUL KUMAR VERMA"


def test_headings_are_not_taken_for_a_name():
    assert find_name("UNION OF INDIA\nDRIVING LICENCE\nTRANSPORT DEPARTMENT") is None
    assert find_name("Income Tax Department\nGovt of India") is None


def test_passport_never_uses_the_guess():
    # A passport's name comes from the MRZ and the labelled page only.
    assert "name" not in extract_fields("passport", "RAHUL KUMAR VERMA\nsome text")


def test_relatives_name_is_not_taken():
    text = "Father's Name\nSURESH KUMAR VERMA\nRAHUL KUMAR VERMA\nDOB: 01/06/2006"
    assert find_name(text).name == "RAHUL KUMAR VERMA"


def test_name_found_wherever_it_sits():
    # Name at the bottom of the card, after the number and the dates.
    text = "ID 4417 2208 9931\nIssued 12/03/2020\nValid till 11/03/2030\nPriya Sharma"
    assert find_name(text).name == "Priya Sharma"


def test_labelled_name_beats_an_unlabelled_one():
    text = "AMIT KUMAR SINGH\nName: Neha Gupta\nDOB: 02/02/2000"
    assert find_name(text).name == "Neha Gupta"
