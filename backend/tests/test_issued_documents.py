import pytest

from app.config import get_settings
from app.modules.records import issued_documents as db
from app.modules.records.crosscheck import RecordCheckResult, apply_reference_check
from app.modules.records.pii import hash_document_number, mask_document_number


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "PII_HASH_KEY", "test-key", raising=False)
    path = tmp_path / "issued.sqlite"
    conn = db.connect(path)
    with conn:
        conn.execute("INSERT INTO issued_documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                     ("passport", hash_document_number("O2453770"), mask_document_number("O2453770"),
                      "Geeta Sharma", "1980-04-17", "2030-11-25", 1))
        conn.execute("INSERT INTO meta VALUES ('key_fingerprint', ?)", (db.key_fingerprint(),))
    conn.close()
    return path


def _no_history():
    return RecordCheckResult(status="no_history", source="in-process", document_number="x", summary="First time.")


def test_matching_document_agrees_with_issuing_records(registry):
    r = db.check_issued_document("passport", "O2453770", "GEETA SHARMA", "1980-04-17", "2030-11-25", registry)
    assert r.status == "match" and not r.mismatched


def test_altered_name_or_expiry_is_a_mismatch(registry):
    r = db.check_issued_document("passport", "O2453770", "Rohit Verma", "1980-04-17", "2035-11-25", registry)
    assert r.status == "mismatch" and r.mismatched == ["name", "expiry_date"]


def test_unknown_number_is_not_found_and_other_types_are_separate(registry):
    assert db.check_issued_document("passport", "Z9999999", "Geeta Sharma", None, None, registry).status == "not_found"
    assert db.check_issued_document("pan", "O2453770", "Geeta Sharma", None, None, registry).status == "not_found"


def test_database_built_with_another_key_is_refused(registry, monkeypatch):
    monkeypatch.setattr(get_settings(), "PII_HASH_KEY", "rotated-key", raising=False)
    assert db.check_issued_document("passport", "O2453770", "Geeta Sharma", None, None, registry).status == "unavailable"


def test_number_is_stored_only_hashed_and_masked(registry):
    assert b"O2453770" not in registry.read_bytes()


def test_reference_check_folds_into_the_records_signal(registry):
    ok = apply_reference_check(_no_history(), db.check_issued_document(
        "passport", "O2453770", "Geeta Sharma", "1980-04-17", None, registry))
    assert (ok.status, ok.risk, ok.history_status) == ("consistent", 0, "no_history")

    bad = apply_reference_check(_no_history(), db.check_issued_document(
        "passport", "O2453770", "Rohit Verma", "1980-04-17", None, registry))
    assert (bad.status, bad.risk) == ("conflict", 100)
    assert bad.issues[0].code == "ISSUING_RECORD_MISMATCH"

    unknown = apply_reference_check(_no_history(), db.check_issued_document(
        "passport", "Z9999999", "A B", None, None, registry))
    assert (unknown.status, unknown.risk) == ("no_history", None)
