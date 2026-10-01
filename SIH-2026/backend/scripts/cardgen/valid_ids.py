"""Replace the workbook's random identifiers with ones that follow the real rules.

The spreadsheet's numbers were random, so the screening pipeline (correctly)
rejected most generated cards: ~89% of Aadhaar numbers failed Verhoeff, 299 of
300 passport MRZs had wrong check digits, and PAN letters ignored the holder
type and surname rules. A dataset meant to represent *genuine* documents must
pass those checks, so every identifier is regenerated here, deterministically
per person (same serial -> same numbers on every run), before rendering. The
QR payloads and the sidecar annotations read the same values, so all three
stay consistent.

Rules applied
-------------
* Aadhaar  12 digits, first digit 2-9 (0/1 are never issued), last digit is the
           Verhoeff check digit over the first 11.
* PAN      AAA + P (individual) + first letter of the surname + 4 digits + letter.
* Passport ICAO 9303 TD3 MRZ rebuilt from the printed fields, with correct check
           digits for the number, DOB, expiry, personal number and composite.
           The number keeps the Indian format: one letter + 7 digits.
* Dates    Passports issued in the last 9 years, expiring 10 years less a day later
           (none already expired); DLs issued at 18+ with Motor Vehicles Act validity.
* DL       Every card uses the Delhi transport-department background, so every
           licence is a Delhi licence: ``DL-RRYYYYNNNNNNN`` (RTO code, year of
           issue, 7-digit serial) issued by a real Delhi RTO zone. Holders may
           live elsewhere now; the address stays as in the workbook.
"""
from __future__ import annotations

import random
import re
import string
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.modules.ocr.indian_extractors import verhoeff_checksum  # noqa: E402
from app.modules.ocr.mrz_parser import compute_check_digit  # noqa: E402

# Delhi RTO zones and their codes (DL-01 … ); used for the licensing authority.
DELHI_RTOS = {
    "01": "RTO Mall Road", "02": "RTO IP Estate", "03": "RTO Sheikh Sarai", "04": "RTO Janakpuri",
    "05": "RTO Loni Road", "06": "RTO Sarai Kale Khan", "07": "RTO Mayur Vihar", "08": "RTO Wazirpur",
    "09": "RTO Janakpuri", "10": "RTO Raja Garden", "11": "RTO Rohini", "12": "RTO Vasant Vihar",
    "13": "RTO Surajmal Vihar", "14": "RTO Burari",
}

DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _rng(serial: str, field: str) -> random.Random:
    return random.Random(f"pehchaan-cardgen|{serial}|{field}")


def aadhaar_number(serial: str) -> str:
    r = _rng(serial, "aadhaar")
    body = str(r.randint(2, 9)) + "".join(str(r.randint(0, 9)) for _ in range(10))
    for d in "0123456789":
        if verhoeff_checksum(body + d):
            return body + d
    raise AssertionError("no Verhoeff digit found")  # cannot happen: exactly one digit validates


def pan_number(serial: str, surname: str) -> str:
    r = _rng(serial, "pan")
    initial = next((c for c in (surname or "").upper() if c.isalpha()), "X")
    first = "".join(r.choice(string.ascii_uppercase) for _ in range(3))
    digits = "".join(str(r.randint(0, 9)) for _ in range(4))
    return f"{first}P{initial}{digits}{r.choice(string.ascii_uppercase)}"


def passport_number(serial: str, current: str) -> str:
    if re.fullmatch(r"[A-Z]\d{7}", current or ""):
        return current
    r = _rng(serial, "passport")
    return r.choice("JKLMNPRSTUVWZ") + str(r.randint(1, 9)) + "".join(str(r.randint(0, 9)) for _ in range(6))


def _yymmdd(ddmmyyyy: str) -> str | None:
    m = DATE_RE.match((ddmmyyyy or "").strip())
    return f"{m.group(3)[2:]}{m.group(2)}{m.group(1)}" if m else None


def _mrz_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Z ]", "", (value or "").upper())
    return "<".join(cleaned.split())


def mrz_lines(p: dict) -> tuple[str, str] | None:
    number = p.get("Passport_Number", "")
    dob, expiry = _yymmdd(p.get("Passport_DOB", "")), _yymmdd(p.get("Passport_Date_Of_Expiry", ""))
    sex = (p.get("Passport_Sex") or "").strip().upper()[:1]
    if not (number and dob and expiry and sex in ("M", "F")):
        return None
    code = (p.get("Passport_Country_Code") or "IND").upper()[:3]
    line1 = f"P<{code}{_mrz_name(p.get('Passport_Surname', ''))}<<{_mrz_name(p.get('Passport_Given_Name', ''))}"
    line1 = (line1 + "<" * 44)[:44]
    doc = number.ljust(9, "<")
    personal = "<" * 14
    cds = [compute_check_digit(x) for x in (doc, dob, expiry, personal)]
    composite = compute_check_digit(f"{doc}{cds[0]}{dob}{cds[1]}{expiry}{cds[2]}{personal}{cds[3]}")
    line2 = f"{doc}{cds[0]}{code}{dob}{cds[1]}{sex}{expiry}{cds[2]}{personal}{cds[3]}{composite}"
    return line1, line2


def dl_number(serial: str, issue_date: str) -> tuple[str, str]:
    r = _rng(serial, "dl")
    rto = r.choice(sorted(DELHI_RTOS))
    m = DATE_RE.match((issue_date or "").strip())
    year = m.group(3) if m else str(r.randint(2005, date.today().year))
    # the card slot fits "RTO Delhi (NN)"; the zone name is kept in DELHI_RTOS for reference
    return f"DL-{rto}{year}{r.randint(0, 9999999):07d}", f"RTO Delhi ({rto})"


def _parse(s: str) -> date | None:
    m = DATE_RE.match((s or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def passport_dates(serial: str, today: date) -> tuple[date, date]:
    """Issued within the last 9 years; adult passports expire 10 years less a day later."""
    r = _rng(serial, "passport-dates")
    issue = today - timedelta(days=r.randint(30, 9 * 365))
    return issue, _add_years(issue, 10) - timedelta(days=1)


def dl_dates(serial: str, dob: date | None, today: date) -> tuple[date, date]:
    """Issue at 18+ within the last 15 years; non-transport validity per the
    Motor Vehicles Act age bands (till 40 if issued under 30, 10 years from 30
    to 50, till 60 from 50 to 55, then 5 years)."""
    r = _rng(serial, "dl-dates")
    earliest = max(_add_years(dob, 18) if dob else today - timedelta(days=15 * 365), today - timedelta(days=15 * 365))
    span = max(1, (today - timedelta(days=30) - earliest).days)
    issue = earliest + timedelta(days=r.randint(0, span))
    if not dob:
        return issue, _add_years(issue, 20) - timedelta(days=1)
    age = issue.year - dob.year - ((issue.month, issue.day) < (dob.month, dob.day))
    if age < 30:
        valid = _add_years(dob, 40) - timedelta(days=1)
    elif age < 50:
        valid = _add_years(issue, 10) - timedelta(days=1)
    elif age < 55:
        valid = _add_years(dob, 60) - timedelta(days=1)
    else:
        valid = _add_years(issue, 5) - timedelta(days=1)
    return issue, valid


def normalise_identifiers(person: dict, today: date | None = None) -> dict:
    """Rewrite identifier and date fields in place; returns a {field: (old, new)} change log."""
    today = today or date.today()
    serial = str(person.get("serial", ""))
    surname = person.get("Passport_Surname") or person.get("Last Name") or (person.get("Name", "").split() or [""])[-1]
    changes: dict[str, tuple[str, str]] = {}

    def put(key: str, value: str) -> None:
        old = str(person.get(key, ""))
        if key in person and old != value:
            changes[key] = (old, value)
        if key in person:
            person[key] = value

    # Dates first: the MRZ encodes the passport expiry and the DL number the issue year.
    if "Passport_Date_Of_Issue" in person or "Passport_Date_Of_Expiry" in person:
        issue, expiry = passport_dates(serial, today)
        put("Passport_Date_Of_Issue", _fmt(issue))
        put("Passport_Date_Of_Expiry", _fmt(expiry))
    if "DL_Number" in person:
        dob = _parse(person.get("DOB") or person.get("Aadhaar_DOB") or person.get("Passport_DOB", ""))
        issue, valid = dl_dates(serial, dob, today)
        put("Date_Of_Issue", _fmt(issue))
        put("Issue_Date", _fmt(issue))
        put("Validity_NT", _fmt(valid))

    if "Aadhaar_Number" in person:
        put("Aadhaar_Number", aadhaar_number(serial))
    if "PAN_Number" in person:
        put("PAN_Number", pan_number(serial, surname))
    if "Passport_Number" in person:
        put("Passport_Number", passport_number(serial, person["Passport_Number"]))
        lines = mrz_lines(person)
        if lines:
            put("Passport_MRZ_Line_1", lines[0])
            put("Passport_MRZ_Line_2", lines[1])
    if "DL_Number" in person:
        number, authority = dl_number(serial, person.get("Date_Of_Issue") or person.get("Issue_Date", ""))
        put("DL_Number", number)
        put("Licensing_Authority", authority)
    return changes
