"""Helpers shared by more than one router: turning database rows into API models, access checks,
and the code several sections need. Moved out of app/main.py; a helper used by one router lives there."""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import BASE_DIR, UPLOAD_DIR
from .evaluator.document_extraction import EXTRACTED_MARKDOWN_NAME, EXTRACTION_META_NAME
from .models import AutoEvaluation, Enrollment, InstructorAssignment, SimilarityFlag, Submission, User
from .schemas import UserOut


def _user_out(user: User, db: Session) -> UserOut:
    if user.role == "instructor":
        rows = db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == user.id).all()
        subjects = [row.subject for row in rows]
    elif user.role == "student":
        rows = db.query(Enrollment).filter(Enrollment.student_id == user.id).all()
        subjects = [row.subject for row in rows]
    else:
        subjects = []
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role, subjects=subjects,
                   batch=user.batch or "", register_number=user.register_number or "",
                   must_change_password=bool(user.must_change_password))


#
# One rubric holds all of its criteria (Rubric.criteria). Criteria are
# added, edited and removed through /rubrics/{id}/criteria -- never by
# creating another rubric -- and a second rubric with the same name in a
# subject is rejected. Grades store scores keyed by criterion name, so once
# a rubric has been used for grading its structure is locked: only
# descriptions can still be edited.

def _clean_name(name: Optional[str], what: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(400, f"{what} is required")
    return cleaned


def _marks_released(submission: Submission, now: datetime) -> bool:
    """Whether the student may see this submission's marks and feedback yet.
    Before the assignment's release date the student is told only that the
    work was submitted -- not even that it has been graded."""
    return submission.assignment is None or submission.assignment.marks_released_at(now)


def _remove_upload_part(rel_path: Optional[str], kind: str) -> None:
    """Delete one stored part (code/report/video) of a submission, plus the
    report's extraction sidecars; never touches anything outside uploads/."""
    if not rel_path:
        return
    target = (BASE_DIR / rel_path).resolve()
    root = UPLOAD_DIR.resolve()
    if not target.is_relative_to(root) or target == root:
        return
    upload_dir = root / target.relative_to(root).parts[0]
    shutil.rmtree(upload_dir / kind, ignore_errors=True)
    if kind == "report":
        for sidecar in (EXTRACTED_MARKDOWN_NAME, EXTRACTION_META_NAME):
            (upload_dir / sidecar).unlink(missing_ok=True)
    if upload_dir.is_dir() and not any(upload_dir.iterdir()):
        upload_dir.rmdir()


def _discard_derived_results(db: Session, submission_id: int) -> None:
    """Similarity flags and automated evaluations describe the old files."""
    db.query(SimilarityFlag).filter(
        (SimilarityFlag.submission_a_id == submission_id) | (SimilarityFlag.submission_b_id == submission_id)
    ).delete(synchronize_session=False)
    db.query(AutoEvaluation).filter(AutoEvaluation.submission_id == submission_id).delete(synchronize_session=False)
