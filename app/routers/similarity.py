"""The instructor's similarity checks: the API.

Code similarity across one assignment's submissions (token Winnowing +
UniXcoder; stores SimilarityFlag rows), report similarity (word Winnowing +
MiniLM; stores nothing) and their Excel exports. The comparisons themselves
are in app/similarity_runs.py, shared with the student self-checks
(app/routers/self_checks.py). No flag here ever changes a mark.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import exports as _exports
from ..auth import instructor_subject_ids, require_instructor
from ..common import instructor_subject
from ..db import get_db
from ..models import SimilarityFlag, Submission, User
from ..similarity.semantic import MODEL_NAME as _SEMANTIC_MODEL
from ..similarity_runs import code_similarity_run, report_similarity_run

router = APIRouter()


class SimilarityPairOut(BaseModel):
    submission_a_id: int
    submission_b_id: int
    student_a: str
    student_b: str
    shared_fingerprints: int
    jaccard: float
    containment: float
    # UniXcoder cosine similarity (0-1); None when semantic analysis
    # was unavailable or skipped for this pair (e.g. a tiny submission).
    semantic_similarity: Optional[float]
    token_flagged: bool
    # Final flag: token overlap OR a semantic "review" signal.
    flagged: bool
    flag_level: Optional[str]  # "high" | "review" | None
    flag_reason: Optional[str]


class SemanticSummaryOut(BaseModel):
    status: str  # "ok" | "unavailable" | "disabled"
    model: str
    warning: Optional[str] = None
    submissions_encoded: int = 0
    cache_hits: int = 0
    skipped_too_small: list[int] = []
    pairs_compared: int = 0
    cohort_median: Optional[float] = None
    review_threshold: Optional[float] = None


class SimilarityCheckOut(BaseModel):
    subject_id: int
    assignment_name: str
    compared: int
    pairs: list[SimilarityPairOut]
    semantic: SemanticSummaryOut
    # True when the assignment's starter code was subtracted from the
    # token fingerprints before comparing.
    starter_code_excluded: bool = False
    # Distinct code patterns ignored because most of the class shares them
    # (0 when the assignment's "ignore common code" option is off).
    common_code_removed: int = 0


class ReportPassageOut(BaseModel):
    words: int
    text_a: str
    text_b: str


class ReportSimilarityPairOut(BaseModel):
    submission_a_id: int
    submission_b_id: int
    student_a: str
    student_b: str
    words_a: int
    words_b: int
    shared_fingerprints: int
    jaccard: float
    containment: float
    # Share of each report's words inside an identical passage.
    coverage_a: float
    coverage_b: float
    # all-MiniLM-L6-v2 best-match similarity; None when it didn't run.
    semantic_similarity: Optional[float]
    flag_level: Optional[str]  # "high" (identical passages) | "review" (semantic) | None
    flag_reason: Optional[str]
    passages: list[ReportPassageOut]


class ReportSkippedOut(BaseModel):
    submission_id: int
    student: str
    reason: str


class ReportSemanticSummaryOut(BaseModel):
    status: str  # ok | disabled | unavailable
    model: str
    warning: Optional[str] = None
    pairs_compared: int = 0
    cohort_median: Optional[float] = None
    review_threshold: Optional[float] = None


class ReportSimilarityOut(BaseModel):
    subject_id: int
    assignment_name: str
    compared: int
    skipped: list[ReportSkippedOut]
    # Fingerprints found in most reports (the assignment brief, a template)
    # that were left out of the comparison.
    common_fingerprints_excluded: int
    # The assignment's template PDF that was cut out of every report first.
    template_filename: Optional[str] = None
    template_words_removed: dict[str, int] = {}  # submission id -> words cut
    # Reference lists and cited quotations cut out first (they are meant to match sources).
    cited_words_removed: dict[str, int] = {}  # submission id -> words cut
    pairs: list[ReportSimilarityPairOut]
    semantic: ReportSemanticSummaryOut
    # Thresholds are uncalibrated: results are exploratory review signals.
    exploratory: bool = True


# ---- Similarity check across one subject's assignment submissions ---------

@router.post("/subjects/{subject_id}/assignments/{assignment_name}/check-similarity",
             response_model=SimilarityCheckOut)
def check_similarity(
    subject_id: int, assignment_name: str, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")

    submissions = (
        db.query(Submission)
        .filter(
            Submission.subject_id == subject_id,
            Submission.assignment_name == assignment_name,
            Submission.code_path.isnot(None),
        )
        .all()
    )
    if len(submissions) < 2:
        raise HTTPException(400, "Need at least 2 code submissions for this assignment to compare")

    run = code_similarity_run(db, subject_id, assignment_name, submissions)
    pairs, batch, stats, starter_fp = run.pairs, run.batch, run.stats, run.starter_fp

    db.query(SimilarityFlag).filter(
        SimilarityFlag.subject_id == subject_id, SimilarityFlag.assignment_name == assignment_name
    ).delete()
    for pair in pairs:
        if pair.flagged:
            db.add(SimilarityFlag(
                subject_id=subject_id,
                assignment_name=assignment_name,
                submission_a_id=int(pair.submission_a),
                submission_b_id=int(pair.submission_b),
                jaccard=pair.jaccard,
                containment=pair.containment,
                semantic_similarity=pair.semantic_similarity,
                flag_level=pair.flag_level or "high",
                flag_reason=pair.flag_reason or "High token/fingerprint overlap",
            ))
    db.commit()

    names = {str(s.id): s.student_name for s in submissions}
    return SimilarityCheckOut(
        subject_id=subject_id,
        assignment_name=assignment_name,
        compared=len(submissions),
        pairs=[
            SimilarityPairOut(
                submission_a_id=int(p.submission_a), submission_b_id=int(p.submission_b),
                student_a=names[p.submission_a], student_b=names[p.submission_b],
                shared_fingerprints=p.shared_fingerprints,
                jaccard=p.jaccard, containment=p.containment,
                semantic_similarity=p.semantic_similarity,
                token_flagged=p.token_flagged,
                flagged=p.flagged,
                flag_level=p.flag_level or ("high" if p.token_flagged else None),
                flag_reason=p.flag_reason or ("High token/fingerprint overlap" if p.token_flagged else None),
            )
            for p in pairs
        ],
        semantic=SemanticSummaryOut(
            status=batch.status,
            model=_SEMANTIC_MODEL,
            warning=batch.warning,
            submissions_encoded=batch.encoded,
            cache_hits=batch.cache_hits,
            skipped_too_small=sorted(int(s) for s in batch.skipped_too_small),
            pairs_compared=stats.get("semantic_pairs_compared", 0),
            cohort_median=stats.get("cohort_median"),
            review_threshold=stats.get("review_threshold"),
        ),
        starter_code_excluded=starter_fp is not None,
        common_code_removed=run.common_removed,
    )


@router.post("/subjects/{subject_id}/assignments/{assignment_name}/check-report-similarity",
             response_model=ReportSimilarityOut)
def check_report_similarity(
    subject_id: int, assignment_name: str, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Compare the PDF reports of one assignment pairwise: identical
    passages (Winnowing over words) and similar meaning (all-MiniLM-L6-v2).
    Review signal only -- nothing is stored, so it never affects grading."""
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")

    submissions = (
        db.query(Submission)
        .filter(Submission.subject_id == subject_id, Submission.assignment_name == assignment_name)
        .order_by(Submission.id)
        .all()
    )
    names = {str(s.id): s.student_name for s in submissions}
    run = report_similarity_run(db, subject_id, assignment_name, submissions)
    if run.comparison is None:
        raise HTTPException(400, "Need at least 2 readable PDF reports for this assignment to compare")
    result, assignment = run.comparison, run.assignment
    template = assignment.report_template_text if assignment else None
    return ReportSimilarityOut(
        subject_id=subject_id,
        assignment_name=assignment_name,
        compared=len(run.texts),
        skipped=[ReportSkippedOut(submission_id=s.id, student=s.student_name, reason=reason)
                 for s, reason in run.skipped],
        common_fingerprints_excluded=result.common_fingerprints_excluded,
        template_filename=(assignment.report_template_filename if template else None),
        template_words_removed=result.template_words_removed,
        cited_words_removed=result.cited_words_removed,
        pairs=[
            ReportSimilarityPairOut(
                submission_a_id=int(p.submission_a), submission_b_id=int(p.submission_b),
                student_a=names[p.submission_a], student_b=names[p.submission_b],
                words_a=p.words_a, words_b=p.words_b, shared_fingerprints=p.shared_fingerprints,
                jaccard=p.jaccard, containment=p.containment, coverage_a=p.coverage_a, coverage_b=p.coverage_b,
                semantic_similarity=p.semantic_similarity, flag_level=p.flag_level, flag_reason=p.flag_reason,
                passages=[ReportPassageOut(words=x.words, text_a=x.text_a, text_b=x.text_b) for x in p.passages],
            )
            for p in result.pairs
        ],
        semantic=ReportSemanticSummaryOut(
            status=result.semantic_status, model="sentence-transformers/all-MiniLM-L6-v2",
            warning=result.semantic_warning, pairs_compared=result.semantic_pairs_compared,
            cohort_median=result.cohort_median, review_threshold=result.review_threshold,
        ),
    )


# ---- Excel exports of the two results ---------------------------------------
#
# The browser sends back the result it received and gets the same data as
# .xlsx, so nothing expensive is re-run. Instructor-only, for their own subjects.

@router.post("/exports/code-similarity.xlsx")
def export_code_similarity(
    payload: SimilarityCheckOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = instructor_subject(db, instructor, payload.subject_id)
    return _exports.xlsx_response(_exports.code_similarity_xlsx(payload, f"{subject.name} ({subject.code})"),
                                  "code-similarity", payload.assignment_name)


@router.post("/exports/report-similarity.xlsx")
def export_report_similarity(
    payload: ReportSimilarityOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = instructor_subject(db, instructor, payload.subject_id)
    return _exports.xlsx_response(_exports.report_similarity_xlsx(payload, f"{subject.name} ({subject.code})"),
                                  "report-similarity", payload.assignment_name)
