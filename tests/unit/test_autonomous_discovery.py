"""
Unit tests for Autonomous Opportunity Discovery in Project ZERO.

Verifies:
1. Zero marginal cost (INR 0.00 budget maintained).
2. Public source adapter parsing (HN Algolia, GitHub Issues) with mocked responses.
3. Exclusion of disallowed sources (Reddit, DuckDuckGo) per robots.txt.
4. Independent query generation from broad focus areas (no user-supplied URLs or ideas).
5. Evidence provenance and absence of phantom evidence IDs.
6. Separation of problem reporting (VERIFIED_SOURCE) from market demand (HYPOTHESIS).
7. Conservative scoring gating (DecisionStatus.NEEDS_MORE_EVIDENCE).
8. SQLite persistence and cryptographic audit chain logging.
9. Rate-limit and network failure resilience.
"""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import pytest
import httpx

from zero.database import Database
from zero.research.autonomous import (
    AutonomousDiscoveryEngine,
    build_discovery_queries,
)
from zero.research.evaluator import OfferEvaluator
from zero.research.sources import (
    DiscoverySourceAdapter,
    GitHubIssuesSource,
    HnAlgoliaSource,
    get_active_source_adapters,
    get_all_source_definitions,
)
from zero.research.synthesizer import OpportunitySynthesizer
from zero.schemas import (
    CriterionKey,
    DecisionStatus,
    DiscoveredSource,
    EvidenceType,
    Geography,
)


def test_source_adapters_metadata_and_exclusions():
    """Verify source registry maintains INR 0 cost and strictly excludes disallowed sources."""
    sources = get_all_source_definitions()
    assert len(sources) >= 4

    active_sources = get_active_source_adapters()
    active_names = [s.name for s in active_sources]
    assert "hn_algolia" in active_names
    assert "github_issues" in active_names
    assert "reddit_rss" not in active_names
    assert "duckduckgo_lite" not in active_names

    for s in sources:
        assert s.cost_inr == 0.0
        meta = s.get_metadata()
        assert "name" in meta
        assert "rate_limit_info" in meta
        if not s.is_active:
            assert s.exclusion_reason is not None
            with pytest.raises(PermissionError):
                s.search("test query")


def test_hn_algolia_search_mocked(monkeypatch):
    """Verify HN Algolia adapter parses response correctly and handles HTTP errors."""
    mock_payload = {
        "hits": [
            {
                "objectID": "12345",
                "title": "Ask HN: How do you handle cold email deliverability and SPF?",
                "story_text": "<p>We are struggling with Google spam filters and DKIM setup.</p>",
                "url": "https://news.ycombinator.com/item?id=12345",
                "author": "dev_founder",
                "created_at": "2026-05-10T14:30:00Z",
                "points": 45,
                "num_comments": 22,
            }
        ]
    }

    class MockResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json = json_data

        def json(self):
            return self._json

    class MockClient:
        def get(self, url, params=None):
            return MockResponse(200, mock_payload)

    adapter = HnAlgoliaSource(client=MockClient(), request_delay=0.0)
    findings = adapter.search("email deliverability", limit=5)

    assert len(findings) == 1
    item = findings[0]
    assert item.source_name == "hn_algolia"
    assert "deliverability" in item.title.lower()
    assert "spam filters" in item.excerpt.lower()
    assert item.url == "https://news.ycombinator.com/item?id=12345"
    assert item.author == "dev_founder"
    assert item.query == "email deliverability"

    # Test error resilience
    class ErrorClient:
        def get(self, url, params=None):
            raise httpx.ConnectTimeout("Network timeout")

    err_adapter = HnAlgoliaSource(client=ErrorClient(), request_delay=0.0)
    assert err_adapter.search("test") == []


def test_github_issues_search_mocked():
    """Verify GitHub Issues adapter parses response and respects rate limits."""
    mock_payload = {
        "items": [
            {
                "title": "Webhook dropouts during high traffic API sync",
                "html_url": "https://github.com/example/repo/issues/101",
                "body": "Our webhook payloads are failing silently without automated retries.",
                "user": {"login": "octocat"},
                "created_at": "2026-06-01T09:00:00Z",
                "comments": 4,
                "state": "open",
                "repository_url": "https://api.github.com/repos/example/repo",
            }
        ]
    }

    class MockResponse:
        def __init__(self, status_code, json_data, headers=None):
            self.status_code = status_code
            self._json = json_data
            self.headers = headers or {"X-RateLimit-Remaining": "8"}

        def json(self):
            return self._json

    class MockClient:
        def get(self, url, params=None):
            return MockResponse(200, mock_payload)

    adapter = GitHubIssuesSource(client=MockClient(), request_delay=0.0)
    findings = adapter.search("webhook integration", limit=5)

    assert len(findings) == 1
    assert adapter.rate_limit_remaining == 8
    item = findings[0]
    assert item.source_name == "github_issues"
    assert "webhook" in item.title.lower()
    assert item.author == "octocat"
    assert "failing silently" in item.excerpt

    # Test 403 Rate Limit handling
    class RateLimitedClient:
        def get(self, url, params=None):
            return MockResponse(403, {}, headers={"X-RateLimit-Remaining": "0"})

    rl_adapter = GitHubIssuesSource(client=RateLimitedClient(), request_delay=0.0)
    assert rl_adapter.search("query") == []
    assert rl_adapter.rate_limit_remaining == 0


def test_build_discovery_queries():
    """Verify problem-hunting queries are generated from broad focus terms without user URLs."""
    queries = build_discovery_queries(["saas", "consulting"], geography=Geography.IN)
    assert len(queries) > 0
    assert any("deliverability" in q or "integration" in q for q in queries)
    # Never requires user to provide candidate ideas or URLs
    for q in queries:
        assert not q.startswith("http://") and not q.startswith("https://")


def test_opportunity_synthesizer_clusters_and_hypotheses():
    """Verify evidence clustering, verified vs hypothesis tagging, and absence of phantom IDs."""
    synthesizer = OpportunitySynthesizer()

    discovered = [
        DiscoveredSource(
            source_name="hn_algolia",
            title="Trouble with cold email deliverability and DKIM on custom domain",
            url="https://news.ycombinator.com/item?id=99001",
            excerpt="Our outbound sales emails are landing in spam. Need help configuring SPF/DMARC.",
            query="email deliverability",
            author="founder1",
        ),
        DiscoveredSource(
            source_name="github_issues",
            title="Stripe webhook retry failure in production",
            url="https://github.com/org/repo/issues/42",
            excerpt="When webhook server returns 500, payloads are lost permanently without automated queue.",
            query="api integration",
            author="engineer2",
        ),
    ]

    offers, all_evidence = synthesizer.synthesize(
        discovered_sources=discovered,
        geography=Geography.IN,
        is_sample=False,
    )

    assert len(offers) >= 2
    assert len(all_evidence) > len(discovered)

    ev_by_id = {e.id: e for e in all_evidence}

    # Verify every evidence ID linked to every offer actually exists in all_evidence
    for off in offers:
        for eid in off.evidence_ids:
            assert eid in ev_by_id, f"Phantom evidence ID {eid} found on offer {off.id}"

        # Verify that Problem Severity links to VERIFIED_SOURCE evidence
        prob_score = off.evaluation.criterion_scores[CriterionKey.PROBLEM_SEVERITY.value]
        prob_evs = [ev_by_id[eid] for eid in prob_score.evidence_ids]
        assert any(e.evidence_type == EvidenceType.VERIFIED_SOURCE for e in prob_evs)

        # Verify that Willingness to Pay links to HYPOTHESIS evidence with confidence <= 0.50
        wtp_score = off.evaluation.criterion_scores[CriterionKey.WILLINGNESS_TO_PAY.value]
        wtp_evs = [ev_by_id[eid] for eid in wtp_score.evidence_ids]
        assert all(e.evidence_type == EvidenceType.HYPOTHESIS for e in wtp_evs)
        assert all(e.confidence <= 0.50 for e in wtp_evs)


def test_autonomous_discovery_conservative_scoring_gating():
    """
    CRITICAL SAFETY TEST:
    Verify that newly discovered opportunities MUST be evaluated as NEEDS_MORE_EVIDENCE
    because Willingness to Pay is an unvalidated hypothesis (< 0.65 threshold).
    The system must NEVER fabricate customer demand or market validation from public forum posts.
    """
    synthesizer = OpportunitySynthesizer()

    discovered = [
        DiscoveredSource(
            source_name="hn_algolia",
            title="Huge AWS billing surprise on unattached EBS volumes",
            url="https://news.ycombinator.com/item?id=881122",
            excerpt="Discovered $1,200/month in orphaned EBS volumes from dead development clusters.",
            query="cloud billing surprise",
            author="devops_lead",
        )
    ]

    offers, all_evidence = synthesizer.synthesize(
        discovered_sources=discovered,
        geography=Geography.US,
        is_sample=False,
    )

    assert len(offers) == 1
    offer = offers[0]
    assert offer.evaluation is not None

    # Status MUST be NEEDS_MORE_EVIDENCE
    assert offer.evaluation.status == DecisionStatus.NEEDS_MORE_EVIDENCE
    reasons_str = " ".join(offer.evaluation.reasons)
    assert "willingness_to_pay" in reasons_str or "heuristic threshold" in reasons_str
    # Score should be computed mathematically, but cannot be SELECTED
    assert offer.evaluation.weighted_score > 3.0
    assert offer.evaluation.status != DecisionStatus.SELECTED


def test_autonomous_discovery_engine_end_to_end_mocked():
    """Verify autonomous discovery engine end-to-end with SQLite and audit logging."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "zero_test.db"
        db = Database(db_path=db_path)

        try:
            class MockAdapter(DiscoverySourceAdapter):
                name = "mock_source"
                description = "Mock Source for Tests"
                documentation_url = "https://example.com"
                rate_limit_info = "Mock"
                cost_inr = 0.0
                is_active = True

                def search(self, query: str, limit: int = 5):
                    return [
                        DiscoveredSource(
                            source_name=self.name,
                            title=f"Sample B2B problem found for {query}",
                            url=f"https://example.com/item/{abs(hash(query)) % 10000}",
                            excerpt=f"Extracted discussion about {query} and operational friction.",
                            query=query,
                            author="mock_user",
                        )
                    ]

            engine = AutonomousDiscoveryEngine(
                db=db,
                adapters=[MockAdapter()],
                evaluator=OfferEvaluator(),
            )

            result = engine.discover_opportunities(
                geography=Geography.IN,
                focus_areas=["saas"],
                limit_per_query=2,
                is_sample=True,
            )

            # Verify discovery result
            assert result.budget_spent_inr == 0.0
            assert len(result.sources_discovered) > 0
            assert len(result.evidence_created) > 0
            assert len(result.offers_synthesized) > 0
            assert len(result.next_step_recommendations) >= 3

            # Verify database persistence
            db_offers = db.list_offers(geography=Geography.IN)
            assert len(db_offers) >= len(result.offers_synthesized)

            db_evidence = db.list_evidence(geography=Geography.IN)
            assert len(db_evidence) >= len(result.evidence_created)

            # Verify audit chain integrity
            is_valid, msg, _ = db.audit.verify_chain_integrity()
            assert is_valid is True

            cursor = db.get_connection().cursor()
            cursor.execute("SELECT * FROM audit_events WHERE action = 'AUTONOMOUS_OPPORTUNITY_DISCOVERY'")
            row = cursor.fetchone()
            assert row is not None

        finally:
            db.close()


def test_cli_research_sources_runs(capsys):
    """Verify `zero research sources` runs and outputs evaluated sources."""
    from zero.cli import build_parser, handle_research

    parser = build_parser()
    args = parser.parse_args(["research", "sources"])
    assert args.command == "research"
    assert args.action == "sources"
    handle_research(args)
    captured = capsys.readouterr()
    assert "hn_algolia" in captured.out
    assert "github_issues" in captured.out
    assert "reddit_rss" in captured.out
    assert "duckduckgo" in captured.out
