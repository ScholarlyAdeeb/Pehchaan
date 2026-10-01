"""
Region-assisted field reading.

The Faster R-CNN region detector says *where* each field is printed (name,
date of birth, document number, ...). Each box is cropped and read on its own
with Tesseract in single-line mode, which is far more reliable than picking
the value out of a full-page reading: there is no label text, no neighbouring
field and no background pattern from the rest of the card in the crop.

A region reading is only accepted when it parses as the kind of value its
class promises (a date is a real calendar date, a PAN matches the PAN format,
an Aadhaar number passes Verhoeff, ...). Accepted readings fill fields the
full-page extractor missed, replace values that fail the same check, and,
when both the detection and the reading are confident, replace a full-page
value that disagrees. Every field records where it came from so the report
can show it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from pytesseract import Output
    _TESSERACT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _TESSERACT_AVAILABLE = False

# classes that carry text worth reading (MRZ has its own tuned pass; photo/QR/barcode are not text)
TEXT_CLASSES = {
    "name", "surname", "guardian_name", "date_of_birth", "date_of_issue", "date_of_expiry",
    "document_number", "nationality", "gender", "address", "place_of_birth",
}
_MULTILINE = {"address"}
_MIN_LINE_HEIGHT = 44      # px; smaller crops are enlarged before OCR
_MIN_OCR_CONFIDENCE = 35.0
# A reading this sure of itself replaces a different full-page value: the page
# extractor picks values by nearby labels and can land on the wrong line (the
# old passport number, a country code in the surname column), while the box
# was located as that specific field.
_TRUSTED_OCR_CONFIDENCE = 60.0
_TRUSTED_DETECTION = 0.80


@dataclass
class RegionRead:
    class_name: str
    text: str
    ocr_confidence: float
    detection_confidence: float
    bbox: dict

    def to_dict(self) -> dict:
        return {"class_name": self.class_name, "text": self.text, "ocr_confidence": round(self.ocr_confidence, 1),
                "detection_confidence": round(self.detection_confidence, 3), "bbox": self.bbox}


def _ocr_crop(crop: np.ndarray, multiline: bool) -> tuple[str, float]:
    h = crop.shape[0]
    lines = max(1, round(h / 30)) if multiline else 1
    if h / lines < _MIN_LINE_HEIGHT:
        scale = min(4.0, _MIN_LINE_HEIGHT * lines / h)
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    data = pytesseract.image_to_data(rgb, output_type=Output.DICT, config=f"--oem 3 --psm {6 if multiline else 7}")
    words, confs = [], []
    for text, conf in zip(data["text"], data["conf"]):
        text = text.strip()
        if text and float(conf) >= 0:
            words.append(text)
            confs.append(float(conf))
    return " ".join(words), (sum(confs) / len(confs) if confs else 0.0)


def read_regions(image: np.ndarray, region_result: dict | None) -> list[RegionRead]:
    """OCR every detected text region of ``image`` (BGR, the same pixels the detector saw)."""
    if not _TESSERACT_AVAILABLE or not region_result:
        return []
    from app.modules.ocr.engine import _configure_tesseract

    _configure_tesseract()
    reads: list[RegionRead] = []
    H, W = image.shape[:2]
    for region in region_result.get("regions", []):
        cls = region["class_name"]
        if cls not in TEXT_CLASSES:
            continue
        b = region["bbox"]
        pad = max(3, int(b["h"] * 0.15))
        x0, y0 = max(0, b["x"] - pad), max(0, b["y"] - pad)
        x1, y1 = min(W, b["x"] + b["w"] + pad), min(H, b["y"] + b["h"] + pad)
        if x1 - x0 < 6 or y1 - y0 < 6:
            continue
        try:
            text, conf = _ocr_crop(image[y0:y1, x0:x1], cls in _MULTILINE)
        except Exception as e:  # one unreadable crop must not sink the scan
            logger.warning("Region OCR failed for %s: %s", cls, e)
            continue
        if text:
            reads.append(RegionRead(cls, text, conf, float(region["confidence"]), b))
    return reads


# --------------------------------------------------------------------------- parsing
_DATE_RE = re.compile(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})")
# OCR look-alikes, applied only where the format fixes whether a letter or a digit is expected
_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"})


def _iso_date(text: str) -> str | None:
    m = _DATE_RE.search(text.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"})))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _person_name(text: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z .'-]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .'-")
    words = [w for w in cleaned.split() if len(w) > 1 or w.isupper()]
    if not words or len(cleaned) < 3 or len(words) > 6:
        return None
    return " ".join(words)


def _by_pattern(text: str, shape: str) -> str | None:
    """Fit ``text`` to a letter/digit shape such as "AAAAA9999A", fixing look-alikes by position."""
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    for start in range(0, len(compact) - len(shape) + 1):
        out = []
        for ch, kind in zip(compact[start:start + len(shape)], shape):
            ch = ch.translate(_TO_ALPHA) if kind == "A" else ch.translate(_TO_DIGIT)
            if (kind == "A") != ch.isalpha():
                break
            out.append(ch)
        else:
            return "".join(out)
    return None


def _aadhaar(text: str) -> str | None:
    from app.modules.ocr.indian_extractors import verhoeff_checksum

    digits = re.sub(r"\D", "", text.translate(_TO_DIGIT) if re.search(r"\d", text) else text)
    for start in range(0, len(digits) - 11):
        cand = digits[start:start + 12]
        if cand[0] in "23456789" and verhoeff_checksum(cand):
            return f"{cand[:4]} {cand[4:8]} {cand[8:]}"
    return None


def _gender(text: str, short: bool) -> str | None:
    t = re.sub(r"[^A-Z]", "", text.upper())
    if t in ("F", "FEMALE") or "FEMALE" in t:
        return "F" if short else "Female"
    if t in ("M", "MALE") or t.endswith("MALE"):
        return "M" if short else "Male"
    return None


def _document_number(document_type: str, text: str) -> tuple[str, str, dict] | None:
    """-> (field key, value, extra fields) for a region read of the document number."""
    if document_type in ("aadhar", "national_id"):
        v = _aadhaar(text)
        return ("id_number", v, {"aadhaar_valid": True}) if v else None
    if document_type == "pan":
        v = _by_pattern(text, "AAAAA9999A")
        return ("id_number", v, {"pan_valid": True}) if v else None
    if document_type == "driving_license":
        v = _by_pattern(text, "AA9999999999999")
        return ("license_number", v, {"dl_format_valid": True, "issuing_state": v[:2]}) if v else None
    if document_type == "passport":
        v = _by_pattern(text, "A9999999")
        return ("passport_number_visual", v, {}) if v else None
    return None


# field key written for each region class, per document type
_KEYS = {
    "aadhar": {"name": "name", "date_of_birth": "date_of_birth", "gender": "gender", "address": "address"},
    "pan": {"name": "name", "guardian_name": "father_name", "date_of_birth": "date_of_birth"},
    "driving_license": {"name": "name", "guardian_name": "guardian_name", "date_of_birth": "date_of_birth",
                        "date_of_issue": "issue_date", "date_of_expiry": "valid_till", "address": "address"},
    "passport": {"name": "given_name", "surname": "surname", "guardian_name": "father_name",
                 "date_of_birth": "date_of_birth", "date_of_issue": "issue_date", "date_of_expiry": "expiry_date",
                 "place_of_birth": "place_of_birth", "nationality": "nationality", "gender": "gender",
                 "address": "address"},
}
_KEYS["national_id"] = _KEYS["aadhar"]
_DATE_CLASSES = {"date_of_birth", "date_of_issue", "date_of_expiry"}
_NAME_CLASSES = {"name", "surname", "guardian_name", "place_of_birth"}


def _parse(document_type: str, read: RegionRead) -> tuple[str, str, dict] | None:
    cls, text = read.class_name, read.text
    if cls == "document_number":
        return _document_number(document_type, text)
    key = _KEYS.get(document_type, {}).get(cls)
    if not key:
        return None
    if cls in _DATE_CLASSES:
        v = _iso_date(text)
    elif cls in _NAME_CLASSES:
        v = _person_name(text)
    elif cls == "gender":
        v = _gender(text, short=document_type == "passport")
    elif cls == "nationality":
        m = re.fullmatch(r"[A-Z]{3}", re.sub(r"[^A-Z]", "", text.upper()))
        v = m.group(0) if m else None
    else:  # address
        v = re.sub(r"\s+", " ", text).strip(" ,") if len(text) >= 12 else None
    return (key, v, {}) if v else None


def _page_value_ok(document_type: str, key: str, value) -> bool:
    """Does the full-page value pass the same check a region reading must pass?"""
    if not value:
        return False
    if key == "id_number" and document_type == "pan":
        return bool(re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", str(value)))
    if key == "id_number":
        return _aadhaar(str(value)) is not None
    if key == "passport_number_visual":
        return bool(re.fullmatch(r"[A-Z]\d{7}", str(value)))
    if key == "license_number":
        return bool(re.fullmatch(r"[A-Z]{2}\d{13}", re.sub(r"[^A-Z0-9]", "", str(value).upper())))
    if key == "nationality":
        from app.modules.validation.rules_engine import KNOWN_COUNTRY_CODES

        return str(value).upper() in KNOWN_COUNTRY_CODES
    if key == "surname":  # a country code or label read in place of the surname
        return str(value).upper() not in ("IND", "INDIAN", "SURNAME", "NAME")
    return True


# How many boxes of each class a known card layout carries (anything unlisted: one).
_MAX_INSTANCES = {
    "aadhar": {"document_number": 2},           # number printed on front and back
    "national_id": {"document_number": 2},
    "driving_license": {"date_of_issue": 2},    # issue date printed on front and back
}
_MIN_PARSE_RATE = 0.75
_MAX_EXCESS_BOXES = 1


def assess_layout(document_type: str, reads: list[RegionRead]) -> tuple[bool, str]:
    """Is this a card layout the detector knows?

    The detector was trained on one template per document type. On any other
    layout it still returns boxes, often with high confidence, but they land
    on the wrong text. Two symptoms give that away and neither depends on the
    confidence score: the text in a box is not the kind of value its class
    promises (a place name in a "date of birth" box), and a field that the
    template prints once is found several times. Region readings are only
    used when both checks pass; otherwise the full-page reading stands alone.
    """
    if document_type not in _KEYS:
        return False, f"no region layout is known for document type '{document_type}'"
    relevant = [r for r in reads if r.class_name == "document_number" or r.class_name in _KEYS[document_type]]
    if len(relevant) < 3:
        return False, "too few fields were located to recognise the layout"
    parsed = sum(1 for r in relevant if _parse(document_type, r))
    rate = parsed / len(relevant)
    counts: dict[str, int] = {}
    for r in relevant:
        counts[r.class_name] = counts.get(r.class_name, 0) + 1
    allowed = _MAX_INSTANCES.get(document_type, {})
    excess = sum(max(0, n - allowed.get(cls, 1)) for cls, n in counts.items())
    if rate < _MIN_PARSE_RATE:
        return False, (f"only {parsed} of {len(relevant)} located boxes hold the kind of value expected there "
                       "(unfamiliar card layout)")
    if excess > _MAX_EXCESS_BOXES:
        return False, f"{excess} more field boxes were found than this card type prints (unfamiliar card layout)"
    return True, f"{parsed} of {len(relevant)} located boxes read as the expected kind of value"


def merge_region_fields(document_type: str, fields: dict, reads: list[RegionRead]) -> tuple[dict, dict]:
    """Combine full-page fields with region readings.

    Returns (fields, sources) where sources maps each affected key to
    "region" (taken from a detected box) or "page+region" (both agree).
    Nothing is merged unless assess_layout() recognises the card.
    """
    merged, sources = dict(fields), {}
    if not assess_layout(document_type, reads)[0]:
        return merged, sources
    best: dict[str, tuple[float, str, dict, bool]] = {}
    for read in reads:
        if read.ocr_confidence < _MIN_OCR_CONFIDENCE:
            continue
        parsed = _parse(document_type, read)
        if not parsed:
            continue
        key, value, extra = parsed
        score = read.ocr_confidence * read.detection_confidence
        if key not in best or score > best[key][0]:
            trusted = (read.ocr_confidence >= _TRUSTED_OCR_CONFIDENCE
                       and read.detection_confidence >= _TRUSTED_DETECTION)
            best[key] = (score, value, extra, trusted)

    for key, (_, value, extra, trusted) in best.items():
        current = merged.get(key)
        if current and str(current).replace(" ", "").upper() == str(value).replace(" ", "").upper():
            sources[key] = "page+region"
        elif (trusted or not _page_value_ok(document_type, key, current)
              or (key == "address" and len(value) > len(str(current)))):
            merged[key] = value
            merged.update(extra)
            sources[key] = "region"

    if document_type == "passport" and (sources.get("given_name") == "region" or sources.get("surname") == "region"):
        full = " ".join(filter(None, [merged.get("given_name"), merged.get("surname")]))
        if full:
            merged["name"] = full
            sources["name"] = "region"
    if document_type == "driving_license" and merged.get("valid_till") and not merged.get("expiry_date"):
        merged["expiry_date"] = merged["valid_till"]
    return merged, sources
