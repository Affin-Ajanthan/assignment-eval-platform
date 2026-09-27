"""Pre-submission code-similarity checker.

A self-contained implementation of the "pre-submission checker" module
from the assignment-evaluation platform plan: fast, offline,
MOSS/JPlag-style structural similarity, plus an experimental
AI-content style heuristic. See README.md for usage and caveats.
"""

from .core import (
    Fingerprint,
    PairResult,
    compare_all,
    containment_similarity,
    fingerprint_source,
    jaccard_similarity,
    normalize_tokens,
    winnow,
)
from .ai_heuristics import HeuristicScore, score_source

__all__ = [
    "Fingerprint",
    "PairResult",
    "compare_all",
    "containment_similarity",
    "fingerprint_source",
    "jaccard_similarity",
    "normalize_tokens",
    "winnow",
    "HeuristicScore",
    "score_source",
]
