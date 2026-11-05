# PROJECT ZERO — PHASE 1.1: LIVE RESEARCH VALIDATION REPORT

**Validation Date:** 2026-11-05  
**Auditor:** Antigravity (AI Code Agent)  
**Scope:** Live verification semantics, confidence calibration, independent evidence counting, willingness-to-pay (WTP) handling, and real-world smoke testing.  
**Mode:** Validation-only (Zero code or schema modifications).

---

## Executive Summary

Phase 1 implemented key building blocks: `SourceVerifier`, dynamic evidence confidence, pain-signal query generation, and explicit `UNKNOWN` labeling for commercial willingness to pay.

This Phase 1.1 validation examined these mechanisms against live search results and rigorous edge cases. The system demonstrates solid safety guarantees (conservative gating as `NEEDS_MORE_EVIDENCE`, rejection of generic educational domains, zero cost target). However, this audit reveals critical semantic gaps:
1. **Ambiguous `VERIFIED` Status**: A source whose destination URL cannot be reached (e.g. timeout, DNS failure) is still assigned `SourceVerificationStatus.VERIFIED` if its search snippet contains pain keywords. Search snippets are thus conflated with fetched destination pages.
2. **Organization Deduplication Gap**: `independent_report_count` uses `(netloc, author)`. If author metadata is missing (common in web search), multiple pages from the exact same corporate domain are counted as separate independent reports.
3. **Sandbox Stdio Isolation**: When `zero.cli` is invoked directly inside standard sandboxed PowerShell, Node.js cannot start Wigolo due to `EPERM mkdir 'C:\Users\Narendra\.wigolo'`, necessitating running outside sandbox or query redirection.

**Recommendation:** **NOT READY FOR PHASE 2** until the verification status distinguishes snippet validation from destination page fetch, and domain-level organization deduplication is hardened.

---

## 1. Verification Semantics: What `VERIFIED` Actually Means

In `src/zero/research/fetcher.py`, `SourceVerifier.verify()` processes candidate sources. An inspection of lines 550–665 reveals four distinct pathways that produce status outcomes:

| Provenance Pathway | Destination URL Fetched? | HTTP Status Checked? | Assigned Status | Integrity Assessment |
|---|---|---|---|---|
| **Live Remote Fetch** | ✅ Yes | ✅ Yes (HTTP 200) | `VERIFIED` | **Authentic verification.** Clean body text (>= 50 chars) inspected and confirmed to contain business pain signals. |
| **Redirected Live Fetch** | ✅ Yes | ✅ Yes (HTTP 200) | `REDIRECTED_AND_VERIFIED` | **Authentic verification.** Preserves `original_url`, records `final_url`, confirms body text has pain signals. |
| **API Payload Content** | ❌ No (API used) | ✅ API 200 | `VERIFIED` | **Permitted API verification.** Ingested directly from Hacker News Algolia or GitHub REST API responses without refetching web pages (respects robots.txt and rate limits). |
| **Network Failure Fallback** | ❌ **FAILED** | ❌ None (Errno 11001 / Timeout) | `VERIFIED` | ⚠️ **SEMANTIC CONFLATION DEFECT.** When `fetch_page()` throws `CONNECTION_FAILED` or `TIMEOUT`, lines 590–600 check if the search snippet has >= 20 chars with pain keywords. If so, it assigns `VERIFIED` with an internal metadata note (`network_note`). |

### The Snippet Conflation Defect
A search snippet or search-engine summary is NOT a verified destination webpage.
- **Problem**: When live network fetching fails or times out, the system marks the finding as `SourceVerificationStatus.VERIFIED`.
- **Downstream Impact**: In terminal output and database records, an unverified link with an unreached destination server appears in the `Verified Problem Signals` table alongside genuinely fetched, HTTP-validated pages.
- **Required Fix (before Phase 2)**: Introduce explicit separate statuses:
  - `FETCH_VERIFIED`: Destination URL fetched, HTTP 200, body content substantiated.
  - `REDIRECTED_AND_VERIFIED`: Destination URL followed redirect, HTTP 200, body substantiated.
  - `API_PAYLOAD_VERIFIED`: Verified from documented API response (HN Algolia, GitHub).
  - `SNIPPET_ONLY`: Destination URL unreached; text substantiated only from search engine snippet.

---

## 2. Confidence Calibration Review

The function `calculate_source_evidence_confidence()` in `src/zero/research/synthesizer.py` replaced the previous static `0.75` score. The formula evaluates five discrete vectors:

$$\text{Confidence} = \text{Base} + \Delta_{\text{pain}} + \Delta_{\text{depth}} + \Delta_{\text{recency}} + \Delta_{\text{redirect}}$$

### Component Inspection

1. **Base Provenance**:
   - `github_issues`: 0.65
   - `hn_algolia`: 0.65
   - `wigolo` (with full content > 100 chars): 0.66
   - `wigolo` (snippet only): 0.62
   - Identified author: +0.02
2. **Business Pain Signals ($\Delta_{\text{pain}}$)**:
   - Strong pain signals (2+ strong or 4+ total): +0.07
   - Moderate pain signals (1 strong or 2+ total): +0.04
   - Weak single signal: -0.05
   - Zero explicit signals: -0.12
3. **Content Depth ($\Delta_{\text{depth}}$)**:
   - Rich excerpt (> 250 chars): +0.05
   - Adequate excerpt (70–250 chars): +0.02
   - Thin snippet (< 50 chars): -0.06
4. **Publication Recency ($\Delta_{\text{recency}}$)**:
   - Recent (2025–2026): +0.04
   - Moderately recent (2024): +0.01
   - Older (<= 2023): -0.04
   - Undated / Unknown: 0.00 (neutral; transparently logged)
5. **Redirection Penalty ($\Delta_{\text{redirect}}$)**:
   - Redirect resolved: -0.02

### Calibration Test Cases

| Scenario | Input Attributes | Calculated Score | Explanation Factor String |
|---|---|---|---|
| **A: Rich Live Developer Post** | DEV.to post by Dev Makai, 3500 chars, strong pain ("lost $14k revenue", "silent failure"), 2025 date | **0.84** | `wigolo verified content fetch (base 0.66); identified author 'Dev Makai' (+0.02); strong pain signals [fail, failure, failing] (+0.07); rich excerpt (3556 chars) (+0.05); recent publication '2025-12-09T22:39:09Z' (+0.04)` |
| **B: Moderate HN Post** | Ask HN discussion, 80 chars, moderate pain ("spam filter", "dkim trouble"), undated | **0.73** | `hn_algolia discussion provenance (base 0.65); identified author 'founder1' (+0.02); moderate pain signals [spam, problem] (+0.04); adequate excerpt (81 chars) (+0.02); undated (0.00)` |
| **C: Thin Search Snippet** | Web snippet, 45 chars, single vague term ("slow"), unknown author, undated | **0.52** | `wigolo web snippet provenance (base 0.62); weak single pain signal (-0.05); thin excerpt (45 chars) (-0.06); undated (0.00)` (clamped to minimum 0.52) |
| **D: Generic Marketing Page** | 150 chars, zero pain signals ("Welcome to Acme Cloud partnership") | **0.52** | `wigolo web snippet provenance (base 0.62); no explicit pain signal (-0.12); adequate excerpt (+0.02); undated (0.00)` (clamped to minimum 0.52) |

### Assessment
- ✅ **Dynamic**: Replaced the arbitrary 0.75 score; distinct sources receive distinct scores (0.52 to 0.84).
- ✅ **Recency**: Undated sources receive 0.00 adjustment rather than fabricated dates or penalties.
- ⚠️ **Clamp Floor**: The clamp floor of `0.52` prevents confidence from dropping below 0.50 even when a source has zero pain signals. While `SourceVerifier` rejects zero-pain sources before this step, any unverified item that enters synthesizer directly will never score below 0.52.

---

## 3. Independent Evidence Counting

In `src/zero/research/synthesizer.py` (lines 340–344) and `src/zero/research/autonomous.py` (lines 205–209), independent evidence reports are counted as:

```python
distinct_independent_sources = {
    (urlparse(s.url).netloc.lower(), s.author.lower() if s.author else s.url)
    for s, _ in items
}
indep_count = len(distinct_independent_sources)
```

### Edge Case Evaluation

| Case | System Behavior | Integrity Verdict |
|---|---|---|
| **Same URL with different tracking parameters** | `normalize_url()` strips `utm_source`, `utm_campaign`, `ref`, etc. | ✅ **Handled correctly.** Deduplicated in discovery loop via `seen_urls`. |
| **Exact syndicated content on multiple domains** | `compute_content_fingerprint()` hashes title + first 200 chars. | ✅ **Handled correctly.** Deduplicated via `seen_content_hashes`. |
| **Slightly rephrased syndicated content** | Generates different content hash; URLs are on different domains. | ⚠️ **Overcounted.** Treated as 2 independent sources because `netloc` differs. |
| **Different users on same platform** | `(github.com, user_a)` vs `(github.com, user_b)` | ✅ **Handled correctly.** Treated as 2 independent developer reports. |
| **Multiple pages from same company (no author)** | `(acme.com, acme.com/blog/p1)` vs `(acme.com, acme.com/blog/p2)` | ⚠️ **Overcounted.** When author is None or generic (`public_web`), fallback key uses `s.url`, counting 2 pages from the same vendor as 2 independent reports! |

---

## 4. Willingness-to-Pay (WTP) Handling

### Nature of WTP Value
WTP confidence is **NOT an empirical probability or conversion rate**. It is an **engineering heuristic gate**:
- The PRD requires that all hypotheses remain $\le 0.50$.
- The `OfferEvaluator` requires confidence $\ge 0.65$ for an offer to be marked `SELECTED`.
- Therefore, setting WTP hypothesis confidence $< 0.65$ guarantees that no auto-discovered offer can ever pass without human validation.

### Evidence-Based Calibration vs. Hardcoded Static Value

| Scenario | WTP Confidence | Criterion Score | Rationale & Summary String |
|---|---|---|---|
| **Zero commercial budget signals** | `0.20` | `1 / 5` | `UNKNOWN / ZERO EMPIRICAL EVIDENCE: Public discussions contain problem complaints only, not commercial willingness to pay` |
| **Preliminary commercial spend signals** | `0.35` | `2 / 5` | `Preliminary commercial budget mentions ($800/month, consultant); pilot demand unvalidated` |

### Integrity Audit
- ✅ When public discussions contain only complaints, the system explicitly communicates `UNKNOWN / ZERO EMPIRICAL EVIDENCE` across the claim, notes, and rubric rationale.
- ✅ Forum complaints are strictly prevented from implying willingness to pay.
- ⚠️ Assigning a score of `1` (or `2`) out of 5 still mathematically adds $1 \times 0.25 = 0.25$ to the weighted score (out of 5.0). While `missing_evidence_criteria` correctly gates the decision as `NEEDS_MORE_EVIDENCE`, the weighted score is not 0.

---

## 5. Live Smoke Test Results

### Execution Method
Conducted using the live **Wigolo MCP server** integration via `call_mcp_tool` for live search and fetch operations.

### Run 1: B2B Payment Integration Webhook Failures
- **Query:** `b2b payment webhook failure`
- **Candidate URLs Discovered:** 5
  1. `https://docs.riseworks.io/webhooks/operations/troubleshooting`
  2. `https://primer.io/docs/api-reference/endpoints/v2.4/payment-webhooks/payment-operation-failure`
  3. `https://revatto.com/glossary/failed-payment-webhook`
  4. `https://www.retrykit.com/blog/stripe-webhook-payment-failed-guide-2026`
  5. `https://dev.to/makai_4c7291bbc35741a3920/webhook-warfare-battling-silent-failures-in-payment-integrations-40d5`
- **URLs Actually Fetched:** 1 (`https://dev.to/makai_4c7291bbc35741a3920/...`)
  - **HTTP Status:** 200 OK
  - **Author:** Dev Makai
  - **Date:** 2025-12-09T22:39:09Z
  - **Verified Content:** 3,556 characters of authentic operational experience ("SaaS Company: Lost $14K in monthly recurring revenue because canceled subscriptions kept charging", "E-commerce Store: 200+ digital products never delivered").
  - **Verification Status:** `VERIFIED`
  - **Calculated Confidence:** `0.84`
- **Pages Rejected:**
  - `primer.io` doc endpoint: Rejected (`IRRELEVANT` / Documentation reference)
  - `revatto.com` glossary: Rejected (`IRRELEVANT` / Educational definition)
  - `riseworks.io`: Timed out during snippet fetch (`fetch_failed: timeout`)

### Run 2: Indian B2B Payment Gateway Failures
- **Query:** `payment gateway webhook failure India Razorpay Cashfree`
- **Candidate URLs Discovered:** 5
  1. `https://razorpay.com/blog/payment-gateway-webhooks-india/`
  2. `https://www.cashfree.com/docs/payments/online/webhooks/troubleshooting`
  3. `https://gauravtiwari.org/services/payment-gateway-setup-services/`
  4. `https://razorpay.com/docs/webhooks/payments`
  5. `https://www.ijert.org/payment-gateway-security-in-india-compared-razorpay-vs-cashfree-vs-payu-vs-stripe...`
- **URLs Inspected:**
  - `gauravtiwari.org`: Commercial services page offering setup for ₹12,000 / $149 ("Payments fail, stay pending..."). Detected spend keywords (`$149`, `12,000`), trigger for preliminary WTP signal.
  - `cashfree.com` & `razorpay.com`: Official vendor documentation guides.
  - `ijert.org`: Academic research paper comparing PCI DSS Level 1 compliance.

### Overall Live Pipeline Output
- **Independent Evidence Count:** 2 independent sources (`dev.to/Dev Makai`, `gauravtiwari.org/public_web`).
- **Opportunity Candidate Generated:**
  - **Title:** *B2B API Integration & Webhook Reliability Automation Pilot*
  - **Buyer Profile:** CTOs, VP Engineering, Technical Product Managers at early-stage B2B SaaS firms.
  - **Problem Statement:** Webhook silent dropouts, payment failure discrepancy, manual reconciliation.
  - **Independent Reports:** 2 independent sources
  - **Problem Severity Score:** `4 / 5` (evidenced by 2 independent reports)
  - **WTP Status:** `Preliminary commercial budget mentions ($149, 12,000); pilot demand unvalidated`
  - **WTP Score:** `2 / 5` (confidence 0.35)
  - **Weighted Score:** `3.40 / 5.0`
  - **Decision Status:** `NEEDS_MORE_EVIDENCE` (gated because WTP confidence $0.35 < 0.65$).

---

## 6. Remaining Defects & Vulnerabilities

| # | Defect | Severity | Root Cause |
|---|---|---|---|
| **D-1** | **Conflation of snippet-matching with destination URL verification** | **High** | In `SourceVerifier.verify()`, when connection/DNS fails, snippet matching marks the source as `VERIFIED` rather than `SNIPPET_ONLY`. |
| **D-2** | **Overcounting multiple pages from the same organization** | **Medium** | In `synthesizer.py`, when author is missing, the key is `(netloc, url)`, counting 2 blog posts on `acme.com` as 2 independent sources. |
| **D-3** | **Sandbox stdio process failure for Wigolo** | **Medium** | When invoked from sandboxed powershell, `node D:\wigolo\dist\index.js` fails with `EPERM mkdir 'C:\Users\Narendra\.wigolo'` because Node writes outside workspace. |
| **D-4** | **Confidence clamp floor of 0.52** | **Low** | `calculate_source_evidence_confidence()` clamps minimum confidence to 0.52, meaning any unverified item that enters synthesizer cannot fall below 0.50. |

---

## 7. Recommendation: NOT READY FOR PHASE 2

**Verdict:** **NOT READY FOR PHASE 2** (Human Opportunity Selection).

### Justification
Before allowing a human operator to select an opportunity candidate in Phase 2, the evidence backing that opportunity must be unambiguous:
1. The operator must know whether a supporting evidence item was **actually fetched and read from the remote server** vs. **inferred from a 150-character search engine snippet**.
2. Independent report counts must not overcount multiple pages from the same vendor domain.

### Pre-requisite Remediation (Phase 1.2):
1. **Differentiate verification statuses**:
   - `FETCH_VERIFIED`: Remote page fetched, HTTP 200, static body has pain signals.
   - `API_VERIFIED`: Ingested from official API response (HN Algolia, GitHub Issues).
   - `SNIPPET_UNFETCHED`: Destination server unreached; substantiated by snippet text only.
2. **Fix organization deduplication**:
   - For web sources without an author, key by `netloc` alone (not `(netloc, url)`), preventing multiple pages from the same company from inflating the independent report count.
3. **Adjust confidence floor**:
   - Allow snippet-only sources without full page retrieval to have confidence $\le 0.45$.

Once these three targeted integrity fixes are completed, Project ZERO will be reliably grounded for Phase 2 (Human Opportunity Selection).

