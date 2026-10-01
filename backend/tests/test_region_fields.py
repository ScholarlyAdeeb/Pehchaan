from app.modules.ocr.region_fields import RegionRead, assess_layout, merge_region_fields


def _read(cls, text, ocr=90.0, det=0.99):
    return RegionRead(cls, text, ocr, det, {"x": 0, "y": 0, "w": 10, "h": 10})


# enough correctly read boxes for the layout to be recognised
PAN_CARD = [_read("name", "Geeta Sharma"), _read("guardian_name", "Sunil Kumar Sharma"),
            _read("date_of_birth", "17/04/1980")]
PASSPORT_PAGE = [_read("date_of_birth", "17/04/1980"), _read("date_of_issue", "26/11/2020"),
                 _read("date_of_expiry", "25/11/2030"), _read("nationality", "IND"), _read("gender", "F")]


def test_region_reads_fill_fields_the_page_reading_missed():
    reads = PAN_CARD + [_read("document_number", "WALPS8654H")]
    fields, sources = merge_region_fields("pan", {"pan_valid": False}, reads)
    assert fields["id_number"] == "WALPS8654H" and fields["pan_valid"] is True
    assert fields["name"] == "Geeta Sharma" and fields["father_name"] == "Sunil Kumar Sharma"
    assert fields["date_of_birth"] == "1980-04-17"
    assert set(sources.values()) == {"region"}


def test_lookalike_characters_are_fixed_by_position_only():
    # PAN is 5 letters, 4 digits, 1 letter: O in the digit block is a zero, 5 in the letter block is an S
    fields, _ = merge_region_fields("pan", {}, PAN_CARD + [_read("document_number", "WALP5 86O4H")])
    assert fields["id_number"] == "WALPS8604H"


def test_a_reading_that_does_not_parse_is_ignored():
    reads = [_read("name", "Geeta Sharma"), _read("gender", "FEMALE"), _read("address", "FLAT NO-352 11TH FLOOR, Mumbai"),
             _read("document_number", "3121 5344 4495"), _read("document_number", "3121 5344 4495"),
             _read("date_of_birth", "31/02/1980")]  # no such date
    fields, sources = merge_region_fields("aadhar", {}, reads)
    assert "date_of_birth" not in fields and fields["id_number"] == "3121 5344 4495"


def test_confident_region_reading_replaces_a_wrong_page_value():
    page = {"passport_number_visual": "F7807430", "surname": "INDX", "given_name": "Geeta", "name": "Geeta INDX"}
    reads = PASSPORT_PAGE + [_read("document_number", "O2453770"), _read("surname", "Sharma"), _read("name", "Geeta")]
    fields, sources = merge_region_fields("passport", page, reads)
    assert fields["passport_number_visual"] == "O2453770"
    assert fields["surname"] == "Sharma" and fields["name"] == "Geeta Sharma"
    assert sources["given_name"] == "page+region" and sources["surname"] == "region"


def test_unsure_region_reading_does_not_override_a_valid_page_value():
    page = {"passport_number_visual": "O2453770"}
    reads = PASSPORT_PAGE + [_read("document_number", "Q2453770", ocr=45.0)]
    fields, sources = merge_region_fields("passport", page, reads)
    assert fields["passport_number_visual"] == "O2453770" and "passport_number_visual" not in sources


def test_driving_licence_dates_and_number():
    reads = [_read("document_number", "DL-0120220653097"), _read("date_of_issue", "05/05/2022"),
             _read("date_of_issue", "05/05/2022"), _read("date_of_expiry", "04/05/2032")]
    fields, _ = merge_region_fields("driving_license", {}, reads)
    assert fields["license_number"] == "DL0120220653097" and fields["issuing_state"] == "DL"
    assert fields["issue_date"] == "2022-05-05" and fields["valid_till"] == fields["expiry_date"] == "2032-05-04"


def test_unfamiliar_layout_is_not_trusted_however_confident_the_detector_is():
    # what the detector returned on an older-style passport: confident boxes on the wrong text
    reads = [_read("date_of_birth", "2/05/2023", det=0.999), _read("gender", "F"), _read("document_number", "SPECIMEN"),
             _read("gender", "Surat"), _read("name", "INDIAN"), _read("document_number", "02453770"),
             _read("name", "Geeta"), _read("date_of_expiry", "22/05/2033"), _read("date_of_expiry", "17/04/1980"),
             _read("document_number", "REPUBLIC OF INDIA"), _read("name", "Mumbai"), _read("name", "Sharma"),
             _read("guardian_name", "IND"), _read("date_of_birth", "Mumbai"), _read("gender", "P")]
    ok, note = assess_layout("passport", reads)
    assert not ok and "unfamiliar card layout" in note
    page = {"date_of_birth": "1980-04-17", "expiry_date": "2033-05-22", "given_name": "Geeta"}
    assert merge_region_fields("passport", page, reads) == (page, {})


def test_known_layout_is_recognised_and_other_document_types_are_not():
    assert assess_layout("passport", PASSPORT_PAGE)[0]
    assert not assess_layout("visa", PASSPORT_PAGE)[0]
    assert not assess_layout("passport", PASSPORT_PAGE[:2])[0]  # too little to judge
