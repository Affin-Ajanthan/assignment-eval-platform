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

"moderate" is relative to the class: solutions to the same assignment in the
same language always share a lot (menus, input loops, file handling), and a
large program "contains" most of the common patterns of a small one. So a pair
is moderate only when it stands out above the class's typical overlap (its
median across every pair in the assignment) by a margin, and above a fixed
floor -- or when the semantic check marked it for review.

A small class cannot say what is normal. With fewer than MIN_CLASS_PAIRS pairs
(5 submissions) the result is marked ``small_class`` so the student is told so,
and the Moderate lines change where measured evidence (scripts/evaluate_self_check.py
--class-size 2 3 4) showed the class median misleads:
  - code: a single pair (2 submissions) is its own median and can never stand out
    above it, so it is judged against the fixed floors. With 3-4 submissions the
    median is the middle of 3-6 pairs, ignores one copied pair, and measured
    better than fixed floors, so it is kept.
  - reports: small classes cannot remove common text and honest pairs reach 17%
    coverage, so the coverage floor is raised (REPORT_SMALL_CLASS_COVERAGE) and no
    median is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import env_float, env_int

KINDS = ("code_similarity", "report_similarity", "ai_content")
KIND_LABELS = {"code_similarity": "Code similarity", "report_similarity": "Report similarity",
               "ai_content": "AI-content detection"}




# Checks a student may start per analysis type in a rolling hour.
LIMIT_PER_HOUR = env_int("SELF_CHECK_LIMIT_PER_HOUR", 5)
# A "running" check older than this is treated as failed (e.g. the server restarted).
STALE_AFTER_MINUTES = 15

# Fewer pairs than this (5 submissions) is a "small class": the student is told
# the check cannot say what is normal, and reports use fixed floors. Same cutoff
# as the meaning checks: SemanticThresholds.min_cohort_pairs and
# report_similarity.SEMANTIC_MIN_COHORT_PAIRS (a test keeps them equal).
MIN_CLASS_PAIRS = env_int("SELF_CHECK_MIN_CLASS_PAIRS", 10)
# Code uses the class median from this many pairs on (3 submissions); a single
# pair has no median. Set it to MIN_CLASS_PAIRS for fixed floors in every small class.
MIN_PAIRS_FOR_MEDIAN = env_int("SELF_CHECK_MIN_PAIRS_FOR_MEDIAN", 3)

# Moderate band: a pair must be at least MARGIN above the class median AND at
# least the floor. ("high" is the instructor's own flag rule.) In a small class
# (fewer than MIN_CLASS_PAIRS pairs) the floors alone apply.
CODE_MODERATE_JACCARD = env_float("SELF_CHECK_CODE_MODERATE_JACCARD", 0.45)
CODE_MODERATE_CONTAINMENT = env_float("SELF_CHECK_CODE_MODERATE_CONTAINMENT", 0.70)
CODE_MODERATE_MARGIN = env_float("SELF_CHECK_CODE_MODERATE_MARGIN", 0.15)
REPORT_MODERATE_COVERAGE = env_float("SELF_CHECK_REPORT_MODERATE_COVERAGE", 0.10)
REPORT_MODERATE_JACCARD = env_float("SELF_CHECK_REPORT_MODERATE_JACCARD", 0.15)
REPORT_MODERATE_MARGIN = env_float("SELF_CHECK_REPORT_MODERATE_MARGIN", 0.10)
# Small classes cannot remove common text, and honest report pairs there reach
# ~17% coverage (90th percentile ~9%), so the floor is higher than REPORT_MODERATE_COVERAGE.
REPORT_SMALL_CLASS_COVERAGE = env_float("SELF_CHECK_REPORT_SMALL_CLASS_COVERAGE", 0.20)
# A code pair flagged by the meaning check alone ("review") is Moderate for the
# student only from this UniXcoder score on. The instructor's review flag keeps
# its 0.80 floor (SemanticThresholds.review): there a person looks, and rewritten
# copies score from ~0.81. But honest same-task solutions reach 0.84 on the
# labelled sets (486 pairs), and below 5 submissions there is no cohort bar, so
# at 0.80 honest students saw "Moderate" for their own code (classes of 4:
# 100 of 1,748 honest pairs flagged; 4 at 0.85, with the same copies caught).
CODE_SEMANTIC_MODERATE = env_float("SELF_CHECK_CODE_SEMANTIC_MODERATE", 0.85)

# How much of the student's own work is shown back.
MAX_HIGHLIGHTS = 15
MAX_HIGHLIGHT_LINES = 40
MAX_PASSAGES = 15

_ORDER = {"low": 0, "moderate": 1, "high": 2}


def worst(bands: list[str]) -> str:
    return max(bands, key=_ORDER.__getitem__) if bands else "low"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def code_fixed_lines(n_pairs: int = 0) -> dict:
    """Moderate lines from the fixed floors alone (no class median)."""
    return {"mode": "fixed", "pairs": n_pairs, "median_jaccard": None, "median_containment": None,
            "jaccard_line": CODE_MODERATE_JACCARD, "containment_line": CODE_MODERATE_CONTAINMENT}


def code_class_lines(all_pairs: list) -> dict:
    """The class's typical code overlap and the moderate lines derived from
    it, from EVERY pair in the assignment (not just the student's). Used
    from MIN_CLASS_PAIRS pairs on; see code_moderate_lines."""
    med_j = _median([p.jaccard for p in all_pairs])
    med_c = _median([p.containment for p in all_pairs])
    return {"mode": "class", "pairs": len(all_pairs),
            "median_jaccard": round(med_j, 4), "median_containment": round(med_c, 4),
            "jaccard_line": round(max(CODE_MODERATE_JACCARD, med_j + CODE_MODERATE_MARGIN), 4),
            "containment_line": round(max(CODE_MODERATE_CONTAINMENT, med_c + CODE_MODERATE_MARGIN), 4)}


def code_moderate_lines(all_pairs: list) -> dict:
    """The moderate lines for this assignment: relative to the class median
    when there are enough pairs for one, the fixed floors for a single pair."""
    if len(all_pairs) < MIN_PAIRS_FOR_MEDIAN:
        return code_fixed_lines(len(all_pairs))
    return code_class_lines(all_pairs)


def is_small_class(lines: dict) -> bool:
    """Too few submissions to say what is normal for the assignment."""
    return lines["pairs"] < MIN_CLASS_PAIRS


def code_pair_band(pair, lines: dict) -> str:
    """Band for one code pair (app.similarity.core.PairResult)."""
    if pair.token_flagged or pair.flag_level == "high":
        return "high"
    semantic = pair.flag_level == "review" and (pair.semantic_similarity or 0) >= CODE_SEMANTIC_MODERATE
    if semantic or pair.jaccard >= lines["jaccard_line"] or pair.containment >= lines["containment_line"]:
        return "moderate"
    return "low"


def report_fixed_lines(n_pairs: int = 0) -> dict:
    """Moderate lines for a small class: fixed, with the raised coverage floor."""
    return {"mode": "fixed", "pairs": n_pairs, "median_coverage": None, "median_jaccard": None,
            "coverage_line": REPORT_SMALL_CLASS_COVERAGE, "jaccard_line": REPORT_MODERATE_JACCARD}


def report_class_lines(all_pairs: list) -> dict:
    med_cov = _median([max(p.coverage_a, p.coverage_b) for p in all_pairs])
    med_j = _median([p.jaccard for p in all_pairs])
    return {"mode": "class", "pairs": len(all_pairs),
            "median_coverage": round(med_cov, 4), "median_jaccard": round(med_j, 4),
            "coverage_line": round(max(REPORT_MODERATE_COVERAGE, med_cov + REPORT_MODERATE_MARGIN), 4),
            "jaccard_line": round(max(REPORT_MODERATE_JACCARD, med_j + REPORT_MODERATE_MARGIN), 4)}


def report_moderate_lines(all_pairs: list) -> dict:
    """Like code_moderate_lines, for reports."""
    if len(all_pairs) < MIN_CLASS_PAIRS:
        return report_fixed_lines(len(all_pairs))
    return report_class_lines(all_pairs)


def report_pair_band(pair, own_coverage: float, lines: dict) -> str:
    """Band for one report pair (app.similarity.report_similarity.ReportPair)."""
    if pair.flag_level == "high":
        return "high"
    if (pair.flag_level == "review" or own_coverage >= lines["coverage_line"]
            or pair.jaccard >= lines["jaccard_line"]):
        return "moderate"
    return "low"


@dataclass
class OwnFile:
    """One of the student's own code files: shown name, source, fingerprints.
    `fingerprinted`: the text the fingerprints came from (the source without
    junk code, same line numbers), when it differs from `source`."""
    name: str
    source: str
    hashes: set[int]
    fingerprinted: str | None = None


def code_highlights(files: list[OwnFile], shared: set[int]) -> list[dict]:
    """The student's own lines that carry a fingerprint shared with a
    moderately or highly similar submission."""
    from .similarity.core import matched_line_ranges

    out: list[dict] = []
    for f in files:
        lines = f.source.splitlines()
        fingerprinted = f.source if f.fingerprinted is None else f.fingerprinted
        for start, end in matched_line_ranges(fingerprinted, f.name, shared & f.hashes):
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
    lines = code_moderate_lines(pairs)
    rows = []
    shared: set[int] = set()
    for p in mine:
        other = p.submission_b if p.submission_a == student_sid else p.submission_a
        band = code_pair_band(p, lines)
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
        "class_baseline": lines,
        "small_class": is_small_class(lines),
        "pairs": sorted(rows, key=lambda r: -_ORDER[r["band"]]),
    }


def report_result(student_sid: str, pairs: list, semantic_status: str, skipped_reason: str | None = None) -> dict:
    """Full (instructor-side) result of a report self-check."""
    if skipped_reason:
        return {"band": "low", "compared": 0, "similar_submissions": 0, "passages": [],
                "note": skipped_reason, "semantic_status": semantic_status, "pairs": []}
    rows, passages = [], []
    lines = report_moderate_lines(pairs)
    for p in pairs:
        if student_sid not in (p.submission_a, p.submission_b):
            continue
        mine_is_a = p.submission_a == student_sid
        own_coverage = p.coverage_a if mine_is_a else p.coverage_b
        band = report_pair_band(p, own_coverage, lines)
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
        "class_baseline": lines,
        "small_class": is_small_class(lines),
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
            "similar_submissions": result["similar_submissions"],
            # Too few submissions to say what is normal for the class; results
            # stored before this field existed read as False.
            "small_class": bool(result.get("small_class"))}
    if kind == "code_similarity":
        safe["highlights"] = result.get("highlights", [])
    else:
        safe["passages"] = result.get("passages", [])
    if result.get("note"):
        safe["note"] = result["note"]
    return safe


def own_file_name(code_dir: Path, path: Path) -> str:
    return path.relative_to(code_dir).as_posix()
