# PROJECT ZERO — Architecture Audit Report

**Generated:** 2026-11-05  
**Auditor:** Antigravity (AI Code Agent, read-only inspection)  
**Status:** INSPECTION COMPLETE — No source files were modified.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Existing Architecture](#2-existing-architecture)
3. [End-to-End Data Flow](#3-end-to-end-data-flow)
4. [Feature Inventory](#4-feature-inventory)
5. [Broken and Incomplete Components](#5-broken-and-incomplete-components)
6. [Research Failure Diagnosis](#6-research-failure-diagnosis)
7. [Technology Stack Assessment](#7-technology-stack-assessment)
8. [Target Architecture (Intended Product Workflow)](#8-target-architecture-intended-product-workflow)
9. [Gap Analysis](#9-gap-analysis)
10. [Phased Roadmap](#10-phased-roadmap)
11. [Recommended Next Task](#11-recommended-next-task)

---

## 1. Executive Summary

Project ZERO is a Python CLI tool that aspires to be a **B2B Opportunity-to-Client Acquisition Agent** but currently operates as an **evidence ledger and conservative scoring system**. It has a solid compliance and safety foundation — hash-chained audit logs, budget enforcement, LinkedIn prohibition, suppression lists — but lacks the intelligence-gathering, human interaction, outreach, and tracking workflows needed to function end-to-end.

**Current capability:** Discover public forum posts via permitted APIs, classify them into one of 6 pre-defined offer themes, score them conservatively (all end up `NEEDS_MORE_EVIDENCE`), and persist them to SQLite.

**Missing capability:** Human opportunity selection UI, autonomous prospect discovery from opportunities, email verification, outreach drafting and approval, reply tracking, and any form of LLM or semantic analysis.

**Test coverage:** 76 unit tests, all passing in 5.12 seconds (sandbox, no network).

---

## 2. Existing Architecture

### 2.1 Project Layout

```
d:\Project Zero\
├── src/zero/
│   ├── __init__.py
│   ├── cli.py              (778 lines — single-file CLI entrypoint, all command handlers)
│   ├── config.py           (env-based configuration, DEFAULT_DB_PATH, CONFIDENCE_THRESHOLD)
│   ├── schemas.py          (295 lines — Pydantic v2 models, all business entities)
│   ├── database.py         (634 lines — SQLite persistence layer, full CRUD)
│   ├── audit.py            (161 lines — SHA-256 hash-chained audit log)
│   ├── research/
│   │   ├── __init__.py
│   │   ├── autonomous.py   (233 lines — AutonomousDiscoveryEngine, query builder, dedup)
│   │   ├── evaluator.py    (192 lines — OfferEvaluator, 5-criterion rubric)
│   │   ├── evidence.py     (66 lines — EvidenceService wrapper)
│   │   ├── fetcher.py      (468 lines — PublicWebResearcher, HTML extractor, robots.txt)
│   │   ├── sources.py      (427 lines — HnAlgoliaSource, GitHubIssuesSource, WigoloDiscoverySource, ExcludedSource)
│   │   ├── synthesizer.py  (340 lines — OpportunitySynthesizer, 6 THEME_DEFINITIONS)
│   │   └── wigolo_client.py (238 lines — JSON-RPC 2.0 stdio client for Wigolo MCP)
│   ├── demos/
│   │   └── generator.py    (93 lines — DemoAssetGenerator, creates markdown proof assets)
│   └── prospects/
│       ├── discovery.py    (178 lines — ProspectDiscoveryEngine, public page fetch + extraction)
│       └── qualification.py (99 lines — ProspectQualificationEngine, 3-criterion scoring)
├── tests/unit/             (11 test files, 76 tests total)
├── data/
│   └── project_zero.db    (~208 KB SQLite, 122 audit events, 65 evidence items, 7 offers, 0 prospects)
├── docs/
│   └── Project_ZERO_PRD.docx
├── examples/
│   └── seed_stage_a_demo.py
├── pyproject.toml
├── .env.example
├── AGENTS.md
└── README.md
```

### 2.2 Data Models (`schemas.py`)

| Model | Purpose | Key Fields |
|---|---|---|
| `Evidence` | A single unit of market evidence | `id`, `claim`, `evidence_type`, `geography`, `confidence`, `source_url`, `excerpt`, `is_sample` |
| `OfferCandidate` | A B2B offer hypothesis | `id`, `title`, `buyer_profile`, `problem_statement`, `proposed_deliverable`, `evidence_ids`, `evaluation` |
| `EvaluationResult` | Rubric scoring output | `status`, `weighted_score`, `criterion_scores`, `average_confidence`, `missing_evidence_criteria` |
| `Prospect` | A real business prospect | `id`, `company_name`, `domain_or_website`, `geography`, `fit_score`, `verified_facts`, `assumptions` |
| `ProofAsset` | Demo artifact with mandatory disclaimer | `id`, `offer_id`, `content`, `disclaimer` |
| `Run` | A single agent execution run | `run_id`, `current_stage`, `budget_spent_inr`, `is_sample` |
| `AuditEvent` | Hash-chained audit entry | `sequence`, `actor`, `action`, `payload_hash`, `prev_hash`, `event_hash` |
| `DiscoveredSource` | Raw finding from a source adapter | `source_name`, `title`, `url`, `excerpt`, `published_date`, `query` |
| `SuppressionRecord` | Do-not-contact record | `domain_or_email`, `reason` |

### 2.3 Database Schema (SQLite)

Seven tables in `data/project_zero.db`:

- **`runs`** — execution run state machine
- **`evidence`** — market evidence items (65 records as of audit)
- **`offers`** — synthesized offer candidates (7 records)
- **`prospects`** — discovered business prospects (0 records)
- **`proof_assets`** — markdown demo artifacts
- **`suppression_list`** — opt-out / do-not-contact registry
- **`audit_events`** — 122 hash-chained events

Schema migration is applied inline at startup via `PRAGMA table_info` checks with `ALTER TABLE … ADD COLUMN`.

### 2.4 CLI Commands

```
zero status                           # System health, evidence/offer stats, audit integrity
zero research list [--geo] [--type]   # List evidence records
zero research add --claim --type ...  # Manually record evidence
zero research fetch <url> --claim ... # Fetch public URL, extract excerpt, persist
zero research sources                 # List active/excluded source adapters
zero research auto [--geo] [--focus] [--sources] [--limit] [--sample]
                                      # Autonomous opportunity discovery (key command)
zero evaluate list [--geo]            # List offer candidates
zero evaluate show <offer_id>         # Show rubric breakdown for one offer
zero prospects list                   # List discovered prospects
zero prospects discover --url --source # Discover a prospect from public URL
zero prospects qualify --id --offer   # Score prospect fit against an offer
zero suppression list                 # List suppression records
zero suppression add <id> --reason    # Add entry to suppression list
zero suppression check <id>           # Check if identifier is suppressed
zero demo create --offer <id>         # Generate proof-of-concept markdown asset
zero demo list                        # List generated demo assets
zero demo show <asset_id>             # Display asset content
```

### 2.5 Source Adapters

| Adapter | Status | API | Rate Limit | Cost |
|---|---|---|---|---|
| `HnAlgoliaSource` | ✅ ACTIVE | `https://hn.algolia.com/api/v1/search` | 10,000 req/hr | ₹0 |
| `GitHubIssuesSource` | ✅ ACTIVE | `https://api.github.com/search/issues` | 10 req/min (unauth) | ₹0 |
| `WigoloDiscoverySource` | ✅ ACTIVE | Local Wigolo MCP process (stdio JSON-RPC 2.0) | Local process | ₹0 |
| `ExcludedSource` (reddit_rss) | ❌ EXCLUDED | robots.txt Disallow | — | — |
| `ExcludedSource` (duckduckgo_lite) | ❌ EXCLUDED | robots.txt Disallow | — | — |

### 2.6 Audit System

`AuditManager` (in `audit.py`) maintains a **cryptographic SHA-256 hash chain** in the `audit_events` table:

- Each event records `sequence`, `timestamp`, `actor`, `action`, `payload_hash`, `prev_hash`, `event_hash`
- Chain can be verified with `verify_chain_integrity()` which replays all events
- **Limitation acknowledged in source**: An adversary with direct SQLite write access could recompute the chain (no external trust anchor)
- 122 events recorded as of this audit

---

## 3. End-to-End Data Flow

```
User runs: python -m zero.cli research auto --geo IN --sources hn
                            │
                   cli.py: handle_research(args)
                            │
                   AutonomousDiscoveryEngine.discover_opportunities()
                            │
                   build_discovery_queries(focus_areas, geography)
                   → produces 3 hard-coded query templates × focus terms
                   e.g., "b2b deliverability problem India"
                            │
              ┌─────────────┴─────────────────────────┐
              ▼                                         ▼
    HnAlgoliaSource.search(q)              GitHubIssuesSource.search(q)
    → GET https://hn.algolia.com/api/v1/   → GET https://api.github.com/
      search?query=...&tags=(story,comment)   search/issues?q=...is:issue
    → Returns hits[]: {title, url, text}   → Returns items[]: {title, url, body}
    → Creates DiscoveredSource per hit     → Creates DiscoveredSource per item
              │                                         │
              └─────────────────────────────────────────┘
                            │
                   URL normalization + content fingerprint dedup
                   (normalize_url, compute_content_fingerprint)
                            │
                   OpportunitySynthesizer.synthesize(discovered_sources)
                            │
                   For each DiscoveredSource:
                     → Creates Evidence(VERIFIED_SOURCE, confidence=0.75)
                       claim: "Reported B2B problem in public discussion: '<title>'"
                   For each matched THEME_DEFINITION (6 themes by keyword):
                     → Creates 3 HYPOTHESIS evidence records (WTP=0.40, Buyer=0.50, Sales=0.45)
                     → Creates 1 USER_PROVIDED evidence record (Delivery=0.90)
                     → Builds OfferCandidate with pre-written buyer_profile, deliverable, risks
                     → OfferEvaluator.evaluate() → status = NEEDS_MORE_EVIDENCE
                       (because WTP evidence confidence 0.40 < threshold 0.65)
                            │
                   Database.save_evidence() × N records
                   Database.save_offer() × M candidates
                   AuditManager.record_event("AUTONOMOUS_OPPORTUNITY_DISCOVERY")
                            │
                   Return AutonomousDiscoveryResult to CLI
                            │
                   CLI renders Rich tables to terminal
                   (sources found, candidate offers, conservative gating notice)
```

**All offer candidates always evaluate to `NEEDS_MORE_EVIDENCE`** because the WTP hypothesis evidence is explicitly capped at 0.40 confidence, which is below the 0.65 threshold hardcoded in `OfferEvaluator`.

---

## 4. Feature Inventory

### IMPLEMENTED AND UNIT-TESTED

| Feature | Module | Test File | Status |
|---|---|---|---|
| Pydantic data models with validators | `schemas.py` | `test_schemas.py` | ✅ Working |
| SQLite persistence (CRUD for all entities) | `database.py` | `test_database.py` | ✅ Working |
| Hash-chained audit log | `audit.py` | `test_audit.py` | ✅ Working |
| Evidence recording CLI (`research add`) | `cli.py` | `test_cli.py` | ✅ Working |
| `HnAlgoliaSource` search adapter | `sources.py` | `test_autonomous_discovery.py` | ✅ Working |
| `GitHubIssuesSource` search adapter | `sources.py` | `test_autonomous_discovery.py` | ✅ Working |
| `WigoloDiscoverySource` stub adapter | `sources.py` | `test_wigolo_discovery.py` | ✅ Working (mock) |
| Wigolo MCP stdio client | `wigolo_client.py` | `test_wigolo_discovery.py` | ✅ Working (mock) |
| URL normalization + content fingerprinting | `autonomous.py` | `test_autonomous_discovery.py` | ✅ Working |
| `OpportunitySynthesizer` (6 themes) | `synthesizer.py` | `test_autonomous_discovery.py` | ✅ Working |
| `OfferEvaluator` (5-criterion rubric) | `evaluator.py` | `test_evaluator.py` | ✅ Working |
| `EvidenceService` wrapper | `evidence.py` | `test_autonomous_discovery.py` | ✅ Working |
| `PublicWebResearcher` (HTML extract + robots.txt) | `fetcher.py` | `test_research_fetcher.py` | ✅ Working |
| `research auto` CLI command | `cli.py` | `test_cli.py` | ✅ Working |
| `ProspectDiscoveryEngine` (public page fetch) | `prospects/discovery.py` | `test_prospects.py` | ✅ Working |
| `ProspectQualificationEngine` (3-criterion fit) | `prospects/qualification.py` | `test_prospects.py` | ✅ Working |
| `DemoAssetGenerator` (markdown proof assets) | `demos/generator.py` | `test_demo_assets.py` | ✅ Working |
| Suppression list (add/check/list) | `database.py` + `cli.py` | `test_stage_b_safety_and_budget.py` | ✅ Working |
| Sample/production data separation | `schemas.py`, `database.py` | `test_stage_b_safety_and_budget.py` | ✅ Working |
| Budget enforcement (zero paid APIs) | `config.py`, `sources.py` | `test_zero_budget.py` | ✅ Working |
| LinkedIn prohibition (validator) | `schemas.py` | `test_stage_b_safety_and_budget.py` | ✅ Working |
| `research sources` list command | `cli.py` | `test_cli.py` | ✅ Working |

### PRESENT IN CODE BUT NOT FULLY FUNCTIONAL

| Feature | Module | Gap | Notes |
|---|---|---|---|
| Wigolo live integration | `wigolo_client.py` | Requires `BypassSandbox: true` in Antigravity (sandbox blocks `C:\Users\Narendra\.wigolo` mkdir) | Works in real environment via `node D:\wigolo\dist\index.js` |
| `research fetch` command | `cli.py` + `fetcher.py` | Makes live HTTP requests; works in unblocked environment | Robots.txt compliance implemented |
| `prospects discover` | `cli.py` + `discovery.py` | Requires live HTTP to target company website | HTML extraction + email regex works on fetched content |
| Demo asset export | `demos/generator.py` | Writes markdown to `data/demos/`; works but content is generic boilerplate | No real specification detail |

### NOT IMPLEMENTED

| Feature | Location | Status |
|---|---|---|
| Human opportunity selection UI | Missing | No interactive CLI or web UI for human pick |
| Opportunity presentation + selection persistence | Missing | Candidates are listed but never marked as "selected by user" |
| Automated prospect discovery from selected opportunity | Missing | `prospects discover` requires user-supplied URL |
| Email verification | Missing | Email regex extracts visible addresses from public pages only; no SMTP verification, MX lookup, or Catch-All detection |
| Outreach draft generation | Missing | No templating engine for personalized pitch emails |
| User approval workflow for outreach | Missing | No confirmation step before sending |
| Email sending integration | Missing | No SMTP/API integration; `GEMINI_API_KEY` and `GROQ_API_KEY` env vars defined but unused |
| Reply tracking | Missing | No concept of sent messages, reply classification, or thread management |
| Pilot proposal workflow | Missing | RunState has `PILOT_PROPOSAL` state but no handler |
| Handover workflow | Missing | RunState has `HANDOVER` state but no handler |
| AI/LLM integration | Missing | No calls to any LLM for semantic analysis, claim generation, or email drafting |
| Semantic relevance filtering | Missing | Search results are accepted by keyword match only; no content quality gate |
| Content fetching in discovery | Missing | `WigoloDiscoverySource` defaults `include_content=False`, `search_depth="fast"` |
| RSS source adapters | Missing | Intentionally excluded pending robots.txt verification |
| Cluster analysis (beyond keyword) | Missing | Themes matched by substring, not embeddings or semantic similarity |

---

## 5. Broken and Incomplete Components

### 5.1 `WigoloDiscoverySource` — Search Quality Problem

**What's broken:** The `search()` method passes `search_depth="fast"` and `include_content=False` to the Wigolo client. This was deliberately set to prevent timeouts but means:
- Only search engine snippets are returned (no actual page content)
- Snippets from DuckDuckGo-based results can be generic or unrelated to B2B problems
- No validation that the returned URL actually contains a problem discussion

**Impact:** Live runs with `--sources wigolo` returned Wikipedia pages, Microsoft Learn docs, and B2B portal homepages — none of which represent problem discussions.

### 5.2 `OpportunitySynthesizer` — Confidence Score is Static

**What's broken:** Every `DiscoveredSource`, regardless of content quality, is recorded as `Evidence(confidence=0.75)`. A result titled "Microsoft Azure Documentation" receives the same confidence as a genuine HN "Ask HN: How do you handle webhook failures?" post.

**Impact:** The `confidence=0.75` claim label reads "Verified report existence from documented public API" — this is misleading because it validates the API call, not the problem report content.

### 5.3 `OfferEvaluator` — Conservative Gate Prevents Any SELECTED Status

**What's by design but needs documentation:** The WTP hypothesis evidence is always `confidence=0.40`. The evaluator checks:
```python
if key in (PROBLEM_SEVERITY, WILLINGNESS_TO_PAY):
    max_confidence = max((ev.confidence for ev in linked), default=0.0)
    if max_confidence < self.confidence_threshold:  # 0.65
        missing_evidence_criteria.append(...)
```

Since `0.40 < 0.65`, all auto-discovered offers are always `NEEDS_MORE_EVIDENCE`. This is **intentionally conservative** per the PRD but means no offer can ever be selected without human intervention to add higher-confidence WTP evidence.

### 5.4 `ProspectDiscoveryEngine` — Email Extraction is Unreliable

**What's broken:** The email extraction uses a broad regex on raw HTML text:
```python
re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", clean_text)
```
This finds any string matching the email pattern on any public page, including spam bait, schema-encoded text, and SVG asset filenames. There is no MX validation, SMTP ping, or catch-all detection.

### 5.5 Missing `RunState` State Machine Transitions

**What's broken:** `RunState` defines 17 states (`RESEARCH`, `OFFER_DECISION`, `DEMO`, `PROSPECTING`, `DRAFTING`, `AWAITING_APPROVAL`, `OUTREACH`, `REPLY_HANDLING`, `PILOT_PROPOSAL`, `HANDOVER`, etc.), but only `CREATED`, `RESEARCH`, and `NEEDS_MORE_EVIDENCE` are reachable through existing code. `update_run_stage()` is called only for the `research auto` path.

### 5.6 `DemoAssetGenerator` — Generic Content Only

**What's present:** The generator creates a markdown template with standard headings (Problem Context, Proposed Deliverable Specification, Operational Verification Checklist, Risk Assessment). The content is populated from the `OfferCandidate` fields.

**What's missing:** No actual demo specification — no real data sample, no code example, no acceptance criteria list, no visual walkthrough. It is a disclaimer + field-mapping template, not an actionable demo spec.

---

## 6. Research Failure Diagnosis

The `python -m zero.cli research auto --geo IN --sources wigolo --limit 2 --sample` command returned irrelevant URLs in a previous session. Root causes:

| # | Root Cause | Location | Evidence |
|---|---|---|---|
| 1 | **No relevance filtering on search results** | `WigoloDiscoverySource.search()` | Any URL with valid `https://` scheme is accepted. Wigolo's underlying DuckDuckGo search can return any commercially ranked page. |
| 2 | **`search_depth="fast"` skips content validation** | `sources.py` L327-328 | Fast mode returns only search engine snippets (title + 1-2 sentence description). Page content is never examined. |
| 3 | **`include_content=False` prevents actual fetch** | `sources.py` L328 | The optional `enrich_with_fetch` path (L347-353) is disabled by default. Wigolo's `fetch()` tool is never called in live discovery. |
| 4 | **No HTTP status validation before evidence creation** | `synthesizer.py` L157-178 | URLs from search results are recorded as `VERIFIED_SOURCE` evidence without verifying the URL is actually reachable or relevant. |
| 5 | **Confidence=0.75 assigned to all results** | `synthesizer.py` L171 | Search engine relevance score is not used. Every result regardless of snippet quality receives the same confidence label. |
| 6 | **Keyword clustering without semantic validation** | `synthesizer.py` L186-196 | Themes matched by `kw in text_to_search.lower()`. A result titled "cloud hosting" matches the `cloud_cost` theme even if the content is a commercial sales page. |
| 7 | **Search queries are too generic for DuckDuckGo** | `autonomous.py` L88-120 | Queries like "b2b deliverability problem India" match generic marketing pages. HN Algolia and GitHub APIs handle such queries better since they search within specific, known communities. |

**HN Algolia and GitHub source adapters do NOT have this problem** — they search within structured developer communities. Wigolo's DuckDuckGo search lacks community context and returns broader commercial results.

---

## 7. Technology Stack Assessment

| Component | Technology | Version | Assessment |
|---|---|---|---|
| Language | Python | 3.13.12 | ✅ Modern, appropriate |
| Data validation | Pydantic v2 | 2.x | ✅ Excellent for schema enforcement |
| CLI display | Rich | — | ✅ Good terminal UX |
| HTTP client | httpx | — | ✅ Appropriate (sync mode) |
| Database | SQLite | stdlib | ✅ Zero-cost, appropriate scale |
| Test framework | pytest | 9.1.1 | ✅ Adequate |
| MCP integration | Wigolo (Node.js stdio) | v0.3.1 | ⚠️ Local process; requires OS-level file access outside sandbox |
| LLM integration | None | — | ❌ Missing — no semantic analysis possible without it |
| Email sending | None | — | ❌ Missing — no outreach capability |
| AI provider keys | `GEMINI_API_KEY`, `GROQ_API_KEY` | Defined in `.env.example` | ❌ Defined but completely unused in any source file |
| Browser automation | None in ZERO code | — | ⚠️ Wigolo uses Playwright internally (not controlled by ZERO) |
| Package manager | pip / pyproject.toml | — | ✅ Standard |

**Key structural observation:** The project has no LLM calls anywhere in its production code. All "intelligence" is deterministic keyword matching and pre-written templates. This is architecturally sound for ₹0 budget enforcement but severely limits discovery quality and offer personalization.

---

## 8. Target Architecture (Intended Product Workflow)

The intended 8-stage workflow from the PRD and AGENTS.md:

```
Stage 1: Configuration
  Read operating instructions (budget, geography, tools, restrictions)

Stage 2: Autonomous Opportunity Discovery  ← PARTIAL (see Section 4)
  Search public sources → extract problems → cluster → rank candidates

Stage 3: Human Opportunity Selection       ← NOT IMPLEMENTED
  Present candidates → user picks one → persist selection

Stage 4: Prospect Discovery                ← PARTIAL (URL-required, no auto-discovery)
  Research companies with selected problem → find decision-makers →
  find public emails → verify emails → store with evidence

Stage 5: Demo Preparation                  ← PARTIAL (generic template only)
  Generate actionable demo spec → features, workflow, sample data, acceptance criteria

Stage 6: Personalized Outreach             ← NOT IMPLEMENTED
  Draft individual emails → require user approval → send

Stage 7: Reply Tracking                    ← NOT IMPLEMENTED
  Track sent messages → classify replies → draft appropriate follow-ups

Stage 8: Pilot Proposal / Handover         ← NOT IMPLEMENTED
  Pilot terms → handover documentation
```

---

## 9. Gap Analysis

### Gap 1: Human Opportunity Selection (Critical)

**What exists:** `zero evaluate list` shows all synthesized candidates. `zero evaluate show <id>` displays rubric details.

**What's missing:**
- No `zero select <offer_id>` command to mark a user's chosen opportunity
- No persistence of a "selected" state on an offer (all offers stay `NEEDS_MORE_EVIDENCE` or `REJECTED`)
- No transition from `RunState.RESEARCH` → `RunState.OFFER_DECISION` triggered by selection
- No research history snapshot saved at selection time

### Gap 2: Autonomous Prospect Discovery (Significant)

**What exists:** `zero prospects discover --url <company_url> --source <source_url>` requires the user to supply an individual company URL. `ProspectDiscoveryEngine.discover_from_public_url()` fetches the page and extracts facts.

**What's missing:**
- No automated discovery of companies that have the selected problem (e.g., searching "who uses X integration" or scanning job postings)
- No decision-maker identification (name, title, public profile)
- No email verification beyond regex extraction
- No MX validation, SMTP RCPT-TO test, or catch-all detection

### Gap 3: Email Verification (Critical Safety Gap)

**What exists:** Regex email extraction from public HTML pages.

**What's missing:**
- MX record lookup to confirm domain has mail servers
- SMTP RCPT-TO verification (permissible without sending)
- Catch-all domain detection
- Clear labeling of verified vs. inferred vs. guessed email addresses
- **PRD Rule:** "Never generate or guess an email and label it verified" — this rule cannot be enforced without verification infrastructure

### Gap 4: Outreach Generation and Approval (Complete)

**What's missing (entirely):**
- Email template engine with per-company personalization slots
- Evidence-to-claim linking in email body
- User approval step presenting exact recipient + exact message
- Send confirmation gate (PRD requires this)
- SMTP or provider integration (even a free tier like Mailjet, Resend, or Gmail API)

### Gap 5: Reply Tracking (Complete)

**What's missing (entirely):**
- Tracking table for sent messages (timestamp, recipient, message hash)
- Inbox polling or webhook integration
- Reply classification (positive/negative/out-of-office/auto-reply)
- Follow-up draft queue

### Gap 6: LLM Integration for Quality (Significant)

**What's missing:**
- Semantic relevance scoring of discovered content (is this actually a problem discussion?)
- Claim extraction from raw text ("what exactly is the user complaining about?")
- Personalized email drafting based on company facts
- Opportunity summarization for human selection UI

**What's already defined:** `GEMINI_API_KEY` and `GROQ_API_KEY` environment variables exist in `.env.example` but are referenced in zero production code.

### Gap 7: Search Quality Improvements (Significant)

**What's missing:**
- Relevance filter on Wigolo search results (reject commercial/documentation pages)
- Content-based problem signal detection (fetch page when snippet is thin)
- More targeted query templates (e.g., HN-specific `site:news.ycombinator.com` queries, GitHub label filters)
- Minimum recency filter (exclude discussions older than N months)

---

## 10. Phased Roadmap

### Phase 1: Search Quality Fix (1–2 days) — IMMEDIATE

**Goal:** Make `research auto` return genuine problem discussions.

1. Add minimum relevance heuristic to `WigoloDiscoverySource`: require snippet length ≥ 50 chars AND at least one "problem signal" keyword in the snippet before accepting a result.
2. Enable `search_depth="basic"` or `include_content=True` for HN and GitHub results where fetch is fast.
3. Add `enrich_with_fetch=True` as a configurable flag on `WigoloDiscoverySource`.
4. Add a minimum quality score gate in `OpportunitySynthesizer`: skip sources with snippet < 30 chars and no problem-signal keywords.
5. Replace static `confidence=0.75` with a computed score based on presence of problem-signal keywords in excerpt.

### Phase 2: Human Opportunity Selection (2–3 days)

**Goal:** Let the user pick one opportunity and record the selection.

1. Add `zero select <offer_id>` CLI command.
2. Add `selected_offer_id` field to the `runs` table (schema migration).
3. Add `handle_select(args)` to `cli.py` that updates run state from `RESEARCH` to `OFFER_DECISION`.
4. Persist a research history snapshot: which queries were run, how many sources found, which adapters used.
5. Display all `NEEDS_MORE_EVIDENCE` candidates in a numbered list; prompt user to pick one.

### Phase 3: Automated Prospect Discovery (3–5 days)

**Goal:** Given a selected opportunity, find companies that likely have the problem.

1. Build `ProspectSearchEngine` that uses HN Algolia + GitHub to find posts mentioning the offer keywords AND company names or domains.
2. Extract `company_name` from post author profiles, referenced companies, and org names in GitHub repo URLs.
3. Use `PublicWebResearcher` to fetch company public websites and extract verified facts.
4. Implement basic MX validation (`dns.resolver` from `dnspython`, free library) to verify email domains.
5. Add `zero prospects auto --offer <id>` CLI command.

### Phase 4: Demo Specification (2–3 days)

**Goal:** Generate an actionable demo spec, not just a markdown header template.

1. Add `OfferSpecification` model with fields: `features`, `workflow_steps`, `sample_data_description`, `expected_output`, `acceptance_criteria`.
2. Update `DemoAssetGenerator.generate_proof_asset()` to populate these fields using the offer's theme definition.
3. Add per-theme demo spec templates to `THEME_DEFINITIONS` (e.g., email auth theme includes sample DNS zone file, expected DMARC report format, etc.).

### Phase 5: Outreach Generation + Approval Gate (3–5 days)

**Goal:** Draft personalized emails, require explicit user approval, then send.

1. Build `OutreachDraftEngine` that:
   - Takes a qualified prospect + selected offer
   - Generates a personalized email subject and body using company facts, evidence excerpts, and offer details
   - References supporting public source URLs in the email body
2. Add `zero outreach draft --prospect <id> --offer <id>` command.
3. Implement approval gate: `zero outreach approve <draft_id>` explicitly confirmed by user before any send.
4. Integrate with one free transactional email provider (e.g., Resend free tier: 3,000 emails/month) or fall back to `mailto://` link for manual dispatch.
5. Persist sent outreach with timestamp, recipient, message hash, and approval confirmation in a new `outreach` table.

### Phase 6: Reply Tracking (2–3 days)

**Goal:** Track sent messages and classify incoming replies.

1. Add `outreach_threads` table: `sent_at`, `recipient_domain`, `message_hash`, `status` (SENT/OPENED/REPLIED/BOUNCED).
2. Implement basic inbox polling if provider supports webhooks.
3. Add `zero replies list` and `zero replies classify <id>` commands.

### Phase 7: LLM Integration (Optional but High-Impact)

**Goal:** Upgrade discovery and email drafting with semantic intelligence.

1. Integrate Gemini API (free tier, `GEMINI_API_KEY` already in `.env.example`) for:
   - Relevance scoring: "Is this a genuine problem discussion? Score 0-1."
   - Claim extraction: "What is the specific business problem in this text?"
   - Email personalization: "Draft a cold email for [company] given [facts] and [offer]."
2. Add budget enforcement: count API tokens used, alert if quota at risk.
3. All LLM outputs labeled as `HYPOTHESIS` (not `VERIFIED_SOURCE`) in the evidence chain.

---

## 11. Recommended Next Task

> [!IMPORTANT]
> **Priority 1: Phase 1 Search Quality Fix** — before investing in any new feature, the core discovery loop must return relevant content. Currently, `research auto` with Wigolo is non-functional for real discovery. HN Algolia and GitHub adapters work but suffer from the same static confidence score problem.

**Specific recommended next task (1–2 days, zero external dependencies):**

Implement **search quality gating** in `sources.py` and `synthesizer.py`:

1. In `WigoloDiscoverySource.search()`: reject results where `len(snippet) < 50` or no problem-signal keyword in `title + snippet`.
2. In `synthesizer.py`: compute `evidence_confidence` based on presence of problem signals in `src.excerpt`, ranging from 0.55 (keyword present) to 0.75 (multiple keywords + excerpt length > 100). Remove the static `confidence=0.75`.
3. In `autonomous.py`: add geography-specific problem-signal keyword lists (`PROBLEM_SIGNAL_KEYWORDS_IN`, `PROBLEM_SIGNAL_KEYWORDS_US`).
4. Add a `--verbose` flag to `research auto` that prints per-source quality scores to help debugging.
5. Update 4–6 unit tests in `test_autonomous_discovery.py` to cover the new gating logic.

**After Phase 1:** Implement Human Opportunity Selection (Phase 2) so the system has a user decision point before automating any outreach-related work.

---

## Appendix: Test File Inventory

| Test File | Tests | What It Covers |
|---|---|---|
| `test_audit.py` | 7 | Hash chain creation, integrity verification, tampering detection |
| `test_autonomous_discovery.py` | 11 | AutonomousDiscoveryEngine, URL normalization, deduplication, synthesizer |
| `test_cli.py` | 9 | research auto, sources list, evidence add, CLI parser arguments |
| `test_database.py` | 8 | Evidence, offer, prospect, suppression, run CRUD operations |
| `test_demo_assets.py` | 5 | DemoAssetGenerator, mandatory disclaimer enforcement |
| `test_evaluator.py` | 10 | 5-criterion scoring, NEEDS_MORE_EVIDENCE gating, weighted score |
| `test_prospects.py` | 7 | ProspectDiscoveryEngine, ProspectQualificationEngine, suppression |
| `test_research_fetcher.py` | 7 | PublicWebResearcher, HTML extraction, robots.txt, paywall detection |
| `test_schemas.py` | 6 | Pydantic model validation, Evidence LinkedIn prohibition |
| `test_stage_b_safety_and_budget.py` | 4 | Sample/production separation, suppression enforcement |
| `test_wigolo_discovery.py` | 8 | WigoloMcpClient mock, WigoloDiscoverySource, JSON-RPC protocol |
| `test_zero_budget.py` | — | Budget constraint verification |
| **Total** | **76** | **All passing (5.12s, no network required)** |

---

*Report generated by read-only inspection of `d:\Project Zero`. No source files were created, modified, or deleted. All file paths and function names reference actual observed code.*

