"""Generate the identity-document dataset from ``mock_government_ids_300.xlsx``.

What this does
--------------
For each of the 300 people in the spreadsheet, and for each of the four cards
that have a real background in ``sample-data/templates``, re-typeset that
person's fields onto the card and draw the measured image holders on top:

    aadhaar          768 x 1024     photo + ghost photo + QR
    pan              768 x  517     photo + QR
    driving_license 1000 x  579     photo
    passport        1264 x 1691     photo + barcode

Field placement is not guessed.  ``extract_layouts.py`` recovers the exact
position, font size and colour of every text run the original PDFs draw on
their page 1, and this script binds each of those runs to a spreadsheet column
by matching the text against row 1.  The same person then gets their own values
dropped into the same slots, re-wrapped to the original line count and width.

Realism
-------
The generator first builds a per-person profile - name, nationality, sex, age
from date of birth, and the state/city implied by the address - and checks the
spreadsheet is internally consistent (PAN name vs Aadhaar name vs passport
name, gender vs sex, age bounds).  Those attributes land in the sidecar
annotation next to every image.  There is no photo in the spreadsheet at all,
so the portrait region is drawn as a labelled placeholder rather than filled;
that is the whole point of the exercise, and it is what a face pipeline needs
ground truth for.

Usage
-----
    python scripts/dataset/generate.py                 # all four types, 300 each
    python scripts/dataset/generate.py --types pan     # one type
    python scripts/dataset/generate.py --limit 20      # quick smoke run
    python scripts/dataset/generate.py --port 9000     # dashboard on another port
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.modules.localization.photo_regions import (  # noqa: E402
    annotation as region_annotation,
    draw_regions,
)
import faces as faces_mod  # noqa: E402
import fillers as fillers_mod  # noqa: E402
import valid_ids  # noqa: E402
from extract_layouts import LAYOUT_DIR  # noqa: E402
from progress_server import Progress  # noqa: E402

SAMPLE_DATA = BACKEND_ROOT.parent / "sample-data"
TEMPLATES = SAMPLE_DATA / "templates"
XLSX = TEMPLATES / "mock_government_ids_300.xlsx"
OUT_ROOT = BACKEND_ROOT / "training" / "data_generated"

#: ``aadhar`` and ``pan`` are the directory names the MobileNetV2 classifier in
#: ``training/train.py`` already expects, so reuse them here.
TYPES: dict[str, dict[str, Any]] = {
    "aadhar": {
        "layout": "aadhaar",
        "region_key": "aadhaar",  # the classifier calls it aadhar, the cards aadhaar
        "background": ("WhatsApp Image 2026-09-26 at 6.43.56 AM (1).jpeg", None),
        "font": "arial.ttf",
        "bold": "arialbd.ttf",
        "cleanup": [(150, 224, 280, 52)],  # leftover pre-printed name/gender
    },
    "pan": {
        "layout": "pan",
        "region_key": "pan",
        "background": ("WhatsApp Image 2026-09-26 at 6.43.56 AM.jpeg", (40, 557)),
        "font": "arial.ttf",
        "bold": "arialbd.ttf",
    },
    "driving_license": {
        "layout": "driving_license",
        "region_key": "driving_license",
        "background": ("DL.jpeg", (605, 1183)),
        "font": "arial.ttf",
        "bold": "arialbd.ttf",
    },
    "passport": {
        "layout": "passport",
        "region_key": "passport",
        "background": ("PASSPORT.jpeg", None),
        "font": "arialbd.ttf",
        "bold": "arialbd.ttf",
        "value_fonts": ("C2_0", "C2_1"),  # ignore the T1_* label redraws
    },
}

FONT_DIR = Path(r"C:\Windows\Fonts")

#: Fields that should be typeset in a monospaced face, e.g. the MRZ.
MONO_FIELDS = ("Passport_MRZ_Line_1", "Passport_MRZ_Line_2")

#: Hand-placed passport slots, ``field -> (x, y, max_lines)``.
#:
#: The passport PDF's own value coordinates are not usable: it drops
#: ``Place of Birth`` and ``Place of Issue`` roughly 150 px below their printed
#: labels, and writes both MRZ lines into the middle of the data page instead of
#: the observations page.  These coordinates are the printed label positions
#: recovered from the layout (fonts ``T1_*``) plus a ~34 px drop, which is what
#: the card actually looks like.
PASSPORT_SLOTS: dict[str, tuple[int, int, int]] = {
    "Passport_Type": (455, 140, 1),
    "Passport_Country_Code": (592, 140, 1),
    "Passport_Number": (1000, 132, 1),
    "Passport_Surname": (445, 188, 1),
    "Passport_Given_Name": (445, 272, 1),
    "Passport_DOB": (450, 358, 1),
    "Passport_Sex": (786, 358, 1),
    "Passport_Place_Of_Birth": (540, 428, 1),
    "Passport_Place_Of_Issue": (616, 514, 1),
    "Passport_Date_Of_Issue": (616, 600, 1),
    "Passport_Date_Of_Expiry": (1000, 600, 1),
    "Passport_Father_Name": (150, 962, 1),
    "Passport_Mother_Name": (150, 1038, 1),
    "Passport_Spouse_Name": (150, 1116, 1),
    "Passport_Address": (132, 1198, 2),
    "Passport_Old_Passport_No": (132, 1300, 1),
    "Passport_File_No": (130, 1544, 1),
    "Passport_MRZ_Line_1": (196, 1392, 1),
    "Passport_MRZ_Line_2": (196, 1486, 1),
}

#: Columns each card draws its values from, in preference order.  Several sheets
#: repeat the same value under different names - the DL ``Address`` and
#: ``Passport_Address`` hold identical strings - so without an explicit order the
#: sidecar annotation records whichever column happened to come first, and short
#: values like ``O+`` never bind at all.
TYPE_COLUMNS: dict[str, list[str]] = {
    "aadhar": ["Aadhaar_Number", "Aadhaar_Name", "Aadhaar_DOB", "Aadhaar_Gender", "Aadhaar_Address"],
    "pan": ["PAN_Number", "PAN_Name", "PAN_Father_Name", "PAN_DOB"],
    "driving_license": [
        "DL_Number", "Name", "S_D_W", "DOB", "Blood_Group", "Class_of_Vehicle",
        "Date_Of_Issue", "Issue_Date", "Validity_NT", "Validity_TR",
        "PSV_Badge_No", "Licensing_Authority", "Address",
    ],
    "passport": [],
}

#: Text the source PDF truncates or omits, mapped to the column that should
#: supply it.  The DL page 1 writes the bare digit ``1`` where the licence
#: number belongs and cuts ``S/D/W`` down to the forename, so both are bound by
#: hand rather than by matching row 1.
FIELD_FIXUPS: dict[str, dict[str, str]] = {
    "driving_license": {
        "1": "DL_Number",
        "Vikram Singh": "S_D_W",
    },
}

#: Printed labels that share a text run with their value.  The Aadhaar writes
#: ``DOB: 05/02/1977`` as one run, so the value alone has to be matched and the
#: label kept for redrawing.
VALUE_LABEL_PREFIXES = ("DOB", "Date of Birth", "Sex", "Gender", "Issue Date")

DOB_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


# --------------------------------------------------------------------------- #
# spreadsheet
# --------------------------------------------------------------------------- #
def _col_index(ref: str) -> int:
    """``"AB12"`` -> 27, the zero-based column of a cell reference."""
    letters = "".join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + (ord(c.upper()) - 64)
    return n - 1


def load_workbook_data(path: Path) -> dict[str, list[dict[str, str]]]:
    """Every sheet in the workbook, as a list of column->value dicts.

    Read with the standard library only: the backend venv has neither
    ``openpyxl`` nor ``pandas`` and neither is in ``requirements.txt``, so
    pulling in a dependency just to read one spreadsheet would be a poor trade
    for the handful of sheets this needs.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    # The r:id on a <sheet> lives in the officeDocument relationships namespace,
    # which is *not* the same one used inside the package .rels file.
    DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {
            r.get("Id"): r.get("Target", "")
            for r in rels.findall(f"{PKG_REL}Relationship")
        }

        sheets_el = wb.find(f"{NS}sheets")
        out: dict[str, list[dict[str, str]]] = {}
        for sheet in (sheets_el if sheets_el is not None else []):
            name = sheet.get("name", "")
            rid = sheet.get(DOC_REL, "")
            target = targets.get(rid, "")
            if not target:
                continue
            part = target[1:] if target.startswith("/") else f"xl/{target}"
            if part not in z.namelist():
                continue

            root = ET.fromstring(z.read(part))
            grid: list[dict[int, str]] = []
            for row in root.iter(f"{NS}row"):
                cells: dict[int, str] = {}
                for c in row.findall(f"{NS}c"):
                    idx = _col_index(c.get("r", "A1"))
                    ctype = c.get("t", "n")
                    if ctype == "s":
                        v = c.find(f"{NS}v")
                        if v is not None and v.text is not None:
                            if v.text.isdigit() and int(v.text) < len(shared):
                                cells[idx] = shared[int(v.text)]
                    elif ctype in ("inlineStr", "str"):
                        cells[idx] = "".join(
                            t.text or "" for t in c.iter(f"{NS}t")
                        )
                    else:
                        v = c.find(f"{NS}v")
                        cells[idx] = v.text if v is not None and v.text else ""
                grid.append(cells)

            if not grid:
                out[name] = []
                continue
            header = {i: (v or "").strip() for i, v in grid[0].items()}
            records: list[dict[str, str]] = []
            for cells in grid[1:]:
                rec = {
                    header[i]: (cells.get(i, "") or "").strip()
                    for i in header
                    if header[i]
                }
                if any(rec.values()):
                    records.append(rec)
            out[name] = records
    return out


def build_people(sheets: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    """Join the per-type sheets onto one record per person.

    Row 1 of the Master Sheet is person 1, and every type sheet carries the same
    serial numbers, so the join is on ``Serial_Number``.
    """
    master = sheets.get("Master Sheet", [])
    by_serial: dict[str, dict[str, Any]] = {}
    for rec in master:
        person = {"serial": rec.get("Serial_Number", "")}
        person.update(rec)
        by_serial[person["serial"]] = person

    # The per-type sheets are more specific than the Master Sheet for their own
    # fields - the master's Aadhaar_Number is literally "[Aadhaar Redacted]",
    # while the Aadhaar sheet carries the real 12-digit number - so the type
    # sheets overwrite rather than fill gaps.
    for sheet_name, records in sheets.items():
        if sheet_name == "Master Sheet":
            continue
        for rec in records:
            person = by_serial.setdefault(rec.get("Serial_Number", ""), {})
            person.setdefault("serial", rec.get("Serial_Number", ""))
            for k, v in rec.items():
                if k != "Serial_Number" and v != "":
                    person[k] = v

    people = [p for p in by_serial.values() if p.get("serial")]
    people.sort(key=lambda p: int(p["serial"]) if str(p["serial"]).isdigit() else 0)
    return people


def age_from_dob(dob: str, today: date | None = None) -> int | None:
    m = DOB_RE.match((dob or "").strip())
    if not m:
        return None
    d, mo, y = (int(v) for v in m.groups())
    try:
        born = date(y, mo, d)
    except ValueError:
        return None
    ref = today or date.today()
    return ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))


#: Indian states, keyed by the token that appears in the address strings.
STATE_TOKENS: dict[str, tuple[str, ...]] = {
    "Maharashtra": ("MUMBAI", "PUNE", "NAGPUR", "THANE", "NASHIK", "AURANGABAD"),
    "Karnataka": ("BANGALORE", "BENGALURU", "MYSORE", "MYSURU", "HUBLI"),
    "Delhi": ("DELHI", "NEW DELHI"),
    "Uttar Pradesh": ("NOIDA", "LUCKNOW", "GHAZIABAD", "KANPUR", "AGRA"),
    "Telangana": ("HYDERABAD",),
    "Tamil Nadu": ("CHENNAI", "COIMBATORE", "MADURAI"),
    "West Bengal": ("KOLKATA",),
    "Gujarat": ("AHMEDABAD", "SURAT", "VADODARA", "RAJKOT"),
    "Rajasthan": ("JAIPUR", "JODHPUR", "UDAIPUR"),
    "Punjab": ("LUDHIANA", "AMRITSAR"),
    "Haryana": ("GURGAON", "GURUGRAM", "FARIDABAD"),
    "Madhya Pradesh": ("BHOPAL", "INDORE"),
}


def state_from_address(address: str) -> str | None:
    """Infer the state from the address, for the ethnicity/region attribute."""
    up = (address or "").upper()
    for state, cities in STATE_TOKENS.items():
        if any(c in up for c in cities):
            return state
    tail = up.rsplit("PIN:", 1)[-1]
    for part in re.split(r"[,\s]+", tail):
        part = part.strip()
        if part and part.isalpha() and len(part) > 3:
            return part.title()
    return None


def sex_from_gender(gender: str, sex: str = "") -> str | None:
    g = (gender or "").strip().upper()
    if g in ("MALE", "M"):
        return "M"
    if g in ("FEMALE", "F"):
        return "F"
    s = (sex or "").strip().upper()
    return s if s in ("M", "F") else None


def profile_for(person: dict[str, Any]) -> dict[str, Any]:
    """Derive the demographic attributes the renderer and sidecar both use."""
    dob = person.get("DOB") or person.get("Aadhaar_DOB") or person.get("Passport_DOB") or ""
    address = (
        person.get("Aadhaar_Address")
        or person.get("Passport_Address")
        or person.get("Address")
        or ""
    )
    return {
        "name": person.get("Name", ""),
        "first_name": person.get("First Name", "") or person.get("Passport_Given_Name", ""),
        "last_name": person.get("Last Name", "") or person.get("Passport_Surname", ""),
        "father_name": person.get("Father Name", "") or person.get("Passport_Father_Name", ""),
        "mother_name": person.get("Mother Name", ""),
        "dob": dob,
        "age": age_from_dob(dob),
        "sex": sex_from_gender(person.get("Aadhaar_Gender", ""), person.get("Passport_Sex", "")),
        "nationality": person.get("Passport_Nationality", "") or "INDIAN",
        "country_code": person.get("Passport_Country_Code", "") or "IND",
        "region": state_from_address(address),
        "address": address,
    }


def consistency_issues(p: dict[str, Any]) -> list[str]:
    """Spreadsheet rows whose fields disagree with each other."""
    issues: list[str] = []
    names = {
        n for n in (
            p.get("Name"), p.get("PAN_Name"), p.get("Aadhaar_Name"),
            p.get("Passport_Given_Name"),
        ) if n
    }
    if len(names) > 1 and not (
        p.get("Name") == " ".join(
            x for x in (p.get("Passport_Given_Name"), p.get("Passport_Surname")) if x
        )
    ):
        issues.append(f"serial {p.get('serial')}: name mismatch {sorted(names)}")

    gender = sex_from_gender(p.get("Aadhaar_Gender", ""))
    sex = (p.get("Passport_Sex") or "").strip().upper()
    if gender and sex and gender != sex:
        issues.append(f"serial {p.get('serial')}: Aadhaar gender {gender} vs passport sex {sex}")

    age = age_from_dob(p.get("DOB", ""))
    if age is not None and not (18 <= age <= 95):
        issues.append(f"serial {p.get('serial')}: implausible age {age}")

    dob_set = {d for d in (p.get("DOB"), p.get("PAN_DOB"), p.get("Aadhaar_DOB")) if d}
    if len(dob_set) > 1:
        issues.append(f"serial {p.get('serial')}: DOB mismatch {sorted(dob_set)}")
    return issues


# --------------------------------------------------------------------------- #
# layout binding
# --------------------------------------------------------------------------- #
@dataclass
class Line:
    """One typeset line on a card, optionally bound to a spreadsheet field."""

    y: float
    x: float
    size: float
    color: tuple[int, int, int]
    text: str
    field: str | None = None
    group: int | None = None
    width: float = 0.0
    bold: bool = False
    mono: bool = False
    prefix: str = ""


def _norm(value: str) -> str:
    v = unicodedata.normalize("NFKC", value or "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", v).strip()


def group_runs(runs: Sequence[dict], *, value_fonts: Sequence[str] | None = None) -> list[Line]:
    """Merge the extracted text runs into cells.

    Runs on the same baseline merge only when they are actually adjacent: a wide
    horizontal gap means two separate fields happen to share a baseline (the
    passport's ``Type`` and ``Code``, or ``Date of Issue`` and ``Date of
    Expiry``), and merging those would fuse two spreadsheet values into one
    unmatched blob.
    """
    kept = [
        r for r in runs
        if value_fonts is None or r["font"] in value_fonts
    ]
    kept.sort(key=lambda r: (round(r["y"], 1), r["x"]))
    lines: list[Line] = []
    end_x = 0.0
    for r in kept:
        text = r["text"]
        if not text.strip():
            continue
        width = _approx_text_width(text, r["size"])
        adjacent = (
            lines
            and abs(lines[-1].y - r["y"]) <= 2.0
            and (r["x"] - end_x) <= r["size"] * 2.5
        )
        if adjacent:
            lines[-1].text += text
            lines[-1].width = max(lines[-1].width, r["x"] + width)
        else:
            lines.append(
                Line(
                    y=r["y"], x=r["x"], size=r["size"], color=tuple(r["color"]),
                    text=text, width=r["x"] + width,
                )
            )
        end_x = r["x"] + width
    return lines


def _approx_text_width(text: str, size: float) -> float:
    """Rough advance width; only used to size the re-wrap budget."""
    narrow = sum(1 for c in text if c in "iljI.,:;'|!()[] ")
    return size * (0.30 * narrow + 0.58 * (len(text) - narrow))


def bind_fields(
    lines: list[Line],
    person: dict[str, Any],
    *,
    candidates: Sequence[str] | None = None,
    fixups: dict[str, str] | None = None,
) -> int:
    """Bind lines to spreadsheet columns by matching row 1's text.

    A line is bound when its text equals a value, or is a contiguous slice of
    one (the address arrives split across several lines).  ``fixups`` then binds
    any still-unbound line whose text is listed, for fields the source PDF
    truncated or omitted.  Returns the number of lines bound.
    """
    pool: list[str] = list(candidates) if candidates else [
        k for k in person if isinstance(person.get(k), str)
    ]
    lookup: dict[str, str] = {}
    for key in pool:
        val = _norm(str(person.get(key, "")))
        # 2 characters, not 3: blood groups ("O+") and vehicle classes are short
        # and the pool is already restricted to this card's own columns.
        if len(val) >= 2:
            lookup.setdefault(val, key)

    bound = 0
    group_id = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        target = _norm(line.text)
        if target in lookup:
            line.field = lookup[target]
            line.group = group_id
            group_id += 1
            bound += 1
            i += 1
            continue
        # try to absorb a run of consecutive lines into one longer value
        for span in range(min(4, len(lines) - i), 1, -1):
            joined = _norm(" ".join(l.text for l in lines[i:i + span]))
            if joined in lookup:
                for l in lines[i:i + span]:
                    l.field = lookup[joined]
                    l.group = group_id
                    l.x = min(l.x for l in lines[i:i + span])
                    bound += 1
                group_id += 1
                i += span
                break
        else:
            i += 1

    for line in lines:
        if line.field is None and fixups and _norm(line.text) in fixups:
            line.field = fixups[_norm(line.text)]
            line.group = group_id
            line.width = line.x + 220.0  # a licence-number-sized slot
            group_id += 1
            bound += 1
        elif line.field is None:
            # "DOB: 05/02/1977" -> prefix "DOB:", value from Aadhaar_DOB
            prefix, bare = _split_label(_norm(line.text))
            if prefix and bare in lookup:
                line.field = lookup[bare]
                line.prefix = f"{prefix} "
                line.group = group_id
                line.width = line.x + 260.0
                group_id += 1
                bound += 1
    return bound


def _split_label(text: str) -> tuple[str, str]:
    """Split a leading printed label off a value, e.g. ``("DOB:", "05/02/1977")``."""
    for label in VALUE_LABEL_PREFIXES:
        prefix = f"{label}:"
        if text.lower().startswith(prefix.lower()):
            return prefix, text[len(prefix):].strip()
    return "", text


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
class FontCache:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def get(self, name: str, size: float) -> ImageFont.FreeTypeFont:
        key = (name, max(6, int(round(size))))
        if key not in self._cache:
            path = FONT_DIR / name
            if not path.exists():
                path = FONT_DIR / "arial.ttf"
            self._cache[key] = ImageFont.truetype(str(path), key[1])
        return self._cache[key]


def remove_preprinted_text(bgr: np.ndarray, rects: Iterable[tuple[int, int, int, int]]) -> np.ndarray:
    """Inpaint leftover printed text so generated values land on clean card stock.

    The Aadhaar background still carries a dummy name and gender from whenever
    it was scanned.  Masking only the dark glyph pixels and running Telea
    inpainting keeps the pastel gradient intact, which a flat fill would not.
    """
    out = bgr
    for x, y, w, h in rects:
        ih, iw = out.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(iw, x + w), min(ih, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = out[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Compare against a heavily blurred copy so the mask follows glyphs but
        # ignores the pastel gradient the card is printed on.
        local_bg = cv2.GaussianBlur(gray, (0, 0), 9)
        mask = (gray.astype(np.int16) < local_bg.astype(np.int16) - 18).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        if mask.any():
            out[y0:y1, x0:x1] = cv2.inpaint(roi, mask, 6, cv2.INPAINT_TELEA)
    return out


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
    max_lines: int,
) -> list[str]:
    """Greedy word wrap, keeping at most ``max_lines`` lines."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if font.getlength(trial) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        lines = [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    # fold any overflow into the last permitted line rather than losing it
    if max_lines == len(lines) and words:
        consumed = " ".join(lines).split()
        if len(consumed) < len(words):
            lines[-1] = (lines[-1] + " " + " ".join(words[len(consumed):])).strip()
    return lines


@dataclass
class CardRenderer:
    """Typesets one document type onto its background."""

    document_type: str
    spec: dict[str, Any]
    lines: list[Line]
    font_cache: FontCache = field(default_factory=FontCache)

    def __post_init__(self) -> None:
        self.background = self._load_background()
        self.region_key = self.spec.get("region_key", self.document_type)
        for line in self.lines:
            if line.field in MONO_FIELDS:
                line.mono = True
            line.bold = line.size >= 15.0

    def _load_background(self) -> np.ndarray:
        filename, crop = self.spec["background"]
        img = cv2.imread(str(TEMPLATES / filename), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"background not readable: {TEMPLATES / filename}")
        if crop:
            img = img[crop[0]:crop[1] + 1]
        for rect in self.spec.get("cleanup", ()):
            img = remove_preprinted_text(img, [rect])
        return img

    def _group_extent(self, group: int | None) -> tuple[int, int, int, float]:
        """(x, y0, line_count, width) for a wrapped field group."""
        members = [l for l in self.lines if l.group == group] if group is not None else []
        if not members:
            return 0, 0, 1, 0
        x = min(l.x for l in members)
        y0 = min(l.y for l in members)
        count = len(members)
        width = max(l.width for l in members) - x
        return int(round(x)), int(round(y0)), count, width

    def render(self, person: dict[str, Any]) -> np.ndarray:
        pil = Image.fromarray(cv2.cvtColor(self.background, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        # Exact pixel box of every value this render prints (one entry per
        # printed occurrence: the Aadhaar number appears on both sides); these
        # become the region detector's training labels.
        self.text_boxes: list[tuple[str, list[int]]] = []

        # first pass: lines with no bound field, i.e. static card furniture
        for line in self.lines:
            if line.field is None:
                self._draw_line(draw, line, line.text, line.x, line.y)

        # second pass: one render per *group*, not per line.  A field that
        # arrived split over three lines is a single group, so only its first
        # line emits text; drawing from each line would stack three copies of
        # the whole block on top of each other.
        for group, members in self._groups().items():
            head = members[0]
            value = _norm(str(person.get(head.field or "", "")))
            if not value:
                continue
            _, _, count, width = self._group_extent(group)
            if width <= 0:
                width = max(40.0, pil.width - head.x - 8)
            # a little slack so longer values still fit the original slot
            budget = width * 1.06
            font = self._font_for(head)
            pieces = wrap_text(value, font, budget, count)
            step = self._line_step(group)
            group_box: list[int] | None = None
            for k, piece in enumerate(pieces):
                # the label prefix only belongs on the first line
                lead = head.prefix if k == 0 else ""
                box = self._draw_line(draw, head, lead + piece, head.x, head.y + k * step, skip=lead)
                if box:
                    group_box = box if not group_box else [
                        min(group_box[0], box[0]), min(group_box[1], box[1]),
                        max(group_box[2], box[2]), max(group_box[3], box[3])]
            if group_box and head.field:
                self.text_boxes.append((head.field, group_box))

        rgb = np.array(pil)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def _groups(self) -> dict[int, list[Line]]:
        groups: dict[int, list[Line]] = {}
        for line in self.lines:
            if line.field is None:
                continue
            groups.setdefault(line.group if line.group is not None else -1, []).append(line)
        for members in groups.values():
            members.sort(key=lambda l: l.y)
        return groups

    def _line_step(self, group: int | None) -> float:
        members = sorted(
            (l for l in self.lines if l.group == group), key=lambda l: l.y
        ) if group is not None else []
        if len(members) < 2:
            return members[0].size * 1.25 if members else 14.0
        gaps = [b.y - a.y for a, b in zip(members, members[1:]) if b.y > a.y]
        return float(min(gaps)) if gaps else members[0].size * 1.25

    def _font_for(self, line: Line) -> ImageFont.FreeTypeFont:
        if line.mono:
            return self.font_cache.get("cour.ttf", line.size)
        name = self.spec["bold"] if line.bold else self.spec["font"]
        return self.font_cache.get(name, line.size)

    def _draw_line(
        self, draw: ImageDraw.ImageDraw, line: Line, text: str, x: float, y: float, skip: str = ""
    ) -> list[int] | None:
        """Draw one line; return the pixel box of the text after ``skip``
        (a printed label sharing the run, e.g. ``DOB: ``), or None if empty."""
        font = self._font_for(line)
        # The PDF baseline sits a few pixels above the glyph bottoms; nudge down
        # so the text sits on the card the way the original did.
        origin = (x, y - line.size * 0.82)
        draw.text(origin, text, font=font, fill=tuple(int(c) for c in line.color))
        value = text[len(skip):] if skip and text.startswith(skip) else text
        if not value.strip():
            return None
        vx = origin[0] + (draw.textlength(skip, font=font) if skip and text.startswith(skip) else 0)
        x0, y0, x1, y1 = draw.textbbox((vx, origin[1]), value, font=font)
        return [int(x0), int(y0), int(x1), int(y1)]


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
#: Text sizes for the hand-placed passport slots, in pixels of the 1264x1691
#: background.  ``T1_*`` label runs measure 8-14 px, so values sit at 26 px and
#: the machine-readable zone at 34 px.
PASSPORT_SIZES: dict[str, float] = {
    "Passport_MRZ_Line_1": 34.0,
    "Passport_MRZ_Line_2": 34.0,
}


def passport_lines(layout: dict) -> list[Line]:
    """Build the passport's value lines from the slot table.

    Binding by text matching is not usable here: the passport PDF embeds seven
    fonts, the two that carry the values decode cleanly, but its coordinates are
    wrong for four fields (see :data:`PASSPORT_SLOTS`).  The field names are known
    up front, so the slots are placed directly.
    """
    lines: list[Line] = []
    card_w = float(layout["image_size"][0])
    for group_id, (field, (x, y, count)) in enumerate(PASSPORT_SLOTS.items()):
        size = PASSPORT_SIZES.get(field, 26.0)
        for k in range(max(1, count)):
            lines.append(
                Line(
                    y=float(y + k * (size * 1.35)),
                    x=float(x),
                    size=size,
                    color=(0, 0, 0),
                    text="",
                    field=field,
                    group=group_id,
                    # the slot runs to the right margin; without a real width the
                    # wrap budget collapses and every word lands on its own line
                    width=card_w - float(x) - 24.0,
                    mono=field in MONO_FIELDS,
                    bold=False,
                )
            )
    return lines


def prepare(document_type: str, person1: dict[str, Any]) -> tuple[CardRenderer, int]:
    spec = TYPES[document_type]
    layout = json.loads((LAYOUT_DIR / f"{spec['layout']}.json").read_text(encoding="utf-8"))
    if document_type == "passport":
        lines = passport_lines(layout)
        bound = sum(1 for l in lines if l.field)
    else:
        lines = group_runs(layout["runs"], value_fonts=spec.get("value_fonts"))
        preferred = TYPE_COLUMNS.get(document_type, [])
        candidates = [c for c in preferred if c in person1]
        candidates += [k for k in person1 if k not in candidates]
        bound = bind_fields(
            lines, person1,
            candidates=candidates,
            fixups=FIELD_FIXUPS.get(document_type),
        )
    return CardRenderer(document_type=document_type, spec=spec, lines=lines), bound


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--types", nargs="*", default=list(TYPES), choices=list(TYPES))
    ap.add_argument("--limit", type=int, default=0, help="people per type (0 = all)")
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument(
        "--hold", type=float, default=600.0,
        help="seconds to keep the dashboard serving after the run (0 to exit)",
    )
    ap.add_argument(
        "--delay", type=float, default=0.0,
        help="seconds to pause per image; the full run takes ~20s unaided, which "
             "is too quick to watch, so this exists to slow it for a demo",
    )
    ap.add_argument(
        "--preview-every", type=int, default=20,
        help="publish a dashboard thumbnail every Nth card (plus the first two)",
    )
    ap.add_argument(
        "--keep-workbook-ids", action="store_true",
        help="print the spreadsheet's original (random, mostly invalid) identifiers instead of "
             "regenerating Verhoeff-valid Aadhaar, rule-conforming PAN, ICAO MRZ and Delhi DL numbers",
    )
    ap.add_argument(
        "--draw-boxes", action="store_true",
        help="also outline the measured holders on the card; off by default so the "
             "output looks like a real document rather than an annotated one. The "
             "rectangles are recorded in the sidecar either way.",
    )
    args = ap.parse_args(argv)

    progress = Progress(total=0, port=args.port)
    if args.no_browser:
        progress.start()
        progress.note(f"dashboard at http://{progress.host}:{progress.port}/")
        url = f"http://{progress.host}:{progress.port}/"
    else:
        url = progress.open_browser()

    try:
        # ---- stage 1: read the spreadsheet -------------------------------
        progress.stage("reading-workbook", f"loading {XLSX.name}")
        sheets = load_workbook_data(XLSX)
        people = build_people(sheets)
        progress.note(
            "sheets: " + ", ".join(f"{k}={len(v)}" for k, v in sheets.items())
        )
        if not people:
            progress.error("no people found in the workbook")
            return 1

        selected = [p for p in people if p.get("serial")]
        if args.limit:
            selected = selected[: args.limit]

        # ---- stage 2: derive the person profiles -------------------------
        progress.stage("profiling", f"{len(selected)} people")
        profiles = [profile_for(p) for p in selected]
        issues: list[str] = []
        for p in selected:
            issues.extend(consistency_issues(p))
        progress.note(
            f"profiles built; {len(issues)} consistency notes"
        )
        for line in issues[:5]:
            progress.note(line)

        # ---- stage 3: prepare each renderer ------------------------------
        progress.stage("preparing-layouts", "binding text runs to spreadsheet fields")
        bank = faces_mod.FaceBank()
        progress.note(
            f"portraits available for {bank.available()} people "
            f"({'--limit harvest' if not bank.available() else 'cached'})"
        )
        renderers: dict[str, CardRenderer] = {}
        for document_type in args.types:
            renderer, bound = prepare(document_type, selected[0])
            renderers[document_type] = renderer
            total_fields = len({l.field for l in renderer.lines if l.field})
            progress.add_track(document_type, len(selected))
            progress.note(
                f"{document_type}: {len(renderer.lines)} lines, {bound} bound to "
                f"{total_fields} spreadsheet fields, background "
                f"{renderer.background.shape[1]}x{renderer.background.shape[0]}"
            )
            if bound == 0:
                progress.error(f"{document_type}: no field matched row 1, check the layout")
        progress.total = len(selected) * len(renderers)
        progress.note(f"target: {progress.total} images")

        # ---- stage 3b: valid identifiers ----------------------------------
        # After binding (which matches row 1's *original* text against the
        # layout) and before rendering, so the card, its QR code and its
        # annotation all carry the same rule-conforming numbers.
        if not args.keep_workbook_ids:
            progress.stage("identifiers", "Verhoeff Aadhaar, PAN rules, ICAO MRZ, Delhi DL")
            changed = sum(bool(valid_ids.normalise_identifiers(p)) for p in selected)
            progress.note(f"identifiers regenerated for {changed} people")

        # ---- stage 4: render ---------------------------------------------
        for document_type, renderer in renderers.items():
            img_dir = args.out / document_type
            ann_dir = args.out / "annotations" / document_type
            img_dir.mkdir(parents=True, exist_ok=True)
            ann_dir.mkdir(parents=True, exist_ok=True)
            progress.stage("rendering", f"{document_type}: {len(selected)} cards")
            for person, prof in zip(selected, profiles):
                serial = person["serial"]
                try:
                    card = renderer.render(person)
                    holders = fillers_mod.fill_holders(
                        card, renderer.region_key, person, bank,
                        draw_boxes=args.draw_boxes,
                    )
                    name = f"{document_type}_{int(serial):04d}.jpg"
                    cv2.imwrite(
                        str(img_dir / name), card,
                        [cv2.IMWRITE_JPEG_QUALITY, args.quality],
                    )
                    payload = region_annotation(
                        renderer.region_key, card.shape[1], card.shape[0]
                    )
                    payload.update(
                        {
                            "serial_number": serial,
                            "file": name,
                            "profile": prof,
                            "holders": holders,
                            "fields": {
                                l.field: str(person.get(l.field, ""))
                                for l in renderer.lines if l.field
                            },
                            # exact boxes of the printed values (x, y, w, h)
                            "text_regions": [
                                {"field": f, "bbox": {"x": b[0], "y": b[1], "w": b[2] - b[0], "h": b[3] - b[1]}}
                                for f, b in renderer.text_boxes
                            ],
                        }
                    )
                    (ann_dir / f"{document_type}_{int(serial):04d}.json").write_text(
                        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
                    )
                    progress.tick(document_type)
                    # Feed the dashboard's output strip continuously. Publishing
                    # only the first card of each type left the panel showing a
                    # stale image for the rest of the run.
                    n = int(serial)
                    if n <= 2 or n % args.preview_every == 0:
                        progress.add_preview(
                            renderer.document_type, n, img_dir / name
                        )
                    if args.delay:
                        time.sleep(args.delay)
                except Exception as exc:  # keep the run going, report the row
                    progress.error(f"{document_type} serial {serial}: {exc!r}")
            progress.note(f"{document_type}: {len(selected)} written to {img_dir}")

        # ---- stage 5: manifest -------------------------------------------
        progress.stage("writing-manifest", "summary")
        manifest = {
            "source_workbook": str(XLSX),
            "people": len(selected),
            "per_type": {
                d: {
                    "images": len(list((args.out / d).glob("*.jpg"))),
                    "annotations": len(
                        list((args.out / "annotations" / d).glob("*.json"))
                    ),
                    "size_px": list(renderers[d].background.shape[:2][::-1]),
                }
                for d in renderers
            },
            "consistency_notes": issues,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        progress.finish()
        print(json.dumps(manifest, indent=2)[:1200])
        return 0
    finally:
        if url:
            snap = progress.snapshot()
            print(
                f"\ndashboard: {url}\n"
                f"  {snap['done']} images in {snap['elapsed']:.0f}s "
                f"({snap['rate']}/s), {snap['errors']} errors"
            )
            if args.hold > 0:
                print(f"  holding the dashboard for {args.hold:.0f}s (Ctrl-C to stop)")
                try:
                    progress.hold(args.hold)
                except KeyboardInterrupt:
                    pass
        progress.stop()


if __name__ == "__main__":
    raise SystemExit(main())
