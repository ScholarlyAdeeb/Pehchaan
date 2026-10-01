"""Tests for the real content that goes into the card holders.

The QR assertions go further than "something was drawn": the code is decoded
back with ``cv2.QRCodeDetector`` and compared to the payload, so a test fails if
the code stops being scannable - which is the whole reason for using a real
encoder instead of a barcode-shaped texture.

These need the harvested portraits, so they skip on a fresh clone: the face
cache lives under git-ignored ``sample-data``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts" / "cardgen"))

import codes  # noqa: E402
import faces  # noqa: E402
import fillers  # noqa: E402
import generate  # noqa: E402

FACE_CACHE = BACKEND_ROOT.parent / "sample-data" / "templates" / "_face_cache"
HAS_FACES = bool(list(FACE_CACHE.glob("face_*.jpg"))) if FACE_CACHE.is_dir() else False
HAS_CARDS = (BACKEND_ROOT.parent / "sample-data" / "templates" / "DL.jpeg").exists()

requires_faces = pytest.mark.skipif(not HAS_FACES, reason="portrait cache not harvested")
requires_cards = pytest.mark.skipif(not HAS_CARDS, reason="sample-data not present")


# --------------------------------------------------------------------------- #
# codes
# --------------------------------------------------------------------------- #
def test_pan_payload_is_the_pan_number():
    assert codes.pan_payload({"PAN_Number": "RAHEA3658E"}) == "RAHEA3658E"


def test_aadhaar_payload_carries_the_holder_fields():
    payload = codes.aadhaar_payload({
        "Aadhaar_Number": "103647216920", "Aadhaar_Name": "Neelu Kumar",
        "Aadhaar_DOB": "05/02/1977", "Aadhaar_Gender": "FEMALE",
    })
    assert '"uid":"103647216920"' in payload
    assert '"name":"Neelu Kumar"' in payload


def test_aadhaar_payload_stays_inside_a_readable_qr():
    """The address is excluded on purpose - see the codes module docstring.

    With it the payload encodes to version 9, which this build's detector
    cannot read, so the code would look fine and scan to nothing.
    """
    row = {
        "Aadhaar_Number": "103647216920", "Aadhaar_Name": "Vikram Singh Yadav",
        "Aadhaar_DOB": "05/02/1977", "Aadhaar_Gender": "FEMALE",
        "Aadhaar_Address": "FLAT NO-865 5TH FLOOR, SEC-97, Ahmedabad, PIN:918704, Gujarat, INDIA",
    }
    m = codes.qr_matrix(codes.aadhaar_payload(row))
    assert m is not None, "payload no longer fits a readable QR"
    assert m.shape[0] <= codes.MAX_MODULES + 2 * codes.QUIET_ZONE


def test_an_oversized_payload_is_refused_rather_than_emitted():
    """A code that cannot be read must not be drawn at all."""
    too_long = "X" * 400
    assert codes.qr_matrix(too_long) is None


def test_passport_has_no_qr_payload():
    assert codes.payload_for("passport", {"Passport_Number": "M3644328"}) == ""


def test_qr_matrix_is_black_and_white_with_a_quiet_zone():
    m = codes.qr_matrix("RAHEA3658E")
    assert m is not None
    assert set(np.unique(m)) <= {0, 255}
    # the quiet zone is a blank margin, so the outer border must be white
    assert (m[0] == 255).all() and (m[:, 0] == 255).all()
    # and there must actually be dark modules in the middle
    assert (m == 0).any()


def test_empty_payload_yields_no_matrix():
    assert codes.qr_matrix("") is None
    assert codes.qr_matrix("   ") is None


def test_generated_qr_decodes_back_to_its_payload():
    """The real check: round-trip the code through a decoder."""
    payload = "RAHEA3658E"
    canvas = np.full((400, 600, 3), 245, dtype=np.uint8)
    assert codes.draw_qr(canvas, (100, 60, 300, 300), payload, border=1)
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(canvas)
    assert decoded == payload


def test_aadhaar_qr_decodes_back_to_its_json():
    row = {
        "Aadhaar_Number": "103647216920", "Aadhaar_Name": "Neelu Kumar",
        "Aadhaar_DOB": "05/02/1977", "Aadhaar_Gender": "FEMALE",
        "Aadhaar_Address": "FLAT NO-865 5TH FLOOR, SEC-97, Ahmedabad",
    }
    payload = codes.aadhaar_payload(row)
    canvas = np.full((500, 500, 3), 255, dtype=np.uint8)
    assert codes.draw_qr(canvas, (20, 20, 460, 460), payload)
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(canvas)
    import json

    assert json.loads(decoded)["uid"] == "103647216920"


def test_draw_qr_declines_a_box_too_small_to_hold_a_code():
    canvas = np.full((200, 200, 3), 255, dtype=np.uint8)
    assert not codes.draw_qr(canvas, (0, 0, 6, 6), "RAHEA3658E")


def test_draw_qr_reports_failure_rather_than_raising():
    canvas = np.full((200, 200, 3), 255, dtype=np.uint8)
    assert not codes.draw_qr(canvas, (10, 10, 120, 120), "")


# --------------------------------------------------------------------------- #
# fitting
# --------------------------------------------------------------------------- #
def test_fit_face_covers_the_holder_exactly():
    face = np.zeros((300, 200, 3), dtype=np.uint8)
    out = fillers.fit_face(face, 150, 220)
    assert out.shape == (220, 150, 3)


def test_fit_face_survives_a_degenerate_face():
    assert fillers.fit_face(None, 40, 60).shape == (60, 40, 3)
    assert fillers.fit_face(np.zeros((0, 0, 3), dtype=np.uint8), 40, 60).shape == (60, 40, 3)
    assert fillers.fit_face(np.zeros((10, 10, 3), dtype=np.uint8), 0, 0).shape[0] >= 1


def test_paste_clips_a_patch_that_hangs_off_the_canvas():
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    patch = np.full((40, 40, 3), 200, dtype=np.uint8)
    fillers.paste(canvas, patch, (80, 80, 40, 40))
    assert canvas[95, 95].tolist() == [200, 200, 200]
    assert canvas[50, 50].tolist() == [0, 0, 0]


def test_paste_ignores_a_fully_off_canvas_box():
    canvas = np.zeros((50, 50, 3), dtype=np.uint8)
    fillers.paste(canvas, np.full((10, 10, 3), 255, np.uint8), (100, 100, 10, 10))
    assert canvas.max() == 0


def test_ghost_is_washed_out_relative_to_the_primary():
    face = np.full((100, 100, 3), 40, dtype=np.uint8)
    assert fillers._faded(face).mean() > face.mean()


# --------------------------------------------------------------------------- #
# the filled holders
# --------------------------------------------------------------------------- #
@requires_faces
def test_face_bank_returns_a_distinct_portrait_per_person():
    bank = faces.FaceBank()
    assert bank.available() >= 2
    a, b = bank.get(1), bank.get(2)
    assert a is not None and b is not None
    assert a.shape[0] > a.shape[1], "portraits should be upright"
    assert not np.array_equal(a, b), "two people got the same face"


@requires_faces
def test_fill_holders_places_a_face_and_a_code():
    bank = faces.FaceBank()
    canvas = np.full((579, 1000, 3), 250, dtype=np.uint8)
    row = {"serial": "1", "PAN_Number": "RAHEA3658E"}
    report = fillers.fill_holders(canvas, "pan", row, bank)
    assert report["photo"]["filled"] is True
    assert report["photo"]["source"] == "face_0001"
    assert report["qr"]["filled"] is True
    assert report["qr"]["payload"] == "RAHEA3658E"
    # the photo area must no longer be the flat fill it started as
    x, y, w, h = report["photo"]["bbox"].values()
    assert canvas[y:y + h, x:x + w].std() > 10


@requires_faces
def test_aadhaar_ghost_is_smaller_and_faded():
    bank = faces.FaceBank()
    canvas = np.full((1024, 768, 3), 250, dtype=np.uint8)
    row = {"serial": "1", "Aadhaar_Number": "103647216920", "Aadhaar_Name": "Neelu Kumar"}
    report = fillers.fill_holders(canvas, "aadhaar", row, bank)
    ghost, primary = report["ghost_photo"], report["photo"]
    assert ghost["filled"] and primary["filled"]
    assert ghost["faded"] is True and primary["faded"] is False
    assert ghost["bbox"]["w"] < primary["bbox"]["w"]
    assert report["qr"]["filled"] is True


@requires_faces
def test_passport_barcode_is_reported_as_unfilled_rather_than_faked():
    """No PDF417 encoder exists, so the holder must stay empty and say so."""
    bank = faces.FaceBank()
    canvas = np.full((1691, 1264, 3), 250, dtype=np.uint8)
    report = fillers.fill_holders(canvas, "passport", {"serial": "1"}, bank)
    assert report["photo"]["filled"] is True
    assert report["barcode"]["filled"] is False
    assert "no encoder" in report["barcode"]["note"]


@requires_faces
def test_missing_face_is_reported_not_silently_skipped():
    bank = faces.FaceBank()
    canvas = np.full((579, 1000, 3), 250, dtype=np.uint8)
    report = fillers.fill_holders(canvas, "driving_license", {"serial": "999999"}, bank)
    assert report["photo"]["filled"] is False


@requires_faces
@requires_cards
def test_end_to_end_card_carries_a_decodable_qr():
    """A real generated PAN card, decoded."""
    sheets = generate.load_workbook_data(generate.XLSX)
    person = generate.build_people(sheets)[0]
    renderer, _ = generate.prepare("pan", person)
    card = renderer.render(person)
    fillers.fill_holders(card, "pan", person, faces.FaceBank())
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(card)
    assert decoded == person["PAN_Number"]


@requires_faces
@requires_cards
def test_faces_match_across_card_types_for_one_person():
    """Person 1 must show the same portrait on their Aadhaar and their licence."""
    from app.modules.localization.photo_regions import regions_for

    sheets = generate.load_workbook_data(generate.XLSX)
    person = generate.build_people(sheets)[0]
    bank = faces.FaceBank()
    serial = int(person["serial"])
    source = bank.get(serial)
    assert source is not None

    seen = 0
    for doc in ("aadhar", "pan", "driving_license", "passport"):
        renderer, _ = generate.prepare(doc, person)
        card = renderer.render(person)
        fillers.fill_holders(card, renderer.region_key, person, bank)
        holder = next(
            r for r in regions_for(renderer.region_key)
            if r.is_portrait and r.kind == "photo"
        )
        x, y, w, h = holder.to_pixels(card.shape[1], card.shape[0])
        aperture = card[y:y + h, x:x + w]
        assert aperture.shape[:2] == (h, w)
        # the aperture must be exactly the source portrait fitted to it
        assert np.array_equal(aperture, fillers.fit_face(source, w, h))
        seen += 1
    assert seen == 4


# --------------------------------------------------------------------------- #
# the harvest itself
# --------------------------------------------------------------------------- #
@requires_faces
def test_photo_rect_finds_the_mounted_photograph():
    """The specimen template prints every portrait in the same place."""
    import json

    manifest = json.loads((FACE_CACHE / "faces.json").read_text(encoding="utf-8"))
    assert manifest["count"] >= 1
    assert not manifest["missed"], f"serials with no face: {manifest['missed'][:10]}"
    # every crop must be portrait, like a real ID photo
    for info in manifest["faces"].values():
        if "crop_size" in info:
            w, h = info["crop_size"]
            assert h > w, f"crop {w}x{h} is not portrait"
