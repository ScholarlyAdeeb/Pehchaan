"""
Validates the ICAO 9303 check-digit implementation against the standard
worked example published in ICAO Doc 9303 Part 4 (Anna Maria Eriksson,
Utopia passport). If these assertions pass, the check-digit math is
provably correct — this is the one module in the whole system that has an
objective right answer.
"""
from app.modules.ocr.mrz_parser import compute_check_digit, parse_mrz

# The canonical ICAO Doc 9303 Part 4 worked example (Anna Maria Eriksson,
# fictional country "Utopia"), reproduced widely across MRZ-parsing
# libraries and reference implementations. Line 1 is padded to the fixed
# TD3 width (44 chars) programmatically to avoid hand-counting errors;
# line 2 (also 44 chars) includes a populated optional/personal-number
# field ("ZE184226B") and its own check digit, followed by the composite
# check digit for the whole line — every check digit below was verified
# against this implementation's `compute_check_digit`, which itself
# implements the published ICAO 9303 weight-7-3-1 / letter-value algorithm.
ICAO_SAMPLE_LINE_1 = "P<UTOERIKSSON<<ANNA<MARIA".ljust(44, "<")
assert len(ICAO_SAMPLE_LINE_1) == 44

ICAO_SAMPLE_LINE_2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
assert len(ICAO_SAMPLE_LINE_2) == 44


def test_compute_check_digit_known_values():
    # Passport number "L898902C3" -> check digit 6 (ICAO worked example)
    assert compute_check_digit("L898902C3") == 6
    # DOB "740812" -> check digit 2
    assert compute_check_digit("740812") == 2
    # Expiry "120415" -> check digit 9
    assert compute_check_digit("120415") == 9


def test_parse_mrz_icao_sample_is_valid():
    raw_text = ICAO_SAMPLE_LINE_1 + "\n" + ICAO_SAMPLE_LINE_2
    result = parse_mrz(raw_text)

    assert result.detected is True
    assert result.format == "TD3"
    assert result.issuing_country == "UTO"
    assert result.surname == "ERIKSSON"
    assert result.given_names == "ANNA MARIA"
    assert result.date_of_birth == "1974-08-12"
    assert result.date_of_expiry == "2012-04-15"
    assert result.composite_valid is True

    field_by_name = {f.name: f for f in result.fields}
    assert field_by_name["passport_number"].valid is True
    assert field_by_name["date_of_birth"].valid is True
    assert field_by_name["date_of_expiry"].valid is True


def test_parse_mrz_detects_tampered_expiry():
    """Flip one digit of the expiry date without updating its check digit —
    the parser must catch the mismatch, simulating a tampered document."""
    tampered_line_2 = ICAO_SAMPLE_LINE_2.replace("120415", "129415", 1)
    raw_text = ICAO_SAMPLE_LINE_1 + "\n" + tampered_line_2

    result = parse_mrz(raw_text)
    field_by_name = {f.name: f for f in result.fields}
    assert field_by_name["date_of_expiry"].valid is False


def test_parse_mrz_missing_block_returns_not_detected():
    result = parse_mrz("This is just a random block of unrelated OCR text.")
    assert result.detected is False
