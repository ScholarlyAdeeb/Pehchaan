"""
Issued-documents database — the reference a screened document is compared with.

Earlier screenings (crosscheck.py) only say whether a number was seen before.
This database plays the part of the issuing authority's records: for every
document that was issued it holds the holder's name, date of birth and expiry
date. A forged card that reuses a real number with altered biodata, or a
genuine card with an edited date, disagrees with it.

It is a local SQLite file so the check keeps working at a checkpoint with no
network. Document numbers are stored only as keyed hashes (PII_HASH_KEY, the
same hash the screening records use) plus a masked form for display.

Build it with:  python -m scripts.build_issued_documents_db
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.config import BACKEND_ROOT, get_settings
from app.modules.records.pii import hash_document_number, mask_document_number, normalize

logger = logging.getLogger(__name__)

DB_PATH = BACKEND_ROOT / "data" / "registry" / "issued_documents.sqlite"

# the engine's document types that share one kind of record
FAMILY = {"aadhar": "aadhaar", "national_id": "aadhaar", "pan": "pan",
          "driving_license": "driving_license", "passport": "passport"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS issued_documents (
    doc_type      TEXT NOT NULL,
    number_hash   TEXT NOT NULL,
    number_masked TEXT NOT NULL,
    name          TEXT NOT NULL,
    dob           TEXT,
    expiry        TEXT,
    person_ref    INTEGER,
    PRIMARY KEY (doc_type, number_hash)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class ReferenceField:
    field: str
    on_document: str | None
    in_database: str | None
    match: bool


@dataclass
class ReferenceCheck:
    # not_checked | unavailable | not_found | match | mismatch
    status: str
    summary: str
    database_size: int = 0
    fields: list[ReferenceField] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)


def key_fingerprint() -> str | None:
    """Identifies the PII_HASH_KEY a database was built with, without revealing it."""
    key = get_settings().PII_HASH_KEY
    return hashlib.sha256(b"issued-documents|" + key.encode()).hexdigest()[:16] if key else None


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def check_issued_document(
    document_type: str,
    document_number: str | None,
    name: str | None,
    dob: str | None,
    expiry: str | None = None,
    db_path: Path | None = None,
) -> ReferenceCheck:
    from app.modules.records.crosscheck import _name_similarity

    path = db_path or DB_PATH
    family = FAMILY.get(document_type)
    if family is None:
        return ReferenceCheck("not_checked", f"No issuing records are held for document type '{document_type}'.")
    if len(normalize(document_number)) < 5:
        return ReferenceCheck("not_checked", "No document number could be read, so the issuing records could not be searched.")
    if not path.is_file():
        return ReferenceCheck("unavailable", "Issued-documents database has not been built on this machine.")
    number_hash = hash_document_number(document_number)
    if number_hash is None:
        return ReferenceCheck("unavailable", "PII_HASH_KEY is not set, so document numbers cannot be looked up.")

    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            size = conn.execute("SELECT COUNT(*) FROM issued_documents WHERE doc_type = ?", (family,)).fetchone()[0]
            row = conn.execute(
                "SELECT name, dob, expiry FROM issued_documents WHERE doc_type = ? AND number_hash = ?",
                (family, number_hash),
            ).fetchone()
    except sqlite3.Error as e:
        logger.warning("Issued-documents lookup failed: %s", e)
        return ReferenceCheck("unavailable", "Issued-documents database could not be read.")

    if meta.get("key_fingerprint") != key_fingerprint():
        return ReferenceCheck("unavailable", "Issued-documents database was built with a different PII_HASH_KEY; rebuild it.", size)
    masked = mask_document_number(document_number)
    if row is None:
        return ReferenceCheck(
            "not_found", f"Number {masked} is not among the {size} issued {family.replace('_', ' ')} records held here.", size)

    db_name, db_dob, db_expiry = row
    threshold = get_settings().RECORDS_NAME_MATCH_THRESHOLD
    fields = [ReferenceField("name", name, db_name, not name or _name_similarity(name, db_name) >= threshold)]
    if db_dob:
        fields.append(ReferenceField("date_of_birth", dob, db_dob, not dob or dob.strip() == db_dob))
    if db_expiry:
        fields.append(ReferenceField("expiry_date", expiry, db_expiry, not expiry or expiry.strip() == db_expiry))
    mismatched = [f.field for f in fields if not f.match]
    compared = [f.field for f in fields if f.on_document]
    if mismatched:
        return ReferenceCheck(
            "mismatch", f"Number {masked} is issued to a holder whose {', '.join(m.replace('_', ' ') for m in mismatched)} "
            "differ from what this document shows.", size, fields, mismatched)
    return ReferenceCheck(
        "match", f"Number {masked} is in the issuing records and {', '.join(c.replace('_', ' ') for c in compared) or 'the number'} agree.",
        size, fields)
