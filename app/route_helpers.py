"""Helpers shared by more than one router: turning database rows into API models, access checks,
and the code several sections need. Moved out of app/main.py; a helper used by one router lives there."""

from __future__ import annotations

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
