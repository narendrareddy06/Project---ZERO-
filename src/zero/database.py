"""SQLite persistence layer for Project ZERO."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zero.audit import AuditManager
from zero.config import DEFAULT_DB_PATH
from zero.schemas import (
    Evidence,
    EvidenceType,
    Geography,
    OfferCandidate,
    Run,
    RunState,
)


class Database:
    """Encapsulates SQLite connection, schema setup, and transactions."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign keys for durability
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        conn = self.get_connection()
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    current_stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    budget_spent_inr REAL DEFAULT 0.0,
                    is_sample INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    geography TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_url TEXT,
                    captured_at TEXT NOT NULL,
                    notes TEXT,
                    is_sample INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS offers (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    target_geography TEXT NOT NULL,
                    buyer_profile TEXT NOT NULL,
                    problem_statement TEXT NOT NULL,
                    proposed_deliverable TEXT NOT NULL,
                    plausible_pricing_or_pilot TEXT NOT NULL,
                    delivery_method TEXT NOT NULL,
                    risks_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    evaluation_json TEXT,
                    is_sample INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )
            # Lightweight schema migration for existing databases
            for tbl in ["runs", "evidence", "offers"]:
                cursor = conn.execute(f"PRAGMA table_info({tbl})")
                cols = {r["name"] for r in cursor.fetchall()}
                if "is_sample" not in cols:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN is_sample INTEGER DEFAULT 0")

    @property
    def audit(self) -> AuditManager:
        return AuditManager(self.get_connection())

    # --- Run Methods ---
    def create_run(self, run: Run) -> Run:
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (run_id, started_at, ended_at, current_stage, status, budget_spent_inr, is_sample)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.started_at.isoformat(),
                    run.ended_at.isoformat() if run.ended_at else None,
                    run.current_stage.value,
                    run.status,
                    run.budget_spent_inr,
                    1 if run.is_sample else 0,
                ),
            )
        self.audit.record_event("SYSTEM", "RUN_CREATED", {"run_id": run.run_id, "stage": run.current_stage.value, "is_sample": run.is_sample})
        return run

    def get_run(self, run_id: str) -> Optional[Run]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return Run(
            run_id=row["run_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            current_stage=RunState(row["current_stage"]),
            status=row["status"],
            budget_spent_inr=row["budget_spent_inr"],
            is_sample=bool(row["is_sample"]) if "is_sample" in row.keys() else False,
        )

    def update_run_stage(self, run_id: str, stage: RunState, status: str) -> None:
        conn = self.get_connection()
        with conn:
            conn.execute(
                "UPDATE runs SET current_stage = ?, status = ? WHERE run_id = ?",
                (stage.value, status, run_id),
            )
        self.audit.record_event("SYSTEM", "STAGE_UPDATED", {"run_id": run_id, "new_stage": stage.value, "status": status})

    # --- Evidence Methods ---
    def save_evidence(self, ev: Evidence, actor: str = "USER") -> Evidence:
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence (id, claim, evidence_type, geography, confidence, source_url, captured_at, notes, is_sample)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev.id,
                    ev.claim,
                    ev.evidence_type.value,
                    ev.geography.value,
                    ev.confidence,
                    ev.source_url,
                    ev.captured_at.isoformat(),
                    ev.notes,
                    1 if ev.is_sample else 0,
                ),
            )
        self.audit.record_event(
            actor,
            "EVIDENCE_RECORDED",
            {
                "evidence_id": ev.id,
                "evidence_type": ev.evidence_type.value,
                "geography": ev.geography.value,
                "confidence": ev.confidence,
                "is_sample": ev.is_sample,
            },
        )
        return ev

    def get_evidence(self, ev_id: str) -> Optional[Evidence]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evidence WHERE id = ?", (ev_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return Evidence(
            id=row["id"],
            claim=row["claim"],
            evidence_type=EvidenceType(row["evidence_type"]),
            geography=Geography(row["geography"]),
            confidence=row["confidence"],
            source_url=row["source_url"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            notes=row["notes"] or "",
            is_sample=bool(row["is_sample"]) if "is_sample" in row.keys() else False,
        )

    def list_evidence(
        self,
        geography: Optional[Geography] = None,
        evidence_type: Optional[EvidenceType] = None,
        is_sample: Optional[bool] = None,
    ) -> List[Evidence]:
        conn = self.get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM evidence WHERE 1=1"
        params: List[Any] = []
        if geography:
            query += " AND geography = ?"
            params.append(geography.value)
        if evidence_type:
            query += " AND evidence_type = ?"
            params.append(evidence_type.value)
        if is_sample is not None:
            query += " AND is_sample = ?"
            params.append(1 if is_sample else 0)
        query += " ORDER BY captured_at DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            Evidence(
                id=r["id"],
                claim=r["claim"],
                evidence_type=EvidenceType(r["evidence_type"]),
                geography=Geography(r["geography"]),
                confidence=r["confidence"],
                source_url=r["source_url"],
                captured_at=datetime.fromisoformat(r["captured_at"]),
                notes=r["notes"] or "",
                is_sample=bool(r["is_sample"]) if "is_sample" in r.keys() else False,
            )
            for r in rows
        ]

    # --- Offer Methods ---
    def save_offer(self, offer: OfferCandidate, actor: str = "AGENT") -> OfferCandidate:
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO offers 
                (id, title, target_geography, buyer_profile, problem_statement, proposed_deliverable, plausible_pricing_or_pilot, delivery_method, risks_json, evidence_ids_json, evaluation_json, is_sample)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer.id,
                    offer.title,
                    offer.target_geography.value,
                    offer.buyer_profile,
                    offer.problem_statement,
                    offer.proposed_deliverable,
                    offer.plausible_pricing_or_pilot,
                    offer.delivery_method,
                    json.dumps(offer.risks),
                    json.dumps(offer.evidence_ids),
                    json.dumps(offer.evaluation.model_dump()) if offer.evaluation else None,
                    1 if offer.is_sample else 0,
                ),
            )
        self.audit.record_event(
            actor,
            "OFFER_RECORDED",
            {
                "offer_id": offer.id,
                "title": offer.title,
                "geography": offer.target_geography.value,
                "status": offer.evaluation.status.value if offer.evaluation else "PENDING_EVALUATION",
                "is_sample": offer.is_sample,
            },
        )
        return offer

    def get_offer(self, offer_id: str) -> Optional[OfferCandidate]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM offers WHERE id = ?", (offer_id,))
        row = cursor.fetchone()
        if not row:
            return None
        eval_data = json.loads(row["evaluation_json"]) if row["evaluation_json"] else None
        return OfferCandidate(
            id=row["id"],
            title=row["title"],
            target_geography=Geography(row["target_geography"]),
            buyer_profile=row["buyer_profile"],
            problem_statement=row["problem_statement"],
            proposed_deliverable=row["proposed_deliverable"],
            plausible_pricing_or_pilot=row["plausible_pricing_or_pilot"],
            delivery_method=row["delivery_method"],
            risks=json.loads(row["risks_json"]),
            evidence_ids=json.loads(row["evidence_ids_json"]),
            evaluation=eval_data,
            is_sample=bool(row["is_sample"]) if "is_sample" in row.keys() else False,
        )

    def list_offers(
        self,
        geography: Optional[Geography] = None,
        is_sample: Optional[bool] = None,
    ) -> List[OfferCandidate]:
        conn = self.get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM offers WHERE 1=1"
        params: List[Any] = []
        if geography:
            query += " AND target_geography = ?"
            params.append(geography.value)
        if is_sample is not None:
            query += " AND is_sample = ?"
            params.append(1 if is_sample else 0)
        cursor.execute(query, params)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            eval_data = json.loads(r["evaluation_json"]) if r["evaluation_json"] else None
            result.append(
                OfferCandidate(
                    id=r["id"],
                    title=r["title"],
                    target_geography=Geography(r["target_geography"]),
                    buyer_profile=r["buyer_profile"],
                    problem_statement=r["problem_statement"],
                    proposed_deliverable=r["proposed_deliverable"],
                    plausible_pricing_or_pilot=r["plausible_pricing_or_pilot"],
                    delivery_method=r["delivery_method"],
                    risks=json.loads(r["risks_json"]),
                    evidence_ids=json.loads(r["evidence_ids_json"]),
                    evaluation=eval_data,
                    is_sample=bool(r["is_sample"]) if "is_sample" in r.keys() else False,
                )
            )
        return result
