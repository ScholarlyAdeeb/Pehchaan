"""
Insider Threat Detection.

Analyzes audit data to detect anomalous patterns that may indicate
insider threats: officers approving known forgeries, unusual clearance
rates, after-hours activity, etc.
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class InsiderThreatAlert:
    """An alert raised by the insider threat detector."""
    id: str
    type: str  # "high_clearance_rate", "after_hours_activity", "forgery_approval", "anomalous_pattern"
    severity: str  # "low", "medium", "high", "critical"
    officer_id: Optional[str]
    checkpoint_id: Optional[str]
    description: str
    evidence: dict[str, Any]
    created_at: float
    status: str = "open"  # open, investigating, resolved, false_positive

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "officer_id": self.officer_id,
            "checkpoint_id": self.checkpoint_id,
            "description": self.description,
            "evidence": self.evidence,
            "created_at": self.created_at,
            "status": self.status,
        }


def detect_insider_threats(
    lookback_days: int = 7,
    min_scans_for_baseline: int = 50,
) -> list[InsiderThreatAlert]:
    """
    Analyze recent audit data for insider threat indicators.

    Returns a list of alerts that should be reviewed by security team.
    """
    settings = get_settings()
    cutoff = time.time() - (lookback_days * 86400)
    alerts = []

    # Load recent scans from file store (in production, query database)
    scans = _load_recent_scans(cutoff)
    if len(scans) < min_scans_for_baseline:
        logger.info("Not enough scans (%d) for insider threat baseline", len(scans))
        return []

    # Group by officer and checkpoint
    by_officer = _group_by_officer(scans)
    by_checkpoint = _group_by_checkpoint(scans)

    # 1. High clearance rate for flagged documents
    alerts.extend(_detect_high_clearance_rate(by_officer, by_checkpoint))

    # 2. After-hours activity
    alerts.extend(_detect_after_hours_activity(by_officer))

    # 3. Forgery approval (CLEAR verdict on known forgery matches)
    alerts.extend(_detect_forgery_approval(by_officer, scans))

    # 4. Anomalous verdict patterns
    alerts.extend(_detect_anomalous_verdicts(by_officer, by_checkpoint))

    # 5. Rapid successive scans (possible automation/abuse)
    alerts.extend(_detect_rapid_scans(by_officer))

    # Store alerts
    for alert in alerts:
        _store_alert(alert)

    return alerts


def _load_recent_scans(cutoff: float) -> list[dict[str, Any]]:
    """Load scans from file store after cutoff time."""
    settings = get_settings()
    scans = []
    scans_dir = settings.UPLOAD_DIR / "scans"
    if not scans_dir.exists():
        return []

    for path in scans_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            ts = data.get("timestamp")
            if ts:
                # Parse ISO timestamp
                from datetime import datetime
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.timestamp() >= cutoff:
                    scans.append(data)
        except Exception:
            pass
    return scans


def _group_by_officer(scans: list[dict]) -> dict[str, list[dict]]:
    """Group scans by officer ID (from scan metadata)."""
    grouped = defaultdict(list)
    for scan in scans:
        officer_id = scan.get("officer_id") or scan.get("identity", {}).get("officer_id")
        if officer_id:
            grouped[officer_id].append(scan)
    return grouped


def _group_by_checkpoint(scans: list[dict]) -> dict[str, list[dict]]:
    """Group scans by checkpoint ID."""
    grouped = defaultdict(list)
    for scan in scans:
        cp = scan.get("checkpoint_id")
        if cp:
            grouped[cp].append(scan)
    return grouped


def _detect_high_clearance_rate(
    by_officer: dict[str, list],
    by_checkpoint: dict[str, list],
) -> list[InsiderThreatAlert]:
    """Detect officers/checkpoints with unusually high CLEAR rates on risky docs."""
    alerts = []

    for officer_id, scans in by_officer.items():
        if len(scans) < 20:
            continue
        clear_count = sum(1 for s in scans if s.get("risk", {}).get("verdict") == "CLEAR")
        clear_rate = clear_count / len(scans)

        # Also check REJECT rate on documents with forgery registry matches
        flagged_scans = [s for s in scans if s.get("registry_matches")]
        if flagged_scans:
            cleared_flagged = sum(1 for s in flagged_scans if s.get("risk", {}).get("verdict") == "CLEAR")
            if cleared_flagged > 0:
                alert = InsiderThreatAlert(
                    id=f"alert_{int(time.time())}_{hash(officer_id) % 10000}",
                    type="forgery_approval",
                    severity="critical",
                    officer_id=officer_id,
                    checkpoint_id=scans[0].get("checkpoint_id"),
                    description=f"Officer cleared {cleared_flagged} document(s) that matched known forgery templates",
                    evidence={"cleared_flagged": cleared_flagged, "total_flagged": len(flagged_scans)},
                    created_at=time.time(),
                )
                alerts.append(alert)

        # Overall high clearance rate
        if clear_rate > 0.95:  # >95% CLEAR rate is suspicious
            alert = InsiderThreatAlert(
                id=f"alert_{int(time.time())}_{hash(officer_id) % 10000}",
                type="high_clearance_rate",
                severity="high",
                officer_id=officer_id,
                checkpoint_id=scans[0].get("checkpoint_id"),
                description=f"Officer has {clear_rate:.1%} CLEAR rate ({clear_count}/{len(scans)} scans)",
                evidence={"clear_rate": clear_rate, "total_scans": len(scans)},
                created_at=time.time(),
            )
            alerts.append(alert)

    return alerts


def _detect_after_hours_activity(by_officer: dict[str, list]) -> list[InsiderThreatAlert]:
    """Detect officers scanning during unusual hours (e.g., 22:00-05:00)."""
    alerts = []

    for officer_id, scans in by_officer.items():
        after_hours = []
        for scan in scans:
            ts_str = scan.get("timestamp")
            if ts_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    hour = dt.hour
                    if hour < 5 or hour > 22:  # 22:00-05:00
                        after_hours.append(scan)
                except Exception:
                    pass

        if len(after_hours) > 10 and len(after_hours) / len(scans) > 0.3:
            alert = InsiderThreatAlert(
                id=f"alert_{int(time.time())}_{hash(officer_id) % 10000}",
                type="after_hours_activity",
                severity="medium",
                officer_id=officer_id,
                checkpoint_id=scans[0].get("checkpoint_id") if scans else None,
                description=f"Officer performed {len(after_hours)} scans during off-hours (22:00-05:00)",
                evidence={"after_hours_count": len(after_hours), "total_scans": len(scans)},
                created_at=time.time(),
            )
            alerts.append(alert)

    return alerts


def _detect_forgery_approval(
    by_officer: dict[str, list],
    all_scans: list[dict],
) -> list[InsiderThreatAlert]:
    """Detect officers who cleared documents matching known forgery registry."""
    alerts = []

    for officer_id, scans in by_officer.items():
        for scan in scans:
            registry_matches = scan.get("registry_matches", [])
            if registry_matches and scan.get("risk", {}).get("verdict") == "CLEAR":
                alert = InsiderThreatAlert(
                    id=f"alert_{int(time.time())}_{hash(officer_id) % 10000}",
                    type="forgery_approval",
                    severity="critical",
                    officer_id=officer_id,
                    checkpoint_id=scan.get("checkpoint_id"),
                    description="Officer cleared a document matching a known forgery template",
                    evidence={
                        "scan_id": scan.get("id"),
                        "registry_matches": registry_matches,
                        "verdict": scan.get("risk", {}).get("verdict"),
                    },
                    created_at=time.time(),
                )
                alerts.append(alert)

    return alerts


def _detect_anomalous_verdicts(
    by_officer: dict[str, list],
    by_checkpoint: dict[str, list],
) -> list[InsiderThreatAlert]:
    """Detect verdict patterns that deviate from peer group."""
    alerts = []

    # Calculate baseline verdict distribution per checkpoint
    checkpoint_baselines = {}
    for cp, scans in by_checkpoint.items():
        if len(scans) < 30:
            continue
        verdicts = [s.get("risk", {}).get("verdict", "UNKNOWN") for s in scans]
        total = len(verdicts)
        checkpoint_baselines[cp] = {
            "CLEAR": verdicts.count("CLEAR") / total,
            "REVIEW": verdicts.count("REVIEW") / total,
            "REJECT": verdicts.count("REJECT") / total,
        }

    # Compare each officer to their checkpoint baseline
    for officer_id, scans in by_officer.items():
        if len(scans) < 20:
            continue

        cp = scans[0].get("checkpoint_id")
        baseline = checkpoint_baselines.get(cp)
        if not baseline:
            continue

        verdicts = [s.get("risk", {}).get("verdict", "UNKNOWN") for s in scans]
        total = len(verdicts)
        officer_dist = {
            "CLEAR": verdicts.count("CLEAR") / total,
            "REVIEW": verdicts.count("REVIEW") / total,
            "REJECT": verdicts.count("REJECT") / total,
        }

        # Check if officer's REJECT rate is significantly lower than baseline
        reject_diff = baseline["REJECT"] - officer_dist["REJECT"]
        if reject_diff > 0.20:  # Officer rejects 20% less than baseline
            alert = InsiderThreatAlert(
                id=f"alert_{int(time.time())}_{hash(officer_id) % 10000}",
                type="anomalous_pattern",
                severity="high",
                officer_id=officer_id,
                checkpoint_id=cp,
                description=f"Officer's REJECT rate ({officer_dist['REJECT']:.1%}) is {reject_diff:.1%} below checkpoint baseline ({baseline['REJECT']:.1%})",
                evidence={"officer_dist": officer_dist, "baseline": baseline, "scan_count": len(scans)},
                created_at=time.time(),
            )
            alerts.append(alert)

    return alerts


def _detect_rapid_scans(by_officer: dict[str, list]) -> list[InsiderThreatAlert]:
    """Detect officers scanning too rapidly (possible automation)."""
    alerts = []

    for officer_id, scans in by_officer.items():
        if len(scans) < 10:
            continue

        # Sort by timestamp
        timed_scans = []
        for s in scans:
            ts_str = s.get("timestamp")
            if ts_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    timed_scans.append(dt)
                except Exception:
                    pass

        if len(timed_scans) < 10:
            continue

        timed_scans.sort()
        intervals = [(timed_scans[i+1] - timed_scans[i]).total_seconds()
                     for i in range(len(timed_scans)-1)]

        if intervals:
            avg_interval = statistics.mean(intervals)
            median_interval = statistics.median(intervals)

            # If median interval < 30 seconds, likely automated or rushed
            if median_interval < 30:
                alert = InsiderThreatAlert(
                    id=f"alert_{int(time.time())}_{hash(officer_id) % 10000}",
                    type="anomalous_pattern",
                    severity="medium",
                    officer_id=officer_id,
                    checkpoint_id=scans[0].get("checkpoint_id") if scans else None,
                    description=f"Officer's median scan interval is {median_interval:.0f}s (possible automation or rushed processing)",
                    evidence={"avg_interval_sec": avg_interval, "median_interval_sec": median_interval, "scan_count": len(scans)},
                    created_at=time.time(),
                )
                alerts.append(alert)

    return alerts


def _store_alert(alert: InsiderThreatAlert) -> None:
    """Store alert for review."""
    settings = get_settings()
    alert_dir = settings.UPLOAD_DIR / "insider_alerts"
    alert_dir.mkdir(parents=True, exist_ok=True)
    path = alert_dir / f"{alert.id}.json"
    path.write_text(json.dumps(alert.to_dict(), indent=2))


def get_insider_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
) -> list[InsiderThreatAlert]:
    """Retrieve stored insider threat alerts."""
    settings = get_settings()
    alert_dir = settings.UPLOAD_DIR / "insider_alerts"
    if not alert_dir.exists():
        return []

    alerts = []
    for path in sorted(alert_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
            alert = InsiderThreatAlert(**data)
            if status and alert.status != status:
                continue
            if severity and alert.severity != severity:
                continue
            alerts.append(alert)
            if len(alerts) >= limit:
                break
        except Exception as e:
            logger.warning("Failed to load alert %s: %s", path, e)
    return alerts


# Import modules at module level
import json
import time
from collections import defaultdict