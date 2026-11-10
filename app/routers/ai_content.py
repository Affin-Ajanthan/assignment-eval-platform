"""The instructor's AI-content check: the API.

Estimates, for every submission to one assignment, whether the report and the code look machine-generated.
The same detectors as the auto-evaluation and the student self-check (Fast-DetectGPT or the style heuristic
for the report, the style heuristic for the code). A review signal only: nothing is stored and no mark changes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import instructor_subject_ids, require_instructor
from ..common import ANALYZED_EXTENSIONS
from ..db import BASE_DIR, get_db
from ..evaluator.document_extraction import extract_report_text, load_extraction
from ..evaluator.report_analysis import ai_text_signal
from ..models import Submission, User
from ..notebook import read_code
from ..similarity.ai_heuristics import score_source as _score_ai_code

router = APIRouter()


class AiPartOut(BaseModel):
    signal: str  # low | medium | high
    score: int  # 0-100, higher = more AI-like
    method: str  # e.g. "style-heuristic", "fast-detectgpt:Qwen2.5-0.5B"
    reasons: list[str]


class AiContentRowOut(BaseModel):
    submission_id: int
    student_name: str
    student_email: str
    report: Optional[AiPartOut] = None  # None: no readable report
    code: Optional[AiPartOut] = None  # None: no code


class AiContentCheckOut(BaseModel):
    subject_id: int
    assignment_name: str
    checked: int
    flagged: int  # submissions with a high signal on the report or the code
    rows: list[AiContentRowOut]


_ORDER = {"high": 2, "medium": 1, "low": 0}


def _report_part(submission: Submission) -> Optional[AiPartOut]:
    if not submission.report_path:
        return None
    path = BASE_DIR / submission.report_path
    extraction = (load_extraction(path) or extract_report_text(path)) if path.is_file() else None
    if not (extraction and extraction.ok and extraction.text.strip()):
        return None
    s = ai_text_signal(extraction.text)
    return AiPartOut(signal=s.signal, score=s.score, method=s.method, reasons=list(s.reasons))


def _code_part(submission: Submission) -> Optional[AiPartOut]:
    if not submission.code_path:
        return None
    code_dir = BASE_DIR / submission.code_path
    if not code_dir.is_dir():
        return None
    source = "\n".join(
        read_code(p)[1] for p in sorted(code_dir.rglob("*")) if p.is_file() and p.suffix.lower() in ANALYZED_EXTENSIONS
    )
    if not source.strip():
        return None
    s = _score_ai_code(str(submission.id), source)
    return AiPartOut(signal=s.signal, score=s.score, method="style-heuristic", reasons=list(s.reasons))


def _worst(row: AiContentRowOut) -> int:
    return max((_ORDER.get(p.signal, -1) for p in (row.report, row.code) if p), default=-1)


@router.post("/subjects/{subject_id}/assignments/{assignment_name}/check-ai-content", response_model=AiContentCheckOut)
def check_ai_content(
    subject_id: int, assignment_name: str, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Check every submission to one assignment for AI-generated content. Review signal only."""
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    submissions = (
        db.query(Submission)
        .filter(Submission.subject_id == subject_id, Submission.assignment_name == assignment_name)
        .order_by(Submission.id)
        .all()
    )
    if not submissions:
        raise HTTPException(400, "There are no submissions to this assignment yet")

    rows = [
        AiContentRowOut(
            submission_id=s.id, student_name=s.student_name, student_email=s.student_email,
            report=_report_part(s), code=_code_part(s),
        )
        for s in submissions
    ]
    rows.sort(key=lambda r: (-_worst(r), r.student_name.lower()))  # the most AI-like first
    return AiContentCheckOut(
        subject_id=subject_id, assignment_name=assignment_name, checked=len(rows),
        flagged=sum(_worst(r) == 2 for r in rows), rows=rows,
    )
