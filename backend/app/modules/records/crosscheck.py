"""
Records cross-check — compares the document being screened with every
earlier screening of the same document number.

A genuine document presented twice should carry the same holder name and
date of birth both times. If the same number turns up with a different name
or DOB, one of the two presentations is not genuine (cloned number, altered
biodata, or a reused forged template).

Source of prior records:
  * the web app's Postgres table `pehchaan_scans` (when DATABASE_URL is set)
  * otherwise the scans held by this API process (app.storage.file_store)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.config import get_settings
from app.modules.records.pii import hash_document_number, mask_document_number
from app.storage import file_store

logger = logging.getLogger(__name__)

_HIGH_RISK_VERDICTS = {"HIGH RISK", "REJECT"}
# Officer decisions that confirm an earlier flag. The system's own unreviewed
# verdicts are not evidence: counting them would let one OCR misread raise
# every later screening of the same genuine document.
_CONFIRMING_DECISIONS = {"reject", "secondary", "clear_refused"}


@dataclass
class PriorRecord:
    id: str
    name: str | None
    dob: str | None
    verdict: str | None
    checkpoint: str | None
    when: str | None
    officer_decision: str | None = None  # latest officer decision on that screening, if any


@dataclass
class RecordIssue:
    code: str
    message: str
    severity: str  # info | warning | critical


@dataclass
class RecordCheckResult:
    status: str  # not_checked | unavailable | no_history | consistent | conflict | flagged_history
    source: str
    document_number: str | None
    prior_count: int = 0
    prior_records: list[PriorRecord] = field(default_factory=list)
    issues: list[RecordIssue] = field(default_factory=list)
    risk: int | None = None  # None = not applicable to the risk score
    summary: str = ""
    # comparison with the issued-documents database (issued_documents.ReferenceCheck as a dict)
    reference: dict | None = None
    # the earlier-screenings outcome on its own, before the reference check was folded in
    history_status: str = ""
    history_summary: str = ""


def normalize_doc_number(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _normalize_name(value: str | None) -> str:
    return re.sub(r"[^A-Z ]", "", (value or "").upper()).strip()


def _name_similarity(a: str | None, b: str | None) -> float:
    a_n, b_n = _normalize_name(a), _normalize_name(b)
    if not a_n or not b_n:
        return 1.0
    direct = SequenceMatcher(None, a_n, b_n).ratio()
    token_sorted = SequenceMatcher(None, " ".join(sorted(a_n.split())), " ".join(sorted(b_n.split()))).ratio()
    return max(direct, token_sorted)


def _fetch_from_postgres(doc_number: str, exclude_id: str | None) -> list[PriorRecord]:
    import psycopg

    settings = get_settings()
    doc_hash = hash_document_number(doc_number)
    with psycopg.connect(settings.DATABASE_URL, connect_timeout=5) as conn:
        # New records store only a keyed hash of the number; records saved
        # before hashing was introduced still hold the plain number.
        has_decisions = conn.execute("SELECT to_regclass('pehchaan_decisions') IS NOT NULL").fetchone()[0]
        decision_col = (
            # A clear still awaiting co-signature is not a decision yet; one the
            # In-Charge refused upholds the flag.
            "(SELECT CASE WHEN d.status = 'cosign_refused' THEN 'clear_refused' ELSE d.decision END"
            " FROM pehchaan_decisions d WHERE d.scan_id = s.id AND d.status <> 'pending_cosign'"
            " ORDER BY d.created_at DESC LIMIT 1)"
            if has_decisions else "NULL"
        )
        rows = conn.execute(
            f"""
            SELECT s.id, s.presenter_name, s.dob, s.risk_verdict, s.lane, s.created_at, {decision_col}
            FROM pehchaan_scans s
            WHERE (s.doc_number_hash = %s
                   OR (s.doc_number_hash IS NULL
                       AND regexp_replace(upper(coalesce(s.doc_number, '')), '[^A-Z0-9]', '', 'g') = %s))
              AND (%s::text IS NULL OR s.id <> %s::text)
            ORDER BY s.created_at DESC
            LIMIT 25
            """,
            (doc_hash, doc_number, exclude_id, exclude_id),
        ).fetchall()
    return [
        PriorRecord(id=r[0], name=r[1], dob=r[2], verdict=r[3], checkpoint=r[4],
                    when=r[5].isoformat() if r[5] else None, officer_decision=r[6])
        for r in rows
    ]


def _fetch_from_memory(doc_number: str) -> list[PriorRecord]:
    out = []
    for rec in file_store.list_scans(limit=1000):
        fields = rec.get("identity") or {}
        if normalize_doc_number(fields.get("document_number")) != doc_number:
            continue
        out.append(PriorRecord(
            id=rec.get("id"), name=fields.get("name"), dob=fields.get("date_of_birth"),
            verdict=(rec.get("risk") or {}).get("verdict"), checkpoint=None, when=rec.get("timestamp"),
            officer_decision=rec.get("officer_decision"),
        ))
    return out


def apply_reference_check(result: RecordCheckResult, reference) -> RecordCheckResult:
    """Fold the issued-documents comparison into the records result.

    A mismatch with the issuing records is an identity conflict in its own
    right (risk 100). A match is positive evidence, so a document with no
    screening history still gets a records signal of 0 instead of none.
    A number that is simply not in the database changes nothing: the
    database only covers the documents it was built from.
    """
    from dataclasses import asdict

    result.reference = asdict(reference)
    result.history_status, result.history_summary = result.status, result.summary
    if reference.status == "mismatch":
        shown = "; ".join(
            f"{f.field.replace('_', ' ')}: document '{f.on_document}', issuing records '{f.in_database}'"
            for f in reference.fields if not f.match)
        result.issues.insert(0, RecordIssue(
            "ISSUING_RECORD_MISMATCH",
            f"{reference.summary} ({shown})",
            "critical",
        ))
        result.status, result.risk = "conflict", 100
        result.summary = reference.summary
    elif reference.status == "match":
        if result.risk is None:
            result.status, result.risk = "consistent", 0
            result.summary = reference.summary
        else:
            result.summary = f"{result.summary} {reference.summary}"
    return result


def check_against_records(
    document_number: str | None,
    name: str | None,
    dob: str | None,
    exclude_id: str | None = None,
) -> RecordCheckResult:
    settings = get_settings()
    doc = normalize_doc_number(document_number)
    source = "postgres" if settings.DATABASE_URL else "in-process"

    if len(doc) < 5:
        return RecordCheckResult(
            status="not_checked", source=source, document_number=None,
            summary="No document number could be read, so there was nothing to look up.",
        )

    try:
        prior = _fetch_from_postgres(doc, exclude_id) if settings.DATABASE_URL else _fetch_from_memory(doc)
    except Exception as e:
        logger.warning("Records lookup failed: %s", e)
        return RecordCheckResult(
            status="unavailable", source=source, document_number=mask_document_number(doc),
            issues=[RecordIssue("RECORDS_UNAVAILABLE", "Screening records database could not be reached; history check skipped.", "info")],
            summary="Records database unreachable — history check skipped.",
        )

    result = RecordCheckResult(status="no_history", source=source, document_number=mask_document_number(doc),
                               prior_count=len(prior), prior_records=prior)
    if not prior:
        result.summary = "First time this document number has been screened."
        return result

    name_conflicts = [p for p in prior if p.name and name and
                      _name_similarity(p.name, name) < settings.RECORDS_NAME_MATCH_THRESHOLD]
    dob_conflicts = [p for p in prior if p.dob and dob and p.dob.strip() != dob.strip()]
    flagged = [p for p in prior if (p.officer_decision or "").lower() in _CONFIRMING_DECISIONS]
    unreviewed = [p for p in prior if not p.officer_decision and (p.verdict or "").upper() in _HIGH_RISK_VERDICTS]

    if name_conflicts:
        p = name_conflicts[0]
        result.issues.append(RecordIssue(
            "RECORD_NAME_CONFLICT",
            f"Document number {mask_document_number(doc)} was previously screened under the name '{p.name}' "
            f"(record {p.id}); this document shows '{name}'. Same number, different holder.",
            "critical",
        ))
    if dob_conflicts:
        p = dob_conflicts[0]
        result.issues.append(RecordIssue(
            "RECORD_DOB_CONFLICT",
            f"Document number {mask_document_number(doc)} was previously screened with date of birth {p.dob} "
            f"(record {p.id}); this document shows {dob}.",
            "critical",
        ))

    if name_conflicts or dob_conflicts:
        result.status, result.risk = "conflict", 100
        result.summary = f"Identity details conflict with {len(prior)} earlier screening(s) of this number."
    elif flagged:
        result.status, result.risk = "flagged_history", 50
        result.issues.append(RecordIssue(
            "RECORD_PRIOR_HIGH_RISK",
            f"An officer sent this document number to secondary inspection or rejected it in {len(flagged)} "
            f"earlier screening(s) (latest: {flagged[0].id}).",
            "warning",
        ))
        result.summary = "Details match earlier screenings, but an officer flagged this number before."
    else:
        result.status, result.risk = "consistent", 0
        result.summary = f"Name and date of birth match {len(prior)} earlier screening(s) of this number."
        if unreviewed:
            result.issues.append(RecordIssue(
                "RECORD_PRIOR_UNREVIEWED_FLAG",
                f"The system rated this number HIGH RISK in {len(unreviewed)} earlier screening(s) that no officer "
                "reviewed; those verdicts are not counted against this one.",
                "info",
            ))
    return result
