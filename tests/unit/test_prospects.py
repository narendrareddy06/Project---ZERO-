"""Tests for prospect discovery, deduplication, suppression, and qualification in Stage B."""

import pytest
from zero.database import Database
from zero.prospects.discovery import ProspectDiscoveryEngine
from zero.prospects.qualification import ProspectQualificationEngine
from zero.schemas import (
    Geography,
    OfferCandidate,
    Prospect,
    ProspectStatus,
    SuppressionRecord,
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_prospects.db"
    return Database(db_file)


def test_prospect_linkedin_rejection(temp_db):
    engine = ProspectDiscoveryEngine(temp_db)
    # Rejection by domain
    with pytest.raises(ValueError, match="LinkedIn discovery, scraping, and automation are strictly prohibited"):
        engine.create_prospect(
            company_name="Acme Corp",
            website_or_domain="https://www.linkedin.com/company/acme",
            geography=Geography.IN,
            industry_or_niche="IT Consulting",
            public_source_url="https://example.com/directory",
            verified_facts={},
        )

    # Rejection by public source URL
    with pytest.raises(ValueError, match="LinkedIn discovery, scraping, and automation are strictly prohibited"):
        engine.create_prospect(
            company_name="Acme Corp",
            website_or_domain="acmecorp.in",
            geography=Geography.IN,
            industry_or_niche="IT Consulting",
            public_source_url="https://www.linkedin.com/in/some-profile",
            verified_facts={},
        )


def test_prospect_deduplication(temp_db):
    engine = ProspectDiscoveryEngine(temp_db)
    prospect1, is_new1, msg1 = engine.create_prospect(
        company_name="Apex Solutions",
        website_or_domain="https://apexsolutions.in/",
        geography=Geography.IN,
        industry_or_niche="Cloud Consulting",
        public_source_url="https://business-directory.in/apex",
        verified_facts={"services": ["cloud", "devops"]},
        is_sample=False,
    )
    assert is_new1 is True
    assert prospect1.domain_or_website == "apexsolutions.in"

    # Second creation with slightly different URL format
    prospect2, is_new2, msg2 = engine.create_prospect(
        company_name="Apex Solutions Private Limited",
        website_or_domain="www.apexsolutions.in",
        geography=Geography.IN,
        industry_or_niche="Cloud Consulting",
        public_source_url="https://another-dir.in/apex",
        verified_facts={"services": ["cloud", "devops"]},
        is_sample=False,
    )
    assert is_new2 is False
    assert prospect2.id == prospect1.id
    assert "already exists" in msg2

    # Database count must be exactly 1
    stored = temp_db.list_prospects()
    assert len(stored) == 1


def test_prospect_suppression_blocks_qualification(temp_db):
    # Add domain to suppression list
    temp_db.add_suppression(
        SuppressionRecord(
            domain_or_email="donotcontact.in",
            reason="OPT_OUT",
            notes="Customer explicitly requested do-not-contact",
        )
    )

    discovery = ProspectDiscoveryEngine(temp_db)
    prospect, is_new, msg = discovery.create_prospect(
        company_name="Blocked Corp",
        website_or_domain="donotcontact.in",
        geography=Geography.IN,
        industry_or_niche="Software Development",
        public_source_url="https://public-registry.in/blocked",
        verified_facts={"identified_services": ["software development"]},
        is_sample=False,
    )

    assert prospect.status == ProspectStatus.SUPPRESSED
    assert "suppressed" in msg.lower()

    # Attempt qualification
    offer = OfferCandidate(
        id="off_test_prod",
        title="B2B Pipeline Pilot",
        target_geography=Geography.IN,
        buyer_profile="Software Development Agencies",
        problem_statement="High customer acquisition costs",
        proposed_deliverable="Cold Outbound Audit",
        plausible_pricing_or_pilot="INR 0 Pilot",
        delivery_method="Remote async delivery",
        risks=[],
        is_sample=False,
    )

    qualifier = ProspectQualificationEngine(temp_db)
    updated_p, is_qual, rationale = qualifier.qualify_prospect(prospect, offer)
    assert is_qual is False
    assert updated_p.status == ProspectStatus.SUPPRESSED
    assert "suppression/opt-out list" in rationale


def test_sample_offer_cannot_qualify_production_prospect(temp_db):
    discovery = ProspectDiscoveryEngine(temp_db)
    prod_prospect, is_new, _ = discovery.create_prospect(
        company_name="Real Growth Tech",
        website_or_domain="realgrowthtech.in",
        geography=Geography.IN,
        industry_or_niche="IT Consulting",
        public_source_url="https://directory.in/realgrowth",
        verified_facts={"identified_services": ["consulting", "software development"]},
        is_sample=False,  # PRODUCTION PROSPECT
    )

    sample_offer = OfferCandidate(
        id="off_demo_sample",
        title="Sample Demonstration Offer",
        target_geography=Geography.IN,
        buyer_profile="IT Consulting Companies",
        problem_statement="Sample problem statement for demonstration",
        proposed_deliverable="Sample Deliverable",
        plausible_pricing_or_pilot="INR 0 Demo",
        delivery_method="Remote delivery",
        risks=[],
        is_sample=True,  # SAMPLE OFFER
    )

    qualifier = ProspectQualificationEngine(temp_db)
    updated_p, is_qual, rationale = qualifier.qualify_prospect(prod_prospect, sample_offer)
    assert is_qual is False
    assert "Evaluation blocked" in rationale
    assert "Sample/demonstration offer" in rationale
    assert "cannot qualify production prospect" in rationale


def test_production_offer_qualifies_matching_prospect(temp_db):
    discovery = ProspectDiscoveryEngine(temp_db)
    prospect, is_new, _ = discovery.create_prospect(
        company_name="Valid Tech India",
        website_or_domain="validtech.in",
        geography=Geography.IN,
        industry_or_niche="B2B Software Development",
        public_source_url="https://directory.in/validtech",
        verified_facts={
            "identified_services": ["software development", "cloud"],
            "public_contact_email": ["contact@validtech.in"],
        },
        assumptions={"estimated_team_size": "20-50"},
        is_sample=False,
    )

    offer = OfferCandidate(
        id="off_prod_real",
        title="B2B Outbound Architecture Audit",
        target_geography=Geography.IN,
        buyer_profile="B2B Software Development and Cloud Agencies",
        problem_statement="High customer acquisition costs and low cold response rates",
        proposed_deliverable="Architecture and Outbound Strategy Audit",
        plausible_pricing_or_pilot="INR 0 Technical Pilot",
        delivery_method="Async markdown report delivered remotely",
        risks=["Buyer delayed review"],
        is_sample=False,
    )

    qualifier = ProspectQualificationEngine(temp_db)
    updated_p, is_qual, rationale = qualifier.qualify_prospect(prospect, offer)
    assert is_qual is True
    assert updated_p.status == ProspectStatus.QUALIFIED
    assert updated_p.fit_score >= 3.5
    assert "Geographic match" in rationale
    assert "Verified industry/service alignment" in rationale
