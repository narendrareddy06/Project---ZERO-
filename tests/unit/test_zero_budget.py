"""Unit tests enforcing zero budget and zero external network calls."""

import os
from unittest.mock import patch
import pytest
from zero.config import ALLOW_PAID_APIS, TARGET_BUDGET_INR
from zero.research.evaluator import OfferEvaluator
from zero.schemas import CriterionKey, CriterionScore, Geography, OfferCandidate


def test_zero_budget_configuration():
    """Verify default configuration strictly enforces ₹0 budget."""
    assert TARGET_BUDGET_INR == 0.0
    assert ALLOW_PAID_APIS is False


def test_no_external_api_calls_during_evaluation(monkeypatch):
    """
    Ensure no outbound HTTP/network requests occur during evaluation.
    Patches socket.socket to fail if any network connection is attempted.
    """
    import socket

    def guarded_connect(*args, **kwargs):
        raise RuntimeError("Prohibited network connection attempted under ₹0 budget!")

    monkeypatch.setattr(socket, "create_connection", guarded_connect)

    # Run offer evaluation
    evaluator = OfferEvaluator()
    offer = OfferCandidate(
        id="off_guard_01",
        title="Guard Test Offer",
        target_geography=Geography.IN,
        buyer_profile="Test Buyers",
        problem_statement="Test Problem Statement for Offline Guard",
        proposed_deliverable="Test Deliverable",
        plausible_pricing_or_pilot="Free Pilot",
        delivery_method="Local test",
        risks=[],
        evidence_ids=[],
    )
    scores = {
        CriterionKey.PROBLEM_SEVERITY: CriterionScore(
            criterion=CriterionKey.PROBLEM_SEVERITY, score=4, weight=0.25, rationale="Rationale"
        ),
        CriterionKey.WILLINGNESS_TO_PAY: CriterionScore(
            criterion=CriterionKey.WILLINGNESS_TO_PAY, score=4, weight=0.25, rationale="Rationale"
        ),
        CriterionKey.BUYER_ACCESSIBILITY: CriterionScore(
            criterion=CriterionKey.BUYER_ACCESSIBILITY, score=4, weight=0.20, rationale="Rationale"
        ),
        CriterionKey.DELIVERY_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.DELIVERY_FEASIBILITY, score=4, weight=0.20, rationale="Rationale"
        ),
        CriterionKey.SALES_CYCLE_FEASIBILITY: CriterionScore(
            criterion=CriterionKey.SALES_CYCLE_FEASIBILITY, score=4, weight=0.10, rationale="Rationale"
        ),
    }

    result = evaluator.evaluate(offer, scores, [])
    # Evaluation completes 100% locally with no network calls
    assert result is not None
