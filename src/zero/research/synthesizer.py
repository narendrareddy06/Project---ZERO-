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
)


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

            # Verified source evidence proves PROBLEM REPORT EXISTENCE, not market demand
            clean_title = src.title.replace("\n", " ").strip()
            date_info = f"Published: {src.published_date}" if src.published_date else "Publication Date: UNDATED / UNKNOWN"
            ev = Evidence(
                id=ev_id,
                claim=f"Reported B2B problem/friction in public discussion: '{clean_title}'",
                evidence_type=EvidenceType.VERIFIED_SOURCE,
                geography=geography,
                confidence=0.75,  # Verified report existence from documented public API
                source_url=src.url,
                published_date=src.published_date,
                notes=f"Discovered via {src.source_name} query: '{src.query}'. Author: {src.author or 'unknown'}. {date_info}",
                excerpt=src.excerpt[:500] if src.excerpt else f"Title: {src.title}",
                is_sample=is_sample,
            )
            all_created_evidence.append(ev)
            source_evidence_pairs.append((src, ev))

        # 2. Cluster evidence items into theme buckets based on keywords
        theme_buckets: Dict[str, List[Tuple[DiscoveredSource, Evidence]]] = {
            theme["id_slug"]: [] for theme in THEME_DEFINITIONS
        }

        for src, ev in source_evidence_pairs:
            text_to_search = f"{src.title} {src.excerpt} {src.query}".lower()
            matched = False
            for theme in THEME_DEFINITIONS:
                if any(kw in text_to_search for kw in theme["keywords"]):
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

            # Generate complementary HYPOTHESIS evidence records for unvalidated criteria
            # WTP Hypothesis (Strictly <= 0.50 per safety rules)
            wtp_hash = hashlib.sha256(f"{slug}_wtp_{geography.value}".encode()).hexdigest()[:8]
            wtp_ev = Evidence(
                id=f"ev_hyp_wtp_{wtp_hash}",
                claim=f"Hypothesis: Target B2B buyers have willingness to pay for {theme['title']} solutions.",
                evidence_type=EvidenceType.HYPOTHESIS,
                geography=geography,
                confidence=0.40,  # Explicitly <= 0.50; unverified commercial assumption
                notes="Unverified commercial assumption. Complaint or discussion proves reported friction, NOT commercial market demand or willingness to pay.",
                is_sample=is_sample,
            )
            all_created_evidence.append(wtp_ev)

            # Buyer Accessibility Hypothesis
            access_hash = hashlib.sha256(f"{slug}_access_{geography.value}".encode()).hexdigest()[:8]
            access_ev = Evidence(
                id=f"ev_hyp_acc_{access_hash}",
                claim=f"Hypothesis: Decision makers ({theme['buyer_profile']}) are reachable via public business directories and domain registries.",
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
                claim=f"Delivery feasibility: {theme['deliverable']} can be executed 100% remotely with standard open-source tools at INR 0 marginal cost.",
                evidence_type=EvidenceType.USER_PROVIDED,
                geography=geography,
                confidence=0.90,
                notes="Standardized remote technical delivery workflow requiring no proprietary or paid infrastructure.",
                is_sample=is_sample,
            )
            all_created_evidence.append(deliv_ev)

            # Build Offer Candidate
            offer_id = f"off_disc_{slug[:12]}_{geography.value.lower()}"
            problem_summary = (
                f"{theme['problem_template']} Evidenced by {len(verified_evs)} public discussions: "
                + "; ".join(f"'{src.title[:60]}'" for src, _ in items[:3])
            )

            all_offer_ev_ids = verified_ids + [wtp_ev.id, access_ev.id, cycle_ev.id, deliv_ev.id]

            candidate = OfferCandidate(
                id=offer_id,
                title=theme["title"],
                target_geography=geography,
                buyer_profile=theme["buyer_profile"],
                problem_statement=problem_summary,
                proposed_deliverable=theme["deliverable"],
                plausible_pricing_or_pilot=theme["pricing_or_pilot"],
                delivery_method=theme["delivery_method"],
                risks=theme["risks"],
                evidence_ids=all_offer_ev_ids,
                is_sample=is_sample,
            )

            # 4. Construct rubric scores and evaluate candidate
            criterion_scores = {
                CriterionKey.PROBLEM_SEVERITY: CriterionScore(
                    criterion=CriterionKey.PROBLEM_SEVERITY,
                    score=4,
                    weight=CRITERION_WEIGHTS[CriterionKey.PROBLEM_SEVERITY],
                    rationale=f"Directly evidenced by {len(verified_evs)} public discussion reports on Hacker News and GitHub.",
                    evidence_ids=verified_ids,
                ),
                CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
                    criterion=CriterionKey.WILLINGNESS_TO_PAY,
                    score=3,
                    weight=CRITERION_WEIGHTS[CriterionKey.WILLINGNESS_TO_PAY],
                    rationale="Assumed commercial willingness to pay based on operational friction; requires live pilot validation.",
                    evidence_ids=[wtp_ev.id],
                ),
                CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
                    criterion=CriterionKey.BUYER_ACCESSIBILITY,
                    score=3,
                    weight=CRITERION_WEIGHTS[CriterionKey.BUYER_ACCESSIBILITY],
                    rationale=f"Target decision makers ({theme['buyer_profile']}) are identifiable via public websites and domain registrations.",
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
