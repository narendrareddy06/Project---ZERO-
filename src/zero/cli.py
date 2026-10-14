import argparse
from pathlib import Path
import sys

# Ensure src directory is in sys.path when invoked directly
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from zero.config import CONFIDENCE_THRESHOLD, DEFAULT_DB_PATH
from zero.database import Database
from zero.demos.generator import DemoAssetGenerator
from zero.prospects.discovery import ProspectDiscoveryEngine
from zero.prospects.qualification import ProspectQualificationEngine
from zero.research.evaluator import OfferEvaluator
from zero.research.evidence import EvidenceService
from zero.research.fetcher import PublicWebResearcher
from zero.schemas import (
    CRITERION_WEIGHTS,
    CriterionKey,
    CriterionScore,
    DecisionStatus,
    EvidenceType,
    Geography,
    OfferCandidate,
    ProofAsset,
    Prospect,
    ProspectStatus,
    Run,
    RunState,
    SuppressionRecord,
)

console = Console()


def get_db() -> Database:
    return Database()


def handle_status(args):
    """Handle `zero status` command."""
    db = get_db()
    conn = db.get_connection()

    # Query latest run
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1")
    latest_run = cursor.fetchone()

    # Evidence stats distinguishing production from sample data
    cursor.execute("""
        SELECT 
            evidence_type, 
            geography, 
            CASE WHEN is_sample = 1 THEN 'SAMPLE (DEMO)' ELSE 'PRODUCTION' END as origin,
            COUNT(*) as cnt 
        FROM evidence 
        GROUP BY evidence_type, geography, is_sample
    """)
    ev_stats = cursor.fetchall()

    # Offer stats distinguishing production from sample data
    cursor.execute("""
        SELECT 
            target_geography, 
            CASE WHEN is_sample = 1 THEN 'SAMPLE (DEMO)' ELSE 'PRODUCTION' END as origin,
            COUNT(*) as cnt 
        FROM offers 
        GROUP BY target_geography, is_sample
    """)
    offer_stats = cursor.fetchall()

    # Audit chain verification
    is_valid, msg, failure_seq = db.audit.verify_chain_integrity()

    # Total budget spent
    budget_spent = latest_run["budget_spent_inr"] if latest_run else 0.0

    # Build display
    console.print(Panel.fit("[bold cyan]PROJECT ZERO -- SYSTEM STATUS[/bold cyan]", border_style="cyan"))

    # Config & State Table
    info_table = Table(title="Configuration & Environment", show_header=True, header_style="bold magenta")
    info_table.add_column("Property", style="dim")
    info_table.add_column("Value")
    info_table.add_row("Database Path", str(db.db_path))

    run_stage = latest_run["current_stage"] if latest_run else "PREFLIGHT (Stage A)"
    run_status = latest_run["status"] if latest_run else "NO ACTIVE RUN"
    if latest_run and (latest_run["is_sample"] or "SAMPLE" in latest_run["status"] or "DEMO" in latest_run["status"]):
        run_status = f"{run_status} [yellow](DEMO SIMULATION ONLY - NO REAL MARKET RESEARCH COMPLETED)[/yellow]"

    info_table.add_row("Current Stage", run_stage)
    info_table.add_row("Run Status", run_status)
    info_table.add_row("Operating Budget Target", "INR 0.00")
    info_table.add_row("Actual Budget Spent", f"INR {budget_spent:.2f}")
    info_table.add_row("Confidence Threshold (Heuristic)", f"{CONFIDENCE_THRESHOLD:.2f}")
    info_table.add_row(
        "Audit Log Integrity",
        f"[green]{msg}[/green]" if is_valid else f"[bold red]TAMPERED at seq {failure_seq}: {msg}[/bold red]",
    )
    console.print(info_table)

    # Evidence breakdown table
    ev_table = Table(title="Evidence Repository Breakdown", show_header=True, header_style="bold blue")
    ev_table.add_column("Origin", style="bold")
    ev_table.add_column("Reliability Type")
    ev_table.add_column("Geography")
    ev_table.add_column("Count", justify="right")
    if ev_stats:
        for r in ev_stats:
            origin_style = "yellow" if "SAMPLE" in r["origin"] else "green"
            ev_table.add_row(f"[{origin_style}]{r['origin']}[/{origin_style}]", r["evidence_type"], r["geography"], str(r["cnt"]))
    else:
        ev_table.add_row("-", "No evidence recorded yet", "-", "0")
    console.print(ev_table)

    # Offer candidates table
    off_table = Table(title="Offer Candidates Stored", show_header=True, header_style="bold yellow")
    off_table.add_column("Origin", style="bold")
    off_table.add_column("Geography")
    off_table.add_column("Candidate Count", justify="right")
    if offer_stats:
        for r in offer_stats:
            origin_style = "yellow" if "SAMPLE" in r["origin"] else "green"
            off_table.add_row(f"[{origin_style}]{r['origin']}[/{origin_style}]", r["target_geography"], str(r["cnt"]))
    else:
        off_table.add_row("-", "No offers recorded yet", "0")
    console.print(off_table)


def handle_research(args):
    """Handle `zero research` command."""
    db = get_db()
    service = EvidenceService(db)

    if args.action == "add":
        if not args.claim:
            console.print("[red]Error: --claim is required to record evidence.[/red]")
            return

        try:
            ev_type = EvidenceType(args.type)
        except ValueError:
            console.print(f"[red]Error: Invalid evidence type '{args.type}'. Must be one of: {[e.value for e in EvidenceType]}[/red]")
            return

        try:
            geo = Geography(args.geo.upper())
        except ValueError:
            console.print(f"[red]Error: Invalid geography '{args.geo}'. Must be 'IN' or 'US'.[/red]")
            return

        confidence = float(args.confidence)
        if not (0.0 <= confidence <= 1.0):
            console.print("[red]Error: --confidence must be between 0.0 and 1.0.[/red]")
            return

        try:
            ev = service.record_evidence(
                claim=args.claim,
                evidence_type=ev_type,
                geography=geo,
                confidence=confidence,
                source_url=args.url,
                notes=args.notes or "",
                actor="USER",
                is_sample=args.sample,
            )
            origin_tag = "[yellow][SAMPLE][/yellow] " if ev.is_sample else ""
            console.print(f"[green][OK] Recorded evidence {origin_tag}[{ev.id}] ({ev.evidence_type.value}, {ev.geography.value}, conf={ev.confidence:.2f})[/green]")
        except Exception as e:
            console.print(f"[bold red]Validation Error: {e}[/bold red]")

    elif args.action == "list" or args.action is None:
        geo = Geography(args.geo.upper()) if args.geo else None
        ev_type = EvidenceType(args.type) if args.type else None
        evidence_list = service.list_evidence(geography=geo, evidence_type=ev_type)

        table = Table(title=f"Market Evidence ({len(evidence_list)} items)", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="bold")
        table.add_column("Origin")
        table.add_column("Geo", justify="center")
        table.add_column("Type")
        table.add_column("Conf", justify="right")
        table.add_column("Claim")
        table.add_column("Source URL", style="dim")

        for ev in evidence_list:
            color = "green" if ev.evidence_type == EvidenceType.VERIFIED_SOURCE else "yellow" if ev.evidence_type == EvidenceType.USER_PROVIDED else "magenta"
            origin_label = "[yellow]SAMPLE[/yellow]" if ev.is_sample else "[green]PROD[/green]"
            table.add_row(
                ev.id,
                origin_label,
                ev.geography.value,
                f"[{color}]{ev.evidence_type.value}[/{color}]",
                f"{ev.confidence:.2f}",
                ev.claim[:60] + ("..." if len(ev.claim) > 60 else ""),
                ev.source_url or "[none]",
            )
        console.print(table)

    elif args.action == "fetch":
        if not args.url or not args.claim:
            console.print("[red]Error: --url and --claim are required for fetch.[/red]")
            return
        geo = Geography(args.geo.upper()) if args.geo else Geography.IN
        researcher = PublicWebResearcher()
        console.print(f"[cyan]Fetching public source with rate-limits & robots check: {args.url}[/cyan]")
        excerpt_obj, ev_obj = researcher.research_and_extract(
            url=args.url,
            claim=args.claim,
            geography=geo,
            is_sample=args.sample,
        )
        researcher.close()
        db = get_db()
        db.save_evidence(ev_obj, actor="AGENT")

        console.print(Panel.fit(f"[bold]Public Research Result[/bold] (HTTP {excerpt_obj.http_status})", border_style="cyan"))
        console.print(f"[bold]Claim:[/bold] {ev_obj.claim}")
        console.print(f"[bold]Evidence Classification:[/bold] {ev_obj.evidence_type.value} (Confidence: {ev_obj.confidence:.2f})")
        console.print(f"[bold]Supports Claim:[/bold] {'[green]YES[/green]' if excerpt_obj.supports_claim else '[yellow]NO (Hypothesis / Insufficient)[/yellow]'}")
        console.print(f"[bold]Extracted Excerpt:[/bold]\n{excerpt_obj.excerpt}")
        console.print(f"[bold]Notes:[/bold] {excerpt_obj.relevance_notes}")


def handle_evaluate(args):
    """Handle `zero evaluate` command."""
    db = get_db()
    evaluator = OfferEvaluator()

    if args.action == "list" or args.action is None:
        geo = Geography(args.geo.upper()) if args.geo else None
        offers = db.list_offers(geography=geo)

        table = Table(title=f"Candidate Business Offers ({len(offers)} offers)", show_header=True, header_style="bold green")
        table.add_column("ID", style="bold")
        table.add_column("Origin")
        table.add_column("Geo", justify="center")
        table.add_column("Title")
        table.add_column("Target Buyer")
        table.add_column("Status")
        table.add_column("Score", justify="right")

        for off in offers:
            origin_label = "[yellow]SAMPLE[/yellow]" if off.is_sample else "[green]PROD[/green]"
            status_str = "PENDING"
            score_str = "-"
            if off.evaluation:
                if off.evaluation.status == DecisionStatus.SELECTED:
                    status_str = "[yellow]SELECTED (DEMO)[/yellow]" if off.is_sample else "[green]SELECTED[/green]"
                elif off.evaluation.status == DecisionStatus.REJECTED:
                    status_str = "[red]REJECTED[/red]"
                else:
                    status_str = "[yellow]NEEDS_MORE_EVIDENCE[/yellow]"
                score_str = f"{off.evaluation.weighted_score:.2f}/5.0"

            table.add_row(
                off.id,
                origin_label,
                off.target_geography.value,
                off.title,
                off.buyer_profile[:40] + ("..." if len(off.buyer_profile) > 40 else ""),
                status_str,
                score_str,
            )
        console.print(table)

    elif args.action == "show":
        if not args.offer_id:
            console.print("[red]Error: offer_id is required.[/red]")
            return
        off = db.get_offer(args.offer_id)
        if not off:
            console.print(f"[red]Offer not found: {args.offer_id}[/red]")
            return

        if off.is_sample:
            console.print(Panel("[bold yellow]NOTICE: This offer is synthetic demonstration/sample data. It is NOT a validated real-world market recommendation.[/bold yellow]", border_style="yellow"))

        console.print(Panel.fit(f"[bold]{off.title}[/bold] ({off.id})", border_style="green"))
        console.print(f"[bold]Data Origin:[/bold] {'[yellow]SAMPLE (DEMONSTRATION)[/yellow]' if off.is_sample else '[green]PRODUCTION[/green]'}")
        console.print(f"[bold]Target Geography:[/bold] {off.target_geography.value}")
        console.print(f"[bold]Target Buyer:[/bold] {off.buyer_profile}")
        console.print(f"[bold]Problem Statement:[/bold] {off.problem_statement}")
        console.print(f"[bold]Deliverable:[/bold] {off.proposed_deliverable}")
        console.print(f"[bold]Pricing / Pilot:[/bold] {off.plausible_pricing_or_pilot}")
        console.print(f"[bold]Delivery Method:[/bold] {off.delivery_method}")
        console.print(f"[bold]Risks:[/bold] {', '.join(off.risks) if off.risks else 'None recorded'}")
        console.print(f"[bold]Linked Evidence IDs:[/bold] {', '.join(off.evidence_ids) if off.evidence_ids else 'None'}")

        if off.evaluation:
            console.print("\n[bold cyan]--- Evaluation Rubric Breakdown ---[/bold cyan]")
            rubric_table = Table(show_header=True, header_style="bold magenta")
            rubric_table.add_column("Criterion")
            rubric_table.add_column("Weight", justify="right")
            rubric_table.add_column("Score (1-5)", justify="right")
            rubric_table.add_column("Weighted", justify="right")
            rubric_table.add_column("Rationale")

            for crit_key in CriterionKey:
                cs = off.evaluation.criterion_scores.get(crit_key.value)
                if cs:
                    comp = cs.score * cs.weight
                    rubric_table.add_row(
                        crit_key.value,
                        f"{int(cs.weight * 100)}%",
                        f"{cs.score}/5",
                        f"{comp:.2f}",
                        cs.rationale,
                    )
            console.print(rubric_table)
            console.print(f"\n[bold]Total Weighted Score:[/bold] {off.evaluation.weighted_score:.2f} / 5.0")
            console.print(f"[bold]Average Evidence Confidence:[/bold] {off.evaluation.average_confidence:.2f}")
            status_color = "green" if off.evaluation.status == DecisionStatus.SELECTED else "red" if off.evaluation.status == DecisionStatus.REJECTED else "yellow"
            console.print(f"[bold]Decision Status:[/bold] [{status_color}]{off.evaluation.status.value}[/{status_color}]")
            for reason in off.evaluation.reasons:
                console.print(f"  - {reason}")


def handle_prospects(args):
    """Handle `zero prospects` commands."""
    db = get_db()

    if args.action == "list" or args.action is None:
        prospects = db.list_prospects(
            associated_offer_id=args.offer,
            status=ProspectStatus(args.status.upper()) if args.status else None,
            is_sample=True if args.sample else None,
        )
        table = Table(title=f"Business Prospects ({len(prospects)} items)", show_header=True, header_style="bold blue")
        table.add_column("ID", style="bold")
        table.add_column("Origin")
        table.add_column("Company")
        table.add_column("Domain")
        table.add_column("Geo", justify="center")
        table.add_column("Status")
        table.add_column("Fit Score", justify="right")
        table.add_column("Public Facts")

        for p in prospects:
            color = "green" if p.status == ProspectStatus.QUALIFIED else "yellow" if p.status == ProspectStatus.DISCOVERED else "red"
            origin = "[yellow]SAMPLE[/yellow]" if p.is_sample else "[green]PROD[/green]"
            facts_summary = f"{len(p.verified_facts.get('identified_services', []))} services"
            if "public_contact_email" in p.verified_facts:
                facts_summary += f", {len(p.verified_facts['public_contact_email'])} emails"

            table.add_row(
                p.id,
                origin,
                p.company_name[:25],
                p.domain_or_website,
                p.geography.value,
                f"[{color}]{p.status.value}[/{color}]",
                f"{p.fit_score:.2f}/5.0" if p.fit_score is not None else "-",
                facts_summary,
            )
        console.print(table)

    elif args.action == "discover":
        if not args.url or not args.source:
            console.print("[red]Error: --url and --source are required for prospect discovery.[/red]")
            return
        geo = Geography(args.geo.upper()) if args.geo else Geography.IN
        discovery = ProspectDiscoveryEngine(db)
        try:
            prospect, is_new, msg = discovery.discover_from_public_url(
                company_website_url=args.url,
                public_source_url=args.source,
                geography=geo,
                industry_or_niche=args.niche or "Technology & Professional Services",
                associated_offer_id=args.offer,
                is_sample=args.sample,
            )
            if prospect:
                status_color = "green" if prospect.status == ProspectStatus.DISCOVERED else "yellow"
                console.print(f"[{status_color}][OK] {msg} Prospect ID: {prospect.id} ({prospect.company_name}, {prospect.domain_or_website})[/{status_color}]")
            else:
                console.print(f"[red][FAILED] {msg}[/red]")
        except Exception as e:
            console.print(f"[bold red]Discovery Error: {e}[/bold red]")

    elif args.action == "qualify":
        if not args.id or not args.offer:
            console.print("[red]Error: --id (prospect ID) and --offer (offer ID) are required.[/red]")
            return
        prospect = db.get_prospect(args.id)
        if not prospect:
            console.print(f"[red]Error: Prospect '{args.id}' not found.[/red]")
            return
        offer = db.get_offer(args.offer)
        if not offer:
            console.print(f"[red]Error: Offer '{args.offer}' not found.[/red]")
            return
        engine = ProspectQualificationEngine(db)
        prospect, is_qual, rationale = engine.qualify_prospect(prospect, offer)
        res_color = "green" if is_qual else "yellow"
        console.print(Panel.fit(f"[bold]Prospect Qualification: {prospect.company_name}[/bold]", border_style=res_color))
        console.print(f"[bold]Status:[/bold] [{res_color}]{prospect.status.value}[/{res_color}]")
        console.print(f"[bold]Fit Score:[/bold] {prospect.fit_score:.2f} / 5.0")
        console.print(f"[bold]Rationale:[/bold] {rationale}")


def handle_suppression(args):
    """Handle `zero suppression` commands."""
    db = get_db()
    if args.action == "list" or args.action is None:
        records = db.list_suppression()
        table = Table(title=f"Suppression / Opt-Out List ({len(records)} entries)", show_header=True, header_style="bold red")
        table.add_column("Domain / Email", style="bold")
        table.add_column("Reason")
        table.add_column("Added At")
        table.add_column("Notes")

        for r in records:
            table.add_row(r.domain_or_email, r.reason, r.added_at.strftime("%Y-%m-%d %H:%M"), r.notes or "")
        console.print(table)

    elif args.action == "add":
        if not args.identifier or not args.reason:
            console.print("[red]Error: identifier and --reason are required.[/red]")
            return
        record = SuppressionRecord(
            domain_or_email=args.identifier,
            reason=args.reason,
            notes=args.notes or "",
        )
        db.add_suppression(record, actor="USER")
        console.print(f"[green][OK] Added '{record.domain_or_email}' to suppression registry ({record.reason}).[/green]")

    elif args.action == "check":
        if not args.identifier:
            console.print("[red]Error: identifier is required.[/red]")
            return
        is_sup = db.is_suppressed(args.identifier)
        if is_sup:
            console.print(f"[red][SUPPRESSED] '{args.identifier}' is on the suppression list. Contact strictly prohibited.[/red]")
        else:
            console.print(f"[green][CLEAR] '{args.identifier}' is NOT on the suppression list.[/green]")


def handle_demo(args):
    """Handle `zero demo` commands."""
    db = get_db()

    if args.action == "create":
        if not args.offer:
            console.print("[red]Error: --offer is required.[/red]")
            return
        offer = db.get_offer(args.offer)
        if not offer:
            console.print(f"[red]Error: Offer '{args.offer}' not found.[/red]")
            return
        generator = DemoAssetGenerator(db)
        asset = generator.generate_proof_asset(
            offer=offer,
            asset_type=args.type or "AUDIT_CHECKLIST",
            title=args.title,
        )
        console.print(f"[green][OK] Proof asset created: {asset.id} ('{asset.title}')[/green]")
        console.print(Panel(f"[yellow]{asset.disclaimer}[/yellow]", title="Mandatory Demonstration Notice", border_style="yellow"))

    elif args.action == "list" or args.action is None:
        assets = db.list_proof_assets(offer_id=args.offer)
        table = Table(title=f"Demonstration Proof Assets ({len(assets)} items)", show_header=True, header_style="bold yellow")
        table.add_column("Asset ID", style="bold")
        table.add_column("Offer ID")
        table.add_column("Type")
        table.add_column("Title")
        table.add_column("Created At")

        for a in assets:
            table.add_row(a.id, a.offer_id, a.asset_type, a.title, a.created_at.strftime("%Y-%m-%d %H:%M"))
        console.print(table)

    elif args.action == "show":
        if not args.id:
            console.print("[red]Error: asset ID is required.[/red]")
            return
        asset = db.get_proof_asset(args.id)
        if not asset:
            console.print(f"[red]Error: Proof asset '{args.id}' not found.[/red]")
            return
        console.print(Panel.fit(f"[bold]{asset.title}[/bold] ({asset.id})", border_style="yellow"))
        console.print(f"[bold yellow]DISCLAIMER:[/bold yellow] {asset.disclaimer}\n")
        console.print(asset.content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zero",
        description="Project ZERO — Autonomous B2B Customer-Acquisition Agent CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # zero status
    subparsers.add_parser("status", help="Show system status, configuration, evidence stats, and audit integrity")

    # zero research
    research_parser = subparsers.add_parser("research", help="Manage and inspect market research evidence")
    research_sub = research_parser.add_subparsers(dest="action")

    # zero research list
    res_list = research_sub.add_parser("list", help="List stored market evidence")
    res_list.add_argument("--geo", choices=["IN", "US", "in", "us"], help="Filter by geography")
    res_list.add_argument("--type", choices=[e.value for e in EvidenceType], help="Filter by evidence reliability type")

    # zero research add
    res_add = research_sub.add_parser("add", help="Record a new piece of market evidence")
    res_add.add_argument("--claim", required=True, help="Specific claim about market need or behavior")
    res_add.add_argument("--type", required=True, choices=[e.value for e in EvidenceType], help="Evidence reliability type")
    res_add.add_argument("--geo", required=True, choices=["IN", "US", "in", "us"], help="Applicable geography")
    res_add.add_argument("--confidence", required=True, type=float, help="Confidence from 0.0 to 1.0")
    res_add.add_argument("--url", help="Public source URL if verified")
    res_add.add_argument("--notes", help="Context or caveats")
    res_add.add_argument("--sample", action="store_true", default=False, help="Explicitly mark as demonstration/sample data")

    # zero research fetch
    res_fetch = research_sub.add_parser("fetch", help="Retrieve public web page and verify claim support")
    res_fetch.add_argument("url", help="Public page URL to fetch")
    res_fetch.add_argument("--claim", required=True, help="Asserted claim to evaluate against page content")
    res_fetch.add_argument("--geo", choices=["IN", "US", "in", "us"], default="IN", help="Geography")
    res_fetch.add_argument("--sample", action="store_true", default=False, help="Mark as demonstration/sample data")

    # zero evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Inspect and evaluate offer candidates")
    eval_sub = eval_parser.add_subparsers(dest="action")

    # zero evaluate list
    eval_list = eval_sub.add_parser("list", help="List all candidate offers and evaluation statuses")
    eval_list.add_argument("--geo", choices=["IN", "US", "in", "us"], help="Filter by geography")

    # zero evaluate show
    eval_show = eval_sub.add_parser("show", help="Show detailed evaluation rubric breakdown for an offer")
    eval_show.add_argument("offer_id", help="Offer ID to inspect")

    # zero prospects
    prosp_parser = subparsers.add_parser("prospects", help="Discover, list, and qualify business prospects")
    prosp_sub = prosp_parser.add_subparsers(dest="action")

    # zero prospects list
    prosp_list = prosp_sub.add_parser("list", help="List discovered prospects")
    prosp_list.add_argument("--offer", help="Filter by associated offer ID")
    prosp_list.add_argument("--status", choices=["DISCOVERED", "QUALIFIED", "DISQUALIFIED", "SUPPRESSED"], help="Filter by status")
    prosp_list.add_argument("--sample", action="store_true", default=False, help="Filter demonstration prospects")

    # zero prospects discover
    prosp_disc = prosp_sub.add_parser("discover", help="Discover a prospect from permitted public company URL")
    prosp_disc.add_argument("--url", required=True, help="Public website of the company")
    prosp_disc.add_argument("--source", required=True, help="Permitted public source URL where business was found")
    prosp_disc.add_argument("--geo", choices=["IN", "US", "in", "us"], default="IN", help="Target geography")
    prosp_disc.add_argument("--niche", help="Industry sector or specialty")
    prosp_disc.add_argument("--offer", help="Candidate offer ID to associate")
    prosp_disc.add_argument("--sample", action="store_true", default=False, help="Mark as demonstration data")

    # zero prospects qualify
    prosp_qual = prosp_sub.add_parser("qualify", help="Evaluate prospect fit against an offer candidate")
    prosp_qual.add_argument("--id", required=True, help="Prospect ID to qualify")
    prosp_qual.add_argument("--offer", required=True, help="Offer candidate ID to evaluate against")

    # zero suppression
    supp_parser = subparsers.add_parser("suppression", help="Manage suppression and do-not-contact records")
    supp_sub = supp_parser.add_subparsers(dest="action")

    # zero suppression list
    supp_sub.add_parser("list", help="List all suppression records")

    # zero suppression add
    supp_add = supp_sub.add_parser("add", help="Add domain or email to suppression list")
    supp_add.add_argument("identifier", help="Domain or email address to suppress")
    supp_add.add_argument("--reason", required=True, help="Reason: OPT_OUT, DO_NOT_CONTACT, COMPETITOR, etc.")
    supp_add.add_argument("--notes", help="Optional context or notes")

    # zero suppression check
    supp_chk = supp_sub.add_parser("check", help="Check if an identifier is suppressed")
    supp_chk.add_argument("identifier", help="Domain or email address to check")

    # zero demo
    demo_parser = subparsers.add_parser("demo", help="Generate and inspect truthful demonstration proof assets")
    demo_sub = demo_parser.add_subparsers(dest="action")

    # zero demo create
    demo_create = demo_sub.add_parser("create", help="Create a proof asset for an offer")
    demo_create.add_argument("--offer", required=True, help="Offer ID to generate proof asset for")
    demo_create.add_argument("--type", choices=["AUDIT_CHECKLIST", "SPECIFICATION", "PROTOTYPE_WALKTHROUGH"], default="AUDIT_CHECKLIST")
    demo_create.add_argument("--title", help="Custom asset title")

    # zero demo list
    demo_list = demo_sub.add_parser("list", help="List proof assets")
    demo_list.add_argument("--offer", help="Filter by offer ID")

    # zero demo show
    demo_show = demo_sub.add_parser("show", help="Display proof asset content and mandatory notice")
    demo_show.add_argument("id", help="Proof asset ID")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "status":
        handle_status(args)
    elif args.command == "research":
        handle_research(args)
    elif args.command == "evaluate":
        handle_evaluate(args)
    elif args.command == "prospects":
        handle_prospects(args)
    elif args.command == "suppression":
        handle_suppression(args)
    elif args.command == "demo":
        handle_demo(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
