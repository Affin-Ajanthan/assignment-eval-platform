"""How a student gets into a subject.

The admin gives a subject to instructors only. An instructor then opens it to students and sets a password for it
(GET/PUT /instructor/subjects/{id}/access). Every student sees the open subjects (GET /student/open-subjects) and
joins one by entering its password (POST /student/subjects/{id}/join), which enrols them: from then on it is one of
their subjects, as if the admin had enrolled them. Closing a subject stops new students joining; the students
already in it stay.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_instructor, require_student, student_subject_ids
from ..common import instructor_subject
from ..db import get_db
from ..models import Enrollment, InstructorAssignment, Subject, User
from .student_runs import RunLimitError, UnlockLimiter

router = APIRouter()

_PASSWORD_MAX = 100

# Keeps a student from guessing a subject's password (per student and subject).
join_limiter = UnlockLimiter()


class SubjectAccessIn(BaseModel):
    open: bool
    # None keeps the password as it is; "" removes it (a subject without a password can't be open).
    password: Optional[str] = Field(default=None, max_length=_PASSWORD_MAX)


class SubjectAccessOut(BaseModel):
    open: bool
    password: str = ""  # for the instructor to read back and share


class OpenSubjectOut(BaseModel):
    id: int
    name: str
    code: str
    batch: str = ""
    instructors: list[str] = []


class JoinIn(BaseModel):
    password: str = Field(max_length=_PASSWORD_MAX)


class JoinedOut(BaseModel):
    id: int
    name: str
    code: str
    batch: str = ""


def _access_out(subject: Subject) -> SubjectAccessOut:
    return SubjectAccessOut(open=bool(subject.open_to_students), password=subject.join_password or "")


@router.get("/instructor/subjects/{subject_id}/access", response_model=SubjectAccessOut)
def get_subject_access(subject_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    return _access_out(instructor_subject(db, instructor, subject_id))


@router.put("/instructor/subjects/{subject_id}/access", response_model=SubjectAccessOut)
def set_subject_access(
    subject_id: int, payload: SubjectAccessIn,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Open the subject to students (with a password) or close it. A password left out stays as it was."""
    subject = instructor_subject(db, instructor, subject_id)
    if payload.password is not None:
        subject.join_password = payload.password.strip() or None
    if payload.open and not subject.join_password:
        raise HTTPException(400, "Set a password before opening the subject to students.")
    subject.open_to_students = payload.open
    db.commit()
    return _access_out(subject)


@router.get("/student/open-subjects", response_model=list[OpenSubjectOut])
def open_subjects(student: User = Depends(require_student), db: Session = Depends(get_db)):
    """The subjects the instructors have opened that the student has not joined yet."""
    joined = student_subject_ids(db, student)
    subjects = db.query(Subject).filter(Subject.open_to_students.is_(True)).order_by(Subject.name, Subject.id).all()
    out = []
    for s in subjects:
        if s.id in joined:
            continue
        teachers = (
            db.query(User.full_name)
            .join(InstructorAssignment, InstructorAssignment.instructor_id == User.id)
            .filter(InstructorAssignment.subject_id == s.id)
            .order_by(User.full_name)
            .all()
        )
        out.append(OpenSubjectOut(id=s.id, name=s.name, code=s.code, batch=s.batch or "",
                                  instructors=[name for (name,) in teachers]))
    return out


@router.post("/student/subjects/{subject_id}/join", response_model=JoinedOut)
def join_subject(
    subject_id: int, payload: JoinIn, student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Enter the subject's password. Right: the student is enrolled for good. Wrong: refused, and after a few wrong
    tries in a row the student must wait. A subject that is not open can't be joined."""
    subject = db.get(Subject, subject_id)
    if subject is None or not subject.open_to_students or not subject.join_password:
        raise HTTPException(404, "This subject is not open to students.")
    if subject_id not in student_subject_ids(db, student):
        key = (student.id, subject.id)
        try:
            join_limiter.check(key)
        except RunLimitError as exc:
            raise HTTPException(exc.status, exc.detail)
        given = payload.password.strip().encode("utf-8")
        if not hmac.compare_digest(given, subject.join_password.strip().encode("utf-8")):
            join_limiter.miss(key)
            raise HTTPException(403, "Wrong password.")
        join_limiter.clear(key)
        db.add(Enrollment(student_id=student.id, subject_id=subject.id))
        db.commit()
    return JoinedOut(id=subject.id, name=subject.name, code=subject.code, batch=subject.batch or "")
