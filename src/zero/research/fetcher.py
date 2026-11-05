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
    DiscoveredSource,
    Evidence,
    EvidenceType,
    FetchStatus,
    Geography,
    ResearchExcerpt,
    SourceVerificationStatus,
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
        self.meta_description: Optional[str] = None
        self.published_date: Optional[str] = None
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
        elif tag_lower == "time":
            attrs_dict = {k.lower(): (v.strip() if v else "") for k, v in attrs}
            dt = attrs_dict.get("datetime", "")
            if dt and not self.published_date:
                self.published_date = dt
        elif tag_lower == "meta":
            attrs_dict = {k.lower(): (v if v else "") for k, v in attrs}
            name_val = attrs_dict.get("name", "").lower()
            prop_val = attrs_dict.get("property", "").lower()
            itemprop_val = attrs_dict.get("itemprop", "").lower()
            content_val = attrs_dict.get("content", "").strip()

            if name_val == "description" or prop_val == "og:description":
                if content_val and not self.meta_description:
                    self.meta_description = content_val

            # Authentic publication date extraction from standard HTML metadata
            date_meta_keys = {
                "article:published_time", "og:published_time", "date", "pubdate",
                "publication_date", "sailthru.date", "parsely-pub-date",
            }
            if (name_val in date_meta_keys or prop_val in date_meta_keys or itemprop_val == "datepublished") and content_val:
                if not self.published_date:
                    self.published_date = content_val

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
        self.last_meta_description: Optional[str] = None
        self.last_final_url: Optional[str] = None
        self.last_was_redirected: bool = False
        self.last_published_date: Optional[str] = None

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

        self.last_final_url = str(resp.url) if hasattr(resp, "url") and resp.url else url
        self.last_was_redirected = bool(getattr(resp, "history", None))

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

        self.last_meta_description = parser.meta_description
        self.last_published_date = getattr(parser, "published_date", None)

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

        # 1. Genuine retrieval failure (HTTP error, connection error, timeout, robots disallowed, paywall/auth wall)
        if status != FetchStatus.SUCCESS:
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

        # 2. Retrieval succeeded (HTTP 200), but no readable static body text was extracted
        # (e.g. client-side JavaScript Single Page Application shell or empty body)
        if not clean_text or not clean_text.strip():
            meta_desc = getattr(self, "last_meta_description", None)
            if meta_desc:
                excerpt_msg = (
                    f"[NO STATIC TEXT] Page retrieved successfully, but no readable static body text was extracted. "
                    f"Public metadata description: \"{meta_desc}\""
                )
                relevance = (
                    f"Page retrieved successfully (HTTP {http_code}), but body contains no readable static text "
                    f"(client-side JavaScript application shell or empty body). "
                    f"Metadata description noted, but cannot corroborate arbitrary claims without page body content."
                )
            else:
                excerpt_msg = "[NO STATIC TEXT] Page retrieved successfully, but no readable static body text was extracted."
                relevance = (
                    f"Page retrieved successfully (HTTP {http_code}), but body contains no readable static text "
                    f"(client-side JavaScript application shell or empty body)."
                )

            excerpt_obj = ResearchExcerpt(
                source_url=url,
                retrieved_at=retrieved_at,
                http_status=http_code,
                title=title,
                excerpt=excerpt_msg,
                supports_claim=False,
                relevance_notes=relevance,
                is_conflicting=False,
            )
            evidence_obj = Evidence(
                id=f"ev_res_{int(retrieved_at.timestamp())}",
                claim=claim,
                evidence_type=EvidenceType.HYPOTHESIS,
                geography=geography,
                confidence=0.30,  # <= 0.50 hypothesis cap, unverified
                source_url=url,
                captured_at=retrieved_at,
                retrieved_at=retrieved_at,
                excerpt=excerpt_obj.excerpt,
                notes=relevance,
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


class SourceVerifier:
    """
    Verifies discovered public sources for Project ZERO.

    Enforces Task 3 verification rules:
    - Preserves original discovered URL.
    - Resolves redirects and records final canonical URL.
    - Retrieves actual page content.
    - Checks HTTP status and extraction success.
    - Identifies authentic publication date if available (never fabricates).
    - Rejects irrelevant or empty pages and stores exact rejection reason.
    - Assigns explicit SourceVerificationStatus.
    """

    IRRELEVANT_DOMAINS = {
        "wikipedia.org",
        "w3schools.com",
        "dictionary.com",
        "investopedia.com",
        "coursera.org",
        "udemy.com",
        "policies.google.com",
        "support.apple.com",
        "support.google.com",
    }

    BUSINESS_PAIN_SIGNALS = {
        "error", "errors", "fail", "failed", "failing", "failure", "failures",
        "problem", "problems", "issue", "issues", "bug", "bugs",
        "manual", "manually", "reconcil", "reconciliation", "bottleneck", "bottlenecks",
        "broken", "slow", "delay", "delays", "friction", "drop", "dropped", "dropouts",
        "cost", "costs", "billing", "expensive", "waste", "struggle", "struggling",
        "nightmare", "overspend", "overrun", "churn", "complaint", "complaints",
        "headache", "leak", "vulnerability", "lost deals", "lost revenue", "bounce",
        "bounces", "spam", "inbox placement", "sync error", "outage", "timeout",
        "downtime", "backlog", "unattached", "orphaned", "discrepanc",
    }

    def __init__(self, researcher: Optional[PublicWebResearcher] = None):
        self.researcher = researcher or PublicWebResearcher(check_robots=True)
        self._owns_researcher = researcher is None

    def close(self):
        if self._owns_researcher and self.researcher:
            self.researcher.close()

    def verify(
        self,
        source: DiscoveredSource,
        fetch_remote: bool = True,
    ) -> DiscoveredSource:
        """
        Verify a single discovered source. Updates source fields and returns it.
        """
        # 1. Preserve original URL before any redirection
        if not source.original_url:
            source.original_url = source.url

        # 2. Check for irrelevant reference/educational domains upfront
        parsed = urlparse(source.url)
        netloc = parsed.netloc.lower()
        if any(bad in netloc for bad in self.IRRELEVANT_DOMAINS):
            source.verification_status = SourceVerificationStatus.IRRELEVANT
            source.rejection_reason = (
                f"Generic reference or educational domain '{netloc}' lacks empirical B2B customer problem signals"
            )
            return source

        # Check for generic root homepages without problem discussion in path or title
        clean_path = parsed.path.strip("/")
        if not clean_path and not any(sig in source.title.lower() for sig in self.BUSINESS_PAIN_SIGNALS):
            source.verification_status = SourceVerificationStatus.IRRELEVANT
            source.rejection_reason = "Generic corporate root homepage without explicit business problem discussion"
            return source

        # 3. If status already explicitly established (e.g., pre-verified mock), return
        if source.verification_status is not None:
            return source

        # 4. Remote content retrieval and verification
        if fetch_remote and source.url.startswith(("http://", "https://")):
            status, title, clean_text, http_code, msg = self.researcher.fetch_page(source.url)
            source.http_status = http_code

            # Resolve redirects
            final_url = self.researcher.last_final_url or source.url
            was_redirected = self.researcher.last_was_redirected or (final_url != source.original_url)
            source.url = final_url

            # Extract authentic publication date from page metadata if available and not yet set
            if self.researcher.last_published_date and not source.published_date:
                source.published_date = self.researcher.last_published_date

            if status in (FetchStatus.TIMEOUT, FetchStatus.CONNECTION_FAILED):
                # If network connection/DNS fails (e.g. offline sandbox or unreached host),
                # check if the source already has a valid extracted snippet with authentic pain signals.
                # Task 1 & Task 6 rule: Snippet-only fallback must NEVER be classified as FETCH_VERIFIED or VERIFIED.
                content_text = source.raw_content or source.excerpt or ""
                if len(content_text.strip()) >= 20:
                    text_to_check = f"{source.title} {content_text}".lower()
                    matched_signals = [sig for sig in self.BUSINESS_PAIN_SIGNALS if sig in text_to_check]
                    if matched_signals:
                        source.verification_status = SourceVerificationStatus.SNIPPET_UNFETCHED
                        source.rejection_reason = None
                        source.metadata["network_note"] = f"Network unreached ({msg}); preserved search snippet for discovery (unfetched)"
                        return source

                source.verification_status = SourceVerificationStatus.UNAVAILABLE
                source.rejection_reason = f"Connection failed or timed out: {msg}"
                return source

            if status == FetchStatus.HTTP_ERROR:
                source.verification_status = SourceVerificationStatus.HTTP_ERROR
                source.rejection_reason = f"HTTP {http_code} error response"
                return source

            if status in (FetchStatus.ROBOTS_DISALLOWED, FetchStatus.BLOCKED_DOMAIN):
                source.verification_status = SourceVerificationStatus.UNAVAILABLE
                source.rejection_reason = msg
                return source

            if status == FetchStatus.LOGIN_OR_PAYWALL_DETECTED:
                source.verification_status = SourceVerificationStatus.NEEDS_MANUAL_REVIEW
                source.rejection_reason = f"Authentication or paywall detected: {msg}"
                return source

            if not clean_text or len(clean_text.strip()) < 50:
                source.verification_status = SourceVerificationStatus.EMPTY_CONTENT
                source.rejection_reason = "Page body has empty or negligible static text content (< 50 characters)"
                return source

            # Check for authentic business problem signals in retrieved body text (rejects misleading clickbait titles)
            source.raw_content = clean_text
            matched_signals = [sig for sig in self.BUSINESS_PAIN_SIGNALS if sig in clean_text.lower()]

            if not matched_signals:
                source.verification_status = SourceVerificationStatus.IRRELEVANT
                source.rejection_reason = (
                    "Retrieved content body lacks any B2B operational friction, error, or business pain signals "
                    "(title may be misleading, promotional, or clickbait)"
                )
                return source

            # Enrich excerpt from content if original snippet was short
            if len(source.excerpt.strip()) < 80:
                paras = [p.strip() for p in clean_text.split("\n") if len(p.strip()) > 40]
                for p in paras:
                    if any(sig in p.lower() for sig in self.BUSINESS_PAIN_SIGNALS):
                        source.excerpt = p[:500]
                        break

            source.verification_status = (
                SourceVerificationStatus.REDIRECTED_AND_VERIFIED
                if was_redirected
                else SourceVerificationStatus.FETCH_VERIFIED
            )
            source.rejection_reason = None
            return source

        # 5. Local verification from pre-retrieved content or API excerpts (when fetch_remote=False)
        content_text = source.raw_content or source.excerpt or ""
        if len(content_text.strip()) < 20:
            source.verification_status = SourceVerificationStatus.EMPTY_CONTENT
            source.rejection_reason = "Source excerpt and content are empty or negligible"
            return source

        text_to_check = f"{source.title} {content_text}".lower()
        matched_signals = [sig for sig in self.BUSINESS_PAIN_SIGNALS if sig in text_to_check]
        if not matched_signals:
            source.verification_status = SourceVerificationStatus.IRRELEVANT
            source.rejection_reason = "Source title and excerpt lack B2B business problem signals"
            return source

        if source.api_provider:
            source.verification_status = SourceVerificationStatus.API_VERIFIED
        else:
            source.verification_status = SourceVerificationStatus.SNIPPET_UNFETCHED
        source.rejection_reason = None
        return source
