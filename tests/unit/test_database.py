"""Unit tests for SQLite database persistence and transaction handling."""

import sqlite3
import pytest
from zero.database import Database
from zero.schemas import (
    Evidence,
    EvidenceType,
    Geography,
    OfferCandidate,
    Run,
    RunState,
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_project_zero.db"
    db = Database(db_file)
    yield db
    db.close()


def test_database_initialization(temp_db):
    """Database tables are created upon initialization."""
    conn = temp_db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cursor.fetchall()}
    assert {"runs", "evidence", "offers", "audit_events"}.issubset(tables)


def test_evidence_save_and_filter(temp_db):
    """Test saving evidence and filtering by geography and type."""
    ev_in = Evidence(
        id="ev_in_01",
        claim="Indian enterprise procurement requires GST invoice validation.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.90,
        source_url="https://gst.gov.in/rules",
    )
    ev_us = Evidence(
        id="ev_us_01",
        claim="US trucking carriers face ELD mandate compliance friction.",
        evidence_type=EvidenceType.USER_PROVIDED,
        geography=Geography.US,
        confidence=0.75,
        notes="Interview with freight broker",
    )

    temp_db.save_evidence(ev_in)
    temp_db.save_evidence(ev_us)

    # Fetch by ID
    fetched_in = temp_db.get_evidence("ev_in_01")
    assert fetched_in is not None
    assert fetched_in.claim == ev_in.claim
    assert fetched_in.evidence_type == EvidenceType.VERIFIED_SOURCE

    # Filter by geography
    in_list = temp_db.list_evidence(geography=Geography.IN)
    assert len(in_list) == 1
    assert in_list[0].id == "ev_in_01"

    us_list = temp_db.list_evidence(geography=Geography.US)
    assert len(us_list) == 1
    assert us_list[0].id == "ev_us_01"

    # Filter by type
    verified_list = temp_db.list_evidence(evidence_type=EvidenceType.VERIFIED_SOURCE)
    assert len(verified_list) == 1
    assert verified_list[0].id == "ev_in_01"


def test_offer_save_and_retrieve(temp_db):
    """Test offer candidate persistence."""
    offer = OfferCandidate(
        id="off_test_01",
        title="Test Freight Audit Pilot",
        target_geography=Geography.IN,
        buyer_profile="Freight Logistics Managers",
        problem_statement="Overcharging by regional transporters",
        proposed_deliverable="Automated discrepancy report",
        plausible_pricing_or_pilot="Free audit of 50 bills",
        delivery_method="Remote python script",
        risks=["Missing rate card data"],
        evidence_ids=["ev_in_01"],
    )
    temp_db.save_offer(offer)

    fetched = temp_db.get_offer("off_test_01")
    assert fetched is not None
    assert fetched.title == offer.title
    assert fetched.target_geography == Geography.IN
    assert fetched.risks == ["Missing rate card data"]


def test_run_lifecycle_persistence(temp_db):
    """Test run creation and state transition persistence."""
    run = Run(run_id="run_001", current_stage=RunState.RESEARCH, status="IN_PROGRESS")
    temp_db.create_run(run)

    fetched = temp_db.get_run("run_001")
    assert fetched is not None
    assert fetched.current_stage == RunState.RESEARCH

    temp_db.update_run_stage("run_001", RunState.OFFER_DECISION, "EVALUATING")
    updated = temp_db.get_run("run_001")
    assert updated.current_stage == RunState.OFFER_DECISION
    assert updated.status == "EVALUATING"


def test_transaction_rollback_on_failure(temp_db):
    """Database rolls back properly when an error occurs during a transaction."""
    conn = temp_db.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            # First insert succeeds
            conn.execute(
                "INSERT INTO runs (run_id, started_at, current_stage, status) VALUES (?, datetime('now'), ?, ?)",
                ("run_tx_01", RunState.CREATED.value, "INIT"),
            )
            # Duplicate ID triggers IntegrityError and rolls back
            conn.execute(
                "INSERT INTO runs (run_id, started_at, current_stage, status) VALUES (?, datetime('now'), ?, ?)",
                ("run_tx_01", RunState.CREATED.value, "INIT"),
            )

    # Verify that run_tx_01 was NOT committed due to rollback
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs WHERE run_id = 'run_tx_01'")
    assert cursor.fetchone() is None


def test_is_sample_persistence_and_filtering(temp_db):
    """Test saving and filtering sample vs production records."""
    ev_prod = Evidence(
        id="ev_prod_01",
        claim="Real empirical finding from market research",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.85,
        source_url="https://example.com/real-study",
        is_sample=False,
    )
    ev_demo = Evidence(
        id="ev_demo_01",
        claim="Synthetic demonstration evidence for testing",
        evidence_type=EvidenceType.HYPOTHESIS,
        geography=Geography.IN,
        confidence=0.40,
        is_sample=True,
    )
    temp_db.save_evidence(ev_prod)
    temp_db.save_evidence(ev_demo)

    prod_only = temp_db.list_evidence(is_sample=False)
    assert len(prod_only) == 1
    assert prod_only[0].id == "ev_prod_01"

    demo_only = temp_db.list_evidence(is_sample=True)
    assert len(demo_only) == 1
    assert demo_only[0].id == "ev_demo_01"

    # Test offers
    off_prod = OfferCandidate(
        id="off_prod_01",
        title="Production Offer Candidate",
        target_geography=Geography.IN,
        buyer_profile="Real Buyers",
        problem_statement="Real Problem Statement",
        proposed_deliverable="Real Deliverable",
        plausible_pricing_or_pilot="Pilot Terms",
        delivery_method="Remote delivery",
        is_sample=False,
    )
    off_demo = OfferCandidate(
        id="off_demo_01",
        title="Sample Demo Offer Candidate",
        target_geography=Geography.IN,
        buyer_profile="Demo Buyers",
        problem_statement="Demo Problem Statement",
        proposed_deliverable="Demo Deliverable",
        plausible_pricing_or_pilot="Demo Terms",
        delivery_method="Remote delivery",
        is_sample=True,
    )
    temp_db.save_offer(off_prod)
    temp_db.save_offer(off_demo)

    prod_offers = temp_db.list_offers(is_sample=False)
    assert len(prod_offers) == 1
    assert prod_offers[0].id == "off_prod_01"

    demo_offers = temp_db.list_offers(is_sample=True)
    assert len(demo_offers) == 1
    assert demo_offers[0].id == "off_demo_01"

