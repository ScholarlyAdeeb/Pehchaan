"""
Trusted Timestamping for Scan Receipts.

Each scan produces a receipt that can be independently verified.
Optional: submit to a public timestamping authority (RFC 3161) for
cryptographic proof of existence at a specific time.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TimestampedReceipt:
    """A verifiable receipt for a document scan."""
    receipt_id: str
    scan_id: str
    scan_timestamp: float
    receipt_timestamp: float
    scan_hash: str  # SHA-256 of the canonical scan record
    receipt_signature: str  # HMAC-SHA256 of receipt fields
    tsa_response: Optional[dict] = None  # RFC 3161 TSA response if available

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


def _canonical_scan_hash(record: dict[str, Any]) -> str:
    """Compute SHA-256 of canonical scan record (excludes volatile fields)."""
    excluded = {"signature", "signed_at", "receipt", "receipt_id"}
    canonical = {k: v for k, v in record.items() if k not in excluded}
    data = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def create_scan_receipt(record: dict[str, Any]) -> TimestampedReceipt:
    """
    Create a timestamped receipt for a scan record.

    1. Compute canonical hash of the scan
    2. Create receipt with metadata
    3. Sign with AUDIT_SIGNING_KEY
    4. Optionally submit to TSA for public timestamping
    """
    settings = get_settings()
    scan_id = record.get("id", str(uuid.uuid4()))

    scan_hash = _canonical_scan_hash(record)

    scan_timestamp = time.time()
    try:
        ts_str = record.get("timestamp")
        if ts_str:
            from datetime import datetime
            scan_timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp()
    except Exception:
        pass

    receipt_timestamp = time.time()
    receipt_id = str(uuid.uuid4())

    receipt_payload = {
        "receipt_id": receipt_id,
        "scan_id": scan_id,
        "scan_timestamp": scan_timestamp,
        "receipt_timestamp": receipt_timestamp,
        "scan_hash": scan_hash,
    }
    payload_data = json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")).encode()

    settings = get_settings()
    key = settings.AUDIT_SIGNING_KEY.encode()
    receipt_signature = hmac.new(key, payload_data, hashlib.sha256).hexdigest()

    tsa_response = None
    if settings.TIMESTAMP_AUTHORITY_URL:
        tsa_response = _request_tsa_timestamp(scan_hash, settings)

    receipt = TimestampedReceipt(
        receipt_id=receipt_id,
        scan_id=scan_id,
        scan_timestamp=scan_timestamp,
        receipt_timestamp=receipt_timestamp,
        scan_hash=scan_hash,
        receipt_signature=receipt_signature,
        tsa_response=tsa_response,
    )

    _store_receipt(receipt)

    return receipt


def _request_tsa_timestamp(data_hash: str, settings) -> Optional[dict]:
    """Request RFC 3161 timestamp from a TSA (simplified)."""
    if not settings.TIMESTAMP_AUTHORITY_URL or not settings.TIMESTAMP_AUTHORITY_TOKEN:
        return None

    try:
        payload = {"hash": data_hash, "algorithm": "SHA-256"}
        headers = {"Authorization": f"Bearer {settings.TIMESTAMP_AUTHORITY_TOKEN}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{settings.TIMESTAMP_AUTHORITY_URL}/timestamp",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning("TSA timestamping failed: %s", e)
    return None


def _store_receipt(receipt: TimestampedReceipt) -> None:
    """Store receipt locally."""
    settings = get_settings()
    receipt_dir = settings.UPLOAD_DIR / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"{receipt.receipt_id}.json"
    path.write_text(receipt.to_json())


def verify_scan_receipt(receipt: TimestampedReceipt | dict) -> tuple[bool, str]:
    """Verify a scan receipt. Returns (is_valid, message)."""
    if isinstance(receipt, dict):
        receipt = TimestampedReceipt(**receipt)

    payload = {
        "receipt_id": receipt.receipt_id,
        "scan_id": receipt.scan_id,
        "scan_timestamp": receipt.scan_timestamp,
        "receipt_timestamp": receipt.receipt_timestamp,
        "scan_hash": receipt.scan_hash,
    }
    payload_data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    settings = get_settings()
    key = settings.AUDIT_SIGNING_KEY.encode()
    expected_signature = hmac.new(key, payload_data, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_signature, receipt.receipt_signature):
        return False, "Invalid receipt signature"

    if receipt.tsa_response:
        pass  # In production, verify TSA signature and certificate chain

    return True, "Receipt verified"


def get_receipt(receipt_id: str) -> Optional[TimestampedReceipt]:
    """Retrieve a stored receipt by ID."""
    settings = get_settings()
    receipt_dir = settings.UPLOAD_DIR / "receipts"
    path = receipt_dir / f"{receipt_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return TimestampedReceipt(**data)
    except Exception:
        return None


def get_receipts_for_scan(scan_id: str) -> list[TimestampedReceipt]:
    """Get all receipts for a given scan."""
    settings = get_settings()
    receipt_dir = settings.UPLOAD_DIR / "receipts"
    if not receipt_dir.exists():
        return []

    receipts = []
    for path in receipt_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            if data.get("scan_id") == scan_id:
                receipts.append(TimestampedReceipt(**data))
        except Exception:
            pass
    return receipts