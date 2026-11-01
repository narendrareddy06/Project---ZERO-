"""
Permitted public source adapters for Autonomous Opportunity Discovery.

Strictly operates within the INR 0 operating budget target.
Uses permitted public APIs without requiring paid API keys or subscriptions:
1. Hacker News Algolia Search API (documented, free public endpoint, 10,000 req/hr)
2. GitHub Issues Search API (documented, free public endpoint, 10 req/min unauthenticated)

Excluded sources (explicitly checked and rejected per AGENTS.md rules):
- Reddit RSS / Search: Excluded due to robots.txt 'Disallow: /' for automated bots.
- DuckDuckGo HTML / Lite: Excluded due to robots.txt crawl restrictions.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import html
import re
import time
from typing import Any, Dict, List, Optional
import httpx

from zero.research.fetcher import DEFAULT_USER_AGENT
from zero.research.wigolo_client import WigoloMcpClient
from zero.schemas import DiscoveredSource


def clean_html_snippet(raw_html: str) -> str:
    """Helper to strip basic HTML markup from API text snippets."""
    if not raw_html:
        return ""
    # Unescape HTML entities
    text = html.unescape(raw_html)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse multiple whitespaces
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


class DiscoverySourceAdapter(ABC):
    """Abstract base class for permitted opportunity discovery source adapters."""

    name: str
    description: str
    documentation_url: str
    rate_limit_info: str
    cost_inr: float = 0.0
    is_active: bool = True
    exclusion_reason: Optional[str] = None

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[DiscoveredSource]:
        """Search the public source for relevant discussions, problems, or issues."""
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """Return standardized source metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "documentation_url": self.documentation_url,
            "rate_limit_info": self.rate_limit_info,
            "cost_inr": self.cost_inr,
            "is_active": self.is_active,
            "exclusion_reason": self.exclusion_reason,
        }


class HnAlgoliaSource(DiscoverySourceAdapter):
    """
    Hacker News search adapter using the official Algolia public search API.
    
    API Docs: https://hn.algolia.com/api
    Cost: INR 0.00 (Free public endpoint, no authentication required).
    Rate limit: ~10,000 requests per hour.
    """

    name = "hn_algolia"
    description = "Hacker News Algolia Search API (Posts, 'Ask HN', and Comments)"
    documentation_url = "https://hn.algolia.com/api"
    rate_limit_info = "10,000 requests/hour unauthenticated"
    cost_inr = 0.0
    is_active = True
    exclusion_reason = None

    BASE_URL = "https://hn.algolia.com/api/v1/search"

    def __init__(self, client: Optional[httpx.Client] = None, request_delay: float = 0.2):
        self._client = client or httpx.Client(
            timeout=10.0,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=True,
        )
        self._owns_client = client is None
        self.request_delay = request_delay
        self.total_requests = 0

    def close(self):
        if self._owns_client and self._client:
            self._client.close()

    def search(self, query: str, limit: int = 10) -> List[DiscoveredSource]:
        """Search Hacker News for problem reports and discussion threads."""
        if self.request_delay > 0:
            time.sleep(self.request_delay)

        params = {
            "query": query,
            "tags": "(story,comment)",
            "hitsPerPage": min(limit, 20),
        }

        results: List[DiscoveredSource] = []
        try:
            resp = self._client.get(self.BASE_URL, params=params)
            self.total_requests += 1

            if resp.status_code != 200:
                return []

            data = resp.json()
            hits = data.get("hits", [])

            for hit in hits:
                obj_id = hit.get("objectID")
                title = hit.get("title") or hit.get("story_title") or f"HN Discussion #{obj_id}"
                raw_url = hit.get("url") or f"https://news.ycombinator.com/item?id={obj_id}"
                author = hit.get("author") or "anonymous"

                # Extract excerpt from story_text, comment_text, or title
                raw_text = hit.get("story_text") or hit.get("comment_text") or title
                excerpt = clean_html_snippet(raw_text)[:600]

                # Parse created_at
                created_str = hit.get("created_at")
                if created_str:
                    try:
                        # Algolia uses ISO 8601 like '2023-01-01T12:00:00Z'
                        created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    except Exception:
                        created_at = datetime.now(timezone.utc)
                else:
                    created_at = datetime.now(timezone.utc)

                results.append(
                    DiscoveredSource(
                        source_name=self.name,
                        title=title.strip(),
                        url=raw_url.strip(),
                        excerpt=excerpt.strip(),
                        created_at=created_at,
                        author=author,
                        query=query,
                        metadata={
                            "points": hit.get("points", 0),
                            "num_comments": hit.get("num_comments", 0),
                            "objectID": obj_id,
                        },
                    )
                )

        except Exception:
            # Network, parse, or timeout errors return empty list gracefully
            return []

        return results


class GitHubIssuesSource(DiscoverySourceAdapter):
    """
    GitHub Issues search adapter using the official GitHub REST API.
    
    API Docs: https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-issues-and-pull-requests
    Cost: INR 0.00 (Free public endpoint, no authentication required).
    Rate limit: 10 requests per minute unauthenticated.
    """

    name = "github_issues"
    description = "GitHub Issues & Discussions Search API"
    documentation_url = "https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests"
    rate_limit_info = "10 requests/minute unauthenticated"
    cost_inr = 0.0
    is_active = True
    exclusion_reason = None

    BASE_URL = "https://api.github.com/search/issues"

    def __init__(self, client: Optional[httpx.Client] = None, request_delay: float = 0.5):
        self._client = client or httpx.Client(
            timeout=10.0,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/vnd.github.v3+json",
            },
            follow_redirects=True,
        )
        self._owns_client = client is None
        self.request_delay = request_delay
        self.total_requests = 0
        self.rate_limit_remaining: Optional[int] = None

    def close(self):
        if self._owns_client and self._client:
            self._client.close()

    def search(self, query: str, limit: int = 10) -> List[DiscoveredSource]:
        """Search open GitHub issues for developer and business workflow friction."""
        if self.rate_limit_remaining is not None and self.rate_limit_remaining <= 0:
            return []

        if self.request_delay > 0:
            time.sleep(self.request_delay)

        q = f"{query} is:issue state:open"
        params = {
            "q": q,
            "per_page": min(limit, 20),
            "sort": "updated",
        }

        results: List[DiscoveredSource] = []
        try:
            resp = self._client.get(self.BASE_URL, params=params)
            self.total_requests += 1

            if "X-RateLimit-Remaining" in resp.headers:
                try:
                    self.rate_limit_remaining = int(resp.headers["X-RateLimit-Remaining"])
                except ValueError:
                    pass

            if resp.status_code == 403 or resp.status_code == 429:
                self.rate_limit_remaining = 0
                return []

            if resp.status_code != 200:
                return []

            data = resp.json()
            items = data.get("items", [])

            for item in items:
                title = item.get("title", "")
                html_url = item.get("html_url", "")
                author = item.get("user", {}).get("login", "unknown")
                raw_body = item.get("body") or ""
                excerpt = clean_html_snippet(raw_body)[:600]

                created_str = item.get("created_at")
                if created_str:
                    try:
                        created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    except Exception:
                        created_at = datetime.now(timezone.utc)
                else:
                    created_at = datetime.now(timezone.utc)

                results.append(
                    DiscoveredSource(
                        source_name=self.name,
                        title=title.strip(),
                        url=html_url.strip(),
                        excerpt=excerpt.strip(),
                        created_at=created_at,
                        author=author,
                        query=query,
                        metadata={
                            "comments": item.get("comments", 0),
                            "state": item.get("state", "open"),
                            "repo_url": item.get("repository_url", ""),
                        },
                    )
                )

        except Exception:
            return []

        return results


class WigoloDiscoverySource(DiscoverySourceAdapter):
    """
    Local-first Web Intelligence source adapter powered by Wigolo MCP server.
    
    Supports search and fetch over permitted public sources with zero marginal cost.
    Cost: INR 0.00 (Local process / free public search engines).
    """

    name = "wigolo"
    description = "Wigolo Local-First Web Intelligence MCP Server (Search & Fetch)"
    documentation_url = "https://wigolo.app"
    rate_limit_info = "Local MCP Server / Permitted public search & fetch"
    cost_inr = 0.0
    is_active = True
    exclusion_reason = None

    def __init__(
        self,
        client: Optional[WigoloMcpClient] = None,
        enrich_with_fetch: bool = False,
    ):
        self._owns_client = client is None
        self.enrich_with_fetch = enrich_with_fetch
        if client is not None:
            self._client = client
        else:
            try:
                self._client = WigoloMcpClient()
            except Exception as e:
                self.is_active = False
                self.exclusion_reason = f"Wigolo MCP server initialization failed: {e}"
                self._client = None

    def close(self):
        if self._owns_client and self._client:
            self._client.close()

    def search(self, query: str, limit: int = 5) -> List[DiscoveredSource]:
        if not self._client:
            return []

        try:
            data = self._client.search(
                query=query,
                max_results=limit,
                search_depth="fast",
                include_content=False,
            )
        except Exception:
            return []

        raw_results = data.get("results", [])
        if not raw_results:
            return []

        findings: List[DiscoveredSource] = []
        for item in raw_results:
            raw_url = item.get("url") or ""
            if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
                continue

            raw_title = item.get("title") or "Public Web Finding"
            snippet = item.get("snippet") or ""

            # Optionally enrich with fetch if snippet is minimal and client is available
            if self.enrich_with_fetch and len(snippet.strip()) < 80 and self._client:
                try:
                    fetch_data = self._client.fetch(raw_url)
                    if fetch_data.get("markdown"):
                        snippet = fetch_data["markdown"][:600]
                except Exception:
                    pass

            pub_date = item.get("published_date")
            if not pub_date or str(pub_date).lower() in ("none", "null", "unknown", ""):
                pub_date = None

            findings.append(
                DiscoveredSource(
                    source_name=self.name,
                    title=clean_html_snippet(raw_title).strip() or "Public Web Finding",
                    url=raw_url.strip(),
                    excerpt=clean_html_snippet(snippet).strip()[:600],
                    created_at=datetime.now(timezone.utc),
                    published_date=pub_date,
                    author=item.get("author") or "public_web",
                    query=query,
                    metadata={
                        "evidence_score": item.get("evidence_score", {}),
                        "relevance_score": item.get("relevance_score", 0.0),
                        "fetch_failed": item.get("fetch_failed"),
                    },
                )
            )

        return findings


class ExcludedSource(DiscoverySourceAdapter):
    """Representation of an evaluated public source that is explicitly excluded per safety rules."""

    def __init__(
        self,
        name: str,
        description: str,
        documentation_url: str,
        exclusion_reason: str,
    ):
        self.name = name
        self.description = description
        self.documentation_url = documentation_url
        self.rate_limit_info = "N/A (Crawl disallowed)"
        self.cost_inr = 0.0
        self.is_active = False
        self.exclusion_reason = exclusion_reason

    def search(self, query: str, limit: int = 10) -> List[DiscoveredSource]:
        raise PermissionError(
            f"Source '{self.name}' is strictly excluded from Project ZERO automated discovery: {self.exclusion_reason}"
        )


def get_all_source_definitions() -> List[DiscoverySourceAdapter]:
    """Return all evaluated source adapters, including active permitted adapters and safely excluded sources."""
    return [
        WigoloDiscoverySource(),
        HnAlgoliaSource(),
        GitHubIssuesSource(),
        ExcludedSource(
            name="reddit_rss",
            description="Reddit RSS & Search Feeds",
            documentation_url="https://www.reddit.com/robots.txt",
            exclusion_reason="Disallowed by Reddit robots.txt ('Disallow: /') for automated user-agents per AGENTS.md rules.",
        ),
        ExcludedSource(
            name="duckduckgo_lite",
            description="DuckDuckGo HTML / Lite Search",
            documentation_url="https://duckduckgo.com/robots.txt",
            exclusion_reason="Disallowed by DuckDuckGo robots.txt for automated scrapers per AGENTS.md rules.",
        ),
    ]


def get_active_source_adapters() -> List[DiscoverySourceAdapter]:
    """Return only permitted, active source adapters compliant with INR 0 budget and robots.txt."""
    return [s for s in get_all_source_definitions() if s.is_active]
