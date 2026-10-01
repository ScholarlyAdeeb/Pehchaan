"""
Pydantic schemas describing the *official standard shape* of each supported
document type. These are deliberately separate from the API's request/response
models (in `app/models`) — these describe domain truth (what a valid Indian/
ICAO-compliant document looks like), while the API models describe wire
format.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    PASSPORT = "passport"
    VISA = "visa"
    NATIONAL_ID = "national_id"
    DRIVING_LICENSE = "driving_license"
    PERMIT = "permit"


class PassportFields(BaseModel):
    name: str | None = None
    passport_number: str | None = Field(None, pattern=r"^[A-Z0-9]{6,9}$")
    nationality: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    date_of_birth: str | None = None
    date_of_expiry: str | None = None
    gender: str | None = Field(None, pattern=r"^[MFX]$")


class VisaFields(BaseModel):
    visa_number: str | None = None
    visa_type: str | None = None
    entry_validation: str | None = None
    stay_duration: str | None = None
    issue_date: str | None = None
    expiry_date: str | None = None


# ISO 3166-1 alpha-3 codes are ~250 entries; for a prototype we keep a
# representative subset covering common transit corridors + flag anything
# else as "unrecognized" (a warning, not a hard fail — the list is not
# exhaustive by design).
KNOWN_COUNTRY_CODES = {
    "IND", "USA", "GBR", "CAN", "AUS", "NPL", "BGD", "PAK", "CHN", "LKA",
    "BTN", "MMR", "AFG", "ARE", "SAU", "SGP", "MYS", "THA", "FRA", "DEU",
    "JPN", "KOR", "RUS", "BRA", "ZAF", "NZL", "IDN", "PHL", "VNM", "ITA",
}
