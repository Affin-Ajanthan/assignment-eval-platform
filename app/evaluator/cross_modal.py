"""
Cross-modal consistency check (plan node H, the "cross-modal
consistency" half; the other half, LLM rubric grading, lives in
``rubric_grading.py``).

Checks whether the code, the report, and the video transcript all
describe the same actual application. The heuristic version here
extracts the meaningful words inside function/class names (splitting
snake_case and camelCase) and measures how many of them also show up
in the report text and the video transcript -- a report or video that
never mentions anything the code actually does is a strong signal that
something doesn't add up (mismatched submission, wrong file attached,
or a report/video describing a different, possibly borrowed, project).

This is deliberately a transparent, explainable check rather than an
LLM judgment call: every flag comes with the exact terms that were and
weren't found, which is far easier for an instructor to audit than an
opaque "consistency score". A real LLM-based pass (comparing narrative
claims, not just vocabulary overlap) can be layered on top using the
same `RubricGrader`-style pluggable pattern as `rubric_grading.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .code_analysis import CodeReport
from .report_analysis import ReportAnalysis

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_COMMON_WORDS = {
    "main", "test", "tests", "run", "init", "self", "data", "value",
    "item", "list", "temp", "helper", "util", "utils", "get", "set",
    "print", "return", "input", "output", "args", "kwargs", "index",
}


def _split_identifier(name: str) -> set[str]:
    name = name.strip("_")
    camel_split = _CAMEL_SPLIT_RE.sub("_", name)
    parts = re.split(r"[_\-\d]+", camel_split)
    return {p.lower() for p in parts if len(p) >= 4}


def _significant_terms(code_reports: list[CodeReport]) -> set[str]:
    terms: set[str] = set()
    for report in code_reports:
        for func in report.functions:
            terms |= _split_identifier(func.name)
    return terms - _COMMON_WORDS


@dataclass
class ConsistencyResult:
    code_terms: list[str]
    report_ratio: float | None
    video_ratio: float | None
    unmentioned_in_report: list[str]
    unmentioned_in_video: list[str]
    consistency_score: int  # 0-100
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def check_consistency(
    code_reports: list[CodeReport],
    report: ReportAnalysis | None,
    video_transcript: str = "",
) -> ConsistencyResult:
    code_terms = _significant_terms(code_reports)

    if not code_terms:
        return ConsistencyResult(
            code_terms=[], report_ratio=None, video_ratio=None,
            unmentioned_in_report=[], unmentioned_in_video=[],
            consistency_score=50, flagged=False,
            reasons=["no distinguishing function/feature names found in the code to cross-check"],
        )

    report_text = report.content.text.lower() if report is not None else ""
    video_text = (video_transcript or "").lower()

    mentioned_in_report = {t for t in code_terms if t in report_text}
    mentioned_in_video = {t for t in code_terms if t in video_text}

    report_ratio = len(mentioned_in_report) / len(code_terms) if report_text else None
    video_ratio = len(mentioned_in_video) / len(code_terms) if video_text else None

    ratios = [r for r in (report_ratio, video_ratio) if r is not None]
    score = round(100 * sum(ratios) / len(ratios)) if ratios else 50

    reasons: list[str] = []
    flagged = False
    if report_ratio is not None and report_ratio < 0.3:
        flagged = True
        reasons.append(
            f"only {report_ratio:.0%} of the code's function/feature terms appear in the report"
        )
    if video_ratio is not None and video_ratio < 0.2:
        flagged = True
        reasons.append(
            f"only {video_ratio:.0%} of the code's function/feature terms appear in the video transcript"
        )
    if report_text == "" and video_text == "":
        reasons.append("no report text or video transcript available to cross-check against the code")
    if not reasons:
        reasons.append("code, report and video appear to describe the same application")

    return ConsistencyResult(
        code_terms=sorted(code_terms),
        report_ratio=report_ratio,
        video_ratio=video_ratio,
        unmentioned_in_report=sorted(code_terms - mentioned_in_report) if report_text else [],
        unmentioned_in_video=sorted(code_terms - mentioned_in_video) if video_text else [],
        consistency_score=score,
        flagged=flagged,
        reasons=reasons,
    )
