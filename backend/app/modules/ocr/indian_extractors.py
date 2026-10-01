"""
Indian document-specific field extractors with format validation.

Each extractor understands the real layout and format constraints of
Indian identity documents — Aadhaar, PAN, Driving Licence, Passport
visual zone — so OCR noise gets filtered out by structural validation
rather than relying on clean text.
"""
from __future__ import annotations

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Verhoeff checksum (used by UIDAI for Aadhaar numbers)
# ---------------------------------------------------------------------------

_VERHOEFF_D = [
    [0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0],
]
_VERHOEFF_P = [
    [0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8],
]
_VERHOEFF_INV = [0,4,3,2,1,5,6,7,8,9]


def verhoeff_checksum(number: str) -> bool:
    """Validate a number string using the Verhoeff algorithm (Aadhaar uses this)."""
    digits = [int(d) for d in reversed(number) if d.isdigit()]
    if len(digits) < 2:
        return False
    c = 0
    for i, d in enumerate(digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][d]]
    return c == 0


# ---------------------------------------------------------------------------
# Line-aware helpers: on printed IDs the label usually sits on one line and
# its value on the same line or one to three lines below (the lines between
# are often OCR noise from the Hindi label).
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{2})\s*[/\-.]\s*(\d{2})\s*[/\-.]\s*(\d{4})")
_NOT_A_NAME = {
    "NAME", "FATHER", "FATHERS", "MOTHER", "DATE", "BIRTH", "GENDER", "MALE", "FEMALE",
    "ADDRESS", "SIGNATURE", "GOVERNMENT", "INDIA", "SPECIMEN", "SYNTHETIC", "INCOME",
    "TAX", "DEPARTMENT", "PERMANENT", "ACCOUNT", "NUMBER", "AADHAAR", "REPUBLIC",
    "PASSPORT", "NATIONALITY", "PLACE", "ISSUE", "EXPIRY", "AUTHORITY", "CARD", "OF",
    "GIVEN", "SURNAME", "LICENCE", "LICENSE", "DRIVING", "VALID", "HOLDER", "SPOUSE",
}


def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


def _as_name(candidate: str) -> str | None:
    cleaned = re.sub(r"^[^A-Za-z]+|[^A-Za-z.]+$", "", candidate).strip()
    if not cleaned or not re.fullmatch(r"[A-Za-z][A-Za-z.']*(?:\s+[A-Za-z][A-Za-z.']*){0,4}", cleaned):
        return None
    words = cleaned.split()
    if not all(w[0].isupper() for w in words):
        return None
    if sum(c.isalpha() for c in cleaned) < 3:
        return None
    if any(w.upper().strip(".") in _NOT_A_NAME for w in words):
        return None
    return cleaned


def _as_date(candidate: str, index: int = 0) -> str | None:
    found = _DATE_RE.findall(candidate)
    if len(found) <= index:
        return None
    d, mo, y = found[index]
    return _parse_indian_date(f"{d}/{mo}/{y}")


def _value_near_label(lines: list[str], label: str, parse, lookahead: int = 3,
                      exclude: str | None = None) -> str | None:
    for i, line in enumerate(lines):
        m = re.search(label, line, re.IGNORECASE)
        if not m or (exclude and re.search(exclude, line, re.IGNORECASE)):
            continue
        rest = line[m.end():].strip(" :-/|")
        for candidate in [rest] + lines[i + 1:i + 1 + lookahead]:
            value = parse(candidate) if candidate else None
            if value:
                return value
    return None


def _date_near_label(lines: list[str], label: str, all_date_labels: list[str], lookahead: int = 3) -> str | None:
    """Handles two labels sharing a line ("Date of Issue   Date of Expiry")
    with their values in the same left-to-right order on the next line."""
    for i, line in enumerate(lines):
        m = re.search(label, line, re.IGNORECASE)
        if not m:
            continue
        positions = sorted(
            mm.start() for lbl in all_date_labels for mm in re.finditer(lbl, line, re.IGNORECASE)
        )
        index = positions.index(m.start()) if m.start() in positions else 0
        rest = line[m.end():]
        if _DATE_RE.search(rest):
            return _as_date(rest, 0)
        for candidate in lines[i + 1:i + 1 + lookahead]:
            if _DATE_RE.search(candidate):
                return _as_date(candidate, index)
    return None


_PAN_TOKEN = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{10})(?![A-Z0-9])")
_TO_LETTER = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})
_TO_DIGIT = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6", "D": "0"})


def _find_pan(raw_text: str) -> str | None:
    upper = raw_text.upper()
    exact = re.search(r"(?<![A-Z0-9])([A-Z]{5}\d{4}[A-Z])(?![A-Z0-9])", upper)
    if exact:
        return exact.group(1)
    for tok in _PAN_TOKEN.findall(upper):
        fixed = tok[:5].translate(_TO_LETTER) + tok[5:9].translate(_TO_DIGIT) + tok[9].translate(_TO_LETTER)
        if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", fixed) and sum(c.isdigit() for c in tok) >= 2:
            return fixed
    return None


# ---------------------------------------------------------------------------
# Aadhaar
# ---------------------------------------------------------------------------

_AADHAAR_PATTERN = re.compile(r"\b(\d{4})\s*(\d{4})\s*(\d{4})\b")
_VID_PATTERN = re.compile(r"\b(\d{4})\s*(\d{4})\s*(\d{4})\s*(\d{4})\b")

_AADHAAR_NAME_LABELS = [
    r"(?:name|naam)\s*[:\-]?\s*([A-Za-z ]{2,50})",
]
_AADHAAR_DOB_LABELS = [
    r"(?:DOB|Date of Birth|D\.O\.B|जन्म\s*तिथि)\s*[:\-]?\s*(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})",
    r"(?:Year of Birth|YOB|जन्म\s*वर्ष)\s*[:\-]?\s*(\d{4})",
]
_AADHAAR_GENDER_LABELS = [
    r"(?:MALE|FEMALE|पुरुष|महिला|TRANSGENDER)",
]
_AADHAAR_ADDRESS_LABELS = [
    r"(?:Address|पता)\s*[:\-]?\s*(.{10,200}?)(?=\d{6}|\n\n|$)",
]
_PINCODE_PATTERN = re.compile(r"\b([1-9]\d{5})\b")


def extract_aadhaar_fields(raw_text: str) -> dict:
    fields: dict = {}

    # Aadhaar number (12 digits, often printed as XXXX XXXX XXXX)
    aadhaar_matches = _AADHAAR_PATTERN.findall(raw_text)
    for groups in aadhaar_matches:
        number = "".join(groups)
        if len(number) == 12 and number[0] != "0" and number[0] != "1":
            if verhoeff_checksum(number):
                fields["id_number"] = f"{groups[0]} {groups[1]} {groups[2]}"
                fields["aadhaar_valid"] = True
                break
            else:
                fields["id_number"] = f"{groups[0]} {groups[1]} {groups[2]}"
                fields["aadhaar_valid"] = False

    # VID (Virtual ID, 16 digits)
    if not fields.get("id_number"):
        vid_matches = _VID_PATTERN.findall(raw_text)
        for groups in vid_matches:
            number = "".join(groups)
            if len(number) == 16 and number[0] != "0":
                if verhoeff_checksum(number):
                    fields["id_number"] = " ".join(groups)
                    fields["id_type"] = "VID"
                    fields["aadhaar_valid"] = True
                    break

    lines = _lines(raw_text)

    # Name: value on the label line or just below it
    name = _value_near_label(lines, r"\b(?:name|naam)\b", _as_name, exclude=r"father|mother")
    if name:
        fields["name"] = name

    # If no labeled name, look for lines that are just names (uppercase, 2+ words)
    if "name" not in fields:
        for line in raw_text.split("\n"):
            line = line.strip()
            if re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?", line):
                fields["name"] = line
                break

    # DOB (or year of birth on older cards)
    dob = _value_near_label(lines, r"DOB|Date of Birth|D\.O\.B|जन्म\s*तिथि", _as_date)
    if dob:
        fields["date_of_birth"] = dob
    else:
        m = re.search(_AADHAAR_DOB_LABELS[1], raw_text, re.IGNORECASE)
        if m:
            fields["date_of_birth"] = _parse_indian_date(m.group(1))

    # Gender
    for pattern in _AADHAAR_GENDER_LABELS:
        m = re.search(pattern, raw_text, re.IGNORECASE)
        if m:
            gender_text = m.group(0).upper()
            if gender_text in ("MALE", "पुरुष"):
                fields["gender"] = "Male"
            elif gender_text in ("FEMALE", "महिला"):
                fields["gender"] = "Female"
            else:
                fields["gender"] = "Other"
            break

    # Address + Pincode
    for pattern in _AADHAAR_ADDRESS_LABELS:
        m = re.search(pattern, raw_text, re.IGNORECASE | re.DOTALL)
        if m:
            addr = m.group(1).strip()
            addr = re.sub(r"\s+", " ", addr)
            fields["address"] = addr
            break

    pin_match = _PINCODE_PATTERN.search(raw_text)
    if pin_match:
        fields["pincode"] = pin_match.group(1)

    # State detection from pincode or text
    state = _detect_state(raw_text)
    if state:
        fields["state"] = state

    return fields


# ---------------------------------------------------------------------------
# PAN Card
# ---------------------------------------------------------------------------

_PAN_PATTERN = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")
_PAN_HOLDER_TYPES = {
    "A": "Association of Persons (AOP)",
    "B": "Body of Individuals (BOI)",
    "C": "Company",
    "F": "Firm",
    "G": "Government",
    "H": "Hindu Undivided Family",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "P": "Individual",
    "T": "Trust",
}


def extract_pan_fields(raw_text: str) -> dict:
    fields: dict = {}

    # PAN number: ABCDE1234F
    # 1-3: Alpha (random), 4: holder type, 5: first letter of surname (for P type)
    pan = _find_pan(raw_text)
    if pan:
        fields["id_number"] = pan
        holder_char = pan[3]
        fields["pan_holder_type"] = _PAN_HOLDER_TYPES.get(holder_char, "Unknown")
        fields["pan_valid"] = True
    else:
        fields["pan_valid"] = False

    lines = _lines(raw_text)
    name = _value_near_label(lines, r"\bname\b|नाम", _as_name, exclude=r"father|पिता")
    if name:
        fields["name"] = name

    father = _value_near_label(lines, r"father'?s?\s*name|पिता\s*का\s*नाम", _as_name)
    if father:
        fields["father_name"] = father

    dob = _value_near_label(lines, r"date of birth|DOB|जन्म", _as_date) or _as_date(raw_text)
    if dob:
        fields["date_of_birth"] = dob

    return fields


# ---------------------------------------------------------------------------
# Indian Driving Licence
# ---------------------------------------------------------------------------

# Format: SS-RR-YYYYNNNNNNN or SS-RRYYYYYYNNNNNNN (varies by state)
_DL_PATTERNS = [
    re.compile(r"\b([A-Z]{2})\s*[\-]?\s*(\d{2})\s*[\-]?\s*(\d{4})\s*[\-]?\s*(\d{7})\b"),
    re.compile(r"\b([A-Z]{2}\d{2})\s*[\-]?\s*(\d{11})\b"),
    re.compile(r"\b(DL|dl)\s*[:\-]?\s*([A-Z]{2}\d{2,14})\b"),
]

_INDIAN_STATES_RTO = {
    "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML",
    "MN", "MP", "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK",
    "TN", "TR", "TS", "UK", "UP", "WB", "AN",
}

_COV_TYPES = {
    "LMV": "Light Motor Vehicle",
    "MCWG": "Motor Cycle With Gear",
    "MCWOG": "Motor Cycle Without Gear",
    "HMV": "Heavy Motor Vehicle",
    "HGMV": "Heavy Goods Motor Vehicle",
    "HPMV": "Heavy Passenger Motor Vehicle",
    "LMV-NT": "Light Motor Vehicle (Non-Transport)",
    "LMV-TR": "Light Motor Vehicle (Transport)",
    "3W-NT": "Three Wheeler (Non-Transport)",
    "3W-TR": "Three Wheeler (Transport)",
}


def extract_dl_fields(raw_text: str) -> dict:
    fields: dict = {}

    # DL Number
    for pattern in _DL_PATTERNS:
        m = pattern.search(raw_text.upper())
        if m:
            dl_num = "".join(m.groups())
            state_code = dl_num[:2]
            if state_code in _INDIAN_STATES_RTO:
                fields["license_number"] = dl_num
                fields["issuing_state"] = state_code
                fields["dl_format_valid"] = True
                break

    lines = _lines(raw_text)
    name = _value_near_label(lines, r"\bname\b|नाम", _as_name, exclude=r"father|guardian|S/W/D")
    if name:
        fields["name"] = name

    # S/W/D of (Son/Wife/Daughter of)
    swd = _find_labeled(raw_text, [r"S/W/D\s*of", r"S/o", r"D/o", r"W/o",
                                     "Son of", "Daughter of", "Wife of",
                                     "पिता/पति का नाम"])
    if swd:
        fields["guardian_name"] = swd

    # DOB
    dob = _value_near_label(lines, r"DOB|Date of Birth|जन्म\s*तिथि", _as_date)
    if dob:
        fields["date_of_birth"] = dob

    # Blood group
    blood_match = re.search(
        r"(?:Blood\s*(?:Group|Gr\.?)|BG)\s*[:\-]?\s*((?:A|B|AB|O)[+\-](?:\s*(?:ve)?)?)",
        raw_text, re.IGNORECASE,
    )
    if not blood_match:
        blood_match = re.search(r"\b((?:AB|A|B|O)[+\-])\b", raw_text)
    if blood_match:
        fields["blood_group"] = blood_match.group(1).strip().upper()

    # Class of Vehicle
    for cov_code in _COV_TYPES:
        if cov_code in raw_text.upper():
            fields.setdefault("class_of_vehicle", []).append(cov_code)

    # Validity dates
    valid_till = _value_near_label(
        lines, r"(?:Valid|Validity|NT|TR)\s*(?:Till|Upto|to)|Date of Expiry|Valid Till", _as_date)
    if valid_till:
        fields["valid_till"] = valid_till

    # Address + Pincode
    pin_match = _PINCODE_PATTERN.search(raw_text)
    if pin_match:
        fields["pincode"] = pin_match.group(1)

    state = _detect_state(raw_text)
    if state:
        fields["state"] = state

    return fields


# ---------------------------------------------------------------------------
# Passport Visual Zone (non-MRZ fields printed on the passport page)
# ---------------------------------------------------------------------------

_PASSPORT_NUMBER_PATTERN = re.compile(r"\b([A-Z]\d{7})\b")
_PLACE_OF_BIRTH_LABELS = ["Place of Birth", "जन्म स्थान", "POB"]
_PLACE_OF_ISSUE_LABELS = ["Place of Issue", "जारी करने का स्थान", "POI"]
_ISSUING_OFFICE_LABELS = ["File No", "File Number"]


def extract_passport_visual_fields(raw_text: str) -> dict:
    fields: dict = {}

    lines = _lines(raw_text)

    # Passport number: prefer the labelled page-1 value (page 2 also prints the OLD passport number)
    def _as_passport_no(candidate: str) -> str | None:
        for tok in re.findall(r"\b[A-Z0-9]{8}\b", candidate.upper()):
            fixed = tok[0].translate(_TO_LETTER) + tok[1:].translate(_TO_DIGIT)
            if _PASSPORT_NUMBER_PATTERN.fullmatch(fixed):
                return fixed
        return None

    pn = _value_near_label(lines, r"Passport\s*(?:No|Number)", _as_passport_no, lookahead=2, exclude=r"old")
    if not pn:
        # Unlabelled: first passport-shaped number before the "previous passport" section.
        for line in lines:
            if re.search(r"old passport|previous passport", line, re.IGNORECASE):
                break
            pn = _as_passport_no(line)
            if pn:
                break
    if pn:
        fields["passport_number_visual"] = pn

    # Name (given name + surname) — OCR often garbles these small labels.
    surname = _value_near_label(lines, r"Sur\s?n?a?me|Sumame|उपनाम", _as_name, lookahead=2)
    if surname:
        fields["surname"] = surname
    given_name = _value_near_label(lines, r"G\w{1,3}n\s*Names?|दिया गया नाम", _as_name, lookahead=2)
    if given_name:
        fields["given_name"] = given_name
    nat_idx = next((i for i, l in enumerate(lines) if re.search(r"\bINDIAN\b|NATIONALITY", l, re.IGNORECASE)), None)
    if not (surname and given_name) and nat_idx is not None:
        # Layout fallback when the small labels are not read: the two lines
        # just above the nationality row are surname then given names.
        names = [n for n in (_as_name(l) for l in lines[max(0, nat_idx - 3):nat_idx]) if n]
        if len(names) >= 2:
            surname, given_name = surname or names[-2], given_name or names[-1]
            fields["surname"], fields["given_name"] = surname, given_name
    if surname or given_name:
        fields["name"] = " ".join(filter(None, [given_name, surname]))

    # Nationality
    if re.search(r"\bINDIAN\b", raw_text.upper()):
        fields["nationality"] = "IND"
    else:
        nationality = _find_labeled(raw_text, ["Nationality", "राष्ट्रीयता"])
        if nationality:
            fields["nationality"] = nationality.upper()[:3]

    # Place of Birth / Issue / Authority
    pob = _value_near_label(lines, r"Place of Birth|जन्म स्थान|\bPOB\b", _as_name, lookahead=2)
    if pob:
        fields["place_of_birth"] = pob

    poi = _value_near_label(lines, r"Place of Issue|Authority|जारी करने का स्थान|\bPOI\b", _as_name, lookahead=2)
    if poi:
        fields["place_of_issue"] = poi

    # Issuing office / File number (contains PSK code)
    file_no = _find_labeled(raw_text, _ISSUING_OFFICE_LABELS)
    if file_no:
        fields["issuing_office"] = file_no

    # Dates
    date_labels = [r"Date of Issue", r"Date of Expiry", r"Date of Birth"]
    labeled_doi = _date_near_label(lines, r"Date of Issue|जारी करने की तारीख|\bDOI\b", date_labels)
    labeled_doe = _date_near_label(lines, r"Date of Expiry|समाप्ति तारीख|\bDOE\b|Valid Until", date_labels)
    labeled_dob = _date_near_label(lines, r"Date of Birth|जन्म तिथि|\bDOB\b", date_labels)
    if not labeled_dob:
        # The DOB label is tiny and often garbled; its value shares a line with nationality.
        labeled_dob = _value_near_label(lines, r"Nationality|National|\bINDIAN\b", _as_date, lookahead=2)
    if not (labeled_doi and labeled_doe):
        # Layout fallback: issue and expiry dates printed side by side on one line.
        for line in lines:
            pair = [_as_date(line, 0), _as_date(line, 1)]
            if all(pair) and pair[0] < pair[1] and pair[0] != labeled_dob:
                labeled_doi, labeled_doe = labeled_doi or pair[0], labeled_doe or pair[1]
                break

    if labeled_doi:
        fields["issue_date"] = labeled_doi
    if labeled_doe:
        fields["expiry_date"] = labeled_doe
    if labeled_dob:
        fields["date_of_birth"] = labeled_dob

    # Gender
    gender_match = re.search(r"\b(MALE|FEMALE|M|F|पुरुष|महिला)\b", raw_text, re.IGNORECASE)
    if gender_match:
        g = gender_match.group(0).upper()
        if g in ("MALE", "M", "पुरुष"):
            fields["gender"] = "M"
        elif g in ("FEMALE", "F", "महिला"):
            fields["gender"] = "F"

    # Address (Old passports have address on page 2)
    address = _find_labeled(raw_text, ["Address", "पता"])
    if address:
        fields["address"] = address
        pin = _PINCODE_PATTERN.search(address)
        if pin:
            fields["pincode"] = pin.group(1)

    state = _detect_state(raw_text)
    if state:
        fields["state"] = state

    return fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INDIAN_STATES = {
    "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "CHHATTISGARH",
    "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JHARKHAND", "KARNATAKA",
    "KERALA", "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA",
    "MIZORAM", "NAGALAND", "ODISHA", "ORISSA", "PUNJAB", "RAJASTHAN",
    "SIKKIM", "TAMIL NADU", "TELANGANA", "TRIPURA", "UTTAR PRADESH",
    "UTTARAKHAND", "UTTARANCHAL", "WEST BENGAL",
    "DELHI", "NEW DELHI", "CHANDIGARH", "PUDUCHERRY", "PONDICHERRY",
    "JAMMU AND KASHMIR", "JAMMU & KASHMIR", "LADAKH",
    "ANDAMAN AND NICOBAR", "DADRA AND NAGAR HAVELI", "DAMAN AND DIU",
    "LAKSHADWEEP",
}


def _detect_state(text: str) -> str | None:
    upper = text.upper()
    for state in _INDIAN_STATES:
        if state in upper:
            return state.title()
    return None


def _find_labeled(text: str, labels: list[str]) -> str | None:
    for label in labels:
        m = re.search(rf"{label}\s*[:\-]?\s*([A-Za-z0-9 /,\.\-]{{2,60}})", text, re.IGNORECASE)
        if m:
            value = m.group(1).strip()
            value = re.split(r"\s{2,}", value)[0].strip()
            if value and not value.isspace():
                return value
    return None


def _find_labeled_date(text: str, labels: list[str]) -> str | None:
    for label in labels:
        m = re.search(
            rf"{label}\s*[:\-]?\s*(\d{{2}}[/\-\.]\d{{2}}[/\-\.]\d{{4}})",
            text, re.IGNORECASE,
        )
        if m:
            return _parse_indian_date(m.group(1))
    return None


def _find_all_dates(text: str) -> list[str]:
    results = []
    for m in re.finditer(r"\b(\d{2})[/\-.](\d{2})[/\-.](\d{4})\b", text):
        d, mo, y = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d))
            results.append(dt.date().isoformat())
        except ValueError:
            pass
    return results


def _parse_indian_date(raw: str) -> str | None:
    """Parse DD/MM/YYYY or DD-MM-YYYY (Indian format) to ISO date."""
    if not raw:
        return None

    # Year only (from YOB field)
    if re.fullmatch(r"\d{4}", raw):
        return f"{raw}-01-01"

    m = re.match(r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})", raw)
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d))
        return dt.date().isoformat()
    except ValueError:
        return None
