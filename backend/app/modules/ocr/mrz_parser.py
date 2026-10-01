"""
Machine Readable Zone (MRZ) parsing per ICAO Doc 9303.

This is the one piece of the pipeline that is fully deterministic and
standards-based rather than heuristic: passports (TD3 format) print a
two-line, 44-characters-per-line MRZ at the bottom of the photo page, and
each numeric field is protected by a check digit computed with a published
weighting algorithm. If OCR reads the MRZ correctly, we can *mathematically
prove* whether the printed number, date of birth, and expiry date are
internally consistent — this is exactly the kind of signal a border officer
cannot get from squinting at a passport.

Reference: ICAO Doc 9303, Part 4, Section 4.9 (check digit algorithm) and
Section 4.2.2 (TD3 MRZ layout for passports).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_WEIGHTS = (7, 3, 1)


def _char_value(ch: str) -> int:
    if ch == "<":
        return 0
    if ch.isdigit():
        return int(ch)
    if ch.isalpha():
        return ord(ch.upper()) - ord("A") + 10
    raise ValueError(f"Invalid MRZ character: {ch!r}")


def compute_check_digit(data: str) -> int:
    """ICAO 9303 check-digit algorithm: weighted sum mod 10, weights 7-3-1 repeating."""
    total = 0
    for i, ch in enumerate(data):
        total += _char_value(ch) * _WEIGHTS[i % 3]
    return total % 10


def _clean_line(line: str) -> str:
    # OCR frequently confuses '<' with 'K', 'C', or drops it; normalize common
    # noise but keep this conservative so we don't hide genuine tampering.
    return re.sub(r"[^A-Z0-9<]", "", line.upper())


@dataclass
class MRZField:
    name: str
    value: str
    check_digit_expected: int | None = None
    check_digit_found: int | None = None

    @property
    def valid(self) -> bool | None:
        if self.check_digit_expected is None:
            return None
        return self.check_digit_expected == self.check_digit_found


@dataclass
class MRZResult:
    detected: bool
    format: str | None = None  # "TD3" (passport/visa) etc.
    document_type: str | None = None
    issuing_country: str | None = None
    surname: str | None = None
    given_names: str | None = None
    fields: list[MRZField] = field(default_factory=list)
    composite_valid: bool | None = None
    raw_lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nationality: str | None = None
    sex: str | None = None
    date_of_birth: str | None = None  # ISO yyyy-mm-dd, best-effort century guess
    date_of_expiry: str | None = None

    @property
    def all_checks_pass(self) -> bool:
        if not self.detected:
            return False
        field_checks = [f.valid for f in self.fields if f.valid is not None]
        checks = field_checks + ([self.composite_valid] if self.composite_valid is not None else [])
        return bool(checks) and all(checks)


def _find_td3_lines(raw_text: str) -> list[str] | None:
    """
    Look for two 44-character MRZ lines inside noisy OCR output.
    OCR word-splitting means the MRZ often doesn't come back as a clean
    line, so we also try reconstructing 44-char runs from concatenated
    uppercase/`<`/digit tokens.
    """
    # Preferred: a name line (P<ISS...<<...) followed by a 40+ char data line.
    # Tesseract often drops the trailing '<' filler of line 1, so it may be short.
    cleaned = [_clean_line(l) for l in raw_text.splitlines()]
    cleaned = [c for c in cleaned if c]
    for i in range(len(cleaned) - 1):
        l1, l2 = cleaned[i], cleaned[i + 1]
        if (re.fullmatch(r"[PVI][A-Z<][A-Z<]{3}[A-Z<]*<<[A-Z<]*", l1) and len(l1) >= 15
                and re.fullmatch(r"[A-Z0-9<]{40,46}", l2) and "<" in l2):
            return [(l1 + "<" * 44)[:44], (l2 + "<" * 44)[:44]]

    # Every real MRZ line carries '<' filler; requiring it stops ordinary
    # uppercase text (headers, addresses) being mistaken for an MRZ.
    candidates = [
        _clean_line(l) for l in raw_text.splitlines() if len(_clean_line(l)) >= 40
    ]
    candidates = [c for c in candidates if re.fullmatch(r"[A-Z0-9<]{40,46}", c) and "<" in c]

    if len(candidates) < 2:
        # Fall back: pull every run of MRZ-legal characters out of the whole
        # blob and slice into 44-char windows.
        blob = _clean_line(raw_text.replace(" ", ""))
        runs = re.findall(r"[A-Z0-9<]{40,}", blob)
        for run in runs:
            if len(run) >= 88 and "<" in run[:44] and "<" in run[44:88]:
                candidates = [run[:44], run[44:88]]
                break

    if len(candidates) < 2:
        return None

    # Prefer the pair whose first line starts with a document code (P/V/I).
    lines = candidates[-2:]
    for i in range(len(candidates) - 1):
        if re.match(r"[PVI][A-Z<][A-Z<]{3}", candidates[i]):
            lines = candidates[i:i + 2]
            break
    return [(l + "<" * 44)[:44] for l in lines]


_LETTER_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
                                  "S": "5", "G": "6", "B": "8"})
_DIGIT_TO_LETTER = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
# TD3 line 2: positions that ICAO 9303 defines as digits-only / letters-only.
_TD3_DIGIT_POSITIONS = [9, *range(13, 20), *range(21, 28), 43]
_TD3_LETTER_POSITIONS = [10, 11, 12, 20]


def _fix_numeric_positions(line2: str) -> str:
    """Undo OCR letter/digit confusions only where the format leaves no doubt
    (e.g. an 'S' inside the date-of-birth field must be a '5')."""
    chars = list(line2)
    for i in _TD3_DIGIT_POSITIONS:
        if i < len(chars) and chars[i] != "<":
            chars[i] = chars[i].translate(_LETTER_TO_DIGIT)
    for i in _TD3_LETTER_POSITIONS:
        if i < len(chars) and chars[i] != "<":
            chars[i] = chars[i].translate(_DIGIT_TO_LETTER)
    return "".join(chars)


_FILLER_LOOKALIKES = set("<CEDKXL")


def _fix_name_filler(line1: str) -> str:
    """Names never contain '<<<'; once that run appears after the surname
    separator, the rest of line 1 is filler that OCR misread (C/E/D/K)."""
    sep = line1.find("<<", 5)
    if sep == -1:
        return line1
    run = line1.find("<<<", sep + 2)
    if run == -1:
        return line1
    return line1[:run] + "<" * (len(line1) - run)


def _fix_personal_filler(line2: str) -> str:
    field = line2[28:42]
    if field.count("<") >= 3 and set(field) <= _FILLER_LOOKALIKES:
        return line2[:28] + "<" * 14 + line2[42:]
    return line2


_NUMBER_SWAPS = {"0": "O", "O": "0", "1": "I", "I": "1"}


def _fix_document_number(line2: str) -> tuple[str, str | None]:
    """Resolve O/0 and I/1 ambiguity in the document number using its own
    check digit. Only a variant that validates is accepted, so a genuinely
    wrong number is never 'fixed'."""
    number, check = line2[0:9], line2[9]
    if not check.isdigit():
        return line2, None
    try:
        if compute_check_digit(number) == int(check):
            return line2, None
    except ValueError:
        return line2, None
    positions = [i for i, c in enumerate(number) if c in _NUMBER_SWAPS]
    if not positions or len(positions) > 6:
        return line2, None
    from itertools import product

    for choice in product([False, True], repeat=len(positions)):
        if not any(choice):
            continue
        chars = list(number)
        for pos, swap in zip(positions, choice):
            if swap:
                chars[pos] = _NUMBER_SWAPS[chars[pos]]
        candidate = "".join(chars)
        if compute_check_digit(candidate) == int(check):
            return candidate + line2[9:], number.replace("<", "")
    return line2, None


def parse_mrz(raw_text: str) -> MRZResult:
    lines = _find_td3_lines(raw_text)
    if not lines:
        return MRZResult(detected=False, warnings=["No MRZ block detected in OCR output."])

    line1, line2 = lines
    line1 = _fix_name_filler(line1)
    line2 = _fix_personal_filler(_fix_numeric_positions(line2))
    line2, number_corrected = _fix_document_number(line2)
    warnings: list[str] = []
    if number_corrected:
        warnings.append(
            f"Document number read as '{number_corrected}' by OCR; corrected O/0 or I/1 confusion "
            "because only the corrected form satisfies its check digit."
        )

    if not line1.startswith(("P<", "P")):
        warnings.append("Line 1 does not start with the expected document code 'P'.")

    doc_type = line1[0:2].replace("<", "")
    issuing_country = line1[2:5].replace("<", "")

    name_field = line1[5:44]
    surname, _, given = name_field.partition("<<")
    surname = surname.replace("<", " ").strip()
    given_names = given.replace("<", " ").strip()

    passport_number_raw = line2[0:9]
    passport_check = line2[9]
    nationality = line2[10:13].replace("<", "")
    dob_raw = line2[13:19]
    dob_check = line2[19]
    sex = line2[20]
    expiry_raw = line2[21:27]
    expiry_check = line2[27]
    personal_number_raw = line2[28:42]
    personal_check = line2[42]

    def make_field(name: str, value: str, expected_digit_char: str) -> MRZField:
        try:
            expected = int(expected_digit_char)
        except ValueError:
            expected = None
        try:
            found = compute_check_digit(value)
        except ValueError:
            found = None
        return MRZField(name=name, value=value, check_digit_expected=expected, check_digit_found=found)

    fields = [
        make_field("passport_number", passport_number_raw, passport_check),
        make_field("date_of_birth", dob_raw, dob_check),
        make_field("date_of_expiry", expiry_raw, expiry_check),
    ]
    if personal_number_raw.strip("<"):
        fields.append(make_field("personal_number", personal_number_raw, personal_check))

    # Composite check digit covers positions 0-9, 13-19, 21-42 of line 2.
    composite_input = line2[0:10] + line2[13:20] + line2[21:43]
    composite_check_char = line2[43] if len(line2) > 43 else "0"
    composite_valid: bool | None
    try:
        composite_expected = int(composite_check_char)
        composite_valid = compute_check_digit(composite_input) == composite_expected
    except ValueError:
        composite_valid = None

    this_yy = date.today().year % 100

    def fmt_date(raw: str, kind: str) -> str | None:
        if len(raw) != 6 or not raw.isdigit():
            return None
        yy, mm, dd = raw[0:2], raw[2:4], raw[4:6]
        # MRZ years are 2-digit. A birth year cannot be in the future; an
        # expiry year is at most ~10 years ahead and rarely decades old.
        if kind == "dob":
            century = "20" if int(yy) <= this_yy else "19"
        else:
            century = "20" if int(yy) <= this_yy + 20 else "19"
        return f"{century}{yy}-{mm}-{dd}"

    return MRZResult(
        detected=True,
        format="TD3",
        document_type=doc_type or "P",
        issuing_country=issuing_country,
        surname=surname or None,
        given_names=given_names or None,
        fields=fields,
        composite_valid=composite_valid,
        raw_lines=[line1, line2],
        warnings=warnings,
        nationality=nationality or None,
        sex=sex if sex in ("M", "F") else None,
        date_of_birth=fmt_date(dob_raw, "dob"),
        date_of_expiry=fmt_date(expiry_raw, "expiry"),
    )
