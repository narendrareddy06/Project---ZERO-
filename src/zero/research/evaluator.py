"""Offer evaluation engine with deterministic multi-criteria scoring and evidence checks."""

from typing import Dict, List, Optional, Set
from zero.config import CONFIDENCE_THRESHOLD
from zero.schemas import (
    CRITERION_WEIGHTS,
    CriterionKey,
    CriterionScore,
    DecisionStatus,
    EvaluationResult,
    Evidence,
    EvidenceType,
    OfferCandidate,
)

MIN_SCORE_FOR_SELECTION = 3.5  # Out of 5.0


class OfferEvaluator:
    """
    Evaluates candidate business offers against evidence using PRD Section 6 rubric.
    
    Weights:
    - Problem severity: 25% (0.25)
    - Willingness-to-pay evidence: 25% (0.25)
    - Buyer accessibility: 20% (0.20)
    - Delivery feasibility: 20% (0.20)
    - 72-hour sales-cycle feasibility: 10% (0.10)
    """

    def __init__(
        self,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        min_score: float = MIN_SCORE_FOR_SELECTION,
    ):
        self.confidence_threshold = confidence_threshold
        self.min_score = min_score

    def evaluate(
        self,
        offer: OfferCandidate,
        criterion_scores: Dict[CriterionKey, CriterionScore],
        evidence_records: List[Evidence],
    ) -> EvaluationResult:
        """
        Evaluate an offer candidate against linked evidence records and criteria scores.
        Ensures strict separation between mathematical score and evidence validity.
        """
        evidence_by_id: Dict[str, Evidence] = {e.id: e for e in evidence_records}
        missing_evidence_criteria: List[str] = []
        contradictions_found: List[str] = []
        reasons: List[str] = []

        # 1. Verify that all 5 required criteria are present
        for key in CriterionKey:
            if key not in criterion_scores:
                raise ValueError(f"Missing required evaluation criterion: {key.value}")

        # 2. Check each criterion's linked evidence
        total_linked_ev_count = 0
        total_ev_confidence = 0.0

        for key, c_score in criterion_scores.items():
            linked = [evidence_by_id[eid] for eid in c_score.evidence_ids if eid in evidence_by_id]
            
            # Check for missing evidence
            if not linked:
                missing_evidence_criteria.append(key.value)
                continue

            for ev in linked:
                total_linked_ev_count += 1
                total_ev_confidence += ev.confidence

                # Check for unresolved contradictions
                if ev.evidence_type == EvidenceType.CONFLICTING_OR_INSUFFICIENT:
                    contradictions_found.append(
                        f"Contradiction in {key.value} from evidence {ev.id}: '{ev.claim}'"
                    )

            # Critical criteria check: Problem Severity and Willingness to Pay
            # MUST have at least one verified or high-confidence evidence item
            if key in (CriterionKey.PROBLEM_SEVERITY, CriterionKey.WILLINGNESS_TO_PAY):
                max_confidence = max((ev.confidence for ev in linked), default=0.0)
                if max_confidence < self.confidence_threshold:
                    missing_evidence_criteria.append(
                        f"{key.value} (evidence confidence {max_confidence:.2f} is below threshold {self.confidence_threshold:.2f})"
                    )

        avg_confidence = (
            total_ev_confidence / total_linked_ev_count if total_linked_ev_count > 0 else 0.0
        )

        # 3. Calculate deterministic weighted score
        weighted_score = sum(
            c_score.score * CRITERION_WEIGHTS[key]
            for key, c_score in criterion_scores.items()
        )
        weighted_score = round(weighted_score, 3)

        # 4. Determine decision status based on evidence integrity and rubric gates
        if contradictions_found:
            status = DecisionStatus.NEEDS_MORE_EVIDENCE
            reasons.append("Unresolved contradictory or disputed evidence detected.")
            reasons.extend(contradictions_found)

        elif missing_evidence_criteria:
            status = DecisionStatus.NEEDS_MORE_EVIDENCE
            reasons.append(
                f"Missing or insufficient evidence for criteria: {', '.join(missing_evidence_criteria)}."
            )

        elif avg_confidence < self.confidence_threshold:
            status = DecisionStatus.NEEDS_MORE_EVIDENCE
            reasons.append(
                f"Average evidence confidence ({avg_confidence:.2f}) is below threshold ({self.confidence_threshold:.2f})."
            )

        elif (
            criterion_scores[CriterionKey.DELIVERY_FEASIBILITY].score <= 2
            or weighted_score < self.min_score
        ):
            status = DecisionStatus.REJECTED
            if criterion_scores[CriterionKey.DELIVERY_FEASIBILITY].score <= 2:
                reasons.append(
                    f"Delivery feasibility score is too low ({criterion_scores[CriterionKey.DELIVERY_FEASIBILITY].score}/5) for remote ₹0 execution."
                )
            if weighted_score < self.min_score:
                reasons.append(
                    f"Weighted score ({weighted_score:.2f}/5.0) is below qualification minimum ({self.min_score:.2f})."
                )

        else:
            status = DecisionStatus.SELECTED
            reasons.append(
                f"Qualified with weighted score {weighted_score:.2f}/5.0 and average confidence {avg_confidence:.2f}."
            )

        # Format criterion_scores dictionary with string keys for serialization
        criterion_dict = {k.value: v for k, v in criterion_scores.items()}

        return EvaluationResult(
            status=status,
            weighted_score=weighted_score,
            criterion_scores=criterion_dict,
            average_confidence=round(avg_confidence, 3),
            reasons=reasons,
            missing_evidence_criteria=missing_evidence_criteria,
            contradictions_found=contradictions_found,
        )
