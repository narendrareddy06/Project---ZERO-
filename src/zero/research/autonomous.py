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
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import uuid

from zero.database import Database
from zero.research.evaluator import OfferEvaluator
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


def build_discovery_queries(focus_areas: List[str], geography: Geography) -> List[str]:
    """Generate problem-oriented search queries from broad focus areas tailored to geography."""
    clean_focus = [f.strip() for f in focus_areas if f.strip()]
    if not clean_focus:
        clean_focus = ["b2b", "saas", "professional services"]

    if geography == Geography.IN:
        templates = [
            "{term} deliverability problem India",
            "{term} payment gateway webhook failure",
            "{term} invoice reconciliation manual friction",
            "{term} API integration error",
            "{term} cloud billing cost surprise",
        ]
    elif geography == Geography.US:
        templates = [
            "{term} deliverability DMARC spam problem",
            "{term} API webhook failure",
            "{term} compliance audit checklist manual",
            "{term} cloud infrastructure cost waste",
            "{term} contractor payout reconciliation",
        ]
    else:
        templates = [
            "{term} deliverability problem",
            "{term} api integration failure",
            "{term} manual reconciliation",
            "{term} cloud billing surprise",
            "{term} secrets leak vulnerability",
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
    ):
        self.db = db
        self.adapters = adapters if adapters is not None else get_active_source_adapters()
        self.evaluator = evaluator or OfferEvaluator()
        self.synthesizer = OpportunitySynthesizer(evaluator=self.evaluator)

    def close(self):
        """Clean up HTTP clients on active adapters."""
        for adapter in self.adapters:
            if hasattr(adapter, "close") and callable(adapter.close):
                adapter.close()

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

        all_sources: List[DiscoveredSource] = []
        seen_urls = set()
        seen_content_hashes = set()

        # 1. Search active source adapters with deduplication of URLs and syndicated content
        for q in queries:
            for adapter in self.adapters:
                try:
                    findings = adapter.search(q, limit=limit_per_query)
                    for item in findings:
                        norm_url = normalize_url(item.url)
                        content_hash = compute_content_fingerprint(item.title, item.excerpt)

                        if norm_url not in seen_urls and content_hash not in seen_content_hashes:
                            seen_urls.add(norm_url)
                            seen_content_hashes.add(content_hash)
                            all_sources.append(item)
                except Exception:
                    # Individual source failure does not abort the discovery process
                    continue

        # 2. Synthesize candidate offers and evidence records
        offers, evidence_list = self.synthesizer.synthesize(
            discovered_sources=all_sources,
            geography=geography,
            is_sample=is_sample,
            run_prefix=run_id[:12],
        )

        # 3. Formulate transparent next validation recommendations
        recommendations = [
            "Conduct structured pilot discovery conversations with 3 target decision makers to validate commercial Willingness to Pay.",
            "Verify deliverability and DNS compliance with a live test domain before client deployment.",
            "Do NOT initiate mass outbound outreach until pilot terms and pricing acceptability are verified.",
        ]

        # 4. Persist to Database if provided
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
                    "sources_discovered_count": len(all_sources),
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
            sources_discovered=all_sources,
            evidence_created=evidence_list,
            offers_synthesized=offers,
            budget_spent_inr=0.0,
            is_sample=is_sample,
            next_step_recommendations=recommendations,
        )
