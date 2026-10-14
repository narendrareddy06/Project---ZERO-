"""
Prospect discovery engine for Project ZERO.

Finds real business prospects through permitted public web sources.
Safety constraints strictly enforced:
- Zero paid APIs or tools.
- NO LinkedIn scraping, automation, or messaging.
- Deduplicates prospects against database.
- Checks suppression and do-not-contact records before qualification.
- Separates verified public facts from assumptions/hypotheses.
- Read-only: does not send messages, emails, or form submissions.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from zero.database import Database
from zero.research.fetcher import PublicWebResearcher
from zero.schemas import Geography, Prospect, ProspectStatus


class ProspectDiscoveryEngine:
    """Discovers and parses prospective businesses from permitted public web sources."""

    def __init__(self, db: Database, researcher: Optional[PublicWebResearcher] = None):
        self.db = db
        self.researcher = researcher or PublicWebResearcher()

    def normalize_domain(self, domain_or_url: str) -> str:
        """Normalizes a domain or URL into a clean lowercase domain name."""
        cleaned = domain_or_url.strip().lower()
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed = urlparse(cleaned)
            cleaned = parsed.netloc
        # Strip leading www.
        if cleaned.startswith("www."):
            cleaned = cleaned[4:]
        # Strip trailing slash or path if any
        if "/" in cleaned:
            cleaned = cleaned.split("/", 1)[0]
        # Strip port if any
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[0]
        return cleaned

    def create_prospect(
        self,
        company_name: str,
        website_or_domain: str,
        geography: Geography,
        industry_or_niche: str,
        public_source_url: str,
        verified_facts: Dict[str, Any],
        assumptions: Optional[Dict[str, Any]] = None,
        associated_offer_id: Optional[str] = None,
        is_sample: bool = False,
    ) -> Tuple[Prospect, bool, str]:
        """
        Creates and stores a prospect while checking:
        1. LinkedIn exclusion (hard prohibited).
        2. Suppression / opt-out list.
        3. Deduplication against existing records.
        
        Returns: (Prospect, is_new, message)
        """
        norm_domain = self.normalize_domain(website_or_domain)

        # Safety check 1: LinkedIn prohibition
        if "linkedin.com" in norm_domain or "linkedin.com" in public_source_url.lower():
            raise ValueError(
                "LinkedIn discovery, scraping, and automation are strictly prohibited by Project ZERO safety rules (AGENTS.md)."
            )

        # Safety check 2: Deduplication
        existing = self.db.find_prospect_by_domain(norm_domain)
        if existing:
            return existing, False, f"Prospect with domain '{norm_domain}' already exists in database (ID: {existing.id})."

        # Safety check 3: Suppression check
        is_suppressed = self.db.is_suppressed(norm_domain)
        status = ProspectStatus.SUPPRESSED if is_suppressed else ProspectStatus.DISCOVERED

        now = datetime.now(timezone.utc)
        prospect_id = f"prosp_{abs(hash(norm_domain + str(now.timestamp()))) % 100000000:08d}"

        prospect = Prospect(
            id=prospect_id,
            company_name=company_name.strip(),
            domain_or_website=norm_domain,
            geography=geography,
            industry_or_niche=industry_or_niche.strip(),
            public_source_url=public_source_url.strip(),
            discovered_at=now,
            status=status,
            verified_facts=verified_facts,
            assumptions=assumptions or {},
            associated_offer_id=associated_offer_id,
            is_sample=is_sample,
        )

        saved = self.db.save_prospect(prospect, actor="AGENT")
        msg = "Prospect suppressed per opt-out/suppression record." if is_suppressed else "Discovered and recorded."
        return saved, True, msg

    def discover_from_public_url(
        self,
        company_website_url: str,
        public_source_url: str,
        geography: Geography = Geography.IN,
        industry_or_niche: str = "Technology & Professional Services",
        associated_offer_id: Optional[str] = None,
        is_sample: bool = False,
    ) -> Tuple[Optional[Prospect], bool, str]:
        """
        Retrieves a public company page to extract verified facts:
        - Page title / company name.
        - Public email / contact endpoint.
        - Core services / tech stack keywords.
        Returns: (Prospect, is_new, status_message)
        """
        norm_domain = self.normalize_domain(company_website_url)
        if "linkedin.com" in norm_domain:
            raise ValueError(
                "LinkedIn discovery, scraping, and automation are strictly prohibited by Project ZERO safety rules (AGENTS.md)."
            )

        # Check existing first before making network request (rate & resource optimization)
        existing = self.db.find_prospect_by_domain(norm_domain)
        if existing:
            return existing, False, f"Prospect with domain '{norm_domain}' already exists."

        # Fetch page with polite rate-limiting & robots.txt check
        status, title, clean_text, http_code, message = self.researcher.fetch_page(company_website_url)
        if not clean_text:
            return None, False, f"Failed to retrieve public company page: {message}"

        # Extract verified facts from clean page text
        verified_facts: Dict[str, Any] = {
            "source_http_status": http_code,
            "page_title": title,
        }

        # Extract public email addresses if present on page
        emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", clean_text)
        valid_emails = [e.lower() for e in emails if not e.endswith((".png", ".jpg", ".svg"))]
        if valid_emails:
            # Deduplicate while preserving order
            verified_facts["public_contact_email"] = list(dict.fromkeys(valid_emails))[:3]

        # Extract service mentions
        service_keywords = [
            "consulting", "software development", "cloud", "security", "ai",
            "machine learning", "analytics", "marketing", "logistics", "automation"
        ]
        found_services = [kw for kw in service_keywords if kw in clean_text.lower()]
        verified_facts["identified_services"] = found_services

        # Explicit assumptions (hypotheses that are not directly proven)
        assumptions = {
            "estimated_business_type": "B2B Professional Services" if "client" in clean_text.lower() else "General Business",
            "remote_collaboration_readiness": "High" if ("cloud" in clean_text.lower() or "remote" in clean_text.lower()) else "Moderate",
        }

        company_name = title.split("-")[0].split("|")[0].strip() if title else norm_domain

        return self.create_prospect(
            company_name=company_name or norm_domain,
            website_or_domain=norm_domain,
            geography=geography,
            industry_or_niche=industry_or_niche,
            public_source_url=public_source_url,
            verified_facts=verified_facts,
            assumptions=assumptions,
            associated_offer_id=associated_offer_id,
            is_sample=is_sample,
        )
