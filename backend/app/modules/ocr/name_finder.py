"""Finds the document holder's name anywhere in a card's OCR text.

Different cards print the name in different places, with or without a label,
and OCR adds stray marks around it. Instead of looking in one place, every
line (and every run of capitalised words inside a line) is scored on
independent pieces of evidence, and the best candidate wins if its score is
high enough. Otherwise no name is reported: a missing name is better than a
wrong one.

Evidence for a candidate:
  * shape: two to four capitalised alphabetic words, the whole line or nearly;
  * a "Name" label on the same line or just above;
  * a date-of-birth or gender line within two lines;
  * a line in Devanagari just above (bilingual cards print the name twice);
  * words that are common Indian name parts (a weak hint only).
Evidence against:
  * a word that names an organisation, a heading or a field;
  * a father's, mother's, husband's or guardian's label next to it, so a
    relative's name is not taken for the holder's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_NAME_LABEL = re.compile(r"(?<![A-Za-z])(?:name|naam)(?![A-Za-z])|नाम", re.IGNORECASE)
_RELATIVE_LABEL = re.compile(
    r"father|mother|husband|guardian|spouse|पिता|पति|माता|(?<![A-Za-z])[SDWC]\s*[/\\]\s*O(?![A-Za-z])",
    re.IGNORECASE,
)
_DOB_OR_GENDER = re.compile(
    r"DOB|D\.O\.B|Date\s*of\s*Birth|Year\s*of\s*Birth|YOB|जन्म|(?<![A-Za-z])(?:MALE|FEMALE)(?![A-Za-z])|पुरुष|महिला",
    re.IGNORECASE,
)

# Words that are never part of a person's name on an identity document.
_NOT_A_NAME = {
    "NAME", "FATHER", "FATHERS", "MOTHER", "HUSBAND", "GUARDIAN", "DATE", "BIRTH", "GENDER",
    "MALE", "FEMALE", "ADDRESS", "SIGNATURE", "GOVERNMENT", "GOVT", "INDIA", "INDIAN", "SPECIMEN",
    "SYNTHETIC", "INCOME", "TAX", "DEPARTMENT", "DEPT", "PERMANENT", "ACCOUNT", "NUMBER", "AADHAAR",
    "AADHAR", "REPUBLIC", "PASSPORT", "NATIONALITY", "PLACE", "ISSUE", "EXPIRY", "AUTHORITY", "CARD",
    "OF", "THE", "AND", "FOR", "GIVEN", "SURNAME", "LICENCE", "LICENSE", "DRIVING", "VALID", "UPTO",
    "HOLDER", "SPOUSE", "COLLEGE", "UNIVERSITY", "INSTITUTE", "SCHOOL", "ENGINEERING", "TECHNOLOGY",
    "TECHNOLOGICAL", "NCT", "STATE", "UNION", "TRANSPORT", "IDENTITY", "STUDENT", "MINISTRY",
    "OFFICE", "BANK", "ELECTION", "COMMISSION", "ELECTOR", "COUNCIL", "BOARD", "CORPORATION",
    "LIMITED", "LTD", "PVT", "SERVICES", "UIDAI", "DIRECTORATE", "BUREAU", "POLICE", "PROOF",
    "CITIZENSHIP", "VERIFICATION", "AUTHENTICATION", "ONLINE", "OFFLINE", "SCANNING", "CODE",
    "ENROLMENT", "ENROLLMENT", "VIRTUAL", "MOBILE", "EMAIL", "BLOOD", "GROUP", "EMERGENCY",
    "CONTACT", "PRINCIPAL", "REGISTRAR", "DIRECTOR", "ISSUING", "SEX", "TYPE", "COUNTRY",
}

# Common parts of Indian names across regions and communities. A weak hint:
# a candidate is never accepted or rejected on this alone.
_NAME_PARTS = {
    # given names
    "AARAV", "ADITI", "ADITYA", "AHMED", "AISHA", "AJAY", "AKASH", "AKSHAY", "ALI", "AMAN",
    "AMIT", "ANAND", "ANIL", "ANITA", "ANJALI", "ANKIT", "ANUJ", "ARJUN", "ARUN", "ASHA",
    "ASHOK", "AYESHA", "DEEPAK", "DEEPIKA", "DEV", "DIVYA", "FARHAN", "FATIMA", "GAURAV",
    "GEETA", "HARSH", "HASSAN", "IMRAN", "ISHA", "JASPREET", "JOHN", "JOSEPH", "KAVITA",
    "KIRAN", "KRISHNA", "LAKSHMI", "MANISH", "MANOJ", "MARY", "MEERA", "MOHAMMED", "MOHAMMAD",
    "MOHD", "MUHAMMAD", "NEHA", "NIKHIL", "NISHA", "POOJA", "PRIYA", "RAHUL", "RAJ", "RAJESH",
    "RAKESH", "RAM", "RAVI", "REKHA", "ROHIT", "SACHIN", "SANJAY", "SARITA", "SHREYA", "SIMRAN",
    "SNEHA", "SUNIL", "SUNITA", "SURESH", "TANVI", "UMA", "VIJAY", "VIKAS", "VIKRAM", "VINOD",
    "YASH", "ZAINAB", "ABDUL", "ARIF", "ASIF", "BHAVYA", "GURPREET",
    "HARPREET", "IRFAN", "JAVED", "KAMAL", "NASIR", "RITU", "SALMAN", "SAMEER",
    "SHAHID", "TARIQ", "USHA", "VARUN", "ZOYA",
    # family names
    "AGARWAL", "AHMAD", "ANSARI", "BANERJEE", "BHATT", "CHAUDHARY", "CHOUDHARY", "DAS",
    "DESAI", "DUBEY", "GHOSH", "GUPTA", "IYER", "JAIN", "JOSHI", "KAPOOR", "KHAN", "KUMAR",
    "KUMARI", "MALHOTRA", "MEHTA", "MISHRA", "MUKHERJEE", "NAIR", "PANDEY", "PATEL", "PILLAI",
    "QURESHI", "RAO", "REDDY", "SAXENA", "SHAH", "SHAIKH", "SHARMA", "SHUKLA", "SIDDIQUI",
    "SINGH", "SINHA", "SRIVASTAVA", "TIWARI", "TRIPATHI", "VERMA", "YADAV", "DEVI", "BEGUM",
    "KAUR", "NATH", "PRASAD", "CHAND", "LAL",
}

_MIN_SCORE = 3.0


@dataclass
class NameGuess:
    name: str
    score: float
    reasons: list[str] = field(default_factory=list)


def _name_like(token: str) -> bool:
    core = token.strip(".,'")
    if not core.isalpha() or not core[0].isupper():
        return False
    if len(core) == 1:
        return token.endswith(".")          # an initial, "A."
    return core.upper() not in _NOT_A_NAME


def _runs(line: str) -> list[tuple[list[str], int]]:
    """Maximal runs of name-like tokens in a line, with the count of other tokens."""
    tokens = line.split()
    runs, current = [], []
    for t in tokens:
        if _name_like(t):
            current.append(t.strip(",'"))
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    return [(r, len(tokens) - len(r)) for r in runs]


def find_name(raw_text: str) -> NameGuess | None:
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    best: NameGuess | None = None
    for i, line in enumerate(lines):
        if _RELATIVE_LABEL.search(line):
            continue                                     # a relative's name, not the holder's
        for words, others in _runs(line):
            if not 2 <= len(words) <= 4:
                continue
            if sum(c.isalpha() for c in "".join(words)) < 5:
                continue
            score, why = 2.0, ["two to four capitalised words"]
            noise = [t for t in line.split() if t not in words]
            if others == 0 or all(len(t) <= 2 for t in noise):
                score += 1.5
                why.append("the line holds little else")
            if all(w.isupper() for w in words) or all(w[0].isupper() and w[1:].islower() for w in words if len(w) > 1):
                score += 0.5
            above = lines[i - 1] if i else ""
            if _NAME_LABEL.search(line) or (_NAME_LABEL.search(above) and not _RELATIVE_LABEL.search(above)):
                score += 3.0
                why.append("next to a name label")
            if _RELATIVE_LABEL.search(above):
                score -= 4.0
                why.append("below a relative's label")
            near = lines[max(0, i - 2):i] + lines[i + 1:i + 3]
            if any(_DOB_OR_GENDER.search(l) for l in near):
                score += 1.5
                why.append("near the date of birth or gender")
            if above and _DEVANAGARI.search(above):
                score += 1.0
                why.append("below a Hindi line")
            known = sum(w.upper().strip(".") in _NAME_PARTS for w in words)
            if known:
                score += min(2.0, 0.75 * known)
                why.append("common name parts")
            if re.search(r"\d", line):
                score -= 1.0
            if best is None or score > best.score:
                best = NameGuess(" ".join(words), round(score, 2), why)
    return best if best and best.score >= _MIN_SCORE else None
