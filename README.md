 HEAD
# Project ZERO

An autonomous, terminal-first, approval-gated AI business and customer-acquisition agent.
Designed to acquire one genuine remote B2B pilot customer within 72 hours under a strict ₹0 operating-budget target.

## Current Stage: Stage A
**Market Research and Evidence-Based Offer Selection**

Stage A implements:
- Typed Pydantic schemas for evidence, offers, evaluation rubrics, and runs.
- Distinguishes verified sources, user-provided inputs, hypotheses, and conflicting evidence.
- Comparative evaluation for Indian (`IN`) and US (`US`) opportunities without hardcoded winners.
- Deterministic 5-factor weighted scoring rubric (25% problem severity, 25% willingness to pay, 20% buyer accessibility, 20% delivery feasibility, 10% 72h sales cycle).
- Configurable confidence threshold with explicit `NEEDS_MORE_EVIDENCE` guardrails.
- SQLite persistence and cryptographic hash-chain tamper-evident audit logging.
- Stage A CLI: `zero status`, `zero research`, `zero evaluate`.
- 100% test coverage with zero external API calls.

## Quick Start

```powershell
# Run status check
python -m zero.cli status

# Run automated tests
pytest -v
```
=======
# Project---ZERO-
Project ZERO is an AI-powered, human-supervised business agent designed to research markets, identify profitable opportunities, validate demand, discover potential customers. Its goal is to turn business objectives into measurable outcomes and acquire paying customers through evidence-based decisions and controlled autonomy.
>>>>>>> 2c17ca75fe45c17c272fec77ec41a8b19cfcba74
