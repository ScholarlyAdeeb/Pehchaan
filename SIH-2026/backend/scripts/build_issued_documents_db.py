"""
Build the issued-documents database from the generated identity dataset.

Source: training/data_generated/annotations/<type>/*.json — the ground truth
of what was printed on each of the 1200 cards (300 people x Aadhaar, PAN,
driving licence, passport). One row per document: keyed hash of the number,
masked number, holder name, date of birth, expiry date.

Usage (from backend/):
    python -m scripts.build_issued_documents_db [--source <annotations dir>]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.modules.records import issued_documents as db  # noqa: E402
from app.modules.records.pii import hash_document_number, mask_document_number  # noqa: E402

DEFAULT_SOURCE = BACKEND / "training" / "data_generated" / "annotations"

# annotation folder -> (doc_type, number key, name keys, dob key, expiry key)
SOURCES = {
    "aadhar": ("aadhaar", "Aadhaar_Number", ["Aadhaar_Name"], "Aadhaar_DOB", None),
    "pan": ("pan", "PAN_Number", ["PAN_Name"], "PAN_DOB", None),
    "driving_license": ("driving_license", "DL_Number", ["Name"], "DOB", "Validity_NT"),
    "passport": ("passport", "Passport_Number", ["Passport_Given_Name", "Passport_Surname"],
                 "Passport_DOB", "Passport_Date_Of_Expiry"),
}


def iso(ddmmyyyy: str | None) -> str | None:
    try:
        return datetime.strptime((ddmmyyyy or "").strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=db.DB_PATH)
    args = ap.parse_args()

    fingerprint = db.key_fingerprint()
    if fingerprint is None:
        print("PII_HASH_KEY is not set (backend/.env); document numbers cannot be hashed.", file=sys.stderr)
        return 1
    if not args.source.is_dir():
        print(f"No annotations at {args.source}; generate the dataset first (scripts/cardgen/generate.py).", file=sys.stderr)
        return 1

    rows, counts = [], {}
    for folder, (doc_type, number_key, name_keys, dob_key, expiry_key) in SOURCES.items():
        for path in sorted((args.source / folder).glob("*.json")):
            ann = json.loads(path.read_text(encoding="utf-8"))
            f = ann["fields"]
            number = f.get(number_key)
            name = " ".join(filter(None, (f.get(k, "").strip() for k in name_keys)))
            number_hash = hash_document_number(number)
            if not number_hash or not name:
                continue
            rows.append((doc_type, number_hash, mask_document_number(number), name, iso(f.get(dob_key)),
                         iso(f.get(expiry_key)) if expiry_key else None, int(ann.get("serial_number") or 0)))
            counts[doc_type] = counts.get(doc_type, 0) + 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.unlink(missing_ok=True)   # rebuilt from the dataset each time, never edited in place
    conn = db.connect(args.out)
    with conn:
        conn.executemany("INSERT OR REPLACE INTO issued_documents VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [
            ("key_fingerprint", fingerprint),
            ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            ("source", "training/data_generated (synthetic identities)"),
            ("documents", str(len(rows))),
        ])
    conn.close()
    print(f"wrote {args.out} — {len(rows)} documents: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
