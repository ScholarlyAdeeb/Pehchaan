"""
Audit Log Signing.

Every audit record (scan result) is signed with HMAC-SHA256 using
AUDIT_SIGNING_KEY. This provides tamper-evidence for the audit trail:
any modification to a stored record will invalidate its signature.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from app.config import get_settings


def _canonical_json(obj: Any) -> bytes:
    """Deterministic JSON serialization for signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def sign_audit_record(record: dict[str, Any]) -> str:
    """
    Create an HMAC-SHA256 signature of an audit record.

    The signature covers the entire record except any existing 'signature' field.
    Returns hex-encoded signature.
    """
    settings = get_settings()
    key = settings.AUDIT_SIGNING_KEY.encode()

    # Create a copy without signature field
    to_sign = {k: v for k, v in record.items() if k != "signature"}

    # Add timestamp if not present
    if "signed_at" not in to_sign:
        to_sign["signed_at"] = time.time()

    data = _canonical_json(to_sign)
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def verify_audit_signature(record: dict[str, Any]) -> bool:
    """
    Verify the HMAC signature of an audit record.

    Returns True if the signature matches, False otherwise.
    """
    settings = get_settings()
    expected = record.get("signature")
    if not expected:
        return False

    # Recompute signature
    actual = sign_audit_record(record)
    return hmac.compare_digest(expected, actual)


def sign_audit_chain(records: list[dict[str, Any]]) -> str:
    """
    Create a chain signature: each record's signature includes the previous record's signature.
    This creates an append-only, tamper-evident chain (similar to a blockchain).

    Returns the final chain signature (hex).
    """
    prev_sig = ""
    for record in records:
        to_sign = {k: v for k, v in record.items() if k != "signature"}
        to_sign["prev_signature"] = prev_sig
        data = json.dumps(to_sign, sort_keys=True, separators=(",", ":")).encode()
        settings = get_settings()
        key = settings.AUDIT_SIGNING_KEY.encode()
        sig = hmac.new(key, data, hashlib.sha256).hexdigest()
        record["signature"] = sig
        prev_sig = sig
    return prev_sig


def verify_audit_chain(records: list[dict[str, Any]]) -> tuple[bool, int]:
    """
    Verify an entire audit chain.

    Returns (is_valid, first_invalid_index). If valid, index is -1.
    """
    prev_sig = ""
    for i, record in enumerate(records):
        expected = record.get("signature")
        if not expected:
            return False, i

        to_sign = {k: v for k, v in record.items() if k != "signature"}
        to_sign["prev_signature"] = prev_sig
        data = json.dumps(to_sign, sort_keys=True, separators=(",", ":")).encode()

        settings = get_settings()
        key = settings.AUDIT_SIGNING_KEY.encode()
        actual = hmac.new(key, data, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(actual, expected):
            return False, i

        prev_sig = expected

    return True, -1


# Import time at module level
import time