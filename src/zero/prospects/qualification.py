"""
Prospect qualification engine for Project ZERO.

Evaluates fit between a prospective business and a candidate offer.
Enforces safety rules:
- Strictly checks suppression / opt-out status.
- Prevents sample offers from qualifying production prospects.
- Separates verified factual fit from hypotheses.
- Completely read-only: does not send any outbound communications.
"""

from typing import List, Optional, Tuple
from zero.database import Database
from zero.schemas import OfferCandidate, Prospect, ProspectStatus


class ProspectQualificationEngine:
    """Evaluates business prospects against candidate offers using verified facts and rubric criteria."""

    def __init__(self, db: Database):
        self.db = db

    def qualify_prospect(
        self,
        prospect: Prospect,
        offer: OfferCandidate,
        actor: str = "AGENT",
    ) -> Tuple[Prospect, bool, str]:
        """
        Qualifies a prospect against an offer candidate.
        Returns: (Updated Prospect, is_qualified, rationale)
        """
        # Guardrail 1: Suppression check
        if self.db.is_suppressed(prospect.domain_or_website):
            prospect.status = ProspectStatus.SUPPRESSED
            prospect.fit_score = 0.0
            prospect.fit_rationale = "Disqualified: Domain or contact is on the suppression/opt-out list."
            self.db.save_prospect(prospect, actor=actor)
            return prospect, False, prospect.fit_rationale

        # Guardrail 2: Sample offer cannot qualify production prospects
        if offer.is_sample and not prospect.is_sample:
            prospect.fit_score = 0.0
            prospect.fit_rationale = (
                f"Evaluation blocked: Sample/demonstration offer '{offer.id}' cannot qualify production prospect '{prospect.id}'."
            )
            return prospect, False, prospect.fit_rationale

        # Evaluation criteria
        score = 0.0
        rationale_points: List[str] = []

        # 1. Geographic Alignment (Weight: 1.5)
        if prospect.geography == offer.target_geography:
            score += 1.5
            rationale_points.append(f"Geographic match: Both target {offer.target_geography.value} (+1.5)")
        else:
            rationale_points.append(
                f"Geographic mismatch: Prospect is in {prospect.geography.value}, offer targets {offer.target_geography.value} (+0.0)"
            )

        # 2. Industry / Service Alignment (Weight: 2.0)
        buyer_keywords = offer.buyer_profile.lower().split()
        verified_services = [s.lower() for s in prospect.verified_facts.get("identified_services", [])]
        industry_lower = prospect.industry_or_niche.lower()

        matched_services = [s for s in verified_services if any(k in s for k in buyer_keywords)]
        industry_match = any(k in industry_lower for k in buyer_keywords)

        if matched_services or industry_match:
            score += 2.0
            rationale_points.append(
                f"Verified industry/service alignment: Matches offer buyer profile with services [{', '.join(matched_services or [industry_lower])}] (+2.0)"
            )
        else:
            score += 0.5
            rationale_points.append(
                f"General commercial fit, but specific niche alignment requires direct confirmation (+0.5)"
            )

        # 3. Buyer Accessibility & Public Contactability (Weight: 1.5)
        public_emails = prospect.verified_facts.get("public_contact_email", [])
        if public_emails:
            score += 1.5
            rationale_points.append(f"Publicly reachable via verified endpoint ({len(public_emails)} discovered) (+1.5)")
        else:
            score += 0.8
            rationale_points.append("Public website accessible; direct contact endpoint not yet cataloged (+0.8)")

        score = round(score, 2)
        is_qualified = score >= 3.5

        prospect.fit_score = score
        prospect.associated_offer_id = offer.id
        prospect.status = ProspectStatus.QUALIFIED if is_qualified else ProspectStatus.DISQUALIFIED
        prospect.fit_rationale = " | ".join(rationale_points)

        saved = self.db.save_prospect(prospect, actor=actor)
        return saved, is_qualified, prospect.fit_rationale
