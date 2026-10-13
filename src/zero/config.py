"""Configuration management for Project ZERO."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / os.getenv("DATA_DIR", "data")
LOGS_DIR = ROOT_DIR / os.getenv("LOGS_DIR", "logs")
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "project_zero.db"

# Minimum evidence confidence threshold (0.0 to 1.0)
# Default is set to 0.65:
# - Serves as an operational engineering heuristic to filter out speculative hypotheses (< 0.50)
#   and unvetted claims from qualifying an offer.
# - NOTE: This heuristic is NOT a statistically measured or empirically validated probability
#   of market success or conversion.
# - Can be configured via environment variable CONFIDENCE_THRESHOLD
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.65"))

# Budget & Safety limits
ALLOW_PAID_APIS = os.getenv("ALLOW_PAID_APIS", "false").lower() == "true"
TARGET_BUDGET_INR = 0.0
