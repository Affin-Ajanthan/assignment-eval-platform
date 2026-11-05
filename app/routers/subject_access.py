"""How a student gets into a subject.

The admin gives a subject to instructors only. Every subject is shown to every student as soon as it exists
(GET /student/subjects, each marked joined or not), but only a student who has joined can open it and see its
assignments. To join one the student enters its password (POST /student/subjects/{id}/join), which enrols them: from
then on it is one of their subjects, as if the admin had enrolled them. That works only once the instructor has set a
password and allowed students to register (GET/PUT /instructor/subjects/{id}/access); until then the subject is
listed but can't be joined. Switching registration off stops new students joining; the students already in the
subject stay.
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


class TeacherOut(BaseModel):
    name: str
    email: str = ""  # only given to a student who joined the subject


class StudentSubjectOut(BaseModel):
    id: int
    name: str
    code: str
    batch: str = ""
    teachers: list[TeacherOut] = []  # the instructors of the subject
    joined: bool = False  # the student is in it: only then can they open it and see its assignments
    registration_open: bool = False  # the instructor has set a password and allowed students to register


class JoinIn(BaseModel):
    password: str = Field(max_length=_PASSWORD_MAX)


class JoinedOut(BaseModel):
    id: int
    name: str
    code: str
    batch: str = ""


def _access_out(subject: Subject) -> SubjectAccessOut:
    return SubjectAccessOut(open=bool(subject.open_to_students), password=subject.join_password or "")


def _registration_open(subject: Subject) -> bool:
    return bool(subject.open_to_students) and bool(subject.join_password)


@router.get("/instructor/subjects/{subject_id}/access", response_model=SubjectAccessOut)
def get_subject_access(subject_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    return _access_out(instructor_subject(db, instructor, subject_id))


@router.put("/instructor/subjects/{subject_id}/access", response_model=SubjectAccessOut)
def set_subject_access(
    subject_id: int, payload: SubjectAccessIn,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Allow students to register for the subject (with a password) or stop them. A password left out stays as it was."""
    subject = instructor_subject(db, instructor, subject_id)
    if payload.password is not None:
        subject.join_password = payload.password.strip() or None
    if payload.open and not subject.join_password:
        raise HTTPException(400, "Set a password before allowing students to register.")
    subject.open_to_students = payload.open
    db.commit()
    return _access_out(subject)


@router.get("/student/subjects", response_model=list[StudentSubjectOut])
def student_subjects(student: User = Depends(require_student), db: Session = Depends(get_db)):
    """Every subject there is, each marked as joined or not (and, if not, whether registration is open for it)."""
    joined = student_subject_ids(db, student)
    subjects = db.query(Subject).order_by(Subject.name, Subject.id).all()
    out = []
    for s in subjects:
        teachers = (
            db.query(User.full_name, User.email)
            .join(InstructorAssignment, InstructorAssignment.instructor_id == User.id)
            .filter(InstructorAssignment.subject_id == s.id)
            .order_by(User.full_name)
            .all()
        )
        is_joined = s.id in joined
        out.append(StudentSubjectOut(
            id=s.id, name=s.name, code=s.code, batch=s.batch or "",
            # An instructor's e-mail is for the students in the subject; the others see the name only.
            teachers=[TeacherOut(name=name, email=email if is_joined else "") for name, email in teachers],
            joined=is_joined, registration_open=_registration_open(s)))
    return out


@router.post("/student/subjects/{subject_id}/join", response_model=JoinedOut)
def join_subject(
    subject_id: int, payload: JoinIn, student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Enter the subject's password. Right: the student is enrolled for good. Wrong: refused, and after a few wrong
    tries in a row the student must wait. A subject the instructor has not allowed students to register for (no
    password set, or registration switched off) can't be joined yet."""
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found.")
    if subject_id not in student_subject_ids(db, student):
        if not _registration_open(subject):
            raise HTTPException(403, "Registration for this subject is not open yet. Ask your instructor.")
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
