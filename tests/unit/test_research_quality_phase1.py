"""
Unit tests for Phase 1: Research Quality Improvement in Project ZERO.

Verifies:
1. Relevant vs irrelevant search results (filtering out wikipedia, educational, generic homepages).
2. 404 pages and HTTP error handling (HTTP_ERROR).
3. URL redirects resolution and tracking (REDIRECTED_AND_VERIFIED).
4. Empty pages detection and rejection (EMPTY_CONTENT).
5. Duplicate sources deduplication (URL normalization + content fingerprint).
6. Missing publication dates (preserved as None, never fabricated).
7. Misleading titles (rejecting clickbait titles with irrelevant body content).
8. Weak supporting content detection.
9. Multiple independent sources count and problem severity scoring.
10. Removal of static 0.75 confidence in favor of transparent, dynamic calculation.
11. Willingness to Pay remaining unknown/unvalidated (confidence 0.20, score 1) when unsupported.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import httpx
import pytest

from zero.database import Database
from zero.research.autonomous import (
    AutonomousDiscoveryEngine,
    build_discovery_queries,
    compute_content_fingerprint,
    extract_publisher_organization,
    normalize_url,
)
from zero.research.evaluator import OfferEvaluator
from zero.research.fetcher import (
    FetchStatus,
    HTMLTextExtractor,
    PublicWebResearcher,
    SourceVerifier,
)
from zero.research.sources import DiscoverySourceAdapter, WigoloDiscoverySource
from zero.research.synthesizer import (
    OpportunitySynthesizer,
    calculate_source_evidence_confidence,
)
from zero.schemas import (
    CriterionKey,
    DecisionStatus,
    DiscoveredSource,
    EvidenceType,
    Geography,
    OfferCandidate,
    SourceVerificationStatus,
)


# -------------------------------------------------------------------------
# TASK 2: Search Quality & Pain Signals
# -------------------------------------------------------------------------

def test_discovery_queries_target_business_pain_signals():
    """Verify generated search queries target concrete business pain signals."""
    in_queries = build_discovery_queries(["billing", "logistics"], geography=Geography.IN)
    us_queries = build_discovery_queries(["cloud", "compliance"], geography=Geography.US)

    pain_words = {
        "deliverability", "failure", "reconciliation", "error", "cost", "overrun",
        "bottleneck", "audit", "churn", "waste", "friction", "spam", "drop",
    }
    assert any(any(pw in q.lower() for pw in pain_words) for q in in_queries)
    assert any(any(pw in q.lower() for pw in pain_words) for q in us_queries)


def test_wigolo_filters_irrelevant_domains_upfront():
    """Verify Wigolo adapter rejects generic reference/educational domains."""
    mock_payload = {
        "results": [
            {
                "title": "Email Deliverability - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Email_deliverability",
                "snippet": "Email deliverability is the measurement of emails that reach the inbox.",
            },
            {
                "title": "W3Schools HTML Tutorial",
                "url": "https://w3schools.com/html/default.asp",
                "snippet": "Learn HTML basics.",
            },
            {
                "title": "Critical DMARC and SPF authentication dropouts in production",
                "url": "https://devops-discuss.com/dmarc-dropouts",
                "snippet": "We faced recurring webhook and delivery failures when DMARC rejected outbound emails.",
            },
        ]
    }

    mock_client = MagicMock()
    mock_client.search.return_value = mock_payload

    adapter = WigoloDiscoverySource(client=mock_client)
    findings = adapter.search("deliverability")

    # Only the genuine problem discussion should survive; wikipedia and w3schools must be filtered
    assert len(findings) == 1
    assert "devops-discuss.com" in findings[0].url


# -------------------------------------------------------------------------
# TASK 3: Source Verification
# -------------------------------------------------------------------------

def test_source_verifier_relevant_search_result():
    """Verify relevant search result with pain signals is VERIFIED."""
    mock_client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {"content-type": "text/html"}
    resp.text = """
    <html>
        <head><title>Stripe Webhook Dropouts in Production</title></head>
        <body>
            <h1>Recurring Webhook Failures</h1>
            <p>Our payment gateway webhook retries are failing silently without automated error alerts, causing lost customer revenue.</p>
        </body>
    </html>
    """
    resp.url = httpx.URL("https://ops.example.com/stripe-webhook-failure")
    resp.history = []
    mock_client.get.return_value = resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    source = DiscoveredSource(
        source_name="wigolo",
        title="Stripe Webhook Dropouts",
        url="https://ops.example.com/stripe-webhook-failure",
        excerpt="Payment gateway webhook retries are failing silently.",
    )

    verified = verifier.verify(source, fetch_remote=True)
    assert verified.verification_status in (SourceVerificationStatus.FETCH_VERIFIED, SourceVerificationStatus.VERIFIED)
    assert verified.rejection_reason is None
    assert verified.http_status == 200
    assert "lost customer revenue" in verified.raw_content


def test_source_verifier_irrelevant_domains():
    """Verify generic educational or reference domains are rejected as IRRELEVANT."""
    researcher = PublicWebResearcher(check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    wiki_source = DiscoveredSource(
        source_name="wigolo",
        title="Software Testing Overview - Wikipedia",
        url="https://en.wikipedia.org/wiki/Software_testing",
        excerpt="Software testing is the act of checking whether software satisfies requirements.",
    )

    verified = verifier.verify(wiki_source, fetch_remote=False)
    assert verified.verification_status == SourceVerificationStatus.IRRELEVANT
    assert "wikipedia.org" in verified.rejection_reason


def test_source_verifier_404_http_error():
    """Verify HTTP 404 response is marked as HTTP_ERROR with exact rejection reason."""
    mock_client = MagicMock(spec=httpx.Client)
    resp_404 = MagicMock(spec=httpx.Response)
    resp_404.status_code = 404
    resp_404.url = httpx.URL("https://example.com/dead-link")
    resp_404.history = []
    mock_client.get.return_value = resp_404

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    source = DiscoveredSource(
        source_name="wigolo",
        title="Dead Link Discussion",
        url="https://example.com/dead-link",
        excerpt="Some discussion that moved.",
    )

    verified = verifier.verify(source, fetch_remote=True)
    assert verified.verification_status == SourceVerificationStatus.HTTP_ERROR
    assert verified.http_status == 404
    assert "404" in verified.rejection_reason


def test_source_verifier_redirects_resolved_and_recorded():
    """Verify redirects are resolved, original URL is preserved, and status is REDIRECTED_AND_VERIFIED."""
    mock_client = MagicMock(spec=httpx.Client)
    redirect_resp = MagicMock(spec=httpx.Response)
    redirect_resp.status_code = 301

    final_resp = MagicMock(spec=httpx.Response)
    final_resp.status_code = 200
    final_resp.headers = {"content-type": "text/html"}
    final_resp.text = """
    <html>
        <head><title>Cloud Billing Overruns - Canonical Post</title></head>
        <body>
            <p>Our startup encountered severe cloud billing surprises with orphaned disks and unattached IPs.</p>
        </body>
    </html>
    """
    final_resp.url = httpx.URL("https://canonical.com/posts/cloud-billing-waste")
    final_resp.history = [redirect_resp]
    mock_client.get.return_value = final_resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    source = DiscoveredSource(
        source_name="wigolo",
        title="Cloud Billing Waste",
        url="https://short.link/xyz",
        excerpt="Severe cloud billing surprises.",
    )

    verified = verifier.verify(source, fetch_remote=True)
    assert verified.verification_status == SourceVerificationStatus.REDIRECTED_AND_VERIFIED
    assert verified.original_url == "https://short.link/xyz"
    assert verified.url == "https://canonical.com/posts/cloud-billing-waste"
    assert verified.rejection_reason is None


def test_source_verifier_empty_pages_rejected():
    """Verify pages with empty static body are rejected as EMPTY_CONTENT."""
    mock_client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {"content-type": "text/html"}
    resp.text = "<html><head><title>App</title></head><body></body></html>"
    resp.url = httpx.URL("https://app.spa-shell.io/dashboard/report")
    resp.history = []
    mock_client.get.return_value = resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    source = DiscoveredSource(
        source_name="wigolo",
        title="SPA Shell Report",
        url="https://app.spa-shell.io/dashboard/report",
        excerpt="",
    )

    verified = verifier.verify(source, fetch_remote=True)
    assert verified.verification_status == SourceVerificationStatus.EMPTY_CONTENT
    assert "empty or negligible" in verified.rejection_reason.lower()


def test_source_verifier_missing_publication_date_never_fabricated():
    """Verify undated HTML does NOT invent publication dates, while dated HTML captures metadata."""
    # 1. Undated HTML
    extractor_undated = HTMLTextExtractor()
    extractor_undated.feed("<html><head><title>Undated Article</title></head><body><p>Content</p></body></html>")
    assert extractor_undated.published_date is None

    # 2. Dated HTML
    dated_html = """
    <html>
        <head>
            <title>Dated Article</title>
            <meta property="article:published_time" content="2026-03-25T14:30:00Z" />
        </head>
        <body><p>Content</p></body>
    </html>
    """
    extractor_dated = HTMLTextExtractor()
    extractor_dated.feed(dated_html)
    assert extractor_dated.published_date == "2026-03-25T14:30:00Z"


def test_source_verifier_misleading_titles_rejected():
    """Verify clickbait problem title is rejected as IRRELEVANT when page body lacks pain signals."""
    mock_client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {"content-type": "text/html"}
    # Body is generic marketing / corporate brochure with zero pain or problem discussion
    resp.text = """
    <html>
        <head><title>Disastrous Failure in Billing</title></head>
        <body>
            <h1>Welcome to Acme Cloud</h1>
            <p>We are a leading enterprise platform delivering excellence worldwide. Our mission is seamless partnership.</p>
        </body>
    </html>
    """
    resp.url = httpx.URL("https://acme.com/about")
    resp.history = []
    mock_client.get.return_value = resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    clickbait_source = DiscoveredSource(
        source_name="wigolo",
        title="Disastrous Failure in Billing",
        url="https://acme.com/about",
        excerpt="Disastrous failure report.",
    )

    verified = verifier.verify(clickbait_source, fetch_remote=True)
    assert verified.verification_status == SourceVerificationStatus.IRRELEVANT
    assert "lacks any b2b operational friction" in verified.rejection_reason.lower()


# -------------------------------------------------------------------------
# TASK 4: Evidence-Based Dynamic Confidence
# -------------------------------------------------------------------------

def test_static_confidence_removed_and_computed_dynamically():
    """Verify static 0.75 confidence is removed and computed dynamically based on provenance, pain, and recency."""
    # 1. High-quality, recent GitHub issue with strong pain signals and known author
    rich_source = DiscoveredSource(
        source_name="github_issues",
        title="Critical Stripe webhook failure and lost payment events",
        url="https://github.com/org/repo/issues/100",
        excerpt="Our webhook retries are dropping events during checkout spikes, causing lost revenue and manual reconciliation nightmare.",
        author="lead_dev",
        published_date="2026-05-01",
    )
    conf_rich, exp_rich = calculate_source_evidence_confidence(rich_source)
    assert conf_rich != 0.75
    assert conf_rich >= 0.75  # Rich, recent, strong signals receives high confidence (~0.78 - 0.82)
    assert "github_issues" in exp_rich
    assert "strong pain signals" in exp_rich

    # 2. Thin snippet with weak pain signals and no author
    weak_source = DiscoveredSource(
        source_name="wigolo",
        title="Integration note",
        url="https://blog.example/note",
        excerpt="There was an issue with api setup.",
        author="unknown",
        published_date=None,
    )
    conf_weak, exp_weak = calculate_source_evidence_confidence(weak_source)
    assert conf_weak != 0.75
    assert conf_weak < conf_rich  # Must be strictly lower than rich source!
    assert "thin excerpt" in exp_weak or "weak" in exp_weak

    # 3. Synthesizer records exact computed confidence and derivation explanation
    synthesizer = OpportunitySynthesizer()
    _, evidence_list = synthesizer.synthesize([rich_source], geography=Geography.IN)
    ev = next(e for e in evidence_list if e.source_url == rich_source.url)
    assert ev.confidence == conf_rich
    assert "Confidence derivation:" in ev.notes


# -------------------------------------------------------------------------
# TASK 5 & 6: Opportunity Synthesis, WTP & Independent Sources
# -------------------------------------------------------------------------

def test_wtp_remains_unknown_when_unsupported_by_public_sources():
    """Verify Willingness-to-Pay remains unvalidated (confidence 0.20, score 1) when discussions lack commercial spend signals."""
    forum_rant = DiscoveredSource(
        source_name="hn_algolia",
        title="Why is configuring SPF and DKIM such a nightmare?",
        url="https://news.ycombinator.com/item?id=554433",
        excerpt="Spent 6 hours fixing Google spam rejections on our domain. MX records are impossible.",
        author="frustrated_engineer",
    )

    synthesizer = OpportunitySynthesizer()
    offers, evidence = synthesizer.synthesize([forum_rant], geography=Geography.IN)

    assert len(offers) == 1
    offer = offers[0]

    # Verify WTP criterion
    wtp_score = offer.evaluation.criterion_scores[CriterionKey.WILLINGNESS_TO_PAY.value]
    assert wtp_score.score == 1  # 1 out of 5 for completely unvalidated commercial WTP
    assert "UNKNOWN / ZERO EMPIRICAL EVIDENCE" in wtp_score.rationale

    # Verify WTP evidence item
    wtp_ev = next(e for e in evidence if e.id in wtp_score.evidence_ids)
    assert wtp_ev.confidence == 0.20  # Explicitly low confidence for unknown hypothesis
    assert "UNKNOWN / ZERO EMPIRICAL EVIDENCE" in wtp_ev.notes

    # Verify candidate has validation unknowns listed
    assert len(offer.unknowns_requiring_validation) >= 2
    assert "willingness to pay" in offer.unknowns_requiring_validation[0].lower()


def test_wtp_recognizes_preliminary_budget_signals_without_fabricating_demand():
    """Verify preliminary commercial spend mentions adjust WTP hypothesis to 0.35, but keep candidate gated as NEEDS_MORE_EVIDENCE."""
    budget_mention = DiscoveredSource(
        source_name="hn_algolia",
        title="We are paying $800/month for a consultant to fix our DMARC bounces",
        url="https://news.ycombinator.com/item?id=778899",
        excerpt="We currently pay a monthly vendor budget for deliverability monitoring, but the tool is too expensive.",
        author="growth_director",
    )

    synthesizer = OpportunitySynthesizer()
    offers, evidence = synthesizer.synthesize([budget_mention], geography=Geography.US)

    offer = offers[0]
    wtp_score = offer.evaluation.criterion_scores[CriterionKey.WILLINGNESS_TO_PAY.value]
    assert wtp_score.score == 2  # Preliminary spend signal
    assert "Preliminary commercial budget mentions" in wtp_score.rationale

    wtp_ev = next(e for e in evidence if e.id in wtp_score.evidence_ids)
    assert wtp_ev.confidence == 0.35  # <= 0.50 hypothesis, acknowledging spend mention

    # Still strictly gated as NEEDS_MORE_EVIDENCE because 0.35 < 0.65 threshold!
    assert offer.evaluation.status == DecisionStatus.NEEDS_MORE_EVIDENCE


def test_multiple_independent_sources_count_and_severity_scoring():
    """Verify multiple independent sources across distinct domains/authors increase problem severity score."""
    sources = [
        DiscoveredSource(
            source_name="hn_algolia",
            title="DMARC reject failures on custom domain",
            url="https://news.ycombinator.com/item?id=101",
            excerpt="High bounce rates on outreach.",
            author="founder_alpha",
        ),
        DiscoveredSource(
            source_name="github_issues",
            title="SPF alignment broken after DNS provider migration",
            url="https://github.com/org1/repo/issues/12",
            excerpt="Google spam filters rejecting messages.",
            author="engineer_beta",
        ),
        DiscoveredSource(
            source_name="wigolo",
            title="Email authentication and spam placement report",
            url="https://deliverability-ops.org/case-study",
            excerpt="DMARC compliance friction across 50 domains.",
            author="ops_gamma",
        ),
    ]

    synthesizer = OpportunitySynthesizer()
    offers, _ = synthesizer.synthesize(sources, geography=Geography.IN)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.independent_report_count == 3

    # Problem severity score should be 5 for 3+ independent sources
    sev_score = offer.evaluation.criterion_scores[CriterionKey.PROBLEM_SEVERITY.value]
    assert sev_score.score == 5
    assert "3 independent sources" in sev_score.rationale


# -------------------------------------------------------------------------
# PHASE 1.2: Evidence Integrity Regression Tests (Task 6)
# -------------------------------------------------------------------------

def test_regression_1_destination_page_fetched_successfully():
    """Test 1: Destination page fetched successfully assigns FETCH_VERIFIED."""
    mock_client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {"content-type": "text/html"}
    resp.text = """
    <html>
        <head><title>Payment Gateway Webhook Retries Dropping</title></head>
        <body>
            <p>Our payment gateway webhook retries are failing silently without automated error alerts.</p>
        </body>
    </html>
    """
    resp.url = httpx.URL("https://ops.example.com/payment-dropouts")
    resp.history = []
    mock_client.get.return_value = resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    source = DiscoveredSource(
        source_name="wigolo",
        title="Payment Gateway Webhook Retries Dropping",
        url="https://ops.example.com/payment-dropouts",
        excerpt="Webhook retries failing silently.",
    )

    verified = verifier.verify(source, fetch_remote=True)
    assert verified.verification_status == SourceVerificationStatus.FETCH_VERIFIED
    assert verified.http_status == 200
    assert verified.raw_content is not None
    assert "webhook retries are failing silently" in verified.raw_content
    conf, expl = calculate_source_evidence_confidence(verified)
    assert conf >= 0.72
    assert "FETCH_VERIFIED" in expl


def test_regression_2_destination_unreachable_snippet_unfetched():
    """Test 2: Destination page unreachable but useful snippet available assigns SNIPPET_UNFETCHED and confidence <= 0.45."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    verifier = SourceVerifier(researcher=researcher)

    source = DiscoveredSource(
        source_name="wigolo",
        title="Cloud Billing Spike and Orphaned Disks",
        url="https://offline-dev-forum.internal/post/42",
        excerpt="We faced severe billing surprise when orphaned cloud volumes kept costing us without notice.",
    )

    verified = verifier.verify(source, fetch_remote=True)
    assert verified.verification_status == SourceVerificationStatus.SNIPPET_UNFETCHED
    assert verified.rejection_reason is None
    assert "unreached" in verified.metadata.get("network_note", "").lower()
    conf, expl = calculate_source_evidence_confidence(verified)
    assert conf <= 0.45
    assert "SNIPPET_UNFETCHED" in expl


def test_regression_3_official_api_verified_without_pretending_fetch():
    """Test 3: Official API response accepted with API_VERIFIED, api_provider, api_record_id."""
    hn_source = DiscoveredSource(
        source_name="hn_algolia",
        title="Ask HN: How do you handle DMARC compliance failures?",
        url="https://news.ycombinator.com/item?id=38472911",
        excerpt="We are seeing high bounce rates and SPF alignment errors on corporate outbound email.",
        author="hn_founder",
        verification_status=SourceVerificationStatus.API_VERIFIED,
        api_provider="hn_algolia",
        api_record_id="38472911",
    )
    conf, expl = calculate_source_evidence_confidence(hn_source)
    assert hn_source.verification_status == SourceVerificationStatus.API_VERIFIED
    assert hn_source.api_provider == "hn_algolia"
    assert hn_source.api_record_id == "38472911"
    assert 0.60 <= conf <= 0.80
    assert "API_VERIFIED" in expl


def test_regression_4_syndicated_duplicate_content_deduplication():
    """Test 4: Same syndicated content published on two different domains produces identical fingerprint."""
    title1 = "Dealing with Stripe Webhook Dropouts in High-Volume SaaS"
    snippet1 = "Our system experienced silent payment webhook dropouts resulting in unactivated user subscriptions."
    url1 = "https://techblog.alpha.com/posts/stripe-dropouts"

    title2 = "Dealing with Stripe Webhook Dropouts in High-Volume SaaS"
    snippet2 = "Our system experienced silent payment webhook dropouts resulting in unactivated user subscriptions."
    url2 = "https://syndicate-dev.org/mirror/stripe-dropouts"

    fp1 = compute_content_fingerprint(title1, snippet1)
    fp2 = compute_content_fingerprint(title2, snippet2)
    assert fp1 == fp2

    # In engine, discovery deduplicates syndicated content
    engine = AutonomousDiscoveryEngine(adapters=[])
    sources = [
        DiscoveredSource(source_name="wigolo", title=title1, url=url1, excerpt=snippet1),
        DiscoveredSource(source_name="wigolo", title=title2, url=url2, excerpt=snippet2),
    ]
    seen_hashes = set()
    unique_items = []
    for s in sources:
        h = compute_content_fingerprint(s.title, s.excerpt)
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_items.append(s)
    assert len(unique_items) == 1
    engine.close()


def test_regression_5_same_publisher_subdomains_collapse():
    """Test 5: Two articles from blog.acme.com and acme.com map to 1 publisher and do not inflate independent count."""
    org1, status1 = extract_publisher_organization("https://blog.acme.com/cloud-costs", author="dev")
    org2, status2 = extract_publisher_organization("https://acme.com/engineering/billing-leak", author="ops")

    assert org1 == "acme.com"
    assert org2 == "acme.com"
    assert status1 == "CONFIRMED"
    assert status2 == "CONFIRMED"

    # Synthesize offer with these two sources
    s1 = DiscoveredSource(
        source_name="wigolo",
        title="Cloud billing leak and unused instances",
        url="https://blog.acme.com/cloud-costs",
        excerpt="We discovered thousands in idle cloud EC2 spend.",
        publisher_org=org1,
        verification_status=SourceVerificationStatus.FETCH_VERIFIED,
    )
    s2 = DiscoveredSource(
        source_name="wigolo",
        title="Engineering retrospective on cloud waste",
        url="https://acme.com/engineering/billing-leak",
        excerpt="Idle dev servers caused significant budget overrun.",
        publisher_org=org2,
        verification_status=SourceVerificationStatus.FETCH_VERIFIED,
    )

    synthesizer = OpportunitySynthesizer()
    offers, _ = synthesizer.synthesize([s1, s2], geography=Geography.US)
    assert len(offers) == 1
    # Both from acme.com -> independent_report_count must be 1, NOT 2!
    assert offers[0].independent_report_count == 1


def test_regression_6_different_authors_on_multi_tenant_platform():
    """Test 6: Different authors on GitHub or HN count as distinct independent reports."""
    org_gh1, st1 = extract_publisher_organization("https://github.com/repo1/issues/10", author="alice", source_name="github_issues")
    org_gh2, st2 = extract_publisher_organization("https://github.com/repo2/issues/20", author="bob", source_name="github_issues")

    assert org_gh1 == "github:alice"
    assert org_gh2 == "github:bob"
    assert org_gh1 != org_gh2
    assert st1 == "CONFIRMED"
    assert st2 == "CONFIRMED"

    s1 = DiscoveredSource(
        source_name="github_issues",
        title="DMARC alignment failure",
        url="https://github.com/repo1/issues/10",
        excerpt="SPF broken after domain DNS update.",
        author="alice",
        publisher_org=org_gh1,
        verification_status=SourceVerificationStatus.API_VERIFIED,
    )
    s2 = DiscoveredSource(
        source_name="github_issues",
        title="DKIM key rotation broke outbound emails",
        url="https://github.com/repo2/issues/20",
        excerpt="Emails going to spam folder due to invalid signature.",
        author="bob",
        publisher_org=org_gh2,
        verification_status=SourceVerificationStatus.API_VERIFIED,
    )

    synthesizer = OpportunitySynthesizer()
    offers, _ = synthesizer.synthesize([s1, s2], geography=Geography.IN)
    assert len(offers) == 1
    assert offers[0].independent_report_count == 2


def test_regression_7_distinct_organizations_count_as_independent():
    """Test 7: Distinct organizations independently reporting the problem count as separate independent reports."""
    s1 = DiscoveredSource(
        source_name="wigolo",
        title="Payment reconciliation error in distribution logistics",
        url="https://logistics-firm.in/case-studies/reconciliation",
        excerpt="Manual spreadsheet reconciliation of invoice payouts creates massive delay.",
        author="cfo",
        publisher_org="logistics-firm.in",
        verification_status=SourceVerificationStatus.FETCH_VERIFIED,
    )
    s2 = DiscoveredSource(
        source_name="wigolo",
        title="Vendor payout reconciliation bottlenecks in healthcare",
        url="https://med-supply.co.in/tech/invoice-friction",
        excerpt="Manual copy-pasting across disparate spreadsheets caused accounting errors.",
        author="ops_lead",
        publisher_org="med-supply.co.in",
        verification_status=SourceVerificationStatus.FETCH_VERIFIED,
    )

    synthesizer = OpportunitySynthesizer()
    offers, _ = synthesizer.synthesize([s1, s2], geography=Geography.IN)
    assert len(offers) == 1
    assert offers[0].independent_report_count == 2


def test_regression_8_missing_publisher_labeled_unknown():
    """Test 8: Missing publisher/author metadata on multi-tenant or shorteners labeled as UNKNOWN independence."""
    org1, status1 = extract_publisher_organization("https://news.ycombinator.com/item?id=999", author=None, source_name="hn_algolia")
    org2, status2 = extract_publisher_organization("https://bit.ly/3xyz123", author=None)

    assert org1 is None
    assert status1 == "UNKNOWN"
    assert org2 is None
    assert status2 == "UNKNOWN"


def test_regression_9_duplicate_urls_with_tracking_parameters():
    """Test 9: URLs with tracking parameters (utm_*, ref, gclid) normalize to identical canonical URL."""
    u1 = "https://ops.example.com/billing-leak?utm_source=twitter&utm_medium=social"
    u2 = "https://ops.example.com/billing-leak?ref=newsletter&gclid=12345"
    u3 = "https://ops.example.com/billing-leak/"

    norm1 = normalize_url(u1)
    norm2 = normalize_url(u2)
    norm3 = normalize_url(u3)

    assert norm1 == norm2 == norm3 == "https://ops.example.com/billing-leak"


def test_regression_10_snippet_only_evidence_cannot_inflate_independent_count():
    """Test 10: Synthesize an offer with 1 fetched report and 3 snippet-only reports.
    Assert independent_report_count == 1 (not 4).
    Assert unknown_independence_count == 3.
    """
    fetched_source = DiscoveredSource(
        source_name="wigolo",
        title="Cloud cost spikes from unattached EBS volumes",
        url="https://devops-journal.io/ebs-leak",
        excerpt="We discovered thousands of dollars in detached volumes billing each month.",
        author="sysadmin",
        publisher_org="devops-journal.io",
        verification_status=SourceVerificationStatus.FETCH_VERIFIED,
    )

    snippets = [
        DiscoveredSource(
            source_name="wigolo",
            title=f"Cloud billing friction snippet {i}",
            url=f"https://snippet-host-{i}.org/post/{i}",
            excerpt="Cloud billing cost overrun spike surprise.",
            author=f"user_{i}",
            publisher_org=f"snippet-host-{i}.org",
            verification_status=SourceVerificationStatus.SNIPPET_UNFETCHED,
        )
        for i in range(1, 4)
    ]

    all_sources = [fetched_source] + snippets
    synthesizer = OpportunitySynthesizer()
    offers, _ = synthesizer.synthesize(all_sources, geography=Geography.US)

    assert len(offers) == 1
    offer = offers[0]
    # Exactly as specified: independent_report_count must be 1 (not 4), unknown_independence_count must be 3
    assert offer.independent_report_count == 1
    assert offer.unknown_independence_count == 3


def test_regression_11_backward_compatibility_db_records(tmp_path):
    """Test 11: Database save_offer and get_offer handle offers with new and legacy fields gracefully."""
    db_file = tmp_path / "test_compat.db"
    db = Database(str(db_file))

    offer = OfferCandidate(
        id="off_test_compat_01",
        title="B2B Email Deliverability Audit",
        target_geography=Geography.IN,
        buyer_profile="Founders and Sales Ops",
        problem_statement="Reported inbox placement failures and SPF/DKIM authentication errors.",
        proposed_deliverable="A 48-hour diagnostic audit checklist for email deliverability.",
        plausible_pricing_or_pilot="Zero-fee pilot audit.",
        delivery_method="Remote asynchronous inspection.",
        risks=["WTP unvalidated."],
        evidence_ids=[],
        independent_report_count=2,
        unknown_independence_count=1,
    )

    db.save_offer(offer, actor="AGENT")
    loaded = db.get_offer("off_test_compat_01")

    assert loaded is not None
    assert loaded.id == "off_test_compat_01"
    assert loaded.independent_report_count == 2
    assert loaded.unknown_independence_count == 1

