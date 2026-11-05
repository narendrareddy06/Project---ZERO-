# PROJECT ZERO — PHASE 1.2: EVIDENCE INTEGRITY FIXES COMPLETION REPORT

**Date:** November 5, 2026  
**Status:** Completed & Verified  
**Operating Budget Spent:** ₹0.00 (Zero paid APIs/subscriptions)  
**Test Suite:** 100/100 automated tests passing (100% pass rate in 12.35s)

---

## 1. Executive Summary

Phase 1.1 live validation identified two critical evidence integrity defects:
1. **Misleading Verification Provenance:** `SourceVerifier` incorrectly fell back to assigning `VERIFIED` status to search snippets when destination webpages timed out or failed to connect.
2. **Independent Evidence Overcounting:** Articles from different subdomains of the same publisher (e.g., `blog.acme.com` and `acme.com`) were counted as independent evidence points, while multi-tenant platforms (GitHub, Hacker News) lacked author-level disambiguation.

In **Phase 1.2**, we remediated both defects through conservative, audit-grade integrity controls without rewriting the core architecture. All 11 required regression scenarios have been implemented and verified. The system strictly upholds the ₹0 operating budget and preserves backward compatibility with all existing SQLite database records.

---

## 2. Files Changed & Summary of Modifications

| File | Status | Key Edits & Responsibilities |
|---|---|---|
| [`src/zero/schemas.py`](file:///d:/Project%20Zero/src/zero/schemas.py) | Modified | Added explicit `SourceVerificationStatus` values: `FETCH_VERIFIED`, `REDIRECTED_AND_VERIFIED`, `API_VERIFIED`, `SNIPPET_UNFETCHED`. Added provenance metadata fields `api_provider`, `api_record_id`, `publisher_org` to `DiscoveredSource`. Added `unknown_independence_count` to `OfferCandidate`. |
| [`src/zero/research/fetcher.py`](file:///d:/Project%20Zero/src/zero/research/fetcher.py) | Modified | Updated `SourceVerifier.verify()`: destination page HTTP 200 retrieval assigns `FETCH_VERIFIED` (or `REDIRECTED_AND_VERIFIED`). Remote timeouts/connection failures with pain signals assign `SNIPPET_UNFETCHED` (never `VERIFIED`). Local verification assigns `API_VERIFIED` if API provider present, else `SNIPPET_UNFETCHED`. |
| [`src/zero/research/sources.py`](file:///d:/Project%20Zero/src/zero/research/sources.py) | Modified | Updated `HnAlgoliaSource` and `GitHubIssuesSource` to explicitly assign `verification_status=SourceVerificationStatus.API_VERIFIED`, `api_provider`, and exact `api_record_id`. |
| [`src/zero/research/autonomous.py`](file:///d:/Project%20Zero/src/zero/research/autonomous.py) | Modified | Implemented `extract_publisher_organization()` with subdomain collapsing and multi-tenant author handling (`github:alice`, `hn:author`). Updated `AutonomousDiscoveryResult` and `discover_opportunities()` to compute all 6 distinct evidence counts. |
| [`src/zero/research/synthesizer.py`](file:///d:/Project%20Zero/src/zero/research/synthesizer.py) | Modified | Updated `calculate_source_evidence_confidence()`: `FETCH_VERIFIED` base 0.72; `API_VERIFIED` base 0.65; `SNIPPET_UNFETCHED` base 0.42 (hard capped $\le 0.45$). Updated `synthesize()` so `independent_report_count` only counts confirmed independent sources and excludes snippet leads. |
| [`src/zero/database.py`](file:///d:/Project%20Zero/src/zero/database.py) | Modified | Updated SQLite schema and lightweight migrations for `offers` table (`independent_report_count`, `unknown_independence_count`, etc.). Preserved backward compatibility for reading/writing legacy and new records. |
| [`src/zero/cli.py`](file:///d:/Project%20Zero/src/zero/cli.py) | Modified | Updated `zero research auto` CLI to display explicit status color coding (green for `FETCH_VERIFIED`, cyan for `API_VERIFIED`, yellow for `SNIPPET_UNFETCHED`, red for `REJECTED`), a panel with all 6 evidence counts, and clear notices when unfetched snippets are present. |
| [`tests/unit/test_research_quality_phase1.py`](file:///d:/Project%20Zero/tests/unit/test_research_quality_phase1.py) | Modified | Added 11 automated regression tests covering all Task 6 validation criteria. |

---

## 3. Status Model Mapping & Provenance Semantics

Verification statuses now explicitly communicate data provenance:

| Status Enum | Provenance Semantics | Remote Web Fetch? | Confidence Range | Counted in Confirmed Independent? |
|---|---|---|---|---|
| `FETCH_VERIFIED` | Full webpage retrieved (HTTP 200), static HTML body parsed, and business pain signals verified in text. | Yes | 0.72 – 0.88 | **Yes** |
| `REDIRECTED_AND_VERIFIED` | HTTP redirect followed to destination URL (HTTP 200), final URL recorded, pain signals verified. | Yes | 0.70 – 0.86 | **Yes** |
| `API_VERIFIED` | Sourced directly from documented free public API (`hn_algolia`, `github_issues`). Records `api_provider` and `api_record_id`. | No (API JSON payload) | 0.60 – 0.80 | **Yes** |
| `SNIPPET_UNFETCHED` | Destination page timed out, failed connection, or was unreached; search snippet retained as discovery lead. | No | 0.20 – 0.45 (Capped $\le 0.45$) | **No** (Tracked in Unknown Independence) |
| `VERIFIED` | Legacy general verified status preserved for backward compatibility. | Historical | 0.65 – 0.85 | **Yes** (if publisher confirmed) |
| `UNAVAILABLE` | Domain blocked, robots.txt disallowed, or connection failed without useful snippet. | Attempted | 0.05 – 0.20 (Capped $\le 0.20$) | **No** (Rejected) |
| `HTTP_ERROR` | Destination returned HTTP 4xx or 5xx error code. | Yes | 0.05 – 0.20 (Capped $\le 0.20$) | **No** (Rejected) |
| `EMPTY_CONTENT` | Static body text $< 50$ characters (e.g. empty SPA shell). | Yes | 0.05 – 0.20 (Capped $\le 0.20$) | **No** (Rejected) |
| `IRRELEVANT` | Generic reference domain, educational tutorial, or promotional article lacking business pain signals. | Yes/No | 0.05 – 0.20 (Capped $\le 0.20$) | **No** (Rejected) |
| `NEEDS_MANUAL_REVIEW` | Authentication or paywall detected. | Yes | 0.05 – 0.20 (Capped $\le 0.20$) | **No** (Rejected) |

---

## 4. Independent Evidence Rules

To prevent artificial inflation of problem severity, `extract_publisher_organization()` enforces conservative grouping:

1. **URL Normalization (`normalize_url`):**
   - Strips campaign and tracking parameters: `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `ref`, `fbclid`, `gclid`, `source`.
   - Normalizes schemes to lowercase, strips port numbers, and removes trailing slashes.
2. **Syndicated Content Fingerprinting (`compute_content_fingerprint`):**
   - Normalizes title and first 200 characters of content/excerpt.
   - Computes SHA-256 hash. Identical syndicated articles across different mirror domains are collapsed to 1 finding.
3. **Subdomain Collapsing:**
   - Standalone company/publication domains collapse subdomains to the base organizational domain (e.g., `blog.acme.com` and `acme.com/features` both map to `acme.com`).
   - Supports two-part ccTLDs (`.co.in`, `.com.au`, `.co.uk`, `.org.uk`, `.ac.in`).
4. **Multi-Tenant Platform Disambiguation:**
   - Multi-tenant platforms (`github.com`, `news.ycombinator.com`, `dev.to`, `medium.com`, `substack.com`, `reddit.com`, `twitter.com`, `x.com`) are **never** treated as a single publishing entity.
   - Distinct users/authors map to distinct organizational keys (e.g. `github:alice`, `github:bob`, `hn:pg`, `dev.to:author`).
5. **Unknown / Unattributed Origins:**
   - If author metadata is missing on multi-tenant platforms, or if a generic shortener (`bit.ly`, `tinyurl.com`, `t.co`) is used without resolution, status is marked `UNKNOWN` with `publisher_org = None`.
   - The system **never invents independence** for unattributed sources.

---

## 5. The 6 Evidence Counts Model

The pipeline tracks and reports 6 separate counts in `AutonomousDiscoveryResult` and the CLI:

1. **Total Retrieved Records (`total_retrieved_count`):** Total raw findings returned across all query executions and active adapters before deduplication.
2. **Unique URLs (`unique_url_count`):** Distinct canonical URLs after tracking parameter stripping and scheme/path normalization.
3. **Unique Content Items (`unique_content_count`):** Distinct content items after SHA-256 fingerprint deduplication of syndicated articles.
4. **Unique Identified Publishers (`unique_publisher_count`):** Distinct confirmed publisher entities and author-platform namespaces discovered.
5. **Confirmed Independent Reports (`confirmed_independent_count`):** Count of distinct confirmed publishers among `FETCH_VERIFIED`, `REDIRECTED_AND_VERIFIED`, `API_VERIFIED`, and legacy `VERIFIED` sources.
6. **Unknown Independence Count (`unknown_independence_count`):** Count of sources where independence could not be verified (including `SNIPPET_UNFETCHED` leads and unidentifiable/unattributed origins).

> [!IMPORTANT]
> `SNIPPET_UNFETCHED` sources are **strictly excluded** from `confirmed_independent_count`. They cannot inflate problem severity scores.

---

## 6. Confidence Calibration Derivation

`calculate_source_evidence_confidence(src)` derives confidence transparently:

$$\text{Confidence} = \text{round}\Big(\text{clamp}(\text{Base} + \Delta_{\text{author}} + \Delta_{\text{pain}} + \Delta_{\text{depth}} + \Delta_{\text{recency}}, \text{min\_cap}, \text{max\_cap}), 2\Big)$$

- **Base Provenance:**
  - `FETCH_VERIFIED`: `0.72`
  - `REDIRECTED_AND_VERIFIED`: `0.70`
  - `API_VERIFIED`: `0.65`
  - `SNIPPET_UNFETCHED`: `0.42`
  - `VERIFIED`: `0.65`
  - Rejection / unverified statuses: `0.15`
- **Modifiers:**
  - $\Delta_{\text{author}}$: `+0.02` if verified non-anonymous author.
  - $\Delta_{\text{pain}}$: `+0.07` for $\ge 2$ strong signals; `+0.04` for moderate; `-0.05` for single weak; `-0.12` for no explicit pain signal.
  - $\Delta_{\text{depth}}$: `+0.05` ($> 250$ chars); `+0.02` ($> 70$ chars); `-0.06` ($< 50$ chars).
  - $\Delta_{\text{recency}}$: `+0.04` (2025–2026); `+0.01` (2024); `-0.04` (2020–2023); `0.00` (undated).
- **Capping Boundaries:**
  - `SNIPPET_UNFETCHED`: Hard-capped at **$\le 0.45$** (never exceeds the hypothesis threshold of 0.50).
  - Rejections (`UNAVAILABLE`, `HTTP_ERROR`, `EMPTY_CONTENT`, `IRRELEVANT`): Hard-capped at **$\le 0.20$**.
  - Verified sources: Clamped within `[0.52, 0.88]`.

---

## 7. Verification & Automated Test Results

### 7.1 Full Test Suite Output
```
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Project Zero
configfile: pyproject.toml
plugins: anyio-4.14.1
collected 100 items

tests\unit\test_audit.py .....                                           [  5%]
tests\unit\test_autonomous_discovery.py ........                         [ 13%]
tests\unit\test_cli.py ....                                              [ 17%]
tests\unit\test_database.py ......                                       [ 23%]
tests\unit\test_demo_assets.py ..                                        [ 25%]
tests\unit\test_evaluator.py ............                                [ 37%]
tests\unit\test_prospects.py .....                                       [ 42%]
tests\unit\test_research_fetcher.py ............                         [ 54%]
tests\unit\test_research_quality_phase1.py ........................      [ 78%]
tests\unit\test_schemas.py .........                                     [ 87%]
tests\unit\test_stage_b_safety_and_budget.py ...                         [ 90%]
tests\unit\test_wigolo_discovery.py ........                             [ 98%]
tests\unit\test_zero_budget.py ..                                        [100%]

============================ 100 passed in 12.35s =============================
```

### 7.2 Trace of the 11 Regression Scenarios
| Scenario # | Test Name | Verified Behavior |
|---|---|---|
| **1** | `test_regression_1_destination_page_fetched_successfully` | Destination page HTTP 200 retrieval assigned `FETCH_VERIFIED`, raw content recorded, confidence $\ge 0.72$. |
| **2** | `test_regression_2_destination_unreachable_snippet_unfetched` | Unreachable destination assigned `SNIPPET_UNFETCHED`, confidence penalty applied (conf $\le 0.45$), network note recorded. |
| **3** | `test_regression_3_official_api_verified_without_pretending_fetch` | Official API response assigned `API_VERIFIED` with `api_provider` and `api_record_id` without claiming destination was fetched. |
| **4** | `test_regression_4_syndicated_duplicate_content_deduplication` | Identical content on distinct domains produced identical SHA-256 fingerprint; deduplicated in engine. |
| **5** | `test_regression_5_same_publisher_subdomains_collapse` | Articles from `blog.acme.com` and `acme.com` mapped to publisher `acme.com`, resulting in `independent_report_count == 1`. |
| **6** | `test_regression_6_different_authors_on_multi_tenant_platform` | Distinct authors `alice` and `bob` on GitHub mapped to `github:alice` and `github:bob` with `independent_report_count == 2`. |
| **7** | `test_regression_7_distinct_organizations_count_as_independent` | Distinct business domains (`logistics-firm.in` and `med-supply.co.in`) correctly counted as 2 independent reports. |
| **8** | `test_regression_8_missing_publisher_labeled_unknown` | Unattributed sources on HN and generic URL shorteners mapped to `UNKNOWN` with `publisher_org = None`. |
| **9** | `test_regression_9_duplicate_urls_with_tracking_parameters` | URLs with `utm_*`, `ref`, and `gclid` tracking parameters normalized to identical canonical URLs. |
| **10** | `test_regression_10_snippet_only_evidence_cannot_inflate_independent_count` | 1 fetched source + 3 snippet leads synthesized into offer with `independent_report_count == 1` and `unknown_independence_count == 3`. |
| **11** | `test_regression_11_backward_compatibility_db_records` | SQLite database `save_offer()` and `get_offer()` correctly serialized and deserialized new metrics while preserving legacy record readability. |

---

## 8. Unblocking Phase 2

All blocking defects identified in Phase 1.1 validation have been resolved:
- Evidence provenance is unambiguous and tamper-evident.
- Unfetched search snippets can never be mislabeled as fetched pages.
- Independent report counting is mathematically defensible and resists subdomain or syndication inflation.
- The ₹0.00 operating budget constraint is 100% maintained.

**Status:** Phase 1.2 is complete. **Phase 2 (Human Opportunity Selection) is unblocked.**

