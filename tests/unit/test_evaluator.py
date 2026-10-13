"""Unit tests for offer evaluation engine and scoring rubric."""

import pytest
from zero.research.evaluator import OfferEvaluator
from zero.schemas import (
    CriterionKey,
    CriterionScore,
    DecisionStatus,
    Evidence,
    EvidenceType,
    Geography,
    OfferCandidate,
)


@pytest.fixture
def sample_india_offer_and_evidence():
    ev1 = Evidence(
        id="ev_in_01",
        claim="Indian D2C brands spend 30+ hours weekly dealing with RTO (Return to Origin) verification.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.88,
        source_url="https://example.com/india-d2c-rto-report",
        notes="Published industry study",
    )
    ev2 = Evidence(
        id="ev_in_02",
        claim="Shopify store owners in Bangalore actively pay for WhatsApp address-confirmation plugins.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.80,
        source_url="https://example.com/d2c-tech-spend",
        notes="Survey showing $50-$200/mo spend",
    )
    ev3 = Evidence(
        id="ev_in_03",
        claim="D2C founders are reachable via direct company emails and public WhatsApp support numbers.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.75,
        source_url="https://example.com/contact-accessibility",
    )

    offer = OfferCandidate(
        id="off_in_01",
        title="Automated WhatsApp COD Confirmation Bot for Indian D2C Brands",
        target_geography=Geography.IN,
        buyer_profile="D2C Founders and E-commerce Operations Heads in India",
        problem_statement="High Return to Origin (RTO) rate on cash-on-delivery orders erodes 15-20% margin.",
        proposed_deliverable="Setup of automated webhook-based WhatsApp order verification flow.",
        plausible_pricing_or_pilot="Free 7-day pilot with max 200 orders, followed by ₹15,000/month flat.",
        delivery_method="Remote API integration via free tier/open-source tools at ₹0 initial cost.",
        risks=["Meta WhatsApp API message template approval delays"],
        evidence_ids=["ev_in_01", "ev_in_02", "ev_in_03"],
    )

    scores = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY,
            score=5,
            weight=0.25,
            rationale="RTO eats 20% margin, extremely painful daily problem.",
            evidence_ids=["ev_in_01"],
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY,
            score=4,
            weight=0.25,
            rationale="Proven spend on existing paid plugins and OTP services.",
            evidence_ids=["ev_in_02"],
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY,
            score=4,
            weight=0.20,
            rationale="Accessible via direct company email and business channels.",
            evidence_ids=["ev_in_03"],
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY,
            score=4,
            weight=0.20,
            rationale="Delivered 100% remotely using webhook scripts at zero capital expenditure.",
            evidence_ids=["ev_in_01"],
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY,
            score=4,
            weight=0.10,
            rationale="Founders can approve a quick 7-day trial in under 48 hours.",
            evidence_ids=["ev_in_02"],
        ),
    }

    return offer, [ev1, ev2, ev3], scores


@pytest.fixture
def sample_us_offer_and_evidence():
    ev1 = Evidence(
        id="ev_us_01",
        claim="US specialty subcontractors spend 10+ hours preparing AIA G702 billing applications.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.US,
        confidence=0.85,
        source_url="https://example.com/us-construction-billing",
    )
    ev2 = Evidence(
        id="ev_us_02",
        claim="Subcontractors pay $300-$1000/mo for construction accounting software add-ons.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.US,
        confidence=0.82,
        source_url="https://example.com/software-spend-contractors",
    )
    ev3 = Evidence(
        id="ev_us_03",
        claim="Public license registries and business websites provide direct office contact emails.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.US,
        confidence=0.80,
        source_url="https://example.com/contractor-licensing-registry",
    )

    offer = OfferCandidate(
        id="off_us_01",
        title="AIA Billing Sheet Generation Automation for US Trade Contractors",
        target_geography=Geography.US,
        buyer_profile="Office Managers and Owners at US HVAC and Electrical Subcontractors",
        problem_statement="Complex AIA progress billing documents cause delayed payments and dispute risks.",
        proposed_deliverable="Automated Excel/PDF generation tool mapping job costs to AIA G702/G703 format.",
        plausible_pricing_or_pilot="Free pilot for 1 billing cycle (up to 3 pay applications), then $299/mo.",
        delivery_method="Remote delivery via Python script and open-source spreadsheets at ₹0 cost.",
        risks=["Variations in general contractor payment application requirements"],
        evidence_ids=["ev_us_01", "ev_us_02", "ev_us_03"],
    )

    scores = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY,
            score=4,
            weight=0.25,
            rationale="Progress billing delays directly impact contractor cash flow.",
            evidence_ids=["ev_us_01"],
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY,
            score=4,
            weight=0.25,
            rationale="High existing software spend in construction vertical.",
            evidence_ids=["ev_us_02"],
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY,
            score=4,
            weight=0.20,
            rationale="Legitimate public trade registers and business emails available.",
            evidence_ids=["ev_us_03"],
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY,
            score=5,
            weight=0.20,
            rationale="Standard Python Excel libraries deliver this remotely at ₹0 cost.",
            evidence_ids=["ev_us_01"],
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY,
            score=3,
            weight=0.10,
            rationale="Decision makers are busy but pilot can be tested in 1 billing cycle.",
            evidence_ids=["ev_us_02"],
        ),
    }

    return offer, [ev1, ev2, ev3], scores


def test_exact_weighted_scoring_calculation(sample_india_offer_and_evidence):
    """
    Test exact weighted scoring calculation:
    Problem Severity (5 * 0.25 = 1.25)
    Willingness to Pay (4 * 0.25 = 1.00)
    Buyer Accessibility (4 * 0.20 = 0.80)
    Delivery Feasibility (4 * 0.20 = 0.80)
    Sales Cycle Feasibility (4 * 0.10 = 0.40)
    Expected Total = 1.25 + 1.00 + 0.80 + 0.80 + 0.40 = 4.25
    """
    offer, evidence, scores = sample_india_offer_and_evidence
    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.weighted_score == 4.25
    assert result.status == DecisionStatus.SELECTED
    assert result.average_confidence >= 0.65
    assert not result.missing_evidence_criteria
    assert not result.contradictions_found


def test_us_opportunity_evaluation(sample_us_offer_and_evidence):
    """
    Test US opportunity evaluation:
    Problem Severity (4 * 0.25 = 1.00)
    Willingness to Pay (4 * 0.25 = 1.00)
    Buyer Accessibility (4 * 0.20 = 0.80)
    Delivery Feasibility (5 * 0.20 = 1.00)
    Sales Cycle Feasibility (3 * 0.10 = 0.30)
    Expected Total = 1.00 + 1.00 + 0.80 + 1.00 + 0.30 = 4.10
    """
    offer, evidence, scores = sample_us_offer_and_evidence
    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.weighted_score == 4.10
    assert result.status == DecisionStatus.SELECTED
    assert result.average_confidence >= 0.65


def test_deterministic_evaluation(sample_india_offer_and_evidence):
    """Running evaluation 100 times yields identical scores and statuses."""
    offer, evidence, scores = sample_india_offer_and_evidence
    evaluator = OfferEvaluator()

    first_result = evaluator.evaluate(offer, scores, evidence)
    for _ in range(100):
        res = evaluator.evaluate(offer, scores, evidence)
        assert res.weighted_score == first_result.weighted_score
        assert res.status == first_result.status
        assert res.average_confidence == first_result.average_confidence


def test_needs_more_evidence_on_missing_critical_evidence(sample_india_offer_and_evidence):
    """
    High numeric scores must NOT override missing critical evidence!
    If problem severity has no evidence, status MUST be NEEDS_MORE_EVIDENCE.
    """
    offer, evidence, scores = sample_india_offer_and_evidence
    # Remove evidence link for problem_severity
    scores[CriterionKey.PROBLEM_SEVERITY].evidence_ids = []

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert any("problem_severity" in m for m in result.missing_evidence_criteria)


def test_needs_more_evidence_on_low_confidence(sample_india_offer_and_evidence):
    """Evidence with confidence below threshold triggers NEEDS_MORE_EVIDENCE."""
    offer, evidence, scores = sample_india_offer_and_evidence
    # Modify evidence to have speculative confidence 0.30
    for ev in evidence:
        ev.confidence = 0.30

    evaluator = OfferEvaluator(confidence_threshold=0.65)
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert any("below heuristic threshold" in r or "below threshold" in r for r in result.reasons)


def test_needs_more_evidence_on_unresolved_contradictions(sample_india_offer_and_evidence):
    """
    Conflicting or disputed evidence must trigger NEEDS_MORE_EVIDENCE
    even if the numeric score is 5.0 across all criteria.
    """
    offer, evidence, scores = sample_india_offer_and_evidence
    # Add a conflicting evidence item
    conflict_ev = Evidence(
        id="ev_in_conflict",
        claim="Disputed: Survey says 65% of D2C brands have already automated RTO and don't need third-party tools.",
        evidence_type=EvidenceType.CONFLICTING_OR_INSUFFICIENT,
        geography=Geography.IN,
        confidence=0.70,
        notes="Competitor market research contradiction",
    )
    evidence.append(conflict_ev)
    scores[CriterionKey.PROBLEM_SEVERITY].evidence_ids.append("ev_in_conflict")

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert len(result.contradictions_found) > 0
    assert any("Contradiction" in c for c in result.contradictions_found)


def test_rejected_on_low_delivery_feasibility(sample_india_offer_and_evidence):
    """Delivery feasibility score <= 2 triggers REJECTED."""
    offer, evidence, scores = sample_india_offer_and_evidence
    scores[CriterionKey.DELIVERY_FEASIBILITY].score = 2
    scores[CriterionKey.DELIVERY_FEASIBILITY].rationale = "Requires in-person hardware installation which violates remote ₹0 rules."

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.REJECTED
    assert any("Delivery feasibility score is too low" in r for r in result.reasons)


def test_rejected_on_low_weighted_score(sample_india_offer_and_evidence):
    """Weighted score below minimum threshold triggers REJECTED."""
    offer, evidence, scores = sample_india_offer_and_evidence
    for k in scores:
        scores[k].score = 2

    evaluator = OfferEvaluator(min_score=3.5)
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.weighted_score == 2.0
    assert result.status == DecisionStatus.REJECTED
    assert any("below qualification minimum" in r for r in result.reasons)


def test_invalid_evidence_id_triggers_needs_more_evidence(sample_india_offer_and_evidence):
    """Referencing an evidence ID that does not exist in repository triggers NEEDS_MORE_EVIDENCE."""
    offer, evidence, scores = sample_india_offer_and_evidence
    scores[CriterionKey.PROBLEM_SEVERITY].evidence_ids.append("ev_ghost_9999")

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert any("ev_ghost_9999" in m for m in result.missing_or_invalid_evidence_ids)


def test_hypothesis_only_critical_criteria_triggers_needs_more_evidence(sample_india_offer_and_evidence):
    """Critical criterion (Problem Severity) backed solely by a HYPOTHESIS triggers NEEDS_MORE_EVIDENCE."""
    offer, evidence, scores = sample_india_offer_and_evidence
    hyp_ev = Evidence(
        id="ev_hyp_crit",
        claim="Speculative claim that pain is severe",
        evidence_type=EvidenceType.HYPOTHESIS,
        geography=Geography.IN,
        confidence=0.45,
    )
    evidence.append(hyp_ev)
    scores[CriterionKey.PROBLEM_SEVERITY].evidence_ids = ["ev_hyp_crit"]

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert any("relies solely on unverified hypotheses" in m for m in result.missing_evidence_criteria)


def test_sample_offer_has_sample_flag_and_disclaimer(sample_india_offer_and_evidence):
    """Demonstration offer with is_sample=True has is_sample=True in result and prominent disclaimer."""
    offer, evidence, scores = sample_india_offer_and_evidence
    offer.is_sample = True

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.is_sample is True
    assert result.status == DecisionStatus.SELECTED
    assert any("[DEMONSTRATION SAMPLE ONLY]" in r for r in result.reasons)


def test_production_offer_cannot_use_sample_evidence(sample_india_offer_and_evidence):
    """A production offer (is_sample=False) cannot use sample evidence (is_sample=True) to qualify."""
    offer, evidence, scores = sample_india_offer_and_evidence
    offer.is_sample = False  # Production offer
    evidence[0].is_sample = True  # Sample evidence

    evaluator = OfferEvaluator()
    result = evaluator.evaluate(offer, scores, evidence)

    assert result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert any("Production offer cannot use sample/demonstration evidence" in m for m in result.missing_or_invalid_evidence_ids)


