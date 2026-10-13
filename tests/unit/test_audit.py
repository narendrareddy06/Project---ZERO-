"""Unit tests for cryptographic tamper-evident audit logging."""

import json
import sqlite3
import pytest
from zero.audit import AuditManager, GENESIS_HASH
from zero.database import Database


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_audit_zero.db"
    db = Database(db_file)
    yield db
    db.close()


def test_audit_event_sequence_and_genesis(temp_db):
    """First audit event links to genesis hash, subsequent increment sequence."""
    audit = temp_db.audit
    ev1 = audit.record_event("USER", "LOGIN", {"ip": "127.0.0.1"})
    assert ev1.sequence == 1
    assert ev1.prev_hash == GENESIS_HASH
    assert len(ev1.event_hash) == 64

    ev2 = audit.record_event("USER", "SEARCH", {"query": "logistics"})
    assert ev2.sequence == 2
    assert ev2.prev_hash == ev1.event_hash


def test_audit_integrity_verification_success(temp_db):
    """Valid chain of events passes cryptographic verification."""
    audit = temp_db.audit
    for i in range(10):
        audit.record_event("SYSTEM", f"ACTION_{i}", {"index": i})

    is_valid, msg, fail_seq = audit.verify_chain_integrity()
    assert is_valid is True
    assert "Integrity verified for 10 audit events" in msg
    assert fail_seq is None


def test_audit_detects_payload_tampering(temp_db):
    """Direct modification of payload_json in SQLite is detected."""
    audit = temp_db.audit
    audit.record_event("SYSTEM", "INIT", {"step": 1})
    audit.record_event("SYSTEM", "STEP2", {"amount": 100})
    audit.record_event("SYSTEM", "STEP3", {"step": 3})

    # Tamper with row 2 payload directly via SQL
    conn = temp_db.get_connection()
    with conn:
        tampered_details = json.dumps({"amount": 999999})
        conn.execute(
            "UPDATE audit_events SET details_json = ? WHERE sequence = 2",
            (tampered_details,),
        )

    is_valid, msg, fail_seq = audit.verify_chain_integrity()
    assert is_valid is False
    assert fail_seq == 2
    assert "Payload tampering detected at sequence 2" in msg


def test_audit_detects_hash_tampering(temp_db):
    """Direct modification of event_hash or prev_hash is detected."""
    audit = temp_db.audit
    audit.record_event("SYSTEM", "EVENT_1", {})
    audit.record_event("SYSTEM", "EVENT_2", {})

    conn = temp_db.get_connection()
    with conn:
        conn.execute(
            "UPDATE audit_events SET prev_hash = 'badhash0000000000000000000000000000000000000000000000000000000000' WHERE sequence = 2"
        )

    is_valid, msg, fail_seq = audit.verify_chain_integrity()
    assert is_valid is False
    assert fail_seq == 2
    assert "Hash chain broken at sequence 2" in msg


def test_audit_detects_sequence_deletion(temp_db):
    """Deleting an audit row causes sequence break detection."""
    audit = temp_db.audit
    audit.record_event("SYSTEM", "STEP_1", {})
    audit.record_event("SYSTEM", "STEP_2", {})
    audit.record_event("SYSTEM", "STEP_3", {})

    conn = temp_db.get_connection()
    with conn:
        conn.execute("DELETE FROM audit_events WHERE sequence = 2")

    is_valid, msg, fail_seq = audit.verify_chain_integrity()
    assert is_valid is False
    assert fail_seq == 3
    assert "Sequence break" in msg
