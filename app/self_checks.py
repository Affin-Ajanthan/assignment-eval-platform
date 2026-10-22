"""Student self-checks: what a student may learn about their own submission
before the deadline.

Three kinds, each with its own rate limit:
  code_similarity    -- their code against classmates' code (Winnowing + UniXcoder)
  report_similarity  -- their report against classmates' reports (Winnowing + MiniLM)
  ai_content         -- AI-content estimates for their report and code

Results are BANDS ("low" | "moderate" | "high"), never exact percentages, plus
the passages of the student's OWN work that match something. Another student's
name, id, code or text is never part of a student-facing result. The full
detail (exact scores, which submissions matched) is kept in SelfCheck.result
for the instructor.

The band lines are review indicators, not proof of copying, and can be tuned
with environment variables (defaults below). "high" always follows the
instructor's own flag rule, so a student never sees "low" for a pair the
instructor's check would flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

KINDS = ("code_similarity", "report_similarity", "ai_content")
KIND_LABELS = {"code_similarity": "Code similarity", "report_similarity": "Report similarity",
               "ai_content": "AI-content detection"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Checks a student may start per analysis type in a rolling hour.
LIMIT_PER_HOUR = _env_int("SELF_CHECK_LIMIT_PER_HOUR", 5)
# A "running" check older than this is treated as failed (e.g. the server restarted).
STALE_AFTER_MINUTES = 15

# Moderate band lines (below the instructor's flag lines, which define "high").
CODE_MODERATE_JACCARD = _env_float("SELF_CHECK_CODE_MODERATE_JACCARD", 0.35)
CODE_MODERATE_CONTAINMENT = _env_float("SELF_CHECK_CODE_MODERATE_CONTAINMENT", 0.50)
REPORT_MODERATE_COVERAGE = _env_float("SELF_CHECK_REPORT_MODERATE_COVERAGE", 0.10)
REPORT_MODERATE_JACCARD = _env_float("SELF_CHECK_REPORT_MODERATE_JACCARD", 0.15)

# How much of the student's own work is shown back.
MAX_HIGHLIGHTS = 15
MAX_HIGHLIGHT_LINES = 40
MAX_PASSAGES = 15

_ORDER = {"low": 0, "moderate": 1, "high": 2}


def worst(bands: list[str]) -> str:
    return max(bands, key=_ORDER.__getitem__) if bands else "low"


def code_pair_band(pair) -> str:
    """Band for one code pair (app.similarity.core.PairResult)."""
    if pair.token_flagged or pair.flag_level == "high":
        return "high"
    if (pair.flag_level == "review" or pair.jaccard >= CODE_MODERATE_JACCARD
            or pair.containment >= CODE_MODERATE_CONTAINMENT):
        return "moderate"
    return "low"


def report_pair_band(pair, own_coverage: float) -> str:
    """Band for one report pair (app.similarity.report_similarity.ReportPair)."""
    if pair.flag_level == "high":
        return "high"
    if (pair.flag_level == "review" or own_coverage >= REPORT_MODERATE_COVERAGE
            or pair.jaccard >= REPORT_MODERATE_JACCARD):
        return "moderate"
    return "low"


@dataclass
class OwnFile:
    """One of the student's own code files: shown name, source, fingerprints."""
    name: str
    source: str
    hashes: set[int]


def code_highlights(files: list[OwnFile], shared: set[int]) -> list[dict]:
    """The student's own lines that carry a fingerprint shared with a
    moderately or highly similar submission."""
    from .similarity.core import matched_line_ranges

    out: list[dict] = []
    for f in files:
        lines = f.source.splitlines()
        for start, end in matched_line_ranges(f.source, f.name, shared & f.hashes):
            shown_end = min(end, start + MAX_HIGHLIGHT_LINES - 1)
            out.append({"file": f.name, "start_line": start, "end_line": end,
                        "text": "\n".join(lines[start - 1:shown_end]),
                        "truncated": shown_end < end})
            if len(out) >= MAX_HIGHLIGHTS:
                return out
    return out


def code_result(student_sid: str, pairs: list, own_files: list[OwnFile],
                other_hashes: dict[str, set[int]], semantic_status: str) -> dict:
    """Full (instructor-side) result of a code self-check."""
    mine = [p for p in pairs if student_sid in (p.submission_a, p.submission_b)]
    rows = []
    shared: set[int] = set()
    for p in mine:
        other = p.submission_b if p.submission_a == student_sid else p.submission_a
        band = code_pair_band(p)
        rows.append({"other_submission_id": int(other), "band": band, "jaccard": p.jaccard,
                     "containment": p.containment, "semantic_similarity": p.semantic_similarity})
        if band != "low":
            shared |= other_hashes.get(other, set())
    own_hashes = set().union(*(f.hashes for f in own_files)) if own_files else set()
    return {
        "band": worst([r["band"] for r in rows]),
        "compared": len(mine),
        "similar_submissions": sum(r["band"] != "low" for r in rows),
        "highlights": code_highlights(own_files, shared & own_hashes),
        "semantic_status": semantic_status,
        "pairs": sorted(rows, key=lambda r: -_ORDER[r["band"]]),
    }


def report_result(student_sid: str, pairs: list, semantic_status: str, skipped_reason: str | None = None) -> dict:
    """Full (instructor-side) result of a report self-check."""
    if skipped_reason:
        return {"band": "low", "compared": 0, "similar_submissions": 0, "passages": [],
                "note": skipped_reason, "semantic_status": semantic_status, "pairs": []}
    rows, passages = [], []
    for p in pairs:
        if student_sid not in (p.submission_a, p.submission_b):
            continue
        mine_is_a = p.submission_a == student_sid
        own_coverage = p.coverage_a if mine_is_a else p.coverage_b
        band = report_pair_band(p, own_coverage)
        rows.append({"other_submission_id": int(p.submission_b if mine_is_a else p.submission_a),
                     "band": band, "jaccard": p.jaccard, "containment": p.containment,
                     "own_coverage": own_coverage, "semantic_similarity": p.semantic_similarity})
        if band != "low":
            for x in p.passages:
                text = x.text_a if mine_is_a else x.text_b
                if text not in passages:
                    passages.append(text)
    return {
        "band": worst([r["band"] for r in rows]),
        "compared": len(rows),
        "similar_submissions": sum(r["band"] != "low" for r in rows),
        "passages": passages[:MAX_PASSAGES],
        "semantic_status": semantic_status,
        "pairs": sorted(rows, key=lambda r: -_ORDER[r["band"]]),
    }


def ai_band(signal: str | None) -> str | None:
    """AI detector signals (low | medium | high) as self-check bands."""
    return {"low": "low", "medium": "moderate", "high": "high"}.get(signal or "")


def for_student(kind: str, result: dict | None) -> dict | None:
    """What the student may see: bands, counts and their own passages only.
    Never another submission's id, score or text."""
    if result is None:
        return None
    if kind == "ai_content":
        return {"report": result.get("report"), "code": result.get("code")}
    safe = {"band": result["band"], "compared": result["compared"],
            "similar_submissions": result["similar_submissions"]}
    if kind == "code_similarity":
        safe["highlights"] = result.get("highlights", [])
    else:
        safe["passages"] = result.get("passages", [])
    if result.get("note"):
        safe["note"] = result["note"]
    return safe


def own_file_name(code_dir: Path, path: Path) -> str:
    return path.relative_to(code_dir).as_posix()
