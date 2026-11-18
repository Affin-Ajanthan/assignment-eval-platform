"""Manual grading, and the Excel export of a whole-assignment evaluation.

Moved out of app/main.py (Manual grading, Excel export). Included in app/main.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import exports as _exports
from ..auth import get_current_user, instructor_subject_ids, require_instructor
from ..common import instructor_subject as _instructor_subject
from ..db import get_db
from ..models import Grade, Rubric, Submission, User
from ..route_helpers import _can_view_submission, _require_assignment_rubric
from ..schemas import BatchAutoEvaluateOut, GradeIn, GradeOut


router = APIRouter()


def _require_two_decimals(label: str, score: float) -> None:
    """Manual marks have at most 2 decimal places (7.25 is fine, 7.3333 is not)."""
    if round(score, 2) != score:
        raise HTTPException(400, f"{label} must have at most 2 decimal places, got {score}")


@router.post("/submissions/{submission_id}/grade", response_model=GradeOut)
def grade_submission(
    submission_id: int, payload: GradeIn, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    submission = db.get(Submission, submission_id)
    rubric = db.get(Rubric, payload.rubric_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    if submission.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    if rubric.subject_id != submission.subject_id:
        raise HTTPException(400, "That rubric belongs to a different subject than this submission")
    _require_assignment_rubric(submission, rubric)

    if payload.total_score is not None:
        # Final mark only: no per-criterion marks are stored, rather than
        # inventing a split the instructor never decided.
        if payload.criterion_scores:
            raise HTTPException(400, "Send either criterion_scores or total_score, not both")
        if payload.total_score < 0 or payload.total_score > rubric.max_total:
            raise HTTPException(
                400,
                f"Final mark must be between 0 and {rubric.max_total}, got {payload.total_score}",
            )
        _require_two_decimals("Final mark", payload.total_score)
        total = payload.total_score
    else:
        valid_names = {c["name"] for c in rubric.criteria}
        max_points = {c["name"]: c["max_points"] for c in rubric.criteria}
        unknown = set(payload.criterion_scores) - valid_names
        if unknown:
            raise HTTPException(400, f"Unknown criteria for this rubric: {sorted(unknown)}")
        for name, score in payload.criterion_scores.items():
            if score < 0 or score > max_points[name]:
                raise HTTPException(
                    400,
                    f"Score for '{name}' must be between 0 and {max_points[name]}, got {score}",
                )
            _require_two_decimals(f"Score for '{name}'", score)
        total = round(sum(payload.criterion_scores.values()), 2)  # no 0.1 + 0.2 float noise


    grade = Grade(
        submission_id=submission_id,
        rubric_id=payload.rubric_id,
        criterion_scores=payload.criterion_scores,
        total_score=total,
        comments=payload.comments,
        feedback=(payload.feedback or "").strip() or None,
        graded_by_id=instructor.id,
        graded_by=instructor.full_name,
    )
    submission.status = "graded"
    db.add(grade)
    db.add(submission)
    db.commit()
    db.refresh(grade)
    return grade


@router.get("/submissions/{submission_id}/grade", response_model=Optional[GradeOut])
def get_grade(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "student":
        # Criterion-level marks and comments are instructor-only; students get
        # their final mark from GET /submissions and GET /assignments.
        raise HTTPException(403, "Detailed grading is only available to instructors.")
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not _can_view_submission(user, submission, db):
        raise HTTPException(403, "You cannot view this submission")
    return (
        db.query(Grade)
        .filter(Grade.submission_id == submission_id)
        .order_by(Grade.graded_at.desc())
        .first()
    )


#
# The browser sends back the result it received and gets the same data as
# .xlsx, so nothing is re-run. Instructor-only, for their own subjects. (The
# similarity exports are in app/routers/similarity.py.)

@router.post("/exports/batch-evaluation.xlsx")
def export_batch_evaluation(
    payload: BatchAutoEvaluateOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = _instructor_subject(db, instructor, payload.subject_id)
    rubric = db.get(Rubric, payload.rubric_id)
    rubric_name = rubric.name if rubric and rubric.subject_id == subject.id else f"Rubric #{payload.rubric_id}"
    return _exports.xlsx_response(
        _exports.batch_evaluation_xlsx(payload, f"{subject.name} ({subject.code})", rubric_name),
        "evaluation", payload.assignment_name)
