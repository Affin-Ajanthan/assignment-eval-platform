"""Helpers shared by more than one router: turning database rows into API models, access checks,
and the code several sections need. Moved out of app/main.py; a helper used by one router lives there."""

from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from .auth import instructor_subject_ids
from .db import BASE_DIR, UPLOAD_DIR
from .evaluator.document_extraction import EXTRACTED_MARKDOWN_NAME, EXTRACTION_META_NAME
from .models import AutoEvaluation, Enrollment, InstructorAssignment, Rubric, SimilarityFlag, Submission, User
from .schemas import UserOut


# Ids per IN (...) list: well under SQLite's limit on query parameters, whatever its version.
_IN_CHUNK = 900


def _users_out(users: list[User], db: Session) -> list[UserOut]:
    """Users with their subjects (an instructor's teaching subjects, a student's enrolments). The subjects of all of
    them are read together, with the subject rows in the same query: a list of 500 students takes two queries, not
    one or more per student."""
    subjects: dict[int, list] = defaultdict(list)
    for link, owner, role in ((InstructorAssignment, InstructorAssignment.instructor_id, "instructor"),
                              (Enrollment, Enrollment.student_id, "student")):
        ids = [u.id for u in users if u.role == role]
        for start in range(0, len(ids), _IN_CHUNK):
            rows = (db.query(link).options(joinedload(link.subject))
                    .filter(owner.in_(ids[start:start + _IN_CHUNK])).order_by(link.id).all())
            for row in rows:
                subjects[row.instructor_id if role == "instructor" else row.student_id].append(row.subject)
    return [UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role,
                    subjects=subjects.get(u.id, []) if u.role in ("instructor", "student") else [],
                    batch=u.batch or "", register_number=u.register_number or "",
                    must_change_password=bool(u.must_change_password))
            for u in users]


def _user_out(user: User, db: Session) -> UserOut:
    return _users_out([user], db)[0]


def _require_assignment_rubric(submission: Submission, rubric: Rubric) -> None:
    """An assignment with a rubric is graded (and auto-evaluated) with that rubric
    only, so marks never end up on another rubric. Without one, any rubric of the
    subject is allowed."""
    assignment = submission.assignment
    if assignment is not None and assignment.kind == "code_challenge":
        raise HTTPException(400, "A code challenge is marked from its tests, not with a rubric.")
    if assignment is not None and assignment.rubric_id is not None and assignment.rubric_id != rubric.id:
        raise HTTPException(
            400, f"This assignment is graded with the rubric '{assignment.rubric.name}', not '{rubric.name}'"
        )


def _can_view_submission(user: User, submission: Submission, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return submission.student_id == user.id
    if user.role == "instructor":
        return submission.subject_id in instructor_subject_ids(db, user)
    return False


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
