"""
Autonomous Opportunity Discovery Engine for Project ZERO.

Conducts independent, zero-cost market research from broad goals:
- Takes only broad inputs (geography, focus areas, budget constraint).
- Does not require operator to provide URLs, business ideas, or pre-formed offers.
- Uses permitted public APIs (HN Algolia, GitHub Issues) with zero marginal cost.
- Excludes disallowed sources (Reddit, DuckDuckGo) per robots.txt.
- Converts public findings into verified problem evidence.
- Explicitly keeps willingness to pay and 72-hour sales cycle as hypotheses (<= 0.50 confidence).
- Evaluates candidate opportunities conservatively via PRD Section 6 rubric.
- Records all actions, evidence, and offers into SQLite with cryptographic audit logs.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import uuid

from zero.database import Database
from zero.research.evaluator import OfferEvaluator
from zero.research.fetcher import SourceVerifier
from zero.research.sources import (
    DiscoverySourceAdapter,
    GitHubIssuesSource,
    HnAlgoliaSource,
    WigoloDiscoverySource,
    get_active_source_adapters,
)
from zero.research.synthesizer import OpportunitySynthesizer
from zero.schemas import (
    DecisionStatus,
    DiscoveredSource,
    Evidence,
    Geography,
    OfferCandidate,
    SourceVerificationStatus,
)


@dataclass
class AutonomousDiscoveryResult:
    """Structured report returned by the autonomous discovery engine."""
    run_id: str
    geography: Geography
    focus_areas: List[str]
    queries_executed: List[str]
    sources_discovered: List[DiscoveredSource]
    evidence_created: List[Evidence]
    offers_synthesized: List[OfferCandidate]
    budget_spent_inr: float = 0.0
    is_sample: bool = False
    next_step_recommendations: List[str] = field(default_factory=list)
    sources_rejected: List[DiscoveredSource] = field(default_factory=list)
    rejection_summary: Dict[str, int] = field(default_factory=dict)
    independent_evidence_count: int = 0
    # Phase 1.2: 6 distinct counts and verification breakdowns
    total_retrieved_count: int = 0
    unique_url_count: int = 0
    unique_content_count: int = 0
    unique_publisher_count: int = 0
    confirmed_independent_count: int = 0
    unknown_independence_count: int = 0
    fetch_verified_count: int = 0
    api_verified_count: int = 0
    snippet_unfetched_count: int = 0


def normalize_url(url: str) -> str:
    """Normalize URL by stripping tracking parameters, lowercase domain, and stripping trailing slash."""
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        # Filter out common tracking and campaign query parameters
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "ref", "fbclid", "gclid", "source",
        }
        query_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in tracking_params]
        query = urlencode(query_pairs)
        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.strip()


def compute_content_fingerprint(title: str, excerpt: str) -> str:
    """Compute normalized SHA-256 fingerprint to detect syndicated/duplicate content across distinct URLs."""
    normalized_text = f"{title.lower().strip()[:100]} {excerpt.lower().strip()[:200]}"
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


MULTI_TENANT_DOMAINS = {
    "github.com",
    "news.ycombinator.com",
    "reddit.com",
    "dev.to",
    "medium.com",
    "substack.com",
    "twitter.com",
    "x.com",
    "stackoverflow.com",
}

SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "buff.ly", "ow.ly",
}


def extract_publisher_organization(
    url: str,
    author: Optional[str] = None,
    source_name: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Extract identifiable publisher domain or organization entity.
    Returns (org_identifier: Optional[str], status: str) where status is 'CONFIRMED' or 'UNKNOWN'.

    Conservative deduplication rules:
    - Collapses subdomains to root domain for standalone websites (e.g. blog.acme.com and acme.com -> acme.com).
    - Multi-tenant platforms (GitHub, HN, Dev.to, Medium) do NOT collapse to the platform domain;
      they extract distinct author handles or repo owners (e.g. github:alice vs github:bob).
    - If author or origin is unidentifiable or missing, returns (None, 'UNKNOWN') rather than inventing independence.
    """
    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower().split(":")[0]  # strip port
        if not netloc:
            return None, "UNKNOWN"

        if netloc in SHORTENER_DOMAINS:
            return None, "UNKNOWN"

        # Determine base domain (handling common two-part ccTLDs like .co.in, .co.uk, etc.)
        parts = netloc.split(".")
        if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "gov", "edu", "net", "ac"} and len(parts[-1]) == 2:
            base_domain = ".".join(parts[-3:])
        elif len(parts) >= 2:
            base_domain = ".".join(parts[-2:])
        else:
            base_domain = netloc

        clean_author = (author or "").strip().lower()
        has_author = bool(clean_author and clean_author not in {"unknown", "anonymous", "public_web", "none"})

        # Multi-tenant platform check
        if base_domain in MULTI_TENANT_DOMAINS or source_name in {"hn_algolia", "github_issues"}:
            if base_domain == "github.com" or source_name == "github_issues":
                if has_author:
                    return f"github:{clean_author}", "CONFIRMED"
                path_parts = [p for p in parsed.path.split("/") if p]
                if path_parts:
                    return f"github:{path_parts[0].lower()}", "CONFIRMED"
                return None, "UNKNOWN"

            if base_domain == "news.ycombinator.com" or source_name == "hn_algolia":
                if has_author:
                    return f"hn:{clean_author}", "CONFIRMED"
                return None, "UNKNOWN"

            if base_domain == "dev.to":
                if has_author:
                    return f"dev.to:{clean_author}", "CONFIRMED"
                path_parts = [p for p in parsed.path.split("/") if p]
                if path_parts:
                    return f"dev.to:{path_parts[0].lower()}", "CONFIRMED"
                return None, "UNKNOWN"

            if base_domain == "medium.com":
                if has_author:
                    return f"medium:{clean_author}", "CONFIRMED"
                path_parts = [p for p in parsed.path.split("/") if p]
                if path_parts and path_parts[0].startswith("@"):
                    return f"medium:{path_parts[0].lstrip('@').lower()}", "CONFIRMED"
                return None, "UNKNOWN"

            if has_author:
                return f"{base_domain}:{clean_author}", "CONFIRMED"
            return None, "UNKNOWN"

        # Standalone single-tenant domain represents the publisher organization
        return base_domain, "CONFIRMED"

    except Exception:
        return None, "UNKNOWN"


def build_discovery_queries(focus_areas: List[str], geography: Geography) -> List[str]:
    """
    Generate problem-hunting search queries targeting concrete business pain signals:
    - Manual repetitive work & spreadsheet friction
    - Expensive operational processes & cloud billing surprises
    - Failed integrations, sync dropouts, webhook failures
    - Repeated customer complaints & staffing bottlenecks
    - Lost revenue & compliance difficulties
    """
    clean_focus = [f.strip() for f in focus_areas if f.strip()]
    if not clean_focus:
        clean_focus = ["b2b", "saas", "professional services"]

    if geography == Geography.IN:
        templates = [
            "{term} deliverability high bounce rate spam complaints India",
            "{term} payment gateway webhook failure dropped transactions",
            "{term} invoice reconciliation manual friction repetitive hours",
            "{term} API integration error sync failure broken",
            "{term} unexpected cloud billing cost overrun spike",
            "{term} staffing bottleneck manual review backlog delayed",
            "{term} compliance audit checklist manual headache failed",
            "{term} customer churn lost deals broken workflow",
        ]
    elif geography == Geography.US:
        templates = [
            "{term} deliverability DMARC SPF spam failure",
            "{term} API webhook retry failure silent drop",
            "{term} compliance audit SOC2 checklist manual friction",
            "{term} cloud infrastructure cost waste idle resources",
            "{term} contractor payout reconciliation 1099 hours wasted",
            "{term} customer churn lost deals broken workflow",
            "{term} staffing bottleneck backlog manual work",
        ]
    else:
        templates = [
            "{term} deliverability spam failure high bounce",
            "{term} api integration failure webhook drop",
            "{term} manual reconciliation repetitive spreadsheet friction",
            "{term} unexpected cloud billing surprise cost waste",
            "{term} compliance audit manual checklist headache",
            "{term} bottleneck workflow delay customer complaints",
        ]

    queries: List[str] = []
    for term in clean_focus:
        for tpl in templates:
            q = tpl.format(term=term)
            if q not in queries:
                queries.append(q)

    # Return top targeted queries to stay fast and well within unauthenticated rate limits
    return queries[:3]


class AutonomousDiscoveryEngine:
    """
    Engine that orchestrates end-to-end autonomous discovery of B2B opportunities.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        adapters: Optional[List[DiscoverySourceAdapter]] = None,
        evaluator: Optional[OfferEvaluator] = None,
        verifier: Optional[SourceVerifier] = None,
    ):
        self.db = db
        self.adapters = adapters if adapters is not None else get_active_source_adapters()
        self.evaluator = evaluator or OfferEvaluator()
        self.synthesizer = OpportunitySynthesizer(evaluator=self.evaluator)
        self.verifier = verifier or SourceVerifier()

    def close(self):
        """Clean up HTTP clients on active adapters and verifier."""
        for adapter in self.adapters:
            if hasattr(adapter, "close") and callable(adapter.close):
                adapter.close()
        if hasattr(self.verifier, "close") and callable(self.verifier.close):
            self.verifier.close()

    def discover_opportunities(
        self,
        geography: Geography = Geography.IN,
        focus_areas: Optional[List[str]] = None,
        limit_per_query: int = 5,
        is_sample: bool = False,
    ) -> AutonomousDiscoveryResult:
        """
        Execute an autonomous research run.
        """
        run_id = f"run_auto_{uuid.uuid4().hex[:8]}"
        clean_focus = focus_areas or ["b2b", "saas", "professional services"]
        queries = build_discovery_queries(clean_focus, geography)

        total_retrieved = 0
        raw_candidates: List[DiscoveredSource] = []
        seen_urls = set()
        seen_content_hashes = set()

        # 1. Search active source adapters with deduplication of URLs and syndicated content
        for q in queries:
            for adapter in self.adapters:
                try:
                    findings = adapter.search(q, limit=limit_per_query)
                    total_retrieved += len(findings)
                    for item in findings:
                        norm_url = normalize_url(item.url)
                        content_hash = compute_content_fingerprint(item.title, item.excerpt)

                        if norm_url not in seen_urls and content_hash not in seen_content_hashes:
                            seen_urls.add(norm_url)
                            seen_content_hashes.add(content_hash)
                            raw_candidates.append(item)
                except Exception:
                    # Individual source failure does not abort the discovery process
                    continue

        # 2. Verify sources (Task 1 & Task 3): resolve redirects, check HTTP status, reject irrelevant/empty
        verified_sources: List[DiscoveredSource] = []
        rejected_sources: List[DiscoveredSource] = []
        rejection_summary: Dict[str, int] = {}

        for item in raw_candidates:
            # If source has no status established, verify it
            try:
                # Use remote verification if needed, or fallback gracefully
                verified_item = self.verifier.verify(item, fetch_remote=False if item.verification_status is not None else True)
            except Exception:
                verified_item = self.verifier.verify(item, fetch_remote=False)

            # Extract identifiable publisher organization (Task 2)
            if not verified_item.publisher_org:
                org, _ = extract_publisher_organization(
                    verified_item.url,
                    author=verified_item.author,
                    source_name=verified_item.source_name,
                )
                verified_item.publisher_org = org

            valid_statuses = (
                SourceVerificationStatus.FETCH_VERIFIED,
                SourceVerificationStatus.REDIRECTED_AND_VERIFIED,
                SourceVerificationStatus.API_VERIFIED,
                SourceVerificationStatus.SNIPPET_UNFETCHED,
                SourceVerificationStatus.VERIFIED,
            )

            if verified_item.verification_status in valid_statuses:
                verified_sources.append(verified_item)
            else:
                rejected_sources.append(verified_item)
                status_key = verified_item.verification_status.value if verified_item.verification_status else "REJECTED"
                rejection_summary[status_key] = rejection_summary.get(status_key, 0) + 1

        # 6 Separate Counts & Provenance Tracking (Task 2 & Task 4)
        unique_urls_count = len(seen_urls)
        unique_content_count = len(seen_content_hashes)

        # Breakdowns by verification provenance
        fetch_verified = [
            s for s in verified_sources
            if s.verification_status in (SourceVerificationStatus.FETCH_VERIFIED, SourceVerificationStatus.REDIRECTED_AND_VERIFIED)
        ]
        api_verified = [
            s for s in verified_sources
            if s.verification_status == SourceVerificationStatus.API_VERIFIED
        ]
        snippet_unfetched = [
            s for s in verified_sources
            if s.verification_status == SourceVerificationStatus.SNIPPET_UNFETCHED
        ]

        # Publishers across all verified sources
        unique_publishers = {s.publisher_org for s in verified_sources if s.publisher_org}
        unique_publishers_count = len(unique_publishers)

        # Confirmed independent reports: ONLY count verified fetched, API, or legacy verified sources with confirmed publisher
        # (SNIPPET_UNFETCHED sources are NEVER counted as confirmed independent reports)
        confirmed_sources = [
            s for s in verified_sources
            if s.verification_status in (
                SourceVerificationStatus.FETCH_VERIFIED,
                SourceVerificationStatus.REDIRECTED_AND_VERIFIED,
                SourceVerificationStatus.API_VERIFIED,
                SourceVerificationStatus.VERIFIED,
            ) and s.publisher_org is not None
        ]
        confirmed_publishers = {s.publisher_org for s in confirmed_sources}
        confirmed_independent_count = len(confirmed_publishers)

        # Unknown independence: sources where independence could not be established
        # (includes snippet-only leads and sources without identifiable publisher)
        unknown_independence_sources = [
            s for s in verified_sources
            if s.verification_status == SourceVerificationStatus.SNIPPET_UNFETCHED or not s.publisher_org
        ]
        unknown_independence_count = len(unknown_independence_sources)

        # 3. Synthesize candidate offers and evidence records from verified sources
        offers, evidence_list = self.synthesizer.synthesize(
            discovered_sources=verified_sources,
            geography=geography,
            is_sample=is_sample,
            run_prefix=run_id[:12],
        )

        # 4. Formulate transparent next validation recommendations
        recommendations = [
            "Conduct structured pilot discovery conversations with 3 target decision makers to validate commercial Willingness to Pay.",
            "Verify deliverability and DNS compliance with a live test domain before client deployment.",
            "Do NOT initiate mass outbound outreach until pilot terms and pricing acceptability are verified.",
        ]

        # 5. Persist to Database if provided
        if self.db:
            # Persist all evidence records
            for ev in evidence_list:
                self.db.save_evidence(ev, actor="AGENT")

            # Persist all synthesized offer candidates
            for off in offers:
                self.db.save_offer(off, actor="AGENT")

            # Record cryptographic audit event
            self.db.audit.record_event(
                actor="AGENT",
                action="AUTONOMOUS_OPPORTUNITY_DISCOVERY",
                details={
                    "run_id": run_id,
                    "geography": geography.value,
                    "focus_areas": clean_focus,
                    "queries_count": len(queries),
                    "total_retrieved_records": total_retrieved,
                    "unique_urls": unique_urls_count,
                    "unique_content_items": unique_content_count,
                    "unique_publishers": unique_publishers_count,
                    "confirmed_independent_reports": confirmed_independent_count,
                    "unknown_independence_count": unknown_independence_count,
                    "fetch_verified_count": len(fetch_verified),
                    "api_verified_count": len(api_verified),
                    "snippet_unfetched_count": len(snippet_unfetched),
                    "sources_discovered_count": len(verified_sources),
                    "sources_rejected_count": len(rejected_sources),
                    "evidence_created_count": len(evidence_list),
                    "offers_synthesized_count": len(offers),
                    "budget_spent_inr": 0.0,
                    "is_sample": is_sample,
                },
            )

        return AutonomousDiscoveryResult(
            run_id=run_id,
            geography=geography,
            focus_areas=clean_focus,
            queries_executed=queries,
            sources_discovered=verified_sources,
            evidence_created=evidence_list,
            offers_synthesized=offers,
            budget_spent_inr=0.0,
            is_sample=is_sample,
            next_step_recommendations=recommendations,
            sources_rejected=rejected_sources,
            rejection_summary=rejection_summary,
            independent_evidence_count=confirmed_independent_count,
            total_retrieved_count=total_retrieved,
            unique_url_count=unique_urls_count,
            unique_content_count=unique_content_count,
            unique_publisher_count=unique_publishers_count,
            confirmed_independent_count=confirmed_independent_count,
            unknown_independence_count=unknown_independence_count,
            fetch_verified_count=len(fetch_verified),
            api_verified_count=len(api_verified),
            snippet_unfetched_count=len(snippet_unfetched),
        )
