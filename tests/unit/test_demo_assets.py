"""Tests for truthful demonstration proof assets in Stage B."""

import pytest
from zero.database import Database
from zero.demos.generator import DemoAssetGenerator, MANDATORY_DISCLAIMER
from zero.schemas import Geography, OfferCandidate, ProofAsset


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_demos.db"
    return Database(db_file)


def test_demo_asset_creation_and_disclaimer(temp_db, tmp_path):
    demos_dir = tmp_path / "demos"
    generator = DemoAssetGenerator(temp_db, output_dir=demos_dir)

    offer = OfferCandidate(
        id="off_test_demo",
        title="B2B Outbound Deliverability Audit",
        target_geography=Geography.IN,
        buyer_profile="Mid-Market B2B Tech Founders",
        problem_statement="Outbound emails landing in spam folders",
        proposed_deliverable="SPF/DKIM/DMARC Technical Audit Report",
        plausible_pricing_or_pilot="INR 0 Pilot Verification",
        delivery_method="Remote markdown delivery",
        risks=["DNS access delay"],
        is_sample=True,
    )

    asset = generator.generate_proof_asset(offer, asset_type="AUDIT_CHECKLIST")

    assert asset.offer_id == offer.id
    assert "PROJECT ZERO DEMONSTRATION ASSET" in asset.disclaimer
    assert "No testimonials, measured customer metrics, or client endorsements have been fabricated" in asset.disclaimer

    # Verify no fabricated testimonials or fake client claims in content
    forbidden_terms = ["client testimonial", "our customer john doe", "grew revenue by 300%", "case study: acme achieved"]
    content_lower = asset.content.lower()
    for term in forbidden_terms:
        assert term not in content_lower

    # Verify persisted in database
    retrieved = temp_db.get_proof_asset(asset.id)
    assert retrieved is not None
    assert retrieved.id == asset.id

    # Verify exported to file
    exported_file = demos_dir / f"{asset.id}.md"
    assert exported_file.exists()
    assert exported_file.read_text(encoding="utf-8") == asset.content


def test_demo_asset_schema_requires_disclaimer():
    # Attempting to create a ProofAsset without the mandatory disclaimer phrase
    with pytest.raises(ValueError, match="Proof asset disclaimer must contain 'PROJECT ZERO DEMONSTRATION ASSET'"):
        ProofAsset(
            id="asset_invalid",
            offer_id="off_test",
            title="Invalid Proof Asset",
            asset_type="AUDIT_CHECKLIST",
            content="Valid content length more than twenty characters here.",
            disclaimer="Past work from previous clients with 99% satisfaction rate.",
        )
