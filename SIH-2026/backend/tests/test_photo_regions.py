"""Tests for the measured image-holder table and the dataset generator.

The holder coordinates were measured off photographic card scans, so the tests
that matter most are the ones that pin the *relationships* the measurements
imply - which holder sits where relative to the printed labels, and that the
PDF text layout really does put the PAN number above the holder's name.  A
mistake there is invisible in a unit test but obvious on the rendered card,
which is why ``preview_regions.py`` exists alongside these.

Tests that need ``sample-data`` skip when it is absent; that directory is
git-ignored, so a fresh clone has no card backgrounds to measure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

import cv2

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts" / "cardgen"))

from app.modules.localization.photo_regions import (  # noqa: E402
    CODE_KINDS,
    MEASURED_TYPES,
    PORTRAIT_KINDS,
    REGIONS,
    annotation,
    draw_regions,
    portraits_for,
    regions_for,
    validate,
)

SAMPLE_DATA = BACKEND_ROOT.parent / "sample-data"
HAS_CARDS = (SAMPLE_DATA / "templates").is_dir()

requires_cards = pytest.mark.skipif(
    not HAS_CARDS, reason="sample-data/templates not present"
)


# --------------------------------------------------------------------------- #
# the region table
# --------------------------------------------------------------------------- #
def test_table_covers_every_measured_type():
    assert set(REGIONS) == set(MEASURED_TYPES)


def test_validate_reports_no_problems():
    """Catches rects outside 0..1, inverted rects, and absurd aspect ratios."""
    assert validate() == []


def test_aadhaar_has_a_primary_and_a_ghost_portrait():
    names = [r.name for r in regions_for("aadhaar")]
    assert "photo" in names and "ghost_photo" in names
    # the ghost sits to the right of the primary photo
    primary, ghost = portraits_for("aadhaar")
    assert primary.name == "photo" and ghost.name == "ghost_photo"
    assert primary.bbox_norm[0] < ghost.bbox_norm[0]


def test_codes_are_never_mistaken_for_portraits():
    for doc, regions in REGIONS.items():
        for r in regions:
            assert not (r.is_code and r.is_portrait), f"{doc}/{r.name}"
            assert r.kind in PORTRAIT_KINDS | CODE_KINDS, f"{doc}/{r.name}"


def test_driving_license_photo_is_on_the_right():
    """The DL card is the one layout with the portrait on the right."""
    (photo,) = [r for r in regions_for("driving_license") if r.is_portrait]
    assert photo.bbox_norm[0] > 0.5


def test_pan_qr_is_square_and_right_of_the_photo():
    pan = {r.name: r for r in regions_for("pan")}
    assert set(pan) == {"photo", "qr"}
    # Aspect must be judged in pixels, not in normalised units: the PAN page is
    # 768x517, so a square QR comes out as a non-square normalised box.
    _, _, w, h = pan["qr"].to_pixels(768, 517)
    assert 0.85 < w / h < 1.15
    assert pan["photo"].bbox_norm[0] < pan["qr"].bbox_norm[0]


def test_passport_codes_a_pdf417_barcode_not_a_qr():
    kinds = {r.kind for r in regions_for("passport")}
    assert "barcode" in kinds
    assert "qr" not in kinds


@pytest.mark.parametrize("doc", MEASURED_TYPES)
def test_to_pixels_is_monotonic_and_in_bounds(doc):
    width, height = 1200, 800
    for r in regions_for(doc):
        x, y, w, h = r.to_pixels(width, height)
        assert 0 <= x < width and 0 <= y < height
        assert w > 0 and h > 0
        assert x + w <= width and y + h <= height


def test_to_pixels_scales_with_the_page():
    r = regions_for("pan")[0]
    small = r.to_pixels(768, 517)
    large = r.to_pixels(1536, 1034)
    assert large[0] == pytest.approx(small[0] * 2, abs=2)
    assert large[2] == pytest.approx(small[2] * 2, abs=2)


def test_draw_regions_marks_the_image_and_leaves_a_copy_alone():
    blank = np.full((400, 600, 3), 200, dtype=np.uint8)
    drawn = draw_regions(blank, "pan", copy=True)
    assert not np.array_equal(drawn, blank)
    assert np.array_equal(blank, np.full((400, 600, 3), 200, dtype=np.uint8))
    # a type with no measured card is a no-op rather than an error
    assert np.array_equal(draw_regions(blank, "permit", copy=True), blank)


def test_draw_regions_accepts_greyscale():
    gray = np.full((300, 400), 128, dtype=np.uint8)
    assert draw_regions(gray, "aadhaar", copy=True).ndim == 3


def test_annotation_payload_is_serialisable_and_sized():
    payload = annotation("passport", 1264, 1691)
    assert payload["image_width"] == 1264 and payload["image_height"] == 1691
    assert payload["document_type"] == "passport"
    photo = next(r for r in payload["regions"] if r["name"] == "photo")
    x, y, w, h = photo["bbox"].values()
    assert w > 0 and h > 0 and x + w <= 1264 and y + h <= 1691


# --------------------------------------------------------------------------- #
# the generated dataset
# --------------------------------------------------------------------------- #
generate = pytest.importorskip("generate")


def test_age_from_dob():
    from datetime import date

    assert generate.age_from_dob("05/02/1977", date(2026, 9, 28)) == 49
    assert generate.age_from_dob("29/02/2000", date(2026, 9, 28)) == 26
    assert generate.age_from_dob("not a date") is None
    assert generate.age_from_dob("31/02/1977") is None  # impossible date


def test_sex_from_gender():
    assert generate.sex_from_gender("FEMALE") == "F"
    assert generate.sex_from_gender("MALE") == "M"
    assert generate.sex_from_gender("", "F") == "F"
    assert generate.sex_from_gender("", "") is None


def test_state_from_address():
    assert generate.state_from_address(
        "FLAT NO-348 4TH FLOOR, Chennai, PIN:913577, Tamil Nadu, INDIA"
    ) == "Tamil Nadu"
    assert generate.state_from_address("SECTOR 45, DELHI, PIN:171621") == "Delhi"
    assert generate.state_from_address("") is None


def test_split_label_splits_a_printed_prefix():
    assert generate._split_label("DOB: 05/02/1977") == ("DOB:", "05/02/1977")
    assert generate._split_label("05/02/1977") == ("", "05/02/1977")


def test_norm_collapses_whitespace_and_nbsp():
    assert generate._norm("  Neelu\tKumar \u00a0 ") == "Neelu Kumar"


def test_wrap_text_respects_the_line_budget():
    from PIL import ImageFont

    font = ImageFont.truetype(str(Path(r"C:\Windows\Fonts\arial.ttf")), 16)
    value = "FLAT NO-348 4TH FLOOR, SEC-83, CHENNAI, PIN:913577, TAMIL NADU, INDIA"
    lines = generate.wrap_text(value, font, max_width=200, max_lines=3)
    assert 1 <= len(lines) <= 3
    # Every line but the last fits the budget.  The last is allowed to overflow:
    # on a card, showing an overlong value beats silently dropping half of it.
    assert all(font.getlength(line) <= 200 for line in lines[:-1])
    # nothing may be silently dropped
    assert " ".join(lines).split() == value.split()


def test_wrap_text_never_exceeds_max_lines_even_for_long_input():
    from PIL import ImageFont

    font = ImageFont.truetype(str(Path(r"C:\Windows\Fonts\arial.ttf")), 16)
    value = "word " * 200
    assert len(generate.wrap_text(value, font, max_width=120, max_lines=3)) <= 3


def test_consistency_issues_flags_a_name_mismatch():
    person = {
        "serial": "9", "Name": "Asha Rao", "PAN_Name": "Asha Rau",
        "Aadhaar_Name": "Asha Rao", "Passport_Given_Name": "Asha",
        "DOB": "01/01/1980", "PAN_DOB": "01/01/1980", "Aadhaar_DOB": "01/01/1980",
        "Aadhaar_Gender": "FEMALE", "Passport_Sex": "F",
    }
    assert any("name mismatch" in i for i in generate.consistency_issues(person))


def test_consistency_issues_flags_gender_sex_disagreement():
    person = {
        "serial": "9", "Name": "Asha Rao", "DOB": "01/01/1980",
        "Aadhaar_Gender": "MALE", "Passport_Sex": "F",
    }
    assert any("vs passport sex" in i for i in generate.consistency_issues(person))


def test_consistency_issues_flags_an_implausible_age():
    person = {"serial": "9", "DOB": "01/01/1910", "Aadhaar_Gender": "MALE", "Passport_Sex": "M"}
    assert any("implausible age" in i for i in generate.consistency_issues(person))


def test_consistency_issues_quiet_on_a_coherent_row():
    person = {
        "serial": "1", "Name": "Neelu Kumar", "PAN_Name": "Neelu Kumar",
        "Aadhaar_Name": "Neelu Kumar", "Passport_Given_Name": "Neelu",
        "Passport_Surname": "Kumar", "DOB": "05/02/1977", "PAN_DOB": "05/02/1977",
        "Aadhaar_DOB": "05/02/1977", "Aadhaar_Gender": "FEMALE", "Passport_Sex": "F",
    }
    assert generate.consistency_issues(person) == []


def test_group_runs_keeps_widely_separated_cells_apart():
    """Two fields on one baseline must not fuse into one unmatchable blob."""
    runs = [
        {"text": "P", "x": 100.0, "y": 50.0, "size": 12.0, "color": [0, 0, 0], "font": "F1"},
        {"text": "IND", "x": 260.0, "y": 50.2, "size": 12.0, "color": [0, 0, 0], "font": "F1"},
    ]
    lines = generate.group_runs(runs)
    assert len(lines) == 2
    assert lines[0].text.strip() == "P" and lines[1].text.strip() == "IND"


def test_group_runs_merges_adjacent_fragments_of_one_value():
    runs = [
        {"text": "FLAT NO", "x": 100.0, "y": 50.0, "size": 12.0, "color": [0, 0, 0], "font": "F1"},
        {"text": "-865", "x": 145.0, "y": 50.1, "size": 12.0, "color": [0, 0, 0], "font": "F1"},
    ]
    lines = generate.group_runs(runs)
    assert len(lines) == 1
    assert lines[0].text == "FLAT NO-865"


def test_group_runs_can_filter_to_value_fonts():
    runs = [
        {"text": "kept", "x": 10.0, "y": 5.0, "size": 10.0, "color": [0, 0, 0], "font": "C2_1"},
        {"text": "label", "x": 10.0, "y": 40.0, "size": 10.0, "color": [0, 0, 0], "font": "T1_2"},
    ]
    lines = generate.group_runs(runs, value_fonts=("C2_0", "C2_1"))
    assert [l.text for l in lines] == ["kept"]


# --------------------------------------------------------------------------- #
# the extracted PDF layout - this is what pins the image row order
# --------------------------------------------------------------------------- #
@requires_cards
def test_pan_layout_puts_the_pan_number_above_the_name():
    """Guards the vertical flip in ``extract_layouts``.

    If the image's row order is read the wrong way round, these four runs come
    out in reverse - date of birth at the top, PAN number at the bottom - which
    is obviously wrong on a PAN card and silent in every other test.
    """
    import json

    from extract_layouts import LAYOUT_DIR

    layout = json.loads((LAYOUT_DIR / "pan.json").read_text(encoding="utf-8"))
    runs = {r["text"].strip(): r for r in layout["runs"] if r["text"].strip()}
    pan_no = runs["RAHEA3658E"]
    name = runs["Neelu Kumar"]
    father = runs["Vikram Singh Kumar"]
    dob = runs["05/02/1977"]
    assert pan_no["y"] < name["y"] < father["y"] < dob["y"]
    # and the whole card is 517 px tall
    assert layout["image_size"] == [768, 517]


@requires_cards
def test_extracted_sizes_are_plausible_pixel_sizes():
    """Font sizes must be in image pixels, not PDF points.

    Reporting them raw makes every string render about 1.5x too small, which
    looks like a font choice rather than a units bug.
    """
    import json

    from extract_layouts import LAYOUT_DIR

    for name in ("pan", "aadhaar", "driving_license"):
        layout = json.loads((LAYOUT_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert layout["runs"], name
        for r in layout["runs"]:
            assert 8.0 <= r["size"] <= 60.0, f"{name}: {r['size']} px looks wrong"


@requires_cards
def test_every_layout_run_sits_on_its_card():
    """Off-card page furniture must already have been dropped by the extractor.

    The DL page writes a stray ``RTO Delhi`` into the white space above the
    card; the generator would clip it, so the extractor discards runs outside
    the background and counts them.
    """
    import json

    from extract_layouts import LAYOUT_DIR

    for name in ("pan", "aadhaar", "driving_license"):
        layout = json.loads((LAYOUT_DIR / f"{name}.json").read_text(encoding="utf-8"))
        w, h = layout["image_size"]
        for r in layout["runs"]:
            assert 0 <= r["x"] <= w, f"{name}: x={r['x']}"
            assert 0 <= r["y"] <= h, f"{name}: y={r['y']}"


@requires_cards
def test_driving_license_layout_records_the_dropped_stray_run():
    import json

    from extract_layouts import LAYOUT_DIR

    layout = json.loads((LAYOUT_DIR / "driving_license.json").read_text(encoding="utf-8"))
    assert layout["off_card_runs_dropped"] >= 1


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
@requires_cards
def test_renderer_draws_the_right_person_onto_the_card(tmp_path):
    sheets = generate.load_workbook_data(generate.XLSX)
    people = generate.build_people(sheets)
    assert len(people) == 300, "the workbook is the 300-row master sheet"

    person = people[0]
    renderer, bound = generate.prepare("pan", person)
    assert bound >= 4, "PAN should bind name, father's name, DOB and PAN number"

    before = renderer.background.copy()
    card = renderer.render(person)
    assert card.shape == renderer.background.shape
    assert not np.array_equal(card, before), "nothing was typeset"

    other = renderer.render(people[1])
    assert not np.array_equal(card, other), "person 2 rendered the same as person 1"


@requires_cards
def test_aadhaar_background_has_no_leftover_printed_name():
    """The scanned Aadhaar still carries a dummy name; it must be inpainted."""
    renderer, _ = generate.prepare("aadhar", generate.build_people(
        generate.load_workbook_data(generate.XLSX)
    )[0])
    assert "cleanup" in renderer.spec, "aadhar needs a cleanup rect"
    x, y, w, h = renderer.spec["cleanup"][0]
    roi = renderer.background[y:y + h, x:x + w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    spread = int(gray.max()) - int(gray.min())
    # real text would give a wide spread; a cleaned pastel wash will not
    assert spread < 90, f"leftover printed text still present (spread {spread})"


@requires_cards
def test_generated_card_carries_every_measured_holder():
    import json

    sheets = generate.load_workbook_data(generate.XLSX)
    people = generate.build_people(sheets)
    for doc in ("aadhar", "pan", "driving_license", "passport"):
        renderer, _ = generate.prepare(doc, people[0])
        card = renderer.render(people[0])
        with_regions = draw_regions(
            card, renderer.region_key, copy=True, scale=max(1.0, card.shape[0] / 700)
        )
        assert not np.array_equal(card, with_regions), f"{doc}: no holder drawn"
        payload = annotation(renderer.region_key, card.shape[1], card.shape[0])
        assert payload["regions"], doc
        names = {r["name"] for r in payload["regions"]}
        assert "photo" in names, f"{doc} has no primary photo holder"
        assert json.dumps(payload)  # must be serialisable


# --------------------------------------------------------------------------- #
# the progress dashboard
# --------------------------------------------------------------------------- #
def test_progress_snapshot_reports_a_live_eta():
    import progress_server

    p = progress_server.Progress(total=100, port=8790)
    p.add_track("pan", 100)
    p.stage("rendering", "pan: 100 cards")
    p.tick("pan", 50)
    snap = p.snapshot()
    assert snap["done"] == 50 and snap["total"] == 100
    assert snap["percent"] == 50.0
    assert snap["stage"] == "rendering"
    assert snap["tracks"][0]["percent"] == 50.0
    assert snap["errors"] == 0
    assert snap["log"], "the activity log should have entries"


def test_progress_counts_errors_and_keeps_the_log_bounded():
    import progress_server

    p = progress_server.Progress(total=10, port=8790)
    p.error("boom")
    assert p.snapshot()["errors"] == 1
    for i in range(80):
        p.note(f"line {i}")
    assert len(p.snapshot()["log"]) <= 40, "the log must not grow without bound"


def test_dashboard_serves_ascii_only():
    """The em-dash mojibake that showed as 'a?' came from a non-ASCII byte in
    the page source, so the page is asserted to be pure ASCII."""
    import progress_server

    page = progress_server.DASHBOARD
    assert page.isascii(), [c for c in page if not c.isascii()]


def test_preview_strip_keeps_every_document_type():
    """A single global cap let the last card type crowd out the others, so the
    panel ended the run showing only passports."""
    import progress_server

    tmp = progress_server.PREVIEW_DIR
    existed = tmp.is_dir()
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        p = progress_server.Progress(total=100, port=8790)
        src = tmp / "_seed.jpg"
        src.write_bytes(b"not-really-a-jpeg")
        for doc in ("aadhar", "pan", "driving_license", "passport"):
            for serial in (1, 50, 100, 150, 200):
                p.add_preview(doc, serial, src)
        types = [item["document_type"] for item in p.snapshot()["previews"]]
        assert set(types) == {"aadhar", "pan", "driving_license", "passport"}
        for doc in set(types):
            assert types.count(doc) == progress_server.PREVIEW_PER_TYPE
    finally:
        src = tmp / "_seed.jpg"
        if src.exists():
            src.unlink()
        if not existed:
            for f in tmp.glob("*.jpg"):
                f.unlink()
