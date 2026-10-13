"""Unit tests for Pydantic data schemas in Project ZERO."""

import pytest
from pydantic import ValidationError
from zero.schemas import (
    CRITERION_WEIGHTS,
    AuditEvent,
    CriterionKey,
    CriterionScore,
    DecisionStatus,
    Evidence,
    EvidenceType,
    Geography,
    OfferCandidate,
    Run,
    RunState,
)


def test_valid_verified_evidence():
    """Verified evidence with valid URL and confidence passes validation."""
    ev = Evidence(
        id="ev_001",
        claim="82% of mid-sized Indian logistics companies face billing reconciliation delays.",
        evidence_type=EvidenceType.VERIFIED_SOURCE,
        geography=Geography.IN,
        confidence=0.85,
        source_url="https://example.com/logistics-report-2026",
        notes="Survey of 120 logistics operators",
    )
    assert ev.id == "ev_001"
    assert ev.evidence_type == EvidenceType.VERIFIED_SOURCE
    assert ev.geography == Geography.IN
    assert ev.confidence == 0.85
    assert ev.source_url == "https://example.com/logistics-report-2026"


def test_verified_evidence_missing_url_fails():
    """Verified evidence without source_url must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Evidence(
            id="ev_002",
            claim="US dental clinics spend 15 hours weekly on insurance pre-authorization.",
            evidence_type=EvidenceType.VERIFIED_SOURCE,
            geography=Geography.US,
            confidence=0.90,
            source_url=None,  # Missing!
        )
    assert "VERIFIED_SOURCE evidence must have a valid http/https source_url" in str(exc_info.value)


def test_verified_evidence_invalid_url_fails():
    """Verified evidence with non-http URL must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Evidence(
            id="ev_003",
            claim="US dental clinics spend 15 hours weekly on insurance pre-authorization.",
            evidence_type=EvidenceType.VERIFIED_SOURCE,
            geography=Geography.US,
            confidence=0.90,
            source_url="ftp://invalid.url/doc",
        )
    assert "VERIFIED_SOURCE evidence must have a valid http/https source_url" in str(exc_info.value)


def test_user_provided_evidence_without_url_succeeds():
    """User-provided evidence does not require a source_url."""
    ev = Evidence(
        id="ev_004",
        claim="Operator personal experience with local accounting workflow bottlenecks.",
        evidence_type=EvidenceType.USER_PROVIDED,
        geography=Geography.IN,
        confidence=0.70,
        notes="Direct interview with an accountant friend",
    )
    assert ev.evidence_type == EvidenceType.USER_PROVIDED
    assert ev.source_url is None


def test_evidence_confidence_bounds():
    """Confidence must be between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        Evidence(
            id="ev_005",
            claim="Sample claim about market demand",
            evidence_type=EvidenceType.HYPOTHESIS,
            geography=Geography.US,
            confidence=1.2,  # > 1.0
        )

    with pytest.raises(ValidationError):
        Evidence(
            id="ev_006",
            claim="Sample claim about market demand",
            evidence_type=EvidenceType.HYPOTHESIS,
            geography=Geography.US,
            confidence=-0.1,  # < 0.0
        )


def test_criterion_score_valid_weights():
    """CriterionScore validates that weights match PRD Section 6 specification."""
    cs = CriterionScore(
        criterion=CriterionKey.PROBLEM_SEVERITY,
        score=4,
        weight=0.25,
        rationale="Severe daily friction causing financial losses.",
        evidence_ids=["ev_001"],
    )
    assert cs.score == 4
    assert cs.weight == 0.25

    # Incorrect weight must fail
    with pytest.raises(ValidationError) as exc_info:
        CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY,
            score=4,
            weight=0.50,  # Wrong weight!
            rationale="Severe daily friction",
        )
    assert "Weight for problem_severity must be 0.25" in str(exc_info.value)


def test_criterion_score_range():
    """CriterionScore score must be integer between 1 and 5."""
    with pytest.raises(ValidationError):
        CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY,
            score=0,  # < 1
            weight=0.20,
            rationale="Too low",
        )

    with pytest.raises(ValidationError):
        CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY,
            score=6,  # > 5
            weight=0.20,
            rationale="Too high",
        )


def test_offer_candidate_schema():
    """Offer candidate validates all required fields."""
    offer = OfferCandidate(
        id="off_001",
        title="Automated Logistics Invoice Reconciliation Pilot",
        target_geography=Geography.IN,
        buyer_profile="Finance Controllers at Mid-sized Freight Forwarders",
        problem_statement="Manual entry of transporter bills creates 4-week reconciliation lag.",
        proposed_deliverable="A Python-based reconciliation script processing 100 sample bills.",
        plausible_pricing_or_pilot="Free 2-week pilot with explicit success threshold of 95% match.",
        delivery_method="Remote delivery via CSV/Excel processing using open-source Python tools.",
        risks=["Data format variance across vendors"],
        evidence_ids=["ev_001"],
    )
    assert offer.id == "off_001"
    assert offer.target_geography == Geography.IN
    assert offer.evaluation is None
