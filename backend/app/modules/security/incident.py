"""
One-Click Incident Reporting for Admins.

When an officer or in-charge spots a systemic issue (e.g., a new forgery
template, a compromised checkpoint, insider threat), they can trigger an
incident report with one click. The report is sent to the configured webhook
and stored for audit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentType(str, Enum):
    FORGERY_TEMPLATE = "forgery_template"           # New forgery template detected
    COMPROMISED_CHECKPOINT = "compromised_checkpoint"  # Checkpoint security issue
    INSIDER_THREAT = "insider_threat"               # Suspicious officer behavior
    SYSTEM_ANOMALY = "system_anomaly"               # Unexpected system behavior
    DATA_BREACH = "data_breach"                     # Potential data exposure
    MODEL_DRIFT = "model_drift"                     # AI model performance degradation
    OTHER = "other"


@dataclass
class IncidentReport:
    id: str
    type: IncidentType
    severity: IncidentSeverity
    title: str
    description: str
    checkpoint_id: Optional[str]
    officer_id: Optional[str]
    related_scan_ids: list[str]
    metadata: dict[str, Any]
    created_at: float
    created_by: str  # email of reporter

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        """Create a unique fingerprint for deduplication."""
        core = f"{self.type.value}:{self.checkpoint_id}:{self.title}"
        return hashlib.sha256(core.encode()).hexdigest()[:16]


def create_incident_report(
    type: IncidentType,
    severity: IncidentSeverity,
    title: str,
    description: str,
    checkpoint_id: Optional[str] = None,
    officer_id: Optional[str] = None,
    related_scan_ids: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    created_by: str = "system",
) -> IncidentReport:
    """
    Create and dispatch an incident report.

    If INCIDENT_REPORT_WEBHOOK is configured, the report is also POSTed there.
    """
    settings = get_settings()

    report = IncidentReport(
        id=str(uuid.uuid4()),
        type=type,
        severity=severity,
        title=title,
        description=description,
        checkpoint_id=checkpoint_id,
        officer_id=officer_id,
        related_scan_ids=related_scan_ids or [],
        metadata=metadata or {},
        created_at=time.time(),
        created_by=created_by,
    )

    # Store locally (in production, write to database)
    _store_incident(report)

    # Dispatch to webhook if configured
    webhook = settings.INCIDENT_REPORT_WEBHOOK
    if webhook:
        try:
            # Fire and forget - don't block on webhook
            import asyncio
            asyncio.create_task(_dispatch_webhook(webhook, report))
        except Exception as e:
            logger.warning("Failed to dispatch incident webhook: %s", e)

    logger.warning(
        "INCIDENT [%s] %s: %s (checkpoint=%s, officer=%s)",
        report.severity.value.upper(),
        report.type.value,
        report.title,
        checkpoint_id,
        officer_id,
    )

    return report


def _store_incident(report: IncidentReport) -> None:
    """Store incident report locally (in production, write to database)."""
    incident_dir = get_settings().UPLOAD_DIR / "incidents"
    incident_dir.mkdir(parents=True, exist_ok=True)
    path = incident_dir / f"{report.id}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2))


async def _dispatch_webhook(webhook: str, report: IncidentReport) -> None:
    """Send incident report to configured webhook."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(webhook, json=report.to_dict())


def get_incident_reports(
    limit: int = 50,
    severity: Optional[IncidentSeverity] = None,
    type: Optional[IncidentType] = None,
) -> list[IncidentReport]:
    """Retrieve stored incident reports."""
    incident_dir = get_settings().UPLOAD_DIR / "incidents"
    if not incident_dir.exists():
        return []

    reports = []
    for path in sorted(incident_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
            report = IncidentReport(**data)
            if severity and report.severity != severity:
                continue
            if type and report.type != type:
                continue
            reports.append(report)
            if len(reports) >= limit:
                break
        except Exception as e:
            logger.warning("Failed to load incident %s: %s", path, e)
    return reports


# Import json and time at module level
import json
import time