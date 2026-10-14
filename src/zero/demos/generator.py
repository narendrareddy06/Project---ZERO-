"""
Proof and demonstration asset generator for Project ZERO.

Creates concrete, truthful demonstration assets for potential offers.
Strict safety rules:
- Must clearly identify assets as Project ZERO demonstration prototypes, NOT past client work.
- Never invent testimonials, client quotes, synthetic case studies, or measured customer outcomes.
- Persists assets in database and optionally exports clean markdown to data/demos/.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zero.config import DATA_DIR
from zero.database import Database
from zero.schemas import OfferCandidate, ProofAsset

MANDATORY_DISCLAIMER = (
    "PROJECT ZERO DEMONSTRATION ASSET ONLY. This asset is a technical and methodological "
    "demonstration created exclusively by the Project ZERO autonomous research agent. It does "
    "NOT represent previous client engagements, historical case studies, or commercial track "
    "record. No testimonials, measured customer metrics, or client endorsements have been fabricated."
)


class DemoAssetGenerator:
    """Generates truthful demonstration assets for offer candidates."""

    def __init__(self, db: Database, output_dir: Optional[Path] = None):
        self.db = db
        self.output_dir = output_dir or (DATA_DIR / "demos")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_proof_asset(
        self,
        offer: OfferCandidate,
        asset_type: str = "AUDIT_CHECKLIST",
        title: Optional[str] = None,
        custom_content: Optional[str] = None,
    ) -> ProofAsset:
        """
        Creates a structured demonstration asset for the given offer.
        Persists it in SQLite and saves a local markdown copy.
        """
        now = datetime.now(timezone.utc)
        asset_id = f"asset_{offer.id}_{int(now.timestamp())}"
        asset_title = title or f"Demonstration Proof Asset: {offer.title}"

        if custom_content:
            content = custom_content
        else:
            # Generate a truthful, technical proof asset tailored to the offer's proposed deliverable
            content = (
                f"# Demonstration Asset: {offer.title}\n\n"
                f"> **Notice**: {MANDATORY_DISCLAIMER}\n\n"
                f"## 1. Problem Context\n"
                f"{offer.problem_statement}\n\n"
                f"## 2. Proposed Deliverable Specification\n"
                f"{offer.proposed_deliverable}\n\n"
                f"## 3. Remote Zero-Cost Delivery Framework\n"
                f"- **Delivery Method**: {offer.delivery_method}\n"
                f"- **Proposed Structure**: {offer.plausible_pricing_or_pilot}\n"
                f"- **Target Decision Maker**: {offer.buyer_profile}\n"
                f"- **Target Geography**: {offer.target_geography.value}\n\n"
                f"## 4. Operational Verification Checklist\n"
                f"1. [ ] Public domain verification & DNS configuration review.\n"
                f"2. [ ] Rate-limit compliance audit against target services.\n"
                f"3. [ ] Suppression and opt-out registry cross-check prior to any interaction.\n"
                f"4. [ ] Deterministic verification of factual assertions against public documentation.\n\n"
                f"## 5. Risk Assessment & Mitigations\n"
            )
            for risk in offer.risks:
                content += f"- **Risk**: {risk}\n"

        proof_asset = ProofAsset(
            id=asset_id,
            offer_id=offer.id,
            title=asset_title,
            asset_type=asset_type,
            content=content,
            disclaimer=MANDATORY_DISCLAIMER,
            created_at=now,
            is_sample=True,
        )

        saved = self.db.save_proof_asset(proof_asset, actor="AGENT")

        # Export markdown file to output directory
        file_path = self.output_dir / f"{asset_id}.md"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return saved
