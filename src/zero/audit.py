"""Tamper-evident audit logging with cryptographic hash-chaining."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zero.schemas import AuditEvent

GENESIS_HASH = "0" * 64


def compute_payload_hash(details: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of payload details."""
    serialized = json.dumps(details, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_event_hash(
    sequence: int,
    timestamp: str,
    actor: str,
    action: str,
    payload_hash: str,
    prev_hash: str,
) -> str:
    """Compute cryptographic hash linking this event to the chain."""
    message = f"{sequence}|{timestamp}|{actor}|{action}|{payload_hash}|{prev_hash}"
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


class AuditManager:
    """Manages the creation and integrity verification of audit log events."""

    def __init__(self, db_conn):
        self.conn = db_conn

    def record_event(
        self,
        actor: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Append a new audit event to the hash chain."""
        details = details or {}
        payload_hash = compute_payload_hash(details)
        now = datetime.now(timezone.utc)
        timestamp_str = now.isoformat()

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        )
        last_row = cursor.fetchone()

        if last_row:
            sequence = last_row["sequence"] + 1
            prev_hash = last_row["event_hash"]
        else:
            sequence = 1
            prev_hash = GENESIS_HASH

        event_hash = compute_event_hash(
            sequence=sequence,
            timestamp=timestamp_str,
            actor=actor,
            action=action,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
        )

        event_id = f"aud_{sequence:06d}_{event_hash[:8]}"

        event = AuditEvent(
            event_id=event_id,
            sequence=sequence,
            timestamp=now,
            actor=actor,
            action=action,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
            event_hash=event_hash,
            details=details,
        )

        cursor.execute(
            """
            INSERT INTO audit_events 
            (event_id, sequence, timestamp, actor, action, payload_hash, prev_hash, event_hash, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.sequence,
                timestamp_str,
                event.actor,
                event.action,
                event.payload_hash,
                event.prev_hash,
                event.event_hash,
                json.dumps(event.details, sort_keys=True, default=str),
            ),
        )
        self.conn.commit()
        return event

    def verify_chain_integrity(self) -> Tuple[bool, str, Optional[int]]:
        """
        Verify the complete cryptographic chain of audit events.
        Returns: (is_valid, message, failure_sequence)
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT sequence, timestamp, actor, action, payload_hash, prev_hash, event_hash, details_json
            FROM audit_events ORDER BY sequence ASC
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return True, "Audit log is empty (valid)", None

        expected_prev = GENESIS_HASH
        for idx, row in enumerate(rows):
            seq = row["sequence"]
            if seq != idx + 1:
                return False, f"Sequence break: expected {idx + 1}, found {seq}", seq

            if row["prev_hash"] != expected_prev:
                return False, f"Hash chain broken at sequence {seq}: prev_hash mismatch", seq

            details = json.loads(row["details_json"])
            expected_payload_hash = compute_payload_hash(details)
            if row["payload_hash"] != expected_payload_hash:
                return False, f"Payload tampering detected at sequence {seq}", seq

            expected_event_hash = compute_event_hash(
                sequence=seq,
                timestamp=row["timestamp"],
                actor=row["actor"],
                action=row["action"],
                payload_hash=row["payload_hash"],
                prev_hash=row["prev_hash"],
            )
            if row["event_hash"] != expected_event_hash:
                return False, f"Event hash invalid at sequence {seq}", seq

            expected_prev = row["event_hash"]

        return True, f"Integrity verified for {len(rows)} audit events", None
