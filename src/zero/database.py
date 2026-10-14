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
    ProofAsset,
    Prospect,
    ProspectStatus,
    Run,
    RunState,
    SuppressionRecord,
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
                    excerpt TEXT,
                    retrieved_at TEXT,
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

                CREATE TABLE IF NOT EXISTS prospects (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    domain_or_website TEXT NOT NULL,
                    geography TEXT NOT NULL,
                    industry_or_niche TEXT NOT NULL,
                    public_source_url TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fit_score REAL,
                    fit_rationale TEXT,
                    verified_facts_json TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    associated_offer_id TEXT,
                    is_sample INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_prospects_domain ON prospects(domain_or_website);
                CREATE INDEX IF NOT EXISTS idx_prospects_offer ON prospects(associated_offer_id);

                CREATE TABLE IF NOT EXISTS suppression_list (
                    domain_or_email TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS proof_assets (
                    id TEXT PRIMARY KEY,
                    offer_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    disclaimer TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_sample INTEGER DEFAULT 1
                );
                """
            )
            # Lightweight schema migration for existing databases
            for tbl in ["runs", "evidence", "offers", "prospects", "proof_assets"]:
                cursor = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
                if cursor.fetchone():
                    cursor = conn.execute(f"PRAGMA table_info({tbl})")
                    cols = {r["name"] for r in cursor.fetchall()}
                    if "is_sample" not in cols:
                        conn.execute(f"ALTER TABLE {tbl} ADD COLUMN is_sample INTEGER DEFAULT 0")

            cursor = conn.execute("PRAGMA table_info(evidence)")
            ev_cols = {r["name"] for r in cursor.fetchall()}
            if "excerpt" not in ev_cols:
                conn.execute("ALTER TABLE evidence ADD COLUMN excerpt TEXT")
            if "retrieved_at" not in ev_cols:
                conn.execute("ALTER TABLE evidence ADD COLUMN retrieved_at TEXT")

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
                INSERT OR REPLACE INTO evidence (id, claim, evidence_type, geography, confidence, source_url, captured_at, notes, excerpt, retrieved_at, is_sample)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ev.excerpt,
                    ev.retrieved_at.isoformat() if ev.retrieved_at else None,
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
                "has_excerpt": bool(ev.excerpt),
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
            excerpt=row["excerpt"] if "excerpt" in row.keys() else None,
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]) if ("retrieved_at" in row.keys() and row["retrieved_at"]) else None,
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
                excerpt=r["excerpt"] if "excerpt" in r.keys() else None,
                retrieved_at=datetime.fromisoformat(r["retrieved_at"]) if ("retrieved_at" in r.keys() and r["retrieved_at"]) else None,
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

    # --- Prospect Methods ---
    def save_prospect(self, prospect: Prospect, actor: str = "AGENT") -> Prospect:
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO prospects
                (id, company_name, domain_or_website, geography, industry_or_niche, public_source_url,
                 discovered_at, status, fit_score, fit_rationale, verified_facts_json, assumptions_json,
                 associated_offer_id, is_sample)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prospect.id,
                    prospect.company_name,
                    prospect.domain_or_website.lower().strip(),
                    prospect.geography.value,
                    prospect.industry_or_niche,
                    prospect.public_source_url,
                    prospect.discovered_at.isoformat(),
                    prospect.status.value,
                    prospect.fit_score,
                    prospect.fit_rationale,
                    json.dumps(prospect.verified_facts),
                    json.dumps(prospect.assumptions),
                    prospect.associated_offer_id,
                    1 if prospect.is_sample else 0,
                ),
            )
        self.audit.record_event(
            actor,
            "PROSPECT_RECORDED",
            {
                "prospect_id": prospect.id,
                "company_name": prospect.company_name,
                "domain": prospect.domain_or_website,
                "status": prospect.status.value,
                "fit_score": prospect.fit_score,
                "is_sample": prospect.is_sample,
            },
        )
        return prospect

    def get_prospect(self, prospect_id: str) -> Optional[Prospect]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_prospect(row)

    def find_prospect_by_domain(self, domain_or_website: str) -> Optional[Prospect]:
        conn = self.get_connection()
        cursor = conn.cursor()
        norm_domain = domain_or_website.lower().strip()
        cursor.execute(
            "SELECT * FROM prospects WHERE LOWER(domain_or_website) = ? OR LOWER(domain_or_website) LIKE ?",
            (norm_domain, f"%{norm_domain}%"),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_prospect(row)

    def list_prospects(
        self,
        associated_offer_id: Optional[str] = None,
        status: Optional[ProspectStatus] = None,
        is_sample: Optional[bool] = None,
    ) -> List[Prospect]:
        conn = self.get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM prospects WHERE 1=1"
        params: List[Any] = []
        if associated_offer_id:
            query += " AND associated_offer_id = ?"
            params.append(associated_offer_id)
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if is_sample is not None:
            query += " AND is_sample = ?"
            params.append(1 if is_sample else 0)
        query += " ORDER BY discovered_at DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_prospect(r) for r in rows]

    def _row_to_prospect(self, row: sqlite3.Row) -> Prospect:
        return Prospect(
            id=row["id"],
            company_name=row["company_name"],
            domain_or_website=row["domain_or_website"],
            geography=Geography(row["geography"]),
            industry_or_niche=row["industry_or_niche"],
            public_source_url=row["public_source_url"],
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            status=ProspectStatus(row["status"]),
            fit_score=row["fit_score"],
            fit_rationale=row["fit_rationale"],
            verified_facts=json.loads(row["verified_facts_json"]),
            assumptions=json.loads(row["assumptions_json"]),
            associated_offer_id=row["associated_offer_id"],
            is_sample=bool(row["is_sample"]) if "is_sample" in row.keys() else False,
        )

    # --- Suppression Methods ---
    def add_suppression(self, record: SuppressionRecord, actor: str = "USER") -> SuppressionRecord:
        conn = self.get_connection()
        norm_id = record.domain_or_email.lower().strip()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO suppression_list (domain_or_email, reason, added_at, notes)
                VALUES (?, ?, ?, ?)
                """,
                (norm_id, record.reason, record.added_at.isoformat(), record.notes),
            )
        self.audit.record_event(
            actor,
            "SUPPRESSION_ADDED",
            {"domain_or_email": norm_id, "reason": record.reason},
        )
        return record

    def is_suppressed(self, identifier: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        norm_id = identifier.lower().strip()
        cursor.execute("SELECT 1 FROM suppression_list WHERE domain_or_email = ?", (norm_id,))
        if cursor.fetchone():
            return True
        # If identifier is an email (user@example.com), also check domain (@example.com and example.com)
        if "@" in norm_id:
            domain_part = norm_id.split("@", 1)[1]
            cursor.execute("SELECT 1 FROM suppression_list WHERE domain_or_email = ?", (domain_part,))
            if cursor.fetchone():
                return True
        return False

    def list_suppression(self) -> List[SuppressionRecord]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM suppression_list ORDER BY added_at DESC")
        rows = cursor.fetchall()
        return [
            SuppressionRecord(
                domain_or_email=r["domain_or_email"],
                reason=r["reason"],
                added_at=datetime.fromisoformat(r["added_at"]),
                notes=r["notes"] or "",
            )
            for r in rows
        ]

    # --- Proof Asset Methods ---
    def save_proof_asset(self, asset: ProofAsset, actor: str = "AGENT") -> ProofAsset:
        conn = self.get_connection()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO proof_assets (id, offer_id, title, asset_type, content, disclaimer, created_at, is_sample)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.id,
                    asset.offer_id,
                    asset.title,
                    asset.asset_type,
                    asset.content,
                    asset.disclaimer,
                    asset.created_at.isoformat(),
                    1 if asset.is_sample else 0,
                ),
            )
        self.audit.record_event(
            actor,
            "PROOF_ASSET_CREATED",
            {
                "asset_id": asset.id,
                "offer_id": asset.offer_id,
                "title": asset.title,
                "is_sample": asset.is_sample,
            },
        )
        return asset

    def get_proof_asset(self, asset_id: str) -> Optional[ProofAsset]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proof_assets WHERE id = ?", (asset_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return ProofAsset(
            id=row["id"],
            offer_id=row["offer_id"],
            title=row["title"],
            asset_type=row["asset_type"],
            content=row["content"],
            disclaimer=row["disclaimer"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_sample=bool(row["is_sample"]) if "is_sample" in row.keys() else True,
        )

    def list_proof_assets(self, offer_id: Optional[str] = None) -> List[ProofAsset]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if offer_id:
            cursor.execute("SELECT * FROM proof_assets WHERE offer_id = ? ORDER BY created_at DESC", (offer_id,))
        else:
            cursor.execute("SELECT * FROM proof_assets ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [
            ProofAsset(
                id=r["id"],
                offer_id=r["offer_id"],
                title=r["title"],
                asset_type=r["asset_type"],
                content=r["content"],
                disclaimer=r["disclaimer"],
                created_at=datetime.fromisoformat(r["created_at"]),
                is_sample=bool(r["is_sample"]) if "is_sample" in r.keys() else True,
            )
            for r in rows
        ]
