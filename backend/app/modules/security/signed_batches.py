"""
Signed Batch Receipts.

Bundles multiple scan receipts into a signed batch with a Merkle root,
allowing efficient verification of many scans at once. Each scan in the
batch gets a receipt that can be verified independently, and the batch
signature proves the entire set hasn't been tampered with.
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

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SignedBatch:
    """A signed batch of scan receipts."""
    batch_id: str
    created_at: float
    scan_count: int
    merkle_root: str
    batch_signature: str
    scan_ids: list[str]
    receipts: list[str]  # receipt IDs included in this batch
    tsa_response: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


def _merkle_root(hashes: list[str]) -> str:
    """Compute Merkle root from a list of hashes."""
    if not hashes:
        return hashlib.sha256(b"empty").hexdigest()

    level = hashes[:]
    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            combined = hashlib.sha256((left + right).encode()).hexdigest()
            next_level.append(combined)
        level = next_level
    return level[0]


def create_signed_batch(
    scan_ids: list[str],
    receipt_ids: list[str],
) -> SignedBatch:
    """
    Create a signed batch from a list of scan IDs and their receipt IDs.

    1. Fetch receipts for all scan IDs
    2. Compute Merkle root of receipt hashes
    3. Sign the batch with AUDIT_SIGNING_KEY
    5. Optionally submit to TSA
    """
    settings = get_settings()

    if len(scan_ids) != len(receipt_ids):
        raise ValueError("scan_ids and receipt_ids must have same length")

    # Collect receipt hashes for Merkle tree
    receipt_hashes = []
    receipt_dir = settings.UPLOAD_DIR / "receipts"
    for receipt_id in receipt_ids:
        path = receipt_dir / f"{receipt_id}.json"
        if path.exists():
            try:
                receipt = json.loads(path.read_text())
                receipt_hashes.append(receipt["scan_hash"])
            except Exception:
                pass

    if not receipt_hashes:
        raise ValueError("No valid receipts found for batch")

    # Compute Merkle root
    merkle_root = _merkle_root(receipt_hashes)

    batch_id = str(uuid.uuid4())
    created_at = time.time()

    # Sign batch
    batch_payload = {
        "batch_id": batch_id,
        "created_at": created_at,
        "scan_count": len(scan_ids),
        "merkle_root": merkle_root,
        "scan_ids": scan_ids,
        "receipt_ids": receipt_ids,
    }
    payload_data = json.dumps(batch_payload, sort_keys=True, separators=(",", ":")).encode()

    settings = get_settings()
    key = settings.AUDIT_SIGNING_KEY.encode()
    batch_signature = hmac.new(key, payload_data, hashlib.sha256).hexdigest()

    # Optional TSA timestamping
    tsa_response = None
    if settings.TIMESTAMP_AUTHORITY_URL:
        tsa_response = _request_tsa_timestamp(merkle_root, settings)

    batch = SignedBatch(
        batch_id=batch_id,
        created_at=created_at,
        scan_count=len(scan_ids),
        merkle_root=merkle_root,
        batch_signature=batch_signature,
        scan_ids=scan_ids,
        receipts=receipt_ids,
        tsa_response=tsa_response,
    )

    _store_batch(batch)

    return batch


def _request_tsa_timestamp(data_hash: str, settings) -> Optional[dict]:
    """Request RFC 3161 timestamp for batch Merkle root."""
    if not settings.TIMESTAMP_AUTHORITY_URL or not settings.TIMESTAMP_AUTHORITY_TOKEN:
        return None

    try:
        import httpx
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
        logger.warning("TSA timestamping failed for batch: %s", e)
    return None


def _store_batch(batch: SignedBatch) -> None:
    settings = get_settings()
    batch_dir = settings.UPLOAD_DIR / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / f"{batch.batch_id}.json"
    path.write_text(batch.to_json())


def verify_signed_batch(batch: SignedBatch | dict) -> tuple[bool, str]:
    """Verify a signed batch. Returns (is_valid, message)."""
    if isinstance(batch, dict):
        batch = SignedBatch(**batch)

    # Recompute Merkle root
    receipt_hashes = []
    receipt_dir = get_settings().UPLOAD_DIR / "receipts"
    for receipt_id in batch.receipts:
        path = receipt_dir / f"{receipt_id}.json"
        if path.exists():
            try:
                receipt = json.loads(path.read_text())
                receipt_hashes.append(receipt["scan_hash"])
            except Exception:
                pass

    if not receipt_hashes:
        return False, "No valid receipts found"

    merkle_root = _merkle_root(receipt_hashes)
    if merkle_root != batch.merkle_root:
        return False, f"Merkle root mismatch: expected {batch.merkle_root}, got {merkle_root}"

    # Verify batch signature
    batch_payload = {
        "batch_id": batch.batch_id,
        "created_at": batch.created_at,
        "scan_count": batch.scan_count,
        "merkle_root": batch.merkle_root,
        "scan_ids": batch.scan_ids,
        "receipt_ids": batch.receipts,
    }
    payload_data = json.dumps(batch_payload, sort_keys=True, separators=(",", ":")).encode()

    settings = get_settings()
    key = settings.AUDIT_SIGNING_KEY.encode()
    expected_signature = hmac.new(key, payload_data, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_signature, batch.batch_signature):
        return False, "Invalid batch signature"

    return True, "Batch verified"


def get_batch(batch_id: str) -> Optional[SignedBatch]:
    """Retrieve a batch by ID."""
    settings = get_settings()
    batch_dir = settings.UPLOAD_DIR / "batches"
    path = batch_dir / f"{batch_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return SignedBatch(**data)
    except Exception:
        return None


def get_batches_for_scan(scan_id: str) -> list[SignedBatch]:
    """Get all batches containing a specific scan."""
    settings = get_settings()
    batch_dir = settings.UPLOAD_DIR / "batches"
    if not batch_dir.exists():
        return []

    batches = []
    for path in batch_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            if scan_id in data.get("scan_ids", []):
                batches.append(SignedBatch(**data))
        except Exception:
            pass
    return batches