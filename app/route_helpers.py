"""Helpers shared by more than one router: turning database rows into API models, access checks,
and the code several sections need. Moved out of app/main.py; a helper used by one router lives there."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Enrollment, InstructorAssignment, User
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
