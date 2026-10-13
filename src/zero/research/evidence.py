"""Evidence management and market research ingestion helpers."""

from typing import Dict, List, Optional
from zero.database import Database
from zero.schemas import Evidence, EvidenceType, Geography


class EvidenceService:
    """Service for ingesting, validating, and retrieving market research evidence."""

    def __init__(self, db: Database):
        self.db = db

    def record_evidence(
        self,
        claim: str,
        evidence_type: EvidenceType,
        geography: Geography,
        confidence: float,
        source_url: Optional[str] = None,
        notes: str = "",
        actor: str = "USER",
    ) -> Evidence:
        """Create and persist a new validated evidence item."""
        # Generate stable ID with sequence
        cursor = self.db.get_connection().cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM evidence")
        count = cursor.fetchone()["cnt"] + 1
        ev_id = f"ev_{count:04d}"

        evidence = Evidence(
            id=ev_id,
            claim=claim,
            evidence_type=evidence_type,
            geography=geography,
            confidence=confidence,
            source_url=source_url,
            notes=notes,
        )

        return self.db.save_evidence(evidence, actor=actor)

    def list_evidence(
        self,
        geography: Optional[Geography] = None,
        evidence_type: Optional[EvidenceType] = None,
    ) -> List[Evidence]:
        """List stored evidence with optional filters."""
        return self.db.list_evidence(geography=geography, evidence_type=evidence_type)

    def summarize_market_evidence(self, geography: Optional[Geography] = None) -> Dict[str, int]:
        """Generate breakdown counts of evidence by reliability type."""
        all_evidence = self.list_evidence(geography=geography)
        summary = {
            EvidenceType.VERIFIED_SOURCE.value: 0,
            EvidenceType.USER_PROVIDED.value: 0,
            EvidenceType.HYPOTHESIS.value: 0,
            EvidenceType.CONFLICTING_OR_INSUFFICIENT.value: 0,
        }
        for ev in all_evidence:
            summary[ev.evidence_type.value] += 1
        return summary
