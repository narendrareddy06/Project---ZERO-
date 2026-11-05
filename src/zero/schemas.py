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
    """
    A discrete unit of market or customer evidence.

    NOTE ON SOURCE VERIFICATION LIMITATION:
    In Stage A, the system validates that a VERIFIED_SOURCE record contains a syntactically
    valid http/https URL citation. Under the offline INR 0 budget boundary, the system does NOT
    fetch remote web pages or execute automated claim-entailment to verify that the external
    document content proves the asserted claim. Evidence validation confirms citation format,
    not remote ground-truth verification.
    """
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
    excerpt: Optional[str] = Field(None, description="Direct supporting excerpt extracted from public source")
    retrieved_at: Optional[datetime] = Field(None, description="UTC timestamp when source was retrieved")
    published_date: Optional[str] = Field(None, description="Publication date from source metadata if available")
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
    independent_report_count: int = Field(default=1, description="Number of distinct independent source reports supporting this opportunity")
    unknown_independence_count: int = Field(default=0, description="Count of sources where independence could not be established")
    unknowns_requiring_validation: List[str] = Field(default_factory=list, description="Explicit unknowns requiring market validation")
    problem_severity_evidence: Optional[str] = Field(None, description="Direct summary of problem severity from supporting evidence")
    wtp_evidence_summary: Optional[str] = Field(None, description="Summary of commercial willingness-to-pay evidence or explicit unknown status")


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


class FetchStatus(str, Enum):
    """Result status of public web source retrieval."""
    SUCCESS = "SUCCESS"
    HTTP_ERROR = "HTTP_ERROR"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    BLOCKED_DOMAIN = "BLOCKED_DOMAIN"
    NON_HTML = "NON_HTML"
    LOGIN_OR_PAYWALL_DETECTED = "LOGIN_OR_PAYWALL_DETECTED"


class ResearchExcerpt(BaseModel):
    """Supporting excerpt extracted from a public web source."""
    source_url: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    http_status: int
    title: Optional[str] = None
    excerpt: str
    supports_claim: bool
    relevance_notes: str = ""
    is_conflicting: bool = False


class SourceVerificationStatus(str, Enum):
    """Result status of source verification check."""
    FETCH_VERIFIED = "FETCH_VERIFIED"                    # Destination page successfully retrieved (HTTP 200) and content inspected
    REDIRECTED_AND_VERIFIED = "REDIRECTED_AND_VERIFIED"  # Destination page followed redirect (HTTP 200) and content inspected
    API_VERIFIED = "API_VERIFIED"                        # Verified directly from recognized API response (e.g. Algolia, GitHub)
    SNIPPET_UNFETCHED = "SNIPPET_UNFETCHED"              # Search snippet contains pain signals but destination could not be fetched
    # Backward compatibility
    VERIFIED = "VERIFIED"                                # Legacy general verified status
    UNAVAILABLE = "UNAVAILABLE"                          # Connection failed, timed out, robots disallowed, or blocked
    HTTP_ERROR = "HTTP_ERROR"                            # HTTP 4xx or 5xx response
    EMPTY_CONTENT = "EMPTY_CONTENT"                      # Body content empty or < 50 characters
    IRRELEVANT = "IRRELEVANT"                            # Generic domain, tutorial, or lacks business pain signals
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"          # Login or paywall gate detected


class DiscoveredSource(BaseModel):
    """A raw discovery finding retrieved from a permitted public source adapter."""
    source_name: str = Field(..., description="Name of source adapter (e.g. hn_algolia, github_issues)")
    title: str = Field(..., min_length=2, description="Title of the post, issue, or discussion")
    url: str = Field(..., description="Public canonical URL of the finding")
    original_url: Optional[str] = Field(None, description="Original discovered URL before redirects")
    excerpt: str = Field(default="", description="Relevant text excerpt describing the problem or need")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp of discovery/publication")
    published_date: Optional[str] = Field(None, description="Extracted source publication date string if available; None if undated")
    author: Optional[str] = Field(None, description="Author handle or username if publicly visible")
    query: str = Field(default="", description="Search query string that discovered this source")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional source-specific metadata")
    verification_status: Optional[SourceVerificationStatus] = Field(None, description="Status of source verification check")
    rejection_reason: Optional[str] = Field(None, description="Reason if source was rejected or flagged")
    http_status: Optional[int] = Field(None, description="HTTP status code from verification")
    raw_content: Optional[str] = Field(None, description="Extracted clean text content from page")
    api_provider: Optional[str] = Field(None, description="Recognized API provider name if API_VERIFIED")
    api_record_id: Optional[str] = Field(None, description="Original record ID from the API")
    publisher_org: Optional[str] = Field(None, description="Identifiable publisher organization or domain entity")


class ProspectStatus(str, Enum):
    """Qualification status of a business prospect."""
    DISCOVERED = "DISCOVERED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    SUPPRESSED = "SUPPRESSED"


class Prospect(BaseModel):
    """
    A real-world business prospect identified from permitted public sources.
    Strictly forbids LinkedIn scraping/access per AGENTS.md and PRD rules.
    """
    id: str = Field(..., description="Unique prospect ID (e.g. prosp_12345678)")
    company_name: str = Field(..., min_length=2, description="Legal or trading name of business")
    domain_or_website: str = Field(..., min_length=3, description="Company website or public domain")
    geography: Geography = Field(..., description="Target market geography (IN or US)")
    industry_or_niche: str = Field(..., min_length=2, description="Industry sector or specialty")
    public_source_url: str = Field(..., description="Permitted public source where business was discovered")
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp when discovered")
    status: ProspectStatus = Field(default=ProspectStatus.DISCOVERED, description="Current prospect status")
    fit_score: Optional[float] = Field(None, ge=0.0, le=5.0, description="Fit score from 1.0 to 5.0 against offer")
    fit_rationale: Optional[str] = Field(None, description="Detailed rationale explaining fit with supporting public facts")
    verified_facts: Dict[str, Any] = Field(default_factory=dict, description="Verified facts from public sources")
    assumptions: Dict[str, Any] = Field(default_factory=dict, description="Explicit assumptions or hypotheses about prospect")
    associated_offer_id: Optional[str] = Field(None, description="Offer ID this prospect is evaluated against")
    is_sample: bool = Field(default=False, description="Whether this is synthetic demonstration/sample data")

    @field_validator("domain_or_website", "public_source_url")
    @classmethod
    def reject_linkedin_urls(cls, v: str) -> str:
        lower_v = v.lower()
        if "linkedin.com" in lower_v:
            raise ValueError(
                "LinkedIn discovery, scraping, and messaging are strictly prohibited by Project ZERO safety rules (AGENTS.md)."
            )
        return v


class SuppressionRecord(BaseModel):
    """Suppression / opt-out / do-not-contact record."""
    domain_or_email: str = Field(..., min_length=3, description="Normalized domain or email to suppress")
    reason: str = Field(..., min_length=3, description="Reason: OPT_OUT, DO_NOT_CONTACT, COMPETITOR, etc.")
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp when added")
    notes: Optional[str] = Field("", description="Additional context")


class ProofAsset(BaseModel):
    """
    A truthful demonstration asset illustrating an offer capability.
    Must never fabricate past client testimonials, fictional outcomes, or case studies.
    """
    id: str = Field(..., description="Unique proof asset ID (e.g. asset_12345678)")
    offer_id: str = Field(..., description="Offer candidate ID this asset demonstrates")
    title: str = Field(..., min_length=5, description="Title of demonstration asset")
    asset_type: str = Field(..., description="Type of asset: AUDIT_CHECKLIST, SPECIFICATION, PROTOTYPE_WALKTHROUGH")
    content: str = Field(..., min_length=20, description="Asset markdown or text content")
    disclaimer: str = Field(
        ...,
        description="Mandatory disclaimer stating this is a Project ZERO demo, not past client work or fabricated results",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp created")
    is_sample: bool = Field(default=True, description="Proof assets are demonstration records")

    @model_validator(mode="after")
    def validate_disclaimer_content(self) -> "ProofAsset":
        required_phrase = "PROJECT ZERO DEMONSTRATION ASSET"
        if required_phrase not in self.disclaimer.upper():
            raise ValueError(
                f"Proof asset disclaimer must contain '{required_phrase}' to prevent misrepresentation."
            )
        return self
