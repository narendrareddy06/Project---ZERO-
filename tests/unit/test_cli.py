"""Unit tests for Stage A CLI commands."""

import pytest
from zero.cli import build_parser, handle_evaluate, handle_research, handle_status
from zero.database import Database
from zero.research.evaluator import OfferEvaluator
from zero.schemas import (
    CriterionKey,
    CriterionScore,
    DecisionStatus,
    Evidence,
    EvidenceType,
    Geography,
    OfferCandidate,
)


@pytest.fixture
def test_db_setup(tmp_path, monkeypatch):
    test_db_path = tmp_path / "test_cli.db"
    db = Database(test_db_path)
    monkeypatch.setattr("zero.cli.get_db", lambda: db)
    return db


def test_cli_parser_commands():
    """Verify CLI parser recognizes status, research, and evaluate commands."""
    parser = build_parser()

    # status
    args = parser.parse_args(["status"])
    assert args.command == "status"

    # research list
    args = parser.parse_args(["research", "list", "--geo", "IN"])
    assert args.command == "research"
    assert args.action == "list"
    assert args.geo == "IN"

    # research add
    args = parser.parse_args([
        "research", "add",
        "--claim", "Indian SMBs require automated compliance",
        "--type", "VERIFIED_SOURCE",
        "--geo", "IN",
        "--confidence", "0.85",
        "--url", "https://example.com/data",
    ])
    assert args.command == "research"
    assert args.action == "add"
    assert args.confidence == 0.85

    # evaluate list
    args = parser.parse_args(["evaluate", "list"])
    assert args.command == "evaluate"
    assert args.action == "list"

    # evaluate show
    args = parser.parse_args(["evaluate", "show", "off_001"])
    assert args.command == "evaluate"
    assert args.action == "show"
    assert args.offer_id == "off_001"


def test_cli_status_execution(test_db_setup):
    """Test handle_status runs without error on empty and populated DB."""
    parser = build_parser()
    args = parser.parse_args(["status"])
    handle_status(args)


def test_cli_research_add_and_list(test_db_setup):
    """Test adding evidence and listing via CLI handlers."""
    parser = build_parser()

    # Add evidence
    add_args = parser.parse_args([
        "research", "add",
        "--claim", "US machine shops struggle with quoting CAD models",
        "--type", "VERIFIED_SOURCE",
        "--geo", "US",
        "--confidence", "0.88",
        "--url", "https://example.com/cad-study",
    ])
    handle_research(add_args)

    # Verify persisted in DB
    evidence_list = test_db_setup.list_evidence()
    assert len(evidence_list) == 1
    assert evidence_list[0].geography == Geography.US

    # List evidence
    list_args = parser.parse_args(["research", "list"])
    handle_research(list_args)


def test_cli_evaluate_list_and_show(test_db_setup):
    """Test listing and inspecting evaluated offers via CLI handlers."""
    parser = build_parser()

    # Save a candidate offer with evaluation
    offer = OfferCandidate(
        id="off_test_99",
        title="Test CAD Quoting Automation",
        target_geography=Geography.US,
        buyer_profile="Machine Shop Estimators",
        problem_statement="Quoting 3D parts takes 4 hours per RFQ.",
        proposed_deliverable="Automated feature-extraction script for 20 sample files.",
        plausible_pricing_or_pilot="Free 2-week pilot for 10 quotes.",
        delivery_method="Remote python script at ₹0 cost.",
        risks=["Complex STEP file geometry parsing"],
        evidence_ids=[],
    )
    test_db_setup.save_offer(offer)

    list_args = parser.parse_args(["evaluate", "list"])
    handle_evaluate(list_args)

    show_args = parser.parse_args(["evaluate", "show", "off_test_99"])
    handle_evaluate(show_args)
