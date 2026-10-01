"""
Reference data lookup module.

Loads seed data from backend/data/reference/ into memory at startup and
provides fast lookups used by the validation and risk engines during
document screening.

Data sources are mapped from the 45 data.gov.in datasets cataloged in
the PEHCHAAN Dataset Integration Map.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "reference"


def _load_json(filename: str) -> dict | list:
    path = _DATA_DIR / filename
    if not path.exists():
        logger.warning("Reference data file not found: %s", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _pincode_index() -> dict[str, dict]:
    data = _load_json("pincodes_sample.json")
    if not data:
        return {}
    return {
        entry["pincode"]: entry
        for entry in data.get("pincodes", [])
    }


@lru_cache(maxsize=1)
def _psk_index() -> dict[str, dict]:
    data = _load_json("psk_directory.json")
    if not data:
        return {}
    index: dict[str, dict] = {}
    for entry in data.get("psk_codes", []):
        index[entry["code"]] = entry
        index[entry["code"].lower()] = entry
        short = entry["code"].split("-", 1)[-1] if "-" in entry["code"] else entry["code"]
        index[short] = entry
        index[short.lower()] = entry
    return index


@lru_cache(maxsize=1)
def _evisa_set() -> set[str]:
    data = _load_json("evisa_countries.json")
    if not data:
        return set()
    return {c["code"] for c in data.get("eligible_countries", [])}


@lru_cache(maxsize=1)
def _visa_matrix() -> dict[str, dict]:
    data = _load_json("visa_nationality_matrix.json")
    if not data:
        return {}
    return {
        entry["nationality"]: entry
        for entry in data.get("matrix", [])
    }


@lru_cache(maxsize=1)
def _border_threats() -> dict[str, dict]:
    data = _load_json("border_threats.json")
    if not data:
        return {}
    return {
        entry["border"]: entry
        for entry in data.get("borders", [])
    }


@lru_cache(maxsize=1)
def _datasets_catalog() -> list[dict]:
    data = _load_json("datasets_catalog.json")
    return data if isinstance(data, list) else []


# ---- Public API ----

def validate_pincode(pincode: str) -> dict | None:
    """Return pincode details if valid, None if not found in the reference set."""
    return _pincode_index().get(pincode.strip())


def validate_pincode_state(pincode: str, claimed_state: str) -> tuple[bool, str | None]:
    """Check if a pincode matches the claimed state. Returns (match, actual_state)."""
    entry = validate_pincode(pincode)
    if entry is None:
        return True, None  # not in sample set, don't penalize
    actual = entry["state"].lower().strip()
    claimed = claimed_state.lower().strip()
    match = actual == claimed or actual.startswith(claimed) or claimed.startswith(actual)
    return match, entry["state"]


def validate_psk_code(code: str) -> dict | None:
    """Return PSK/PSLK details if the code is recognized, None otherwise."""
    return _psk_index().get(code.strip())


def is_evisa_eligible(nationality_code: str) -> bool:
    """Check if a nationality code is e-visa eligible."""
    return nationality_code.upper().strip() in _evisa_set()


def check_visa_plausibility(nationality_code: str, visa_type: str) -> str:
    """
    Check if a visa type is common/rare/unknown for a nationality.
    Returns: "common", "rare", "unknown_nationality", or "unknown_type".
    """
    matrix = _visa_matrix()
    nat = nationality_code.upper().strip()
    entry = matrix.get(nat)
    if entry is None:
        return "unknown_nationality"

    vtype = visa_type.strip().title()
    if vtype in entry.get("common_types", []):
        return "common"
    if vtype in entry.get("rare_types", []):
        return "rare"
    return "unknown_type"


def get_border_threat_level(border_name: str) -> str:
    """Return threat level for a border: high, medium, low, or unknown."""
    threats = _border_threats()
    for key, entry in threats.items():
        if border_name.lower() in key.lower() or key.lower() in border_name.lower():
            return entry["threat_level"]
    return "unknown"


def get_datasets_catalog() -> list[dict]:
    """Return the full 45-dataset catalog."""
    return _datasets_catalog()


def get_datasets_by_category(category: str) -> list[dict]:
    """Return datasets filtered by category."""
    return [d for d in _datasets_catalog() if d.get("category") == category]


def get_datasets_by_status(status: str) -> list[dict]:
    """Return datasets filtered by ingestion status."""
    return [d for d in _datasets_catalog() if d.get("status") == status]


def get_reference_stats() -> dict:
    """Summary statistics about loaded reference data."""
    return {
        "pincodes_loaded": len(_pincode_index()),
        "psk_codes_loaded": len(_psk_index()) // 3,  # deduplicate aliases
        "evisa_countries": len(_evisa_set()),
        "visa_nationalities": len(_visa_matrix()),
        "borders_tracked": len(_border_threats()),
        "datasets_total": len(_datasets_catalog()),
        "datasets_seeded": len(get_datasets_by_status("seeded")),
        "datasets_pending": len(get_datasets_by_status("pending")),
    }
