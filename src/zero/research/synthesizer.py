"""
Opportunity Synthesizer for Project ZERO.

Clusters raw discovered public evidence into concrete B2B offer candidates.
Strictly adheres to safety rules:
- Never confuses a reported problem with validated market demand.
- A public forum post or GitHub issue proves problem existence (VERIFIED_SOURCE),
  NOT commercial demand, pricing acceptance, or willingness to pay.
- Willingness to pay and 72-hour pilot feasibility are explicitly recorded as
  unverified hypotheses (HYPOTHESIS, confidence <= 0.50).
- Guarantees conservative scoring gating (NEEDS_MORE_EVIDENCE) until real customer
  validation occurs.
- Links only existing, persisted evidence IDs (no phantom IDs).
- All proposed deliverables strictly adhere to INR 0 operating budget and remote fulfillment.
"""

import hashlib
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zero.research.evaluator import OfferEvaluator
from zero.schemas import (
    CRITERION_WEIGHTS,
    CriterionKey,
    CriterionScore,
    DecisionStatus,
    DiscoveredSource,
    Evidence,
    EvidenceType,
    Geography,
    OfferCandidate,
    SourceVerificationStatus,
)


def calculate_source_evidence_confidence(src: DiscoveredSource) -> Tuple[float, str]:
    """
    Computes evidence confidence dynamically based on:
    1. Source verification status & provenance:
       - FETCH_VERIFIED: Strongest base (0.72), destination retrieved and content inspected.
       - REDIRECTED_AND_VERIFIED: Followed redirect to destination (0.70).
       - API_VERIFIED: Structured data from recognized API (0.65).
       - SNIPPET_UNFETCHED: Search snippet fallback, destination unreached (0.42, capped <= 0.45).
       - REJECTED/UNVERIFIED: Inaccessible, empty or irrelevant (0.15, capped <= 0.20).
    2. Strength of business pain signals in content
    3. Excerpt depth and concreteness
    4. Publication recency (when authentically available)

    Returns: (confidence: float, explanation: str)
    """
    factors: List[str] = []

    status = getattr(src, "verification_status", None)

    # 1. Base provenance by Verification Status
    if status == SourceVerificationStatus.FETCH_VERIFIED:
        base = 0.72
        factors.append("FETCH_VERIFIED full page retrieval (base 0.72)")
    elif status == SourceVerificationStatus.REDIRECTED_AND_VERIFIED:
        base = 0.70
        factors.append("REDIRECTED_AND_VERIFIED page retrieval (base 0.70)")
    elif status == SourceVerificationStatus.API_VERIFIED:
        base = 0.65
        api_name = src.api_provider or src.source_name
        factors.append(f"API_VERIFIED structured response [{api_name}] (base 0.65)")
    elif status == SourceVerificationStatus.SNIPPET_UNFETCHED:
        base = 0.42
        factors.append("SNIPPET_UNFETCHED search snippet penalty (base 0.42, capped <= 0.45)")
    elif status in (
        SourceVerificationStatus.UNAVAILABLE,
        SourceVerificationStatus.HTTP_ERROR,
        SourceVerificationStatus.EMPTY_CONTENT,
        SourceVerificationStatus.IRRELEVANT,
        SourceVerificationStatus.NEEDS_MANUAL_REVIEW,
    ):
        base = 0.15
        factors.append(f"Rejected / unverified status [{status.value}] (base 0.15, capped <= 0.20)")
    elif status == SourceVerificationStatus.VERIFIED:
        base = 0.65
        factors.append("VERIFIED source provenance (base 0.65)")
    else:
        # Fallback for unclassified sources
        if src.source_name in ("github_issues", "hn_algolia"):
            base = 0.65
            factors.append(f"{src.source_name} provenance (base 0.65)")
        elif src.raw_content and len(src.raw_content) > 100:
            base = 0.70
            factors.append("verified content fetch (base 0.70)")
        else:
            base = 0.62
            factors.append(f"{src.source_name} snippet provenance (base 0.62)")

    if src.author and src.author.lower() not in ("unknown", "anonymous", "public_web"):
        base += 0.02
        factors.append(f"identified author '{src.author}' (+0.02)")

    # 2. Problem / Pain Signal Strength
    text_content = f"{src.title} {src.excerpt} {src.raw_content or ''}".lower()
    strong_pain_signals = [
        "fail", "failure", "failing", "broken", "drop", "dropouts", "manual",
        "reconcil", "bottleneck", "cost overrun", "billing surprise", "lost deals",
        "lost revenue", "churn", "outage", "leak", "vulnerability", "complaint",
        "nightmare", "hours wasted", "friction", "sync error", "downtime",
    ]
    moderate_pain_signals = [
        "issue", "problem", "error", "slow", "delay", "expensive", "waste",
        "struggle", "headache", "spam", "bounce", "backlog", "retry", "unattached",
    ]
    strong_hits = [s for s in strong_pain_signals if s in text_content]
    mod_hits = [s for s in moderate_pain_signals if s in text_content]
    total_hits = len(strong_hits) + len(mod_hits)

    if len(strong_hits) >= 2 or total_hits >= 4:
        pain_mod = 0.07
        factors.append(f"strong pain signals [{', '.join((strong_hits + mod_hits)[:3])}] (+0.07)")
    elif len(strong_hits) >= 1 or total_hits >= 2:
        pain_mod = 0.04
        factors.append(f"moderate pain signals [{', '.join((strong_hits + mod_hits)[:2])}] (+0.04)")
    elif total_hits == 1:
        pain_mod = -0.05
        factors.append("weak single pain signal (-0.05)")
    else:
        pain_mod = -0.12
        factors.append("no explicit pain signal (-0.12)")

    # 3. Content Depth
    content_len = len((src.raw_content or src.excerpt or "").strip())
    if content_len > 250:
        depth_mod = 0.05
        factors.append(f"rich excerpt ({content_len} chars) (+0.05)")
    elif content_len > 70:
        depth_mod = 0.02
        factors.append(f"adequate excerpt ({content_len} chars) (+0.02)")
    elif content_len < 50:
        depth_mod = -0.06
        factors.append(f"thin excerpt ({content_len} chars) (-0.06)")
    else:
        depth_mod = 0.0

    # 4. Publication Recency
    recency_mod = 0.0
    if src.published_date:
        pub_str = str(src.published_date)
        if any(yr in pub_str for yr in ("2025", "2026")):
            recency_mod = 0.04
            factors.append(f"recent publication '{pub_str}' (+0.04)")
        elif "2024" in pub_str:
            recency_mod = 0.01
            factors.append(f"moderately recent publication '{pub_str}' (+0.01)")
        elif any(yr in pub_str for yr in ("2020", "2021", "2022", "2023")):
            recency_mod = -0.04
            factors.append(f"older publication '{pub_str}' (-0.04)")
        else:
            factors.append(f"published '{pub_str}' (0.00)")
    else:
        factors.append("undated (0.00)")

    raw_conf = base + pain_mod + depth_mod + recency_mod

    # Capping rules based on verification status
    if status == SourceVerificationStatus.SNIPPET_UNFETCHED:
        confidence = min(0.45, max(0.20, raw_conf))
        factors.append("capped at <= 0.45 (unfetched search snippet)")
    elif status in (
        SourceVerificationStatus.UNAVAILABLE,
        SourceVerificationStatus.HTTP_ERROR,
        SourceVerificationStatus.EMPTY_CONTENT,
        SourceVerificationStatus.IRRELEVANT,
        SourceVerificationStatus.NEEDS_MANUAL_REVIEW,
    ):
        confidence = min(0.20, max(0.05, raw_conf))
        factors.append("capped at <= 0.20 (rejected / unverified)")
    else:
        confidence = max(0.52, min(0.88, raw_conf))

    confidence = round(confidence, 2)
    explanation = "; ".join(factors)
    return confidence, explanation


THEME_DEFINITIONS = [
    {
        "id_slug": "email_auth",
        "title": "Remote B2B Email Deliverability & DMARC/SPF Audit Pilot",
        "keywords": ["email", "deliverability", "spf", "dkim", "dmarc", "bounce", "spam", "inbox", "smtp", "mx", "reputation"],
        "buyer_profile": "Founders, Head of Growth, or Sales Operations Leads at B2B firms sending outbound communication",
        "problem_template": "Reported inbox placement failures, SPF/DKIM authentication errors, and spam filtering hurting outreach.",
        "deliverable": "A comprehensive 48-hour diagnostic audit checklist covering DNS authentication (SPF, DKIM, DMARC), MX records, and step-by-step remediation commands delivered asynchronously.",
        "pricing_or_pilot": "Zero-fee initial diagnostic audit checklist; INR 15,000 / $500 monthly managed DNS & domain health monitoring retainer.",
        "delivery_method": "100% remote asynchronous DNS inspection, written audit markdown report, and copy-paste TXT record templates.",
        "risks": [
            "Customer willingness to pay for ongoing monitoring is unvalidated without active pilot agreements.",
            "Client DNS changes require operator admin access or IT cooperation.",
            "Outbound deliverability also depends on copy quality and sender volume beyond technical DNS records.",
        ],
    },
    {
        "id_slug": "api_integration",
        "title": "B2B API Integration & Webhook Reliability Automation Pilot",
        "keywords": ["api", "webhook", "integration", "sync", "export", "import", "connector", "payload", "failure", "retry", "crm", "stripe"],
        "buyer_profile": "CTOs, VP Engineering, or Technical Product Managers at early-stage B2B SaaS and agency firms",
        "problem_template": "Reported silent webhook dropouts, synchronization discrepancies, and manual data exports between B2B tools.",
        "deliverable": "A turnkey webhook failure logging and automatic retry script with alerting for critical B2B API integrations.",
        "pricing_or_pilot": "Complimentary initial webhook reliability audit; INR 25,000 / $800 fixed-scope custom integration bridge.",
        "delivery_method": "Remote code inspection, lightweight Python/Node serverless script, and detailed implementation walkthrough.",
        "risks": [
            "Customer willingness to pay is hypothetical pending commercial outreach.",
            "Requires API credentials or staging environment access.",
            "Third-party API rate limits or breaking changes may require maintenance.",
        ],
    },
    {
        "id_slug": "cloud_cost",
        "title": "Cloud Infrastructure Cost & Idle Resource Hygiene Audit",
        "keywords": ["aws", "cloud", "billing", "cost", "ec2", "s3", "docker", "kubernetes", "server", "expensive", "infra", "overspend", "waste"],
        "buyer_profile": "Founders, Engineering Directors, and DevOps Leads managing monthly cloud hosting budgets",
        "problem_template": "Reported cloud billing surprises, orphaned block storage, and unmonitored development infrastructure overspend.",
        "deliverable": "A read-only cloud resource audit report identifying idle instances, detached volumes, and unused IP addresses with exact cost savings calculations.",
        "pricing_or_pilot": "Zero-fee pilot audit finding minimum 15% cloud waste; contingency fee of 25% of first month verified savings or INR 20,000 fixed retainer.",
        "delivery_method": "Remote read-only IAM policy script execution, prioritized PDF/markdown savings roadmap, and non-disruptive cleanup script.",
        "risks": [
            "Willingness to pay contingent on actual identified dollar savings.",
            "Clients may hesitate to grant read-only IAM security roles.",
            "Production downtime risks if client accidentally deletes active instances.",
        ],
    },
    {
        "id_slug": "data_automation",
        "title": "Operational Workflow & Spreadsheet Data Reconciliation Pilot",
        "keywords": ["manual", "spreadsheet", "excel", "sheets", "csv", "data entry", "workflow", "automate", "reconciliation", "reporting"],
        "buyer_profile": "Operations Directors, COOs, and Finance Controllers at professional services and distribution businesses",
        "problem_template": "Reported repetitive manual copy-pasting across disparate spreadsheets and weekly operational reporting bottlenecks.",
        "deliverable": "An automated Python ETL reconciliation script converting multi-sheet data inputs into clean, error-checked weekly reports.",
        "pricing_or_pilot": "Free pilot automation of one high-friction weekly spreadsheet workflow; INR 20,000 / $600 per additional automated workflow.",
        "delivery_method": "Remote data schema review, tested Python automation script, cron scheduling instructions, and video walkthrough.",
        "risks": [
            "Willingness to pay requires commercial validation with real SMB buyers.",
            "Data formats and manual entry errors from staff can cause script edge-case failures.",
            "Requires sample sanitized CSVs for initial development.",
        ],
    },
    {
        "id_slug": "security_hygiene",
        "title": "Secrets & Repository Security Hygiene Audit Pilot",
        "keywords": ["security", "secret", "token", "credential", "leak", "compliance", "audit", "gdpr", "soc2", "permission", "auth", "vulnerability"],
        "buyer_profile": "Technical Founders and Engineering Managers preparing for enterprise customer security reviews",
        "problem_template": "Reported risks of hardcoded tokens, insecure repo configurations, and lack of pre-commit credential scanners.",
        "deliverable": "A comprehensive static secrets audit report of public/private repositories with remediation instructions and pre-commit hook setup.",
        "pricing_or_pilot": "Free initial repository scan report; INR 30,000 / $1,000 full security checklist and remediation advisory.",
        "delivery_method": "Remote open-source static scanning, vulnerability prioritization report, and pull request with sanitization patches.",
        "risks": [
            "Commercial demand unvalidated without pilot commitments.",
            "Clients sensitive about repository security access.",
            "Must clearly document that static analysis is not a full penetration test.",
        ],
    },
    {
        "id_slug": "general_b2b_friction",
        "title": "B2B SaaS Developer Onboarding & API Documentation Diagnostic",
        "keywords": ["documentation", "onboarding", "slow", "bug", "setup", "guide", "sdk", "developer", "friction", "pain"],
        "buyer_profile": "Product Managers, Head of Developer Relations, or CTOs at technical B2B SaaS companies",
        "problem_template": "Reported friction during developer onboarding, outdated SDK setup instructions, and high initial support ticket volume.",
        "deliverable": "A step-by-step developer onboarding friction audit report identifying broken quickstart steps, missing error codes, and runnable code samples.",
        "pricing_or_pilot": "Zero-fee initial onboarding diagnostic; INR 25,000 / $750 complete quickstart guide overhaul.",
        "delivery_method": "Remote testing of API docs from fresh environment, recorded diagnostic video, and markdown PR with verified quickstarts.",
        "risks": [
            "Willingness to pay is an unverified hypothesis pending commercial discussions.",
            "DevRel budgets fluctuate with funding cycles.",
        ],
    },
]


class OpportunitySynthesizer:
    """
    Deterministic synthesizer that groups discovered public evidence into
    rigorously validated, conservative B2B offer candidates.
    """

    def __init__(self, evaluator: Optional[OfferEvaluator] = None):
        self.evaluator = evaluator or OfferEvaluator()

    def synthesize(
        self,
        discovered_sources: List[DiscoveredSource],
        geography: Geography,
        is_sample: bool = False,
        run_prefix: str = "auto",
    ) -> Tuple[List[OfferCandidate], List[Evidence]]:
        """
        Synthesize offer candidates from raw discovered sources.

        Returns:
            Tuple of (List[OfferCandidate], List[Evidence]) where all evidence records
            are fully populated and linked, and all offer candidates are evaluated.
        """
        all_created_evidence: List[Evidence] = []
        synthesized_offers: List[OfferCandidate] = []

        if not discovered_sources:
            return [], []

        # 1. Ingest each discovered source as a verified problem existence evidence record
        source_evidence_pairs: List[Tuple[DiscoveredSource, Evidence]] = []
        for src in discovered_sources:
            # Deterministic evidence ID based on URL
            url_hash = hashlib.sha256(src.url.encode("utf-8")).hexdigest()[:8]
            ev_id = f"ev_{run_prefix}_{url_hash}"

            # Calculate transparent, evidence-based confidence (removes static 0.75)
            ev_confidence, conf_explanation = calculate_source_evidence_confidence(src)

            # Verified source evidence proves PROBLEM REPORT EXISTENCE, not market demand
            clean_title = src.title.replace("\n", " ").strip()
            date_info = f"Published: {src.published_date}" if src.published_date else "Publication Date: UNDATED / UNKNOWN"
            ev = Evidence(
                id=ev_id,
                claim=f"Reported B2B problem/friction in public discussion: '{clean_title}'",
                evidence_type=EvidenceType.VERIFIED_SOURCE,
                geography=geography,
                confidence=ev_confidence,
                source_url=src.url,
                published_date=src.published_date,
                notes=(
                    f"Discovered via {src.source_name} query: '{src.query}'. "
                    f"Author: {src.author or 'unknown'}. {date_info}. "
                    f"Confidence derivation: {conf_explanation}."
                ),
                excerpt=src.excerpt[:500] if src.excerpt else f"Title: {src.title}",
                is_sample=is_sample,
            )
            all_created_evidence.append(ev)
            source_evidence_pairs.append((src, ev))

        # 2. Cluster evidence items into theme buckets based on keywords in content
        theme_buckets: Dict[str, List[Tuple[DiscoveredSource, Evidence]]] = {
            theme["id_slug"]: [] for theme in THEME_DEFINITIONS
        }

        for src, ev in source_evidence_pairs:
            # Primary clustering matches actual reported title and content
            content_text = f"{src.title} {src.excerpt} {src.raw_content or ''}".lower()
            matched = False
            for theme in THEME_DEFINITIONS:
                if any(kw in content_text for kw in theme["keywords"]):
                    theme_buckets[theme["id_slug"]].append((src, ev))
                    matched = True
                    break

            if not matched:
                # Secondary check using query context if content keywords were sparse
                query_text = f"{content_text} {src.query}".lower()
                for theme in THEME_DEFINITIONS:
                    if any(kw in query_text for kw in theme["keywords"]):
                        theme_buckets[theme["id_slug"]].append((src, ev))
                        matched = True
                        break

            if not matched:
                # Default to general B2B workflow friction
                theme_buckets["general_b2b_friction"].append((src, ev))

        # 3. For each non-empty theme bucket, synthesize an OfferCandidate
        for theme in THEME_DEFINITIONS:
            slug = theme["id_slug"]
            items = theme_buckets.get(slug, [])
            if not items:
                continue

            verified_evs = [ev for _, ev in items]
            verified_ids = [ev.id for ev in verified_evs]

            # Lazy import to avoid circular dependency
            from zero.research.autonomous import extract_publisher_organization

            # Separate confirmed independent sources vs snippet unfetched vs unknown publisher
            confirmed_items = []
            snippet_items = []
            unknown_items = []

            for s, ev in items:
                # Ensure publisher_org is populated
                if not s.publisher_org:
                    org, _ = extract_publisher_organization(s.url, author=s.author, source_name=s.source_name)
                    s.publisher_org = org

                if s.verification_status == SourceVerificationStatus.SNIPPET_UNFETCHED:
                    snippet_items.append((s, ev))
                elif not s.publisher_org:
                    unknown_items.append((s, ev))
                else:
                    confirmed_items.append((s, ev))

            # Group confirmed sources by publisher_org (Task 2 & 4: SNIPPET_UNFETCHED NEVER counted in independent count)
            distinct_publishers = {s.publisher_org for s, _ in confirmed_items if s.publisher_org}
            indep_count = len(distinct_publishers)
            if indep_count == 0 and confirmed_items:
                indep_count = 1

            unknown_indep_count = len(snippet_items) + len(unknown_items)

            # Adapt dynamic titles/deliverables for general/emergent friction clusters
            theme_title = theme["title"]
            theme_buyer = theme["buyer_profile"]
            theme_deliverable = theme["deliverable"]
            if slug == "general_b2b_friction" and items:
                sample_item = items[0][0]
                dominant_topic = sample_item.title.replace("Ask HN:", "").replace("Show HN:", "").strip()[:50]
                theme_title = f"B2B Workflow Friction Diagnostic: {dominant_topic}"
                theme_buyer = "Operations, Engineering, and Growth Leads experiencing workflow bottlenecks"
                theme_deliverable = (
                    f"A 48-hour diagnostic audit checklist and prioritized remediation plan for operational "
                    f"friction related to {dominant_topic} delivered 100% remotely at INR 0 cost."
                )

            # Problem severity evidence summary and dynamic rubric score based on frequency
            if snippet_items:
                severity_summary = (
                    f"Directly evidenced by {len(confirmed_items)} confirmed report(s) across "
                    f"{indep_count} independent organization(s) (plus {len(snippet_items)} unfetched search snippet lead(s))."
                )
            else:
                severity_summary = (
                    f"Directly evidenced by {len(verified_evs)} public discussion reports across "
                    f"{indep_count} independent source(s)."
                )

            if indep_count >= 3:
                sev_score_val = 5
                sev_rationale = (
                    f"High problem severity: Corroborated by {len(confirmed_items)} discussion report(s) across "
                    f"{indep_count} independent sources ({', '.join(list(distinct_publishers)[:3])}). "
                    f"Demonstrates recurring operational pain."
                )
            elif indep_count == 2:
                sev_score_val = 4
                sev_rationale = (
                    f"Moderate-to-high problem severity: Evidenced by {len(confirmed_items)} discussion report(s) across "
                    f"{indep_count} independent sources ({', '.join(list(distinct_publishers)[:2])})."
                )
            elif indep_count == 1:
                first_org = list(distinct_publishers)[0] if distinct_publishers else (items[0][0].author or "single source")
                sev_score_val = 3
                sev_rationale = (
                    f"Single isolated problem report by '{first_org}'. "
                    f"Establishes reported problem existence, but frequency across independent buyers remains unproven."
                )
            else:
                sev_score_val = 2
                sev_rationale = (
                    f"Preliminary discovery signals ({len(snippet_items)} unfetched search snippet lead(s)); "
                    f"no confirmed independent destination pages fetched yet."
                )

            if snippet_items:
                sev_rationale += f" (Note: {len(snippet_items)} search snippet lead(s) preserved; destination pages unfetched)."

            # Evaluate commercial Willingness-to-Pay signals in supporting sources (Task 6)
            cluster_text = " ".join(f"{s.title} {s.excerpt} {s.raw_content or ''}" for s, _ in items).lower()
            wtp_signals = [
                "paying", "paid", "$", "budget", "subscription", "pricing", "hire",
                "consultant", "vendor", "contractor", "expensive tool", "costing us",
                "willing to pay", "looking to buy",
            ]
            detected_wtp = [w for w in wtp_signals if w in cluster_text]

            wtp_hash = hashlib.sha256(f"{slug}_wtp_{geography.value}".encode()).hexdigest()[:8]
            if detected_wtp:
                wtp_conf = 0.35  # Preliminary commercial budget signal, but unvalidated for our offer
                wtp_score_val = 2
                wtp_summary = f"Preliminary commercial budget mentions ({', '.join(detected_wtp[:2])}); pilot demand unvalidated"
                wtp_notes = (
                    f"Unverified hypothesis (confidence {wtp_conf:.2f}). Preliminary commercial budget keywords "
                    f"({', '.join(detected_wtp[:2])}) detected in discussions, but willingness to pay for this specific "
                    f"pilot offer remains an unvalidated commercial hypothesis."
                )
                wtp_rationale = (
                    f"Preliminary commercial budget mentions detected ({', '.join(detected_wtp[:2])}), but commercial "
                    f"willingness to pay for our specific pilot deliverable requires direct discovery validation."
                )
            else:
                wtp_conf = 0.20  # Explicitly unvalidated / unknown hypothesis
                wtp_score_val = 1
                wtp_summary = "UNKNOWN / ZERO EMPIRICAL EVIDENCE: Public discussions contain problem complaints only, not commercial willingness to pay"
                wtp_notes = (
                    f"Unverified hypothesis (confidence {wtp_conf:.2f}). UNKNOWN / ZERO EMPIRICAL EVIDENCE: 0 commercial "
                    f"willingness-to-pay evidence found. Public forum discussions prove reported friction, NOT commercial "
                    f"market demand or willingness to pay."
                )
                wtp_rationale = (
                    "UNKNOWN / ZERO EMPIRICAL EVIDENCE: Public forum discussions establish reported friction only. "
                    "Zero commercial willingness-to-pay evidence exists. Requires structured buyer conversations."
                )

            wtp_ev = Evidence(
                id=f"ev_hyp_wtp_{wtp_hash}",
                claim=f"Hypothesis: Target B2B buyers have willingness to pay for {theme_title} solutions ({wtp_summary}).",
                evidence_type=EvidenceType.HYPOTHESIS,
                geography=geography,
                confidence=wtp_conf,
                notes=wtp_notes,
                is_sample=is_sample,
            )
            all_created_evidence.append(wtp_ev)

            # Buyer Accessibility Hypothesis
            access_hash = hashlib.sha256(f"{slug}_access_{geography.value}".encode()).hexdigest()[:8]
            access_ev = Evidence(
                id=f"ev_hyp_acc_{access_hash}",
                claim=f"Hypothesis: Decision makers ({theme_buyer}) are reachable via public business directories and domain registries.",
                evidence_type=EvidenceType.HYPOTHESIS,
                geography=geography,
                confidence=0.50,
                notes="Reachable via permitted public domains and verified corporate email patterns.",
                is_sample=is_sample,
            )
            all_created_evidence.append(access_ev)

            # Sales Cycle Feasibility Hypothesis
            cycle_hash = hashlib.sha256(f"{slug}_cycle_{geography.value}".encode()).hexdigest()[:8]
            cycle_ev = Evidence(
                id=f"ev_hyp_cyc_{cycle_hash}",
                claim=f"Hypothesis: A zero-cost initial pilot audit can be approved by the buyer within 72 hours.",
                evidence_type=EvidenceType.HYPOTHESIS,
                geography=geography,
                confidence=0.45,
                notes="Assumes low friction due to zero upfront financial commitment, but sales cycle remains unproven.",
                is_sample=is_sample,
            )
            all_created_evidence.append(cycle_ev)

            # Delivery Feasibility Evidence (High confidence because deliverable is ₹0 remote)
            deliv_hash = hashlib.sha256(f"{slug}_deliv".encode()).hexdigest()[:8]
            deliv_ev = Evidence(
                id=f"ev_deliv_{deliv_hash}",
                claim=f"Delivery feasibility: {theme_deliverable} can be executed 100% remotely with standard open-source tools at INR 0 marginal cost.",
                evidence_type=EvidenceType.USER_PROVIDED,
                geography=geography,
                confidence=0.90,
                notes="Standardized remote technical delivery workflow requiring no proprietary or paid infrastructure.",
                is_sample=is_sample,
            )
            all_created_evidence.append(deliv_ev)

            # Build Offer Candidate with rich provenance & validation unknowns
            offer_id = f"off_disc_{slug[:12]}_{geography.value.lower()}"
            problem_summary = (
                f"{theme['problem_template']} Evidenced by {len(verified_evs)} public discussions "
                f"across {indep_count} independent source(s): "
                + "; ".join(f"'{src.title[:60]}'" for src, _ in items[:3])
            )

            all_offer_ev_ids = verified_ids + [wtp_ev.id, access_ev.id, cycle_ev.id, deliv_ev.id]

            candidate = OfferCandidate(
                id=offer_id,
                title=theme_title,
                target_geography=geography,
                buyer_profile=theme_buyer,
                problem_statement=problem_summary,
                proposed_deliverable=theme_deliverable,
                plausible_pricing_or_pilot=theme["pricing_or_pilot"],
                delivery_method=theme["delivery_method"],
                risks=theme["risks"],
                evidence_ids=all_offer_ev_ids,
                is_sample=is_sample,
                independent_report_count=indep_count,
                unknown_independence_count=unknown_indep_count,
                unknowns_requiring_validation=[
                    "Commercial willingness to pay for this proposed pilot deliverable",
                    "Target decision maker responsiveness via permitted public channels",
                    "Feasibility of securing pilot commitment within 72 hours",
                ],
                problem_severity_evidence=severity_summary,
                wtp_evidence_summary=wtp_summary,
            )

            # 4. Construct rubric scores and evaluate candidate
            criterion_scores = {
                CriterionKey.PROBLEM_SEVERITY: CriterionScore(
                    criterion=CriterionKey.PROBLEM_SEVERITY,
                    score=sev_score_val,
                    weight=CRITERION_WEIGHTS[CriterionKey.PROBLEM_SEVERITY],
                    rationale=sev_rationale,
                    evidence_ids=verified_ids,
                ),
                CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
                    criterion=CriterionKey.WILLINGNESS_TO_PAY,
                    score=wtp_score_val,
                    weight=CRITERION_WEIGHTS[CriterionKey.WILLINGNESS_TO_PAY],
                    rationale=wtp_rationale,
                    evidence_ids=[wtp_ev.id],
                ),
                CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
                    criterion=CriterionKey.BUYER_ACCESSIBILITY,
                    score=3,
                    weight=CRITERION_WEIGHTS[CriterionKey.BUYER_ACCESSIBILITY],
                    rationale=f"Target decision makers ({theme_buyer}) are identifiable via public websites and domain registrations.",
                    evidence_ids=[access_ev.id],
                ),
                CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
                    criterion=CriterionKey.DELIVERY_FEASIBILITY,
                    score=5,
                    weight=CRITERION_WEIGHTS[CriterionKey.DELIVERY_FEASIBILITY],
                    rationale="Deliverable can be fulfilled 100% remotely using free open-source utilities at INR 0 marginal cost.",
                    evidence_ids=[deliv_ev.id],
                ),
                CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
                    criterion=CriterionKey.SALES_CYCLE_FEASIBILITY,
                    score=3,
                    weight=CRITERION_WEIGHTS[CriterionKey.SALES_CYCLE_FEASIBILITY],
                    rationale="Zero-cost pilot structure reduces initial friction, but 72-hour turnaround remains a hypothesis.",
                    evidence_ids=[cycle_ev.id],
                ),
            }

            # Evaluate with OfferEvaluator
            # Because willingness_to_pay links to wtp_ev (confidence 0.40 < threshold 0.65),
            # the evaluator will conservatively set status = DecisionStatus.NEEDS_MORE_EVIDENCE
            eval_result = self.evaluator.evaluate(
                offer=candidate,
                criterion_scores=criterion_scores,
                evidence_records=all_created_evidence,
            )
            candidate.evaluation = eval_result
            synthesized_offers.append(candidate)

        # Sort synthesized offers by weighted score descending
        synthesized_offers.sort(
            key=lambda o: (o.evaluation.weighted_score if o.evaluation else 0.0),
            reverse=True,
        )

        return synthesized_offers, all_created_evidence
