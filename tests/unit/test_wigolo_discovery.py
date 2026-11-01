"""
Unit tests for Autonomous Opportunity Discovery with Wigolo MCP Server.

Verifies:
1. Empty search results and provider errors are handled gracefully.
2. Duplicate sources and syndicated content are deduplicated.
3. Missing or undated publication metadata is preserved honestly without inventing dates.
4. Direct observations (VERIFIED_SOURCE) are strictly separated from hypotheses (HYPOTHESIS).
5. Complaints and problem reports do NOT imply willingness to pay.
6. Conservative scoring gates all new opportunities as NEEDS_MORE_EVIDENCE.
7. Zero budget target (INR 0.00) is maintained throughout discovery.
8. End-to-end discovery persists evidence, offers, and hash-chained audit events.
"""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import pytest

from zero.database import Database
from zero.research.autonomous import (
    AutonomousDiscoveryEngine,
    build_discovery_queries,
    compute_content_fingerprint,
    normalize_url,
)
from zero.research.evaluator import OfferEvaluator
from zero.research.sources import WigoloDiscoverySource
from zero.research.synthesizer import OpportunitySynthesizer
from zero.research.wigolo_client import WigoloMcpClient
from zero.schemas import (
    CriterionKey,
    DecisionStatus,
    DiscoveredSource,
    EvidenceType,
    Geography,
)


def test_wigolo_empty_search_and_provider_errors():
    """Verify Wigolo adapter handles empty results and provider errors gracefully."""
    # 1. Empty results
    def mock_empty(name, args):
        return {"results": [], "query": args.get("query")}

    empty_client = WigoloMcpClient(mock_handler=mock_empty)
    adapter = WigoloDiscoverySource(client=empty_client)
    assert adapter.search("b2b billing issue") == []

    # 2. Provider error / exception
    def mock_error(name, args):
        raise RuntimeError("Wigolo search timeout or upstream connection failure")

    err_client = WigoloMcpClient(mock_handler=mock_error)
    err_adapter = WigoloDiscoverySource(client=err_client)
    # Must not raise an uncaught exception; return empty list safely
    assert err_adapter.search("b2b billing issue") == []


def test_wigolo_url_and_syndicated_content_deduplication():
    """Verify duplicate URLs and syndicated duplicate content are not counted as independent evidence."""
    # Test URL normalization
    url1 = "https://example.com/blog/saas-problems/?utm_source=twitter&utm_medium=social"
    url2 = "https://example.com/blog/saas-problems"
    assert normalize_url(url1) == normalize_url(url2)

    # Test syndicated content fingerprinting
    title = "Why B2B SaaS billing integrations fail in production"
    excerpt = "We faced recurring webhook drops and invoice reconciliation errors every month."
    sig1 = compute_content_fingerprint(title, excerpt)
    sig2 = compute_content_fingerprint(title.upper(), excerpt)
    assert sig1 == sig2

    # Mock provider returning:
    # 1. Original post
    # 2. Same post with tracking parameters
    # 3. Syndicated duplicate post on different domain
    # 4. Genuinely distinct post
    def mock_search_duplicates(name, args):
        return {
            "results": [
                {
                    "title": title,
                    "url": "https://first-publisher.com/article",
                    "snippet": excerpt,
                    "published_date": "2026-03-01",
                },
                {
                    "title": title,
                    "url": "https://first-publisher.com/article?ref=newsletter&utm_campaign=promo",
                    "snippet": excerpt,
                    "published_date": "2026-03-01",
                },
                {
                    "title": title,
                    "url": "https://syndicated-aggregator.net/repost-123",
                    "snippet": excerpt,
                    "published_date": "2026-03-02",
                },
                {
                    "title": "Email authentication and DMARC bounce remediation",
                    "url": "https://email-audit.org/guide",
                    "snippet": "DNS SPF and DKIM configuration checklist to prevent spam classification.",
                    "published_date": "2026-04-10",
                },
            ]
        }

    client = WigoloMcpClient(mock_handler=mock_search_duplicates)
    adapter = WigoloDiscoverySource(client=client)

    engine = AutonomousDiscoveryEngine(adapters=[adapter])
    # Run discovery with one query to inspect deduplication
    result = engine.discover_opportunities(geography=Geography.IN, focus_areas=["saas"], limit_per_query=5)

    # Out of 4 items (original, url duplicate, syndicated duplicate, distinct item),
    # exactly 2 unique evidence items should survive!
    assert len(result.sources_discovered) == 2
    discovered_urls = [s.url for s in result.sources_discovered]
    assert "https://first-publisher.com/article" in discovered_urls
    assert "https://email-audit.org/guide" in discovered_urls


def test_wigolo_missing_or_undated_publication_metadata():
    """Verify missing publication metadata is recorded as None/UNDATED and dates are never fabricated."""
    def mock_metadata(name, args):
        return {
            "results": [
                {
                    "title": "Discussion on database migration lock contention",
                    "url": "https://forum.tech/thread/1",
                    "snippet": "Our Postgres migration locked the billing table during checkout.",
                    # No published_date field provided
                },
                {
                    "title": "Dated article on webhook retries",
                    "url": "https://forum.tech/thread/2",
                    "snippet": "Using exponential backoff for webhook drops.",
                    "published_date": "2026-05-15",
                },
            ]
        }

    client = WigoloMcpClient(mock_handler=mock_metadata)
    adapter = WigoloDiscoverySource(client=client)
    findings = adapter.search("migration lock")

    assert len(findings) == 2
    undated_item = findings[0]
    dated_item = findings[1]

    # Verify undated item does NOT fabricate a date
    assert undated_item.published_date is None

    # Verify dated item preserves the authentic date
    assert dated_item.published_date == "2026-05-15"

    # Verify synthesizer propagates this honestly to Evidence notes
    synthesizer = OpportunitySynthesizer()
    _, evidence_list = synthesizer.synthesize(findings, geography=Geography.IN)

    ev_undated = next(e for e in evidence_list if e.source_url == undated_item.url)
    assert "UNDATED / UNKNOWN" in ev_undated.notes
    assert ev_undated.published_date is None


def test_facts_versus_hypotheses_separation():
    """Verify direct observations are VERIFIED_SOURCE (>= 0.65) and assumptions are HYPOTHESIS (<= 0.50)."""
    discovered = [
        DiscoveredSource(
            source_name="wigolo",
            title="SaaS cloud billing surprise on unattached EBS volumes",
            url="https://cloud-ops.example/post/ebs-billing",
            excerpt="Our startup was billed $850 for detached storage volumes that were forgotten.",
            query="cloud billing surprise",
            published_date="2026-04-01",
        )
    ]

    synthesizer = OpportunitySynthesizer()
    offers, evidence = synthesizer.synthesize(discovered, geography=Geography.US)

    assert len(offers) >= 1
    # Problem report must be a direct observation of a public report (VERIFIED_SOURCE)
    observed_ev = next(e for e in evidence if e.source_url == discovered[0].url)
    assert observed_ev.evidence_type == EvidenceType.VERIFIED_SOURCE
    assert observed_ev.confidence >= 0.65

    # Commercial demand and sales cycle feasibility MUST be hypotheses
    hypotheses = [e for e in evidence if e.evidence_type == EvidenceType.HYPOTHESIS]
    assert len(hypotheses) >= 2
    for hyp in hypotheses:
        assert hyp.confidence <= 0.50
        assert hyp.evidence_type == EvidenceType.HYPOTHESIS


def test_unsupported_willingness_to_pay_claims_not_inferred_from_complaints():
    """
    CRITICAL INTEGRITY TEST:
    Verify that an angry forum complaint about high costs or broken tools
    does NOT cause ZERO to infer validated commercial willingness to pay.
    """
    severe_complaint = [
        DiscoveredSource(
            source_name="wigolo",
            title="CRITICAL: We lost $50,000 in customer deals due to email deliverability!",
            url="https://founder-rants.org/lost-deals-spam",
            excerpt="Spam filters killed our entire outbound pipeline. We are desperate for a fix.",
            query="email deliverability problem",
            published_date="2026-06-01",
        )
    ]

    synthesizer = OpportunitySynthesizer()
    offers, evidence = synthesizer.synthesize(severe_complaint, geography=Geography.IN)

    offer = offers[0]
    wtp_score = offer.evaluation.criterion_scores[CriterionKey.WILLINGNESS_TO_PAY.value]

    # Verify WTP criterion links ONLY to hypothesis evidence
    ev_by_id = {e.id: e for e in evidence}
    wtp_linked_evs = [ev_by_id[eid] for eid in wtp_score.evidence_ids]
    assert all(e.evidence_type == EvidenceType.HYPOTHESIS for e in wtp_linked_evs)
    assert all(e.confidence <= 0.50 for e in wtp_linked_evs)

    # Rationale must explicitly state commercial willingness to pay is unvalidated
    assert "live pilot" in wtp_score.rationale.lower() or "requires" in wtp_score.rationale.lower()


def test_conservative_scoring_gates_unvalidated_opportunities():
    """Verify newly discovered opportunities MUST be gated as NEEDS_MORE_EVIDENCE, never SELECTED."""
    discovered = [
        DiscoveredSource(
            source_name="wigolo",
            title="Manual reconciliation of multi-currency payments",
            url="https://finance-ops.dev/manual-reconciliation",
            excerpt="Operations team spends 12 hours every Monday manually matching Stripe and bank statements.",
            query="manual reconciliation",
            published_date="2026-05-20",
        )
    ]

    synthesizer = OpportunitySynthesizer()
    offers, _ = synthesizer.synthesize(discovered, geography=Geography.IN)

    assert len(offers) == 1
    eval_result = offers[0].evaluation
    assert eval_result is not None

    # Status must strictly be NEEDS_MORE_EVIDENCE
    assert eval_result.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    assert eval_result.status != DecisionStatus.SELECTED

    # Reasons must explicitly explain that willingness to pay lacks empirical validation
    reasons_text = " ".join(eval_result.reasons)
    assert "willingness_to_pay" in reasons_text


def test_wigolo_fetch_enrichment_mocked():
    """Verify Wigolo fetch tool can enrich short search snippets with deeper page context."""
    def mock_search_and_fetch(name, args):
        if name == "search":
            return {
                "results": [
                    {
                        "title": "API Webhook Dropouts",
                        "url": "https://api-status.org/issues/99",
                        "snippet": "Short snippet",  # Short snippet triggers fetch enrichment
                        "published_date": "2026-06-10",
                    }
                ]
            }
        elif name == "fetch":
            return {
                "url": args["url"],
                "title": "API Webhook Dropouts Deep Dive",
                "markdown": "Full extracted diagnostic report explaining that silent drops occur when timeout is under 2s.",
                "http_status": 200,
            }
        return {}

    client = WigoloMcpClient(mock_handler=mock_search_and_fetch)
    adapter = WigoloDiscoverySource(client=client, enrich_with_fetch=True)
    findings = adapter.search("webhook drops", limit=1)

    assert len(findings) == 1
    item = findings[0]
    # Verify excerpt was enriched by fetch
    assert "silent drops occur" in item.excerpt
    assert item.published_date == "2026-06-10"


def test_autonomous_discovery_with_wigolo_persists_to_sqlite_and_audit():
    """Verify end-to-end autonomous discovery persisting to SQLite with zero budget spent."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "zero_wigolo_test.db"
        db = Database(db_path=db_path)

        def mock_wigolo_mcp(name, args):
            query = args.get("query", "")
            return {
                "results": [
                    {
                        "title": f"B2B Friction Report for {query}",
                        "url": f"https://public-forum.org/threads/{abs(hash(query)) % 5000}",
                        "snippet": f"Public discussion describing operational headaches with {query}.",
                        "published_date": "2026-06-15",
                    }
                ]
            }

        client = WigoloMcpClient(mock_handler=mock_wigolo_mcp)
        adapter = WigoloDiscoverySource(client=client)

        engine = AutonomousDiscoveryEngine(
            db=db,
            adapters=[adapter],
            evaluator=OfferEvaluator(),
        )

        try:
            result = engine.discover_opportunities(
                geography=Geography.IN,
                focus_areas=["saas"],
                limit_per_query=2,
                is_sample=True,
            )

            # Invariant checks
            assert result.budget_spent_inr == 0.0
            assert len(result.sources_discovered) > 0
            assert len(result.evidence_created) > 0
            assert len(result.offers_synthesized) > 0

            # Database verification
            offers_in_db = db.list_offers(geography=Geography.IN)
            assert len(offers_in_db) == len(result.offers_synthesized)

            evidence_in_db = db.list_evidence(geography=Geography.IN)
            assert len(evidence_in_db) == len(result.evidence_created)

            # Audit chain verification
            is_valid, msg, _ = db.audit.verify_chain_integrity()
            assert is_valid is True
            cursor = db.get_connection().cursor()
            cursor.execute("SELECT * FROM audit_events WHERE action = 'AUTONOMOUS_OPPORTUNITY_DISCOVERY'")
            assert cursor.fetchone() is not None

        finally:
            db.close()

