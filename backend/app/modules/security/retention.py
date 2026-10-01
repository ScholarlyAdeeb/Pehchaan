"""
Data Retention Policy.

Implements automatic cleanup of scan records and associated data
after the configured retention period (default 90 days).
This complies with data minimization principles and the DPDP Act 2023.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RetentionPolicy:
    """Configuration for data retention."""
    scan_retention_days: int = 90
    incident_retention_days: int = 365
    audit_log_retention_days: int = 365
    enabled: bool = True


def get_retention_policy() -> RetentionPolicy:
    """Get the current retention policy from settings."""
    settings = get_settings()
    return RetentionPolicy(
        scan_retention_days=settings.SCAN_RETENTION_DAYS,
        incident_retention_days=365,  # incidents kept longer
        audit_log_retention_days=365,
        enabled=True,
    )


def apply_retention_policy(
    policy: Optional[RetentionPolicy] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Apply the retention policy by deleting expired records.

    Returns a dict with counts of deleted items per category.
    """
    if policy is None:
        policy = get_retention_policy()

    if not policy.enabled:
        logger.info("Retention policy disabled; skipping cleanup")
        return {"scans": 0, "incidents": 0, "audit_logs": 0}

    now = time.time()
    deleted = {"scans": 0, "incidents": 0, "audit_logs": 0}

    # Clean up scans
    deleted["scans"] = _cleanup_scans(policy.scan_retention_days, dry_run)

    # Clean up incidents
    deleted["incidents"] = _cleanup_incidents(policy.incident_retention_days, dry_run)

    # Clean up audit logs
    deleted["audit_logs"] = _cleanup_audit_logs(policy.audit_log_retention_days, dry_run)

    if dry_run:
        logger.info("Retention dry run: would delete %s", deleted)
    else:
        logger.info("Retention cleanup completed: %s", deleted)

    return deleted


def _cleanup_scans(retention_days: int, dry_run: bool) -> int:
    """Delete scans older than retention_days."""
    settings = get_settings()
    upload_dir = settings.UPLOAD_DIR
    cutoff = time.time() - (retention_days * 86400)
    deleted = 0

    # File-based scans
    scans_dir = upload_dir / "scans"
    if scans_dir.exists():
        for path in scans_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    if not dry_run:
                        path.unlink()
                    deleted += 1
            except Exception as e:
                logger.warning("Failed to check scan file %s: %s", path, e)

    return deleted


def _cleanup_incidents(retention_days: int, dry_run: bool) -> int:
    """Delete incidents older than retention_days."""
    settings = get_settings()
    cutoff = time.time() - (retention_days * 86400)
    deleted = 0

    incident_dir = settings.UPLOAD_DIR / "incidents"
    if incident_dir.exists():
        for path in incident_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    if not dry_run:
                        path.unlink()
                    deleted += 1
            except Exception as e:
                logger.warning("Failed to check incident file %s: %s", path, e)

    return deleted


def _cleanup_audit_logs(retention_days: int, dry_run: bool) -> int:
    """Delete audit logs older than retention_days."""
    settings = get_settings()
    cutoff = time.time() - (retention_days * 86400)
    deleted = 0

    audit_dir = settings.UPLOAD_DIR / "audit"
    if audit_dir.exists():
        for path in audit_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    if not dry_run:
                        path.unlink()
                    deleted += 1
            except Exception as e:
                logger.warning("Failed to check audit log file %s: %s", path, e)

    return deleted


def get_retention_stats() -> dict[str, dict]:
    """Get statistics about data age for retention planning."""
    settings = get_settings()
    now = time.time()

    def _age_stats(dir_name: str) -> dict:
        dir_path = settings.UPLOAD_DIR / dir_name
        if not dir_path.exists():
            return {"count": 0, "oldest_days": 0, "newest_days": 0}
        ages = []
        for path in dir_path.glob("*.json"):
            try:
                age_days = (now - path.stat().st_mtime) / 86400
                ages.append(age_days)
            except Exception:
                pass
        if not ages:
            return {"count": 0, "oldest_days": 0, "newest_days": 0}
        return {
            "count": len(ages),
            "oldest_days": round(max(ages), 1),
            "newest_days": round(min(ages), 1),
            "avg_days": round(sum(ages) / len(ages), 1),
        }

    return {
        "scans": _age_stats("scans"),
        "incidents": _age_stats("incidents"),
        "audit_logs": _age_stats("audit"),
    }


# Import time at module level
import time