"""Pydantic data models for Project ZERO."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class Geography(str, Enum):
    """Target geographic market."""
    IN = "IN"  # India
    US = "US"  # United States


class EvidenceType(str, Enum):
    """Categorization of evidence origin and certainty."""
    VERIFIED_SOURCE = "VERIFIED_SOURCE"  # Backed by verifiable public URL/document
    USER_PROVIDED = "USER_PROVIDED"      # Directly supplied by operator/user
    HYPOTHESIS = "HYPOTHESIS"            # Working assumption or unverified hypothesis
    CONFLICTING_OR_INSUFFICIENT = "CONFLICTING_OR_INSUFFICIENT"  # Disputed or inadequate evidence


class Evidence(BaseModel):
    """A discrete unit of market or customer evidence."""
    id: str = Field(..., description="Unique evidence ID (e.g. ev_12345678)")
    claim: str = Field(..., min_length=5, description="Clear, concise claim about market need or buyer behavior")
    evidence_type: EvidenceType = Field(..., description="Classification of evidence reliability")
    geography: Geography = Field(..., description="Applicable market geography")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Qualitative heuristic assessment score from 0.0 (speculative) to 1.0 (verified). Represents evidence rigor, NOT an empirical probability of commercial success.",
    )
    source_url: Optional[str] = Field(None, description="Public URL or source identifier if verified")
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp when captured")
    notes: Optional[str] = Field("", description="Supporting context, caveats, or contradictions")
    is_sample: bool = Field(default=False, description="Whether this record is synthetic demonstration/sample data")

    @field_validator("source_url")
    @classmethod
    def validate_source_url_for_verified_evidence(cls, v: Optional[str], info) -> Optional[str]:
        return v

    @model_validator(mode="after")
    def check_verified_evidence_has_source(self) -> "Evidence":
        if self.evidence_type == EvidenceType.VERIFIED_SOURCE:
            if not self.source_url or not (self.source_url.startswith("http://") or self.source_url.startswith("https://")):
                raise ValueError("VERIFIED_SOURCE evidence must have a valid http/https source_url")
        if self.evidence_type == EvidenceType.HYPOTHESIS and self.confidence > 0.50:
            raise ValueError(
                f"HYPOTHESIS evidence confidence cannot exceed 0.50 (got {self.confidence:.2f}); unverified assumptions must remain <= 0.50"
            )
        return self


class CriterionKey(str, Enum):
    """The 5 evaluation criteria defined in PRD Section 6."""
    PROBLEM_SEVERITY = "problem_severity"
    WILLINGNESS_TO_PAY = "willingness_to_pay"
    BUYER_ACCESSIBILITY = "buyer_accessibility"
    DELIVERY_FEASIBILITY = "delivery_feasibility"
    SALES_CYCLE_FEASIBILITY = "sales_cycle_feasibility"


# Exact weights defined in PRD Section 6
CRITERION_WEIGHTS: Dict[CriterionKey, float] = {
    CriterionKey.PROBLEM_SEVERITY: 0.25,
    CriterionKey.WILLINGNESS_TO_PAY: 0.25,
    CriterionKey.BUYER_ACCESSIBILITY: 0.20,
    CriterionKey.DELIVERY_FEASIBILITY: 0.20,
    CriterionKey.SALES_CYCLE_FEASIBILITY: 0.10,
}


class CriterionScore(BaseModel):
    """Scoring for a single rubric criterion."""
    criterion: CriterionKey
    score: int = Field(..., ge=1, le=5, description="Score on 1-5 scale")
    weight: float = Field(..., ge=0.0, le=1.0, description="Rubric weight")
    rationale: str = Field(..., min_length=5, description="Evidence-backed justification for this score")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of supporting evidence records")

    @model_validator(mode="after")
    def validate_weight_matches_criterion(self) -> "CriterionScore":
        expected_weight = CRITERION_WEIGHTS[self.criterion]
        if abs(self.weight - expected_weight) > 1e-6:
            raise ValueError(f"Weight for {self.criterion.value} must be {expected_weight}, got {self.weight}")
        return self


class DecisionStatus(str, Enum):
    """Evaluation decision outcome."""
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


class EvaluationResult(BaseModel):
    """Comprehensive result of offer evaluation."""
    status: DecisionStatus
    weighted_score: float = Field(..., ge=1.0, le=5.0, description="Mathematically calculated score out of 5.0")
    criterion_scores: Dict[str, CriterionScore]
    average_confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence of linked evidence")
    reasons: List[str] = Field(default_factory=list, description="Summary reasons for decision")
    missing_evidence_criteria: List[str] = Field(default_factory=list, description="Criteria lacking sufficient evidence")
    contradictions_found: List[str] = Field(default_factory=list, description="Unresolved contradictions detected")
    missing_or_invalid_evidence_ids: List[str] = Field(default_factory=list, description="Referenced evidence IDs not found in repository")
    is_sample: bool = Field(default=False, description="Whether this evaluation applies to synthetic demonstration/sample data")


class OfferCandidate(BaseModel):
    """A business offer candidate under consideration."""
    id: str = Field(..., description="Unique offer ID (e.g. off_12345678)")
    title: str = Field(..., min_length=5, description="Clear name of the offer")
    target_geography: Geography = Field(..., description="Target geography (IN or US)")
    buyer_profile: str = Field(..., min_length=5, description="Specific target decision maker / organization type")
    problem_statement: str = Field(..., min_length=10, description="Concrete problem being addressed")
    proposed_deliverable: str = Field(..., min_length=10, description="Specific pilot deliverable")
    plausible_pricing_or_pilot: str = Field(..., min_length=5, description="Proposed pilot structure or pricing")
    delivery_method: str = Field(..., min_length=5, description="How the pilot is fulfilled remotely at INR 0 cost")
    risks: List[str] = Field(default_factory=list, description="Identified risks or challenges")
    evidence_ids: List[str] = Field(default_factory=list, description="Linked evidence IDs")
    evaluation: Optional[EvaluationResult] = None
    is_sample: bool = Field(default=False, description="Whether this offer candidate is synthetic demonstration/sample data")


class RunState(str, Enum):
    """State machine states defined in PRD Section 14."""
    CREATED = "CREATED"
    PREFLIGHT = "PREFLIGHT"
    RESEARCH = "RESEARCH"
    OFFER_DECISION = "OFFER_DECISION"
    DEMO = "DEMO"
    PROSPECTING = "PROSPECTING"
    DRAFTING = "DRAFTING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    OUTREACH = "OUTREACH"
    REPLY_HANDLING = "REPLY_HANDLING"
    PILOT_PROPOSAL = "PILOT_PROPOSAL"
    HANDOVER = "HANDOVER"
    COMPLETED = "COMPLETED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NO_PILOT = "NO_PILOT"


class Run(BaseModel):
    """An execution run of Project ZERO."""
    run_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    current_stage: RunState = RunState.CREATED
    status: str = "INITIALIZED"
    budget_spent_inr: float = 0.0
    is_sample: bool = Field(default=False, description="Whether this run is an isolated demonstration/simulation")


class AuditEvent(BaseModel):
    """A cryptographic hash-chained audit log entry."""
    event_id: str
    sequence: int = Field(..., ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = Field(..., description="Initiator: SYSTEM, USER, or AGENT")
    action: str = Field(..., description="Action performed")
    payload_hash: str = Field(..., description="SHA-256 hash of event details")
    prev_hash: str = Field(..., description="SHA-256 hash of previous audit event in chain")
    event_hash: str = Field(..., description="SHA-256 hash verifying this event's integrity")
    details: Dict[str, Any] = Field(default_factory=dict)
