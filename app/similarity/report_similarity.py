"""
Report similarity across one assignment's PDF reports.

    PDF --PyMuPDF--> page text --clean--> report text
        |-- Winnowing over word k-grams --> overlap scores + matching passages
        '-- all-MiniLM-L6-v2 chunk embeddings --> semantic score
    --> one combined result per pair, for instructor review

Every result is a review signal only: nothing here is stored with the code
similarity flags, so it never changes a mark. The thresholds below have not
been calibrated on real student reports -- treat them as exploratory.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from .core import _stable_hash, containment_similarity, jaccard_similarity

# Winnowing over words: k-grams of 6 words, window of 5, so every identical
# run of at least k + w - 1 = 10 words is guaranteed to share a fingerprint.
WORD_K = 6
WINDOW = 5
# Shorter identical runs are ordinary phrasing, not a copied passage.
MIN_PASSAGE_WORDS = 10
MAX_PASSAGES_PER_PAIR = 5
PASSAGE_CHARS = 400
# Reports with less text than this after cleaning aren't compared.
MIN_REPORT_WORDS = 50

# Text overlap flag (exploratory, uncalibrated).
TEXT_JACCARD_FLAG = 0.30
TEXT_CONTAINMENT_FLAG = 0.40
# Semantic review flag: absolute floor, raised by the cohort-outlier rule
# (median + z * 1.4826 * MAD) once there are enough pairs -- reports on the
# same assignment naturally score high against each other.
SEMANTIC_REVIEW_FLOOR = 0.85
SEMANTIC_OUTLIER_Z = 2.0
SEMANTIC_MIN_COHORT_PAIRS = 10

# Fingerprints found in this many reports are the assignment's own text
# (question brief, template headings) rather than copying between students.
COMMON_MIN_REPORTS = 3
COMMON_SHARE = 0.5


# --------------------------------------------------------------------------
# 1. Extraction (PyMuPDF)
# --------------------------------------------------------------------------

def extract_pdf_pages(path: Path) -> list[str]:
    """Plain text of every page. Raises on unreadable/encrypted files."""
    import pymupdf

    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF is password-protected")
        return [page.get_text("text") for page in doc]


# --------------------------------------------------------------------------
# 2. Cleaning
# --------------------------------------------------------------------------

_PAGE_NUMBER_RE = re.compile(
    r"^(?:page\s*)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?$"  # 3, Page 3, 3 of 10, 3/10
    r"|^[-–—]\s*\d{1,4}\s*[-–—]$"     # - 3 -
    r"|^[ivxlcdm]{1,6}$",                                # roman page numbers
    re.IGNORECASE,
)
_EDGE_LINES = 3


def _line_key(line: str) -> str:
    # "Group Report - page 3" and "... page 4" are the same running header.
    return re.sub(r"\d+", "#", line.lower())


def clean_report_pages(pages: list[str]) -> str:
    """Join the pages into one text without page furniture: page-number
    lines, and running headers/footers -- lines near the top or bottom of
    a page (digits ignored) that repeat on at least half of the pages.
    Words hyphenated across line breaks are rejoined; whitespace is
    collapsed. The wording itself is left untouched."""
    page_lines = [[line.strip() for line in page.splitlines() if line.strip()] for page in pages]
    n_pages = len(page_lines)
    edge_counts: Counter[str] = Counter()
    for lines in page_lines:
        edge_counts.update({_line_key(l) for l in lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]})
    min_repeats = max(2, math.ceil(n_pages * 0.5))
    running = {key for key, count in edge_counts.items() if n_pages >= 2 and count >= min_repeats}

    kept: list[str] = []
    for lines in page_lines:
        for i, line in enumerate(lines):
            at_edge = i < _EDGE_LINES or i >= len(lines) - _EDGE_LINES
            if _PAGE_NUMBER_RE.match(line) or (at_edge and _line_key(line) in running):
                continue
            kept.append(line)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", "\n".join(kept))
    return " ".join(text.split())


# --------------------------------------------------------------------------
# 3. Winnowing over words, keeping positions for passage reporting
# --------------------------------------------------------------------------

@dataclass
class ReportText:
    submission_id: str
    text: str
    words: list[str] = field(default_factory=list)          # lower-cased
    spans: list[tuple[int, int]] = field(default_factory=list)  # char offsets in `text`
    fingerprints: dict[int, list[int]] = field(default_factory=dict)  # hash -> k-gram starts

    @property
    def word_count(self) -> int:
        return len(self.words)


def tokenize(submission_id: str, text: str) -> ReportText:
    report = ReportText(submission_id=submission_id, text=text)
    for m in re.finditer(r"\w+", text):
        report.words.append(m.group().lower())
        report.spans.append(m.span())
    report.fingerprints = winnow_words(report.words)
    return report


def winnow_words(words: list[str], k: int = WORD_K, window: int = WINDOW) -> dict[int, list[int]]:
    """Winnowing (Schleimer et al., 2003) over word k-grams: the minimum
    hash of every window, rightmost on ties, with the k-gram's start."""
    if len(words) < k:
        return {}
    hashes = [_stable_hash(words[i:i + k]) for i in range(len(words) - k + 1)]
    selected: dict[int, list[int]] = {}
    last = -1
    for start in range(max(1, len(hashes) - window + 1)):
        window_hashes = hashes[start:start + window]
        low = min(window_hashes)
        pos = start + max(i for i, h in enumerate(window_hashes) if h == low)
        if pos != last:
            selected.setdefault(low, []).append(pos)
            last = pos
    return selected


def remove_common_fingerprints(reports: list[ReportText]) -> int:
    """Drop fingerprints present in many reports (the assignment brief or a
    template everyone was given). Returns how many distinct ones were dropped."""
    n = len(reports)
    if n < COMMON_MIN_REPORTS:
        return 0
    counts = Counter(h for r in reports for h in r.fingerprints)
    common = {h for h, c in counts.items() if c >= max(COMMON_MIN_REPORTS, math.ceil(n * COMMON_SHARE))}
    for r in reports:
        for h in common:
            r.fingerprints.pop(h, None)
    return len(common)


@dataclass
class Passage:
    words: int
    text_a: str
    text_b: str


def _excerpt(report: ReportText, start: int, end: int) -> str:
    text = report.text[report.spans[start][0]:report.spans[end - 1][1]]
    return text if len(text) <= PASSAGE_CHARS else text[:PASSAGE_CHARS].rstrip() + "…"


def matching_passages(a: ReportText, b: ReportText) -> tuple[list[Passage], int, int]:
    """Identical word runs shared by both reports, grown from each shared
    fingerprint to its full extent. Returns the longest (non-overlapping)
    passages and the number of words of A and of B that they cover."""
    found: list[tuple[int, int, int]] = []  # (start_a, start_b, length)
    for h in a.fingerprints.keys() & b.fingerprints.keys():
        for pa in a.fingerprints[h][:5]:
            for pb in b.fingerprints[h][:5]:
                if a.words[pa:pa + WORD_K] != b.words[pb:pb + WORD_K]:
                    continue  # hash collision
                sa, sb = pa, pb
                while sa > 0 and sb > 0 and a.words[sa - 1] == b.words[sb - 1]:
                    sa, sb = sa - 1, sb - 1
                ea, eb = pa + WORD_K, pb + WORD_K
                while ea < len(a.words) and eb < len(b.words) and a.words[ea] == b.words[eb]:
                    ea, eb = ea + 1, eb + 1
                if ea - sa >= MIN_PASSAGE_WORDS:
                    found.append((sa, sb, ea - sa))

    kept: list[tuple[int, int, int]] = []
    used_a: set[int] = set()
    used_b: set[int] = set()
    for sa, sb, length in sorted(set(found), key=lambda p: (-p[2], p[0], p[1])):
        range_a, range_b = set(range(sa, sa + length)), set(range(sb, sb + length))
        if range_a & used_a or range_b & used_b:
            continue
        kept.append((sa, sb, length))
        used_a |= range_a
        used_b |= range_b
    passages = [Passage(words=length, text_a=_excerpt(a, sa, sa + length), text_b=_excerpt(b, sb, sb + length))
                for sa, sb, length in kept[:MAX_PASSAGES_PER_PAIR]]
    return passages, len(used_a), len(used_b)


# --------------------------------------------------------------------------
# 4. Semantic similarity (all-MiniLM-L6-v2 chunk embeddings)
# --------------------------------------------------------------------------

def best_match_similarity(chunks_a, weights_a, chunks_b, weights_b) -> float:
    """Symmetric best-match cosine: each chunk of one report is matched to
    its most similar chunk of the other (weighted by its word count), in
    both directions, then averaged. A copied section scores high even when
    the rest of the reports differ. Rows must be L2-normalized."""
    import numpy as np

    sims = np.asarray(chunks_a) @ np.asarray(chunks_b).T
    wa, wb = np.asarray(weights_a, dtype=float), np.asarray(weights_b, dtype=float)
    a_to_b = float((sims.max(axis=1) * wa).sum() / wa.sum())
    b_to_a = float((sims.max(axis=0) * wb).sum() / wb.sum())
    return min(1.0, max(0.0, (a_to_b + b_to_a) / 2))


def semantic_review_bar(scores: list[float]) -> tuple[float, float | None]:
    """(review threshold, cohort median). The floor alone until there are
    enough pairs to judge what is normal for this assignment."""
    if len(scores) < SEMANTIC_MIN_COHORT_PAIRS:
        return SEMANTIC_REVIEW_FLOOR, (statistics.median(scores) if scores else None)
    median = statistics.median(scores)
    mad = statistics.median(abs(s - median) for s in scores)
    return max(SEMANTIC_REVIEW_FLOOR, median + SEMANTIC_OUTLIER_Z * 1.4826 * mad), median


# --------------------------------------------------------------------------
# 5. Combined comparison
# --------------------------------------------------------------------------

@dataclass
class ReportPair:
    submission_a: str
    submission_b: str
    words_a: int
    words_b: int
    shared_fingerprints: int
    jaccard: float
    containment: float
    coverage_a: float  # share of A's words inside a matching passage
    coverage_b: float
    passages: list[Passage]
    semantic_similarity: float | None = None
    flag_level: str | None = None  # "high" (identical passages) | "review" (semantic only)
    flag_reason: str | None = None


@dataclass
class ReportComparison:
    pairs: list[ReportPair]
    common_fingerprints_excluded: int
    semantic_status: str  # ok | disabled | unavailable
    semantic_warning: str | None = None
    semantic_pairs_compared: int = 0
    cohort_median: float | None = None
    review_threshold: float | None = None


def compare_reports(texts: dict[str, str], service=None) -> ReportComparison:
    """Compare every pair of cleaned report texts. ``service`` is the
    shared sentence-embedding service (None skips the semantic signal).
    Never raises because the model failed: the text results stand alone."""
    reports = [tokenize(sid, text) for sid, text in texts.items()]
    common = remove_common_fingerprints(reports)

    pairs: list[ReportPair] = []
    for a, b in combinations(reports, 2):
        ha, hb = set(a.fingerprints), set(b.fingerprints)
        passages, covered_a, covered_b = matching_passages(a, b)
        pair = ReportPair(
            submission_a=a.submission_id, submission_b=b.submission_id,
            words_a=a.word_count, words_b=b.word_count,
            shared_fingerprints=len(ha & hb),
            jaccard=round(jaccard_similarity(ha, hb), 4),
            containment=round(containment_similarity(ha, hb), 4),
            coverage_a=round(covered_a / a.word_count, 4) if a.word_count else 0.0,
            coverage_b=round(covered_b / b.word_count, 4) if b.word_count else 0.0,
            passages=passages,
        )
        if pair.jaccard >= TEXT_JACCARD_FLAG or pair.containment >= TEXT_CONTAINMENT_FLAG:
            pair.flag_level = "high"
            pair.flag_reason = (f"Identical passages: {max(pair.coverage_a, pair.coverage_b):.0%} of one "
                                f"report's text also appears word-for-word in the other")
        pairs.append(pair)

    result = ReportComparison(pairs=pairs, common_fingerprints_excluded=common, semantic_status="disabled")
    if service is None or not service.load():
        if service is not None:
            result.semantic_status = service.status
            result.semantic_warning = (
                f"Semantic report comparison unavailable: {service.error}" if service.status == "unavailable"
                else "Semantic report comparison is turned off (CROSS_MODAL_SEMANTIC=0)."
            )
        return result
    try:
        embedded = service.embed_chunks({r.submission_id: r.text for r in reports})
    except Exception as exc:  # inference failure: keep the text results
        result.semantic_status = "unavailable"
        result.semantic_warning = f"Semantic report comparison failed: {exc.__class__.__name__}: {exc}"[:300]
        return result

    for pair in pairs:
        va, wa = embedded[pair.submission_a]
        vb, wb = embedded[pair.submission_b]
        pair.semantic_similarity = round(best_match_similarity(va, wa, vb, wb), 4)
    scores = [p.semantic_similarity for p in pairs]
    bar, median = semantic_review_bar(scores)
    for pair in pairs:
        if pair.flag_level is None and pair.semantic_similarity >= bar:
            pair.flag_level = "review"
            pair.flag_reason = ("Very similar meaning (MiniLM) with few identical passages -- possibly "
                                "paraphrased; compare the reports")
    result.semantic_status = "ok"
    result.semantic_pairs_compared = len(pairs)
    result.cohort_median = round(median, 4) if median is not None else None
    result.review_threshold = round(bar, 4)
    return result
