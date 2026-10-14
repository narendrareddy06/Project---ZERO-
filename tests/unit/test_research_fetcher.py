"""Tests for PublicWebResearcher in Stage B."""

import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from zero.research.fetcher import (
    FetchStatus,
    HTMLTextExtractor,
    PublicWebResearcher,
)
from zero.schemas import EvidenceType, Geography


def test_html_text_extractor_clean_text_and_title():
    html_content = """
    <html>
        <head><title>SaaS Benchmark Report 2026</title></head>
        <body>
            <script>console.log("ignore me");</script>
            <style>.body { color: red; }</style>
            <h1>Key Industry Findings</h1>
            <p>Over 74% of mid-market B2B software agencies report high CAC in 2026.</p>
        </body>
    </html>
    """
    extractor = HTMLTextExtractor()
    extractor.feed(html_content)
    assert extractor.title == "SaaS Benchmark Report 2026"
    text = extractor.get_text()
    assert "Key Industry Findings" in text
    assert "74% of mid-market B2B software agencies report high CAC" in text
    assert "ignore me" not in text
    assert "color: red" not in text


def test_fetcher_rejects_linkedin_scraping():
    researcher = PublicWebResearcher(check_robots=False)
    allowed, reason, status = researcher.check_url_permissions("https://www.linkedin.com/in/someuser")
    assert not allowed
    assert status == FetchStatus.BLOCKED_DOMAIN
    assert "LinkedIn" in reason
    assert "prohibited" in reason


def test_fetcher_rejects_non_http_schemes():
    researcher = PublicWebResearcher(check_robots=False)
    allowed, reason, status = researcher.check_url_permissions("ftp://example.com/data")
    assert not allowed
    assert status == FetchStatus.BLOCKED_DOMAIN
    assert "Unsupported scheme" in reason


def test_fetcher_respects_robots_txt_disallowed():
    mock_client = MagicMock(spec=httpx.Client)
    # Mock robots.txt response disallowing /private
    robots_response = MagicMock(spec=httpx.Response)
    robots_response.status_code = 200
    robots_response.text = "User-agent: *\nDisallow: /private/"
    mock_client.get.return_value = robots_response

    researcher = PublicWebResearcher(client=mock_client, check_robots=True, request_delay=0.0)
    allowed, reason, status = researcher.check_url_permissions("https://example.com/private/data.html")
    assert not allowed
    assert status == FetchStatus.ROBOTS_DISALLOWED
    assert "robots.txt" in reason


def test_fetcher_handles_http_errors_honestly():
    mock_client = MagicMock(spec=httpx.Client)
    # Mock 404 response
    resp_404 = MagicMock(spec=httpx.Response)
    resp_404.status_code = 404
    mock_client.get.return_value = resp_404

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    status, title, clean_text, http_code, msg = researcher.fetch_page("https://example.com/nonexistent")
    assert status == FetchStatus.HTTP_ERROR
    assert http_code == 404
    assert clean_text is None
    assert "404" in msg


def test_fetcher_handles_timeout_and_connection_errors():
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    status, title, clean_text, http_code, msg = researcher.fetch_page("https://timeout.example.com")
    assert status == FetchStatus.TIMEOUT
    assert clean_text is None
    assert "timed out" in msg


def test_fetcher_extracts_supporting_excerpt_and_verifies_claim():
    mock_client = MagicMock(spec=httpx.Client)
    page_resp = MagicMock(spec=httpx.Response)
    page_resp.status_code = 200
    page_resp.headers = {"content-type": "text/html"}
    page_resp.text = """
    <html>
        <head><title>B2B Market Insights</title></head>
        <body>
            <p>Our comprehensive research found that outbound sales development teams face significant customer acquisition cost inflation.</p>
            <p>Specifically, mid-market B2B software agencies report high CAC and slow sales cycles.</p>
        </body>
    </html>
    """
    mock_client.get.return_value = page_resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    claim = "B2B software agencies report high CAC and slow sales cycles"
    excerpt_obj, ev_obj = researcher.research_and_extract(
        url="https://example.com/report",
        claim=claim,
        geography=Geography.IN,
        is_sample=False,
    )

    assert excerpt_obj.supports_claim is True
    assert "mid-market B2B software agencies report high CAC" in excerpt_obj.excerpt
    assert ev_obj.evidence_type == EvidenceType.VERIFIED_SOURCE
    assert ev_obj.confidence >= 0.80
    assert ev_obj.source_url == "https://example.com/report"
    assert ev_obj.excerpt is not None
    assert ev_obj.retrieved_at is not None


def test_unsupported_claim_remains_hypothesis():
    mock_client = MagicMock(spec=httpx.Client)
    page_resp = MagicMock(spec=httpx.Response)
    page_resp.status_code = 200
    page_resp.headers = {"content-type": "text/html"}
    # The page content has nothing to do with the claim
    page_resp.text = """
    <html>
        <head><title>Baking Sourdough Bread</title></head>
        <body>
            <p>To bake the perfect loaf of sourdough bread, maintain your yeast culture at 24 degrees Celsius.</p>
            <p>Flour, water, and salt are the foundational ingredients.</p>
        </body>
    </html>
    """
    mock_client.get.return_value = page_resp

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    claim = "B2B software agencies report high CAC and slow sales cycles"
    excerpt_obj, ev_obj = researcher.research_and_extract(
        url="https://example.com/recipes/bread",
        claim=claim,
        geography=Geography.IN,
        is_sample=False,
    )

    # Even though HTTP status was 200, contents do NOT support the claim!
    assert excerpt_obj.supports_claim is False
    assert ev_obj.evidence_type == EvidenceType.HYPOTHESIS
    assert ev_obj.confidence <= 0.50
    assert "does not substantiate claim" in ev_obj.notes


def test_failed_retrieval_records_insufficient_evidence():
    mock_client = MagicMock(spec=httpx.Client)
    resp_500 = MagicMock(spec=httpx.Response)
    resp_500.status_code = 500
    mock_client.get.return_value = resp_500

    researcher = PublicWebResearcher(client=mock_client, check_robots=False, request_delay=0.0)
    claim = "B2B software agencies report high CAC"
    excerpt_obj, ev_obj = researcher.research_and_extract(
        url="https://example.com/broken-page",
        claim=claim,
        geography=Geography.IN,
        is_sample=False,
    )

    assert excerpt_obj.supports_claim is False
    assert excerpt_obj.is_conflicting is True
    assert ev_obj.evidence_type == EvidenceType.CONFLICTING_OR_INSUFFICIENT
    assert ev_obj.confidence <= 0.20
    assert "[RETRIEVAL FAILED]" in ev_obj.excerpt
