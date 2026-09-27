"""
Heuristic "AI-generated code" signal.

There is no reliable, validated classifier for AI-authored code (see the
platform plan's Risks section: "Code AI-detection has no reliable
dedicated classifier"). This module computes a small set of style-based
features and combines them into an experimental 0-100 score, meant
purely as a *talking point for human review* -- never as an automatic
penalty. It will misfire on students who legitimately use AI-assisted
IDEs, and on anyone with a naturally tidy commenting style.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

_GENERIC_NAMES = {
    "data", "result", "results", "value", "values", "temp", "tmp",
    "output", "input", "item", "items", "obj", "object", "processed",
    "response", "handler", "manager", "helper", "util", "utils",
}

_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_COMMENT_LINE_RE = re.compile(r"^\s*(#|//)")


@dataclass
class HeuristicScore:
    submission_id: str
    score: int  # 0-100, higher = more AI-like signal
    signal: str  # "low" | "medium" | "high"
    reasons: list[str]


def _comment_density(lines: list[str]) -> float:
    if not lines:
        return 0.0
    commented = sum(1 for line in lines if _COMMENT_LINE_RE.match(line))
    return commented / len(lines)


def _line_length_stats(lines: list[str]) -> tuple[float, float]:
    lengths = [len(line) for line in lines if line.strip()]
    if len(lengths) < 2:
        return (float(lengths[0]) if lengths else 0.0, 0.0)
    return statistics.mean(lengths), statistics.pstdev(lengths)


def _generic_name_ratio(source: str) -> float:
    idents = [m.group().lower() for m in _IDENT_RE.finditer(source)]
    if not idents:
        return 0.0
    generic = sum(1 for name in idents if name in _GENERIC_NAMES)
    return generic / len(idents)


def score_source(submission_id: str, source: str) -> HeuristicScore:
    lines = source.splitlines()
    comment_density = _comment_density(lines)
    mean_len, stdev_len = _line_length_stats(lines)
    generic_ratio = _generic_name_ratio(source)

    reasons: list[str] = []
    points = 0

    # AI-generated code tends to over-comment near-uniformly.
    if comment_density > 0.25:
        points += 25
        reasons.append(f"unusually high comment density ({comment_density:.0%} of lines)")

    # Very low variance in line length can indicate templated output.
    if mean_len > 0 and len(lines) > 15 and (stdev_len / mean_len) < 0.25:
        points += 25
        reasons.append("line lengths are unusually uniform")

    # Heavy use of generic placeholder-style names.
    if generic_ratio > 0.08:
        points += 25
        reasons.append(f"high share of generic identifier names ({generic_ratio:.0%})")

    # Docstring-per-function is a common LLM habit; rough proxy: triple
    # quotes or block comments right after a def/function line.
    doc_after_def = len(re.findall(
        r"(def |function )[^\n]*\n\s*(\"\"\"|'''|/\*\*)", source))
    def_count = len(re.findall(r"\b(def|function)\s+\w+", source))
    if def_count and (doc_after_def / def_count) > 0.7:
        points += 25
        reasons.append("nearly every function is immediately documented")

    points = min(points, 100)
    signal = "low" if points < 34 else "medium" if points < 67 else "high"
    if not reasons:
        reasons.append("no strong stylistic signal either way")

    return HeuristicScore(submission_id=submission_id, score=points,
                           signal=signal, reasons=reasons)
