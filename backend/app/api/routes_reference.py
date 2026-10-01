"""
Reference data API routes.

Serves the 45 data.gov.in dataset catalog and reference lookups
used by the screening pipeline and admin analytics.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.modules.reference.lookup import (
    check_visa_plausibility,
    get_border_threat_level,
    get_datasets_by_category,
    get_datasets_catalog,
    get_reference_stats,
    is_evisa_eligible,
    validate_pincode,
    validate_pincode_state,
    validate_psk_code,
)

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/datasets")
async def list_datasets(
    category: str | None = Query(None, description="Filter by category"),
):
    if category:
        return get_datasets_by_category(category)
    return get_datasets_catalog()


@router.get("/stats")
async def reference_stats():
    return get_reference_stats()


@router.get("/pincode/{pincode}")
async def lookup_pincode(pincode: str):
    result = validate_pincode(pincode)
    if result is None:
        raise HTTPException(404, f"Pincode {pincode} not found in reference data")
    return result


@router.get("/pincode/{pincode}/validate")
async def validate_pincode_match(
    pincode: str,
    state: str = Query(..., description="Claimed state to validate against"),
):
    match, actual_state = validate_pincode_state(pincode, state)
    return {
        "pincode": pincode,
        "claimed_state": state,
        "actual_state": actual_state,
        "match": match,
    }


@router.get("/psk/{code}")
async def lookup_psk(code: str):
    result = validate_psk_code(code)
    if result is None:
        raise HTTPException(404, f"PSK/PSLK code {code} not recognized")
    return result


@router.get("/evisa/check/{nationality_code}")
async def check_evisa_eligibility(nationality_code: str):
    eligible = is_evisa_eligible(nationality_code)
    return {
        "nationality_code": nationality_code.upper(),
        "evisa_eligible": eligible,
    }


@router.get("/visa/plausibility")
async def check_visa_type_plausibility(
    nationality: str = Query(..., description="ISO 3166-1 alpha-3 nationality code"),
    visa_type: str = Query(..., description="Visa type (Tourist, Business, etc.)"),
):
    result = check_visa_plausibility(nationality, visa_type)
    return {
        "nationality": nationality.upper(),
        "visa_type": visa_type,
        "plausibility": result,
        "risk_note": {
            "common": None,
            "rare": f"Visa type '{visa_type}' is uncommon for {nationality.upper()} nationals — manual review recommended",
            "unknown_nationality": f"No visa issuance data available for {nationality.upper()} — cannot assess plausibility",
            "unknown_type": f"Visa type '{visa_type}' not in reference matrix — verify manually",
        }.get(result),
    }


@router.get("/border/threat/{border_name}")
async def get_border_threat(border_name: str):
    level = get_border_threat_level(border_name)
    return {
        "border": border_name,
        "threat_level": level,
    }
