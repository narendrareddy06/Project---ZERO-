"""Research and offer evaluation module for Project ZERO."""

from zero.research.evaluator import OfferEvaluator
from zero.research.evidence import EvidenceService
from zero.research.fetcher import PublicWebResearcher
from zero.research.sources import (
    DiscoverySourceAdapter,
    GitHubIssuesSource,
    HnAlgoliaSource,
    WigoloDiscoverySource,
    get_active_source_adapters,
    get_all_source_definitions,
)
from zero.research.wigolo_client import WigoloMcpClient
from zero.research.synthesizer import OpportunitySynthesizer
from zero.research.autonomous import (
    AutonomousDiscoveryEngine,
    AutonomousDiscoveryResult,
)

__all__ = [
    "OfferEvaluator",
    "EvidenceService",
    "PublicWebResearcher",
    "DiscoverySourceAdapter",
    "HnAlgoliaSource",
    "GitHubIssuesSource",
    "WigoloDiscoverySource",
    "WigoloMcpClient",
    "get_active_source_adapters",
    "get_all_source_definitions",
    "OpportunitySynthesizer",
    "AutonomousDiscoveryEngine",
    "AutonomousDiscoveryResult",
]
