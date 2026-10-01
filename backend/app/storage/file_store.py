"""
In-memory audit trail store for the prototype.

The problem statement explicitly asks for "a digital trail for
investigations and intelligence analysis" — every scan result is kept here
with a UUID, timestamp, and full module breakdown so it can be recalled
later. This is a plain in-process dict for the hackathon demo; swapping it
for Postgres/SQLite means changing only this file (the API layer only calls
`save_scan` / `get_scan` / `list_scans`).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

_lock = threading.Lock()
_scans: dict[str, dict[str, Any]] = {}


def save_scan(record: dict[str, Any]) -> str:
    scan_id = str(uuid4())
    record["id"] = scan_id
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _scans[scan_id] = record
    return scan_id


def get_scan(scan_id: str) -> dict[str, Any] | None:
    with _lock:
        return _scans.get(scan_id)


def list_scans(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        records = list(_scans.values())
    records.sort(key=lambda r: r["timestamp"], reverse=True)
    return records[:limit]


def stats() -> dict[str, Any]:
    with _lock:
        records = list(_scans.values())
    total = len(records)
    by_verdict = {"CLEAR": 0, "REVIEW": 0, "REJECT": 0}
    for r in records:
        v = r.get("risk", {}).get("verdict")
        if v in by_verdict:
            by_verdict[v] += 1
    return {"total_scans": total, "by_verdict": by_verdict}
