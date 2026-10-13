"""
Seed script demonstrating Stage A market research and offer evaluation.
Uses CLEARLY LABELED SAMPLE DATA to illustrate how Stage A operates.
All records are explicitly flagged with is_sample=True so they are NEVER
conflated with real-world market research.
"""

from zero.database import Database
from zero.research.evaluator import OfferEvaluator
from zero.research.evidence import EvidenceService
from zero.schemas import (
    CriterionKey,
    CriterionScore,
    EvidenceType,
    Geography,
    OfferCandidate,
    Run,
    RunState,
)


def seed_demo_data():
    db = Database()
    service = EvidenceService(db)
    evaluator = OfferEvaluator()

    # Create run explicitly flagged as sample demonstration
    run = Run(
        run_id="run_stage_a_demo_01",
        current_stage=RunState.OFFER_DECISION,
        status="STAGE_A_SAMPLE_EVALUATION",
        is_sample=True,
    )
    db.create_run(run)

    # 1. Indian Market Evidence (Verified and User-Provided)
    ev_in_1 = service.record_evidence(
        evidence_id="ev_demo_in_01",
        claim="[SAMPLE] Indian D2C brands experience 20-30% Return-to-Origin (RTO) loss on Cash-on-Delivery shipments.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.88,
        source_url="https://example.com/reports/india-d2c-logistics-2026",
        notes="Industry report across 150 fashion and electronics D2C brands",
        is_sample=True,
    )
    ev_in_2 = service.record_evidence(
        evidence_id="ev_demo_in_02",
        claim="[SAMPLE] Indian D2C brands actively spend INR 10k-30k/month on WhatsApp verification and Shopify plugins.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.82,
        source_url="https://example.com/reports/saas-spend-india",
        notes="SaaS tool marketplace pricing benchmarks",
        is_sample=True,
    )
    ev_in_3 = service.record_evidence(
        evidence_id="ev_demo_in_03",
        claim="[SAMPLE] Founder contacts and operations leads are accessible via public website listings and business registries.",
        evidence_type=EvidenceType.USER_PROVIDED,
        geography=Geography.IN,
        confidence=0.75,
        notes="Manual verification across 20 brand websites",
        is_sample=True,
    )

    # 2. US Market Evidence
    ev_us_1 = service.record_evidence(
        evidence_id="ev_demo_us_01",
        claim="[SAMPLE] US specialty subcontractors face 30-day payment delays due to manual AIA G702 billing preparation.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.US,
        confidence=0.85,
        source_url="https://example.com/reports/us-construction-cashflow",
        notes="Survey of 80 HVAC and electrical trade subcontractors",
        is_sample=True,
    )
    ev_us_2 = service.record_evidence(
        evidence_id="ev_demo_us_02",
        claim="[SAMPLE] US trade contractors pay $200-$600/month for specialized construction accounting tools.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.US,
        confidence=0.80,
        source_url="https://example.com/reports/construction-tech-pricing",
        notes="Subscription pricing data from Procore/Foundation",
        is_sample=True,
    )
    ev_us_3 = service.record_evidence(
        evidence_id="ev_demo_us_03",
        claim="[SAMPLE] Commercial subcontractor office managers are reachable via public state contractor licensing boards.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.US,
        confidence=0.85,
        source_url="https://example.com/cslb-public-registry",
        notes="Public contractor state licensing registry records",
        is_sample=True,
    )

    # 3. Weak / Speculative Evidence (to illustrate NEEDS_MORE_EVIDENCE)
    ev_weak_1 = service.record_evidence(
        evidence_id="ev_demo_us_spec_01",
        claim="[SAMPLE HYPOTHESIS] Dental clinics might pay for AI voice receptionists without verification.",
        evidence_type=EvidenceType.HYPOTHESIS,
        geography=Geography.US,
        confidence=0.35,
        notes="Unverified founder hypothesis with no market survey or pricing evidence",
        is_sample=True,
    )

    # Offer Candidate 1 (India): WhatsApp COD Verification
    offer_in = OfferCandidate(
        id="off_in_001",
        title="[SAMPLE] WhatsApp COD Order Verification & Address Check",
        target_geography=Geography.IN,
        buyer_profile="Founders & Ops Heads at Indian D2C E-commerce Brands (INR 50L - 5Cr GMV)",
        problem_statement="High Cash-on-Delivery RTO rates cause dead shipping costs and locked inventory.",
        proposed_deliverable="Automated WhatsApp webhook workflow verifying buyer address and confirming order intent.",
        plausible_pricing_or_pilot="Free 7-day pilot (first 100 orders verified free), then INR 12,000/month.",
        delivery_method="100% remote configuration using free tier webhooks and open-source python scripts at INR 0 cost.",
        risks=["WhatsApp Business API template message approval timelines"],
        evidence_ids=[ev_in_1.id, ev_in_2.id, ev_in_3.id],
        is_sample=True,
    )
    scores_in = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY, score=5, weight=0.25,
            rationale="RTO directly burns 15-20% gross margins daily.", evidence_ids=[ev_in_1.id]
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY, score=4, weight=0.25,
            rationale="Proven spend on existing paid plugins and OTP verification services.", evidence_ids=[ev_in_2.id]
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY, score=4, weight=0.20,
            rationale="Founders easily contacted via legitimate public business email routes.", evidence_ids=[ev_in_3.id]
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY, score=4, weight=0.20,
            rationale="Remote script setup with zero cash outlay.", evidence_ids=[ev_in_1.id]
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY, score=4, weight=0.10,
            rationale="7-day free pilot is easy to approve in under 48 hours.", evidence_ids=[ev_in_2.id]
        ),
    }
    offer_in.evaluation = evaluator.evaluate(offer_in, scores_in, [ev_in_1, ev_in_2, ev_in_3])
    db.save_offer(offer_in)

    # Offer Candidate 2 (US): AIA Billing Automation
    offer_us = OfferCandidate(
        id="off_us_001",
        title="[SAMPLE] AIA Progress Billing Automation for US Trade Subcontractors",
        target_geography=Geography.US,
        buyer_profile="Office Managers and Owners at US Commercial HVAC & Electrical Subcontractors",
        problem_statement="Complex AIA G702/G703 progress billing sheets cause delayed general contractor payments.",
        proposed_deliverable="Automated Excel template generator converting job cost reports into AIA-compliant sheets.",
        plausible_pricing_or_pilot="Free pilot for 1 billing cycle (up to 3 pay applications), then $249/month.",
        delivery_method="100% remote delivery using open-source Python spreadsheet automation at INR 0 cost.",
        risks=["Differing GC-specific supplemental lien waiver formats"],
        evidence_ids=[ev_us_1.id, ev_us_2.id, ev_us_3.id],
        is_sample=True,
    )
    scores_us = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY, score=4, weight=0.25,
            rationale="Delayed billing delays thousands of dollars in subcontractor cash flow.", evidence_ids=[ev_us_1.id]
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY, score=4, weight=0.25,
            rationale="Trade contractors already pay hundreds per month for accounting tools.", evidence_ids=[ev_us_2.id]
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY, score=4, weight=0.20,
            rationale="Public state licensing boards provide verified business contact info.", evidence_ids=[ev_us_3.id]
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY, score=5, weight=0.20,
            rationale="Python openpyxl automation runs 100% remotely at zero software cost.", evidence_ids=[ev_us_1.id]
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY, score=3, weight=0.10,
            rationale="Tied to monthly billing cycle, but pilot commitment is fast.", evidence_ids=[ev_us_2.id]
        ),
    }
    offer_us.evaluation = evaluator.evaluate(offer_us, scores_us, [ev_us_1, ev_us_2, ev_us_3])
    db.save_offer(offer_us)

    # Offer Candidate 3 (Speculative): AI Voice Receptionist
    offer_spec = OfferCandidate(
        id="off_us_spec",
        title="[SAMPLE] AI Voice Receptionist for US Dental Clinics",
        target_geography=Geography.US,
        buyer_profile="Dental Practice Managers",
        problem_statement="Missed patient calls after hours lead to lost appointments.",
        proposed_deliverable="Custom AI voice bot answering calls after 5 PM.",
        plausible_pricing_or_pilot="Free trial then $399/month.",
        delivery_method="Requires third-party telephony APIs (Twilio, paid AI voice providers).",
        risks=["Telephony API costs violate INR 0 budget; HIPAA compliance issues."],
        evidence_ids=[ev_weak_1.id],
        is_sample=True,
    )
    scores_spec = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY, score=4, weight=0.25,
            rationale="Missed calls hurt clinic revenue.", evidence_ids=[ev_weak_1.id]
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY, score=4, weight=0.25,
            rationale="Unverified hypothesis of willingness to pay.", evidence_ids=[ev_weak_1.id]
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY, score=3, weight=0.20,
            rationale="Clinics have public websites.", evidence_ids=[ev_weak_1.id]
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY, score=2, weight=0.20,
            rationale="Violates INR 0 budget due to telephony and paid voice model costs.", evidence_ids=[ev_weak_1.id]
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY, score=2, weight=0.10,
            rationale="High friction due to medical compliance questions.", evidence_ids=[ev_weak_1.id]
        ),
    }
    offer_spec.evaluation = evaluator.evaluate(offer_spec, scores_spec, [ev_weak_1])
    db.save_offer(offer_spec)

    print("Demo sample data seeded successfully with is_sample=True isolation.")


if __name__ == "__main__":
    seed_demo_data()
