"""
Public web research client for Project ZERO.

Strictly operates within the INR 0 operating budget target.
Enforces safety rules:
- Respects robots.txt directives and per-domain rate limits.
- Uses an explicit, identifying research User-Agent.
- Rejects prohibited platforms (e.g., LinkedIn scraping/automation).
- Avoids login bypasses, paywalls, and unauthorized access.
- Accurately captures retrieved text, timestamp, and supporting excerpts.
- Distinguishes URL availability from claim verification.
- Accurately reports inaccessible pages, timeouts, and retrieval errors.
"""

import html.parser
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
import urllib.robotparser

import httpx

from zero.schemas import (
    Evidence,
    EvidenceType,
    FetchStatus,
    Geography,
    ResearchExcerpt,
)

DEFAULT_USER_AGENT = (
    "ProjectZeroBot/0.2 (Research Agent; +https://github.com/narendrareddy06/Project---ZERO-; INR 0 budget research)"
)
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_REQUEST_DELAY_SECONDS = 1.0


class HTMLTextExtractor(html.parser.HTMLParser):
    """Cleanly extracts human-readable text and title from HTML without heavy external deps."""

    def __init__(self):
        super().__init__()
        self._pieces: List[str] = []
        self._in_ignored_tag = False
        self._ignored_tags = {"script", "style", "svg", "noscript"}
        self.title: Optional[str] = None
        self._in_title = False
        self.has_password_field = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_lower = tag.lower()
        if tag_lower in self._ignored_tags:
            self._in_ignored_tag = True
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower == "input":
            attrs_dict = {k.lower(): (v.lower() if v else "") for k, v in attrs}
            if attrs_dict.get("type") == "password":
                self.has_password_field = True

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in self._ignored_tags:
            self._in_ignored_tag = False
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower in {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"}:
            self._pieces.append("\n")

    def handle_data(self, data: str):
        if self._in_title:
            cleaned = data.strip()
            if cleaned:
                self.title = cleaned if not self.title else f"{self.title} {cleaned}"
        elif not self._in_ignored_tag:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self._pieces)
        # Normalize whitespace while preserving line structure
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw_text.splitlines()]
        clean_lines = [line for line in lines if line]
        return "\n".join(clean_lines)


class PublicWebResearcher:
    """
    Polite, rule-compliant public web researcher.
    Conducts read-only factual discovery at zero marginal financial cost.
    """

    def __init__(
        self,
        client: Optional[httpx.Client] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        request_delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
        check_robots: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.user_agent = user_agent
        self.request_delay = request_delay
        self.check_robots = check_robots
        self.timeout = timeout
        self._client = client or httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._robots_cache: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_domain_request: Dict[str, float] = {}

    def close(self):
        """Close the underlying HTTP client session."""
        self._client.close()

    def check_url_permissions(self, url: str) -> Tuple[bool, str, FetchStatus]:
        """
        Validates URL against safety rules:
        - Scheme must be http or https
        - Prohibits LinkedIn scraping (per AGENTS.md)
        - Checks robots.txt directives
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported scheme '{parsed.scheme}': only http and https are permitted.", FetchStatus.BLOCKED_DOMAIN

        domain = parsed.netloc.lower()
        if "linkedin.com" in domain:
            return (
                False,
                "LinkedIn discovery, scraping, and automation are strictly prohibited by Project ZERO safety rules (AGENTS.md).",
                FetchStatus.BLOCKED_DOMAIN,
            )

        if not self.check_robots:
            return True, "Robots checking disabled", FetchStatus.SUCCESS

        # Check robots.txt for domain
        robots_parser = self._get_robots_parser(parsed.scheme, parsed.netloc)
        if robots_parser and not robots_parser.can_fetch(self.user_agent, url):
            return False, f"Access disallowed by robots.txt on {parsed.netloc}", FetchStatus.ROBOTS_DISALLOWED

        return True, "Permitted", FetchStatus.SUCCESS

    def _get_robots_parser(self, scheme: str, netloc: str) -> Optional[urllib.robotparser.RobotFileParser]:
        """Fetches and caches robots.txt for a domain, handling failures gracefully."""
        domain_key = f"{scheme}://{netloc}"
        if domain_key in self._robots_cache:
            return self._robots_cache[domain_key]

        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{domain_key}/robots.txt"
        rp.set_url(robots_url)
        try:
            resp = self._client.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif resp.status_code in (401, 403):
                # If robots.txt is forbidden, default to disallowing access
                rp.disallow_all = True
            else:
                # 404 or other errors typically allow fetching per standard convention
                rp.allow_all = True
        except Exception:
            # On network/connection error reading robots.txt, proceed cautiously or allow
            rp.allow_all = True

        self._robots_cache[domain_key] = rp
        return rp

    def _rate_limit(self, domain: str):
        """Enforces polite inter-request delay per domain."""
        now = time.time()
        last = self._last_domain_request.get(domain, 0.0)
        elapsed = now - last
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_domain_request[domain] = time.time()

    def fetch_page(self, url: str) -> Tuple[FetchStatus, Optional[str], Optional[str], int, str]:
        """
        Fetches a public web page with rate limiting and error handling.
        Returns: (status, page_title, page_clean_text, http_status_code, error_or_info_message)
        """
        allowed, reason, status = self.check_url_permissions(url)
        if not allowed:
            return status, None, None, 0, reason

        parsed = urlparse(url)
        self._rate_limit(parsed.netloc.lower())

        try:
            resp = self._client.get(url)
        except httpx.ConnectTimeout:
            return FetchStatus.TIMEOUT, None, None, 0, f"Connection timed out after {self.timeout}s"
        except httpx.ConnectError as e:
            return FetchStatus.CONNECTION_FAILED, None, None, 0, f"Connection failed: {str(e)}"
        except httpx.RequestError as e:
            return FetchStatus.CONNECTION_FAILED, None, None, 0, f"Request error: {str(e)}"
        except Exception as e:
            return FetchStatus.CONNECTION_FAILED, None, None, 0, f"Unexpected retrieval failure: {str(e)}"

        status_code = resp.status_code
        if status_code >= 400:
            return FetchStatus.HTTP_ERROR, None, None, status_code, f"HTTP {status_code} error response"

        content_type = resp.headers.get("content-type", "").lower()
        if content_type and "text/html" not in content_type and "application/xhtml" not in content_type:
            return FetchStatus.NON_HTML, None, None, status_code, f"Non-HTML content type: {content_type}"

        # Parse HTML text
        parser = HTMLTextExtractor()
        try:
            parser.feed(resp.text)
        except Exception as e:
            return FetchStatus.NON_HTML, None, None, status_code, f"HTML parsing error: {str(e)}"

        # Detect paywalls or mandatory login forms
        if parser.has_password_field:
            return (
                FetchStatus.LOGIN_OR_PAYWALL_DETECTED,
                parser.title,
                None,
                status_code,
                "Password field detected; page requires authentication.",
            )

        clean_text = parser.get_text()
        lower_text = clean_text.lower()
        paywall_phrases = ["subscribe to continue reading", "please sign in to view", "login to access this content"]
        for phrase in paywall_phrases:
            if phrase in lower_text and len(clean_text) < 1000:
                return (
                    FetchStatus.LOGIN_OR_PAYWALL_DETECTED,
                    parser.title,
                    None,
                    status_code,
                    f"Paywall or gate detected ('{phrase}').",
                )

        return FetchStatus.SUCCESS, parser.title, clean_text, status_code, "Successfully retrieved"

    def extract_supporting_excerpt(
        self,
        page_text: str,
        claim: str,
        max_length: int = 400,
    ) -> Tuple[bool, Optional[str], str]:
        """
        Searches page text for excerpts that factually corroborate or contradict the claim.
        Returns: (supports_claim, excerpt, rationale)
        """
        if not page_text or not claim:
            return False, None, "Empty text or claim provided"

        # Extract informative keywords from claim (skip short stop words)
        words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", claim.lower())
        stop_words = {
            "the", "and", "for", "with", "that", "this", "from", "are", "have", "has",
            "not", "our", "will", "can", "been", "more", "into", "their", "about",
        }
        keywords = [w for w in words if w not in stop_words]

        if not keywords:
            return False, None, "Claim contains no substantive keywords for matching"

        # Split page into paragraphs or sentences
        paragraphs = [p.strip() for p in page_text.split("\n") if len(p.strip()) > 30]

        best_para: Optional[str] = None
        best_score = 0
        matched_keywords: List[str] = []

        for para in paragraphs:
            para_lower = para.lower()
            para_matches = [kw for kw in keywords if kw in para_lower]
            score = len(para_matches)
            if score > best_score:
                best_score = score
                best_para = para
                matched_keywords = para_matches

        # Requirement: At least 2 key terms or >= 40% of key terms must match to consider it supported
        min_matches = min(2, len(keywords))
        if best_score >= min_matches and best_para:
            excerpt = best_para
            if len(excerpt) > max_length:
                # Trim cleanly to max_length around first keyword match
                first_kw = matched_keywords[0]
                idx = excerpt.lower().find(first_kw)
                start = max(0, idx - 100)
                end = min(len(excerpt), start + max_length)
                excerpt = ("..." if start > 0 else "") + excerpt[start:end].strip() + ("..." if end < len(excerpt) else "")
            
            # Check for negation or contradiction indicators
            contradiction_terms = ["not", "fails to", "disproved", "contrary to", "however", "no evidence", "untrue"]
            para_lower = best_para.lower()
            is_contradictory = any(term in para_lower for term in contradiction_terms if term in para_lower)
            
            if is_contradictory and any(kw in para_lower for kw in matched_keywords):
                return False, excerpt, f"Excerpts discuss topics ({', '.join(matched_keywords)}) but contain contradiction or qualification indicators."

            return True, excerpt, f"Supported by matching keywords: {', '.join(matched_keywords)}"

        return False, None, f"Page content does not substantiate claim. Found {best_score}/{len(keywords)} matching keywords."

    def research_and_extract(
        self,
        url: str,
        claim: str,
        geography: Geography = Geography.IN,
        is_sample: bool = False,
    ) -> Tuple[ResearchExcerpt, Evidence]:
        """
        Executes a complete research retrieval workflow for an explicit claim:
        1. Validates permissions and robots.txt.
        2. Retrieves the page.
        3. Attempts to extract supporting excerpt.
        4. Accurately classifies evidence:
           - VERIFIED_SOURCE if genuine excerpt corroborates the claim.
           - CONFLICTING_OR_INSUFFICIENT if retrieval failed, paywalled, or contradictory.
           - HYPOTHESIS if URL exists but content does not substantiate the claim.
        """
        retrieved_at = datetime.now(timezone.utc)
        status, title, clean_text, http_code, message = self.fetch_page(url)

        if status != FetchStatus.SUCCESS or not clean_text:
            # Failed or inaccessible retrieval: accurately recorded as CONFLICTING_OR_INSUFFICIENT
            excerpt_obj = ResearchExcerpt(
                source_url=url,
                retrieved_at=retrieved_at,
                http_status=http_code,
                title=title,
                excerpt=f"[RETRIEVAL FAILED] {message} (Status: {status.value})",
                supports_claim=False,
                relevance_notes=message,
                is_conflicting=True,
            )
            evidence_obj = Evidence(
                id=f"ev_res_{int(retrieved_at.timestamp())}",
                claim=claim,
                evidence_type=EvidenceType.CONFLICTING_OR_INSUFFICIENT,
                geography=geography,
                confidence=0.10,
                source_url=url,
                captured_at=retrieved_at,
                retrieved_at=retrieved_at,
                excerpt=excerpt_obj.excerpt,
                notes=f"Inaccessible or blocked source: {message}",
                is_sample=is_sample,
            )
            return excerpt_obj, evidence_obj

        # Page fetched successfully: now test claim support against contents
        supports, excerpt, notes = self.extract_supporting_excerpt(clean_text, claim)

        if supports and excerpt:
            excerpt_obj = ResearchExcerpt(
                source_url=url,
                retrieved_at=retrieved_at,
                http_status=http_code,
                title=title,
                excerpt=excerpt,
                supports_claim=True,
                relevance_notes=notes,
                is_conflicting=False,
            )
            evidence_obj = Evidence(
                id=f"ev_res_{int(retrieved_at.timestamp())}",
                claim=claim,
                evidence_type=EvidenceType.VERIFIED_SOURCE,
                geography=geography,
                confidence=0.85,
                source_url=url,
                captured_at=retrieved_at,
                retrieved_at=retrieved_at,
                excerpt=excerpt,
                notes=f"Corroborated by public source content: {notes}",
                is_sample=is_sample,
            )
        else:
            # URL is valid and accessible, but contents DO NOT substantiate the claim!
            # Must NOT classify as VERIFIED_SOURCE!
            excerpt_obj = ResearchExcerpt(
                source_url=url,
                retrieved_at=retrieved_at,
                http_status=http_code,
                title=title,
                excerpt=excerpt or f"[UNSUPPORTED] Content does not contain corroborating data for claim.",
                supports_claim=False,
                relevance_notes=notes,
                is_conflicting=False,
            )
            evidence_obj = Evidence(
                id=f"ev_res_{int(retrieved_at.timestamp())}",
                claim=claim,
                evidence_type=EvidenceType.HYPOTHESIS,
                geography=geography,
                confidence=0.40,  # <= 0.50 for hypothesis
                source_url=url,
                captured_at=retrieved_at,
                retrieved_at=retrieved_at,
                excerpt=excerpt_obj.excerpt,
                notes=f"URL retrieved successfully (HTTP {http_code}), but page text does not substantiate claim: {notes}",
                is_sample=is_sample,
            )

        return excerpt_obj, evidence_obj
