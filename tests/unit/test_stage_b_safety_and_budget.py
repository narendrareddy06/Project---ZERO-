"""Tests for Stage B budget, safety guardrails, and cryptographic audit integrity."""

import pytest
from zero.config import TARGET_BUDGET_INR
from zero.database import Database
from zero.demos.generator import DemoAssetGenerator
from zero.prospects.discovery import ProspectDiscoveryEngine
from zero.prospects.qualification import ProspectQualificationEngine
from zero.schemas import (
    Geography,
    OfferCandidate,
    ProspectStatus,
    Run,
    RunState,
    SuppressionRecord,
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage_b_safety.db"
    return Database(db_file)


def test_zero_budget_strictly_maintained_in_stage_b(temp_db):
    """Verify that operating budget target and run expenditure remain at INR 0.00."""
    assert TARGET_BUDGET_INR == 0.0

    run = Run(run_id="run_stage_b_test", current_stage=RunState.RESEARCH)
    temp_db.create_run(run)

    # Perform Stage B operations: discovery, suppression, demo generation
    discovery = ProspectDiscoveryEngine(temp_db)
    discovery.create_prospect(
        company_name="Budget Test Corp",
        website_or_domain="budgettest.in",
        geography=Geography.IN,
        industry_or_niche="IT Services",
        public_source_url="https://directory.in/budget",
        verified_facts={"identified_services": ["it services"]},
    )

    temp_db.add_suppression(
        SuppressionRecord(domain_or_email="suppressed.in", reason="OPT_OUT")
    )

    offer = OfferCandidate(
        id="off_budget_test",
        title="Zero Cost Deliverable Audit",
        target_geography=Geography.IN,
        buyer_profile="IT Services",
        problem_statement="Budget tracking",
        proposed_deliverable="Audit Report",
        plausible_pricing_or_pilot="INR 0 Pilot",
        delivery_method="Remote async markdown",
        risks=[],
    )
    generator = DemoAssetGenerator(temp_db)
    generator.generate_proof_asset(offer)

    # Check run record
    retrieved_run = temp_db.get_run("run_stage_b_test")
    assert retrieved_run is not None
    assert retrieved_run.budget_spent_inr == 0.0


def test_audit_chain_integrity_with_all_stage_b_events(temp_db):
    """Verify that all Stage B operations generate valid, tamper-evident hash-chained audit events."""
    # 1. Create run
    run = Run(run_id="run_audit_stage_b", current_stage=RunState.PROSPECTING)
    temp_db.create_run(run)

    # 2. Add suppression
    temp_db.add_suppression(
        SuppressionRecord(domain_or_email="optout-test.in", reason="DO_NOT_CONTACT")
    )

    # 3. Discover prospect
    discovery = ProspectDiscoveryEngine(temp_db)
    prospect, _, _ = discovery.create_prospect(
        company_name="Audit Chain Tech",
        website_or_domain="auditchain.in",
        geography=Geography.IN,
        industry_or_niche="Software Engineering",
        public_source_url="https://directory.in/audit",
        verified_facts={"identified_services": ["software engineering"]},
    )

    # 4. Qualify prospect
    offer = OfferCandidate(
        id="off_audit_test",
        title="Audit Test Offer",
        target_geography=Geography.IN,
        buyer_profile="Software Engineering Companies",
        problem_statement="Engineering pipeline bottlenecks",
        proposed_deliverable="Engineering Audit",
        plausible_pricing_or_pilot="INR 0 Pilot",
        delivery_method="Remote",
        risks=[],
        is_sample=False,
    )
    temp_db.save_offer(offer)

    qualifier = ProspectQualificationEngine(temp_db)
    qualifier.qualify_prospect(prospect, offer)

    # 5. Create demonstration proof asset
    demo_gen = DemoAssetGenerator(temp_db)
    demo_gen.generate_proof_asset(offer)

    # 6. Verify cryptographic hash chain across the entire sequence
    is_valid, msg, failure_seq = temp_db.audit.verify_chain_integrity()
    assert is_valid is True, f"Audit chain broken at seq {failure_seq}: {msg}"
    assert "integrity verified" in msg.lower()


def test_inaccessible_urls_cannot_qualify_production_offer(temp_db):
    """Confirm that an offer relying on failed/inaccessible evidence cannot be qualified."""
    from zero.research.evaluator import OfferEvaluator
    from zero.schemas import CriterionKey, CriterionScore, DecisionStatus, Evidence, EvidenceType

    evaluator = OfferEvaluator()

    # Evidence from failed retrieval (status CONFLICTING_OR_INSUFFICIENT)
    failed_ev = Evidence(
        id="ev_failed_http",
        claim="Companies suffer 40% pipeline drops",
        evidence_type=EvidenceType.CONFLICTING_OR_INSUFFICIENT,
        geography=Geography.IN,
        confidence=0.10,
        source_url="https://example.com/broken-page",
        notes="HTTP 500 error",
        is_sample=False,
    )

    offer = OfferCandidate(
        id="off_failed_ev_test",
        title="Production Offer With Inaccessible Evidence",
        target_geography=Geography.IN,
        buyer_profile="Tech Startups",
        problem_statement="Pipeline drop problem",
        proposed_deliverable="Pipeline Audit",
        plausible_pricing_or_pilot="INR 0 Pilot",
        delivery_method="Remote",
        risks=[],
        evidence_ids=["ev_failed_http"],
        is_sample=False,
    )

    criterion_scores = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY, score=4, weight=0.25, rationale="Assumed high", evidence_ids=["ev_failed_http"]
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY, score=4, weight=0.25, rationale="Assumed high", evidence_ids=["ev_failed_http"]
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY, score=4, weight=0.20, rationale="Online buyers", evidence_ids=["ev_failed_http"]
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY, score=4, weight=0.20, rationale="Remote feasible", evidence_ids=["ev_failed_http"]
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY, score=4, weight=0.10, rationale="Fast cycle", evidence_ids=["ev_failed_http"]
        ),
    }

    result = evaluator.evaluate(offer, criterion_scores, [failed_ev])
    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert any("contradictory or disputed evidence" in r.lower() or "missing or insufficient" in r.lower() for r in result.reasons)
