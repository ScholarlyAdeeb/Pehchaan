"""
Security package for authentication, authorization, and audit signing.
"""
from __future__ import annotations

from .auth import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
    bootstrap_admin,
    require_admin_bootstrap,
)
from .audit_signing import sign_audit_record, verify_audit_signature
from .checkpoint import require_checkpoint_access, CheckpointAccessError
from .incident import create_incident_report, get_incident_reports
from .retention import apply_retention_policy, RetentionPolicy
from .insider_threat import detect_insider_threats, InsiderThreatAlert
from .timestamping import create_scan_receipt, verify_scan_receipt, TimestampedReceipt
from .signed_batches import create_signed_batch, verify_signed_batch, SignedBatch

__all__ = [
    # Auth
    "create_access_token",
    "decode_access_token",
    "get_password_hash",
    "verify_password",
    "bootstrap_admin",
    "require_admin_bootstrap",
    # Audit signing
    "sign_audit_record",
    "verify_audit_signature",
    # Checkpoint access
    "require_checkpoint_access",
    "CheckpointAccessError",
    # Incident reporting
    "create_incident_report",
    "get_incident_reports",
    # Retention
    "apply_retention_policy",
    "RetentionPolicy",
    # Insider threat
    "detect_insider_threats",
    "InsiderThreatAlert",
    # Timestamping
    "create_scan_receipt",
    "verify_scan_receipt",
    "TimestampedReceipt",
    # Signed batches
    "create_signed_batch",
    "verify_signed_batch",
    "SignedBatch",
]