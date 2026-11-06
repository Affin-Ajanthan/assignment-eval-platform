"""How a student gets into a subject.

The admin gives a subject to instructors only. Every subject is shown to every student as soon as it exists
(GET /student/subjects, each marked joined or not), but only a student who has joined can open it and see its
assignments. To join one the student enters its password (POST /student/subjects/{id}/join), which enrols them: from
then on it is one of their subjects, as if the admin had enrolled them. That works only once the instructor has set a
password and allowed students to register (GET/PUT /instructor/subjects/{id}/access); until then the subject is
listed but can't be joined. Switching registration off stops new students joining; the students already in the
subject stay. The instructor can also set an end date: registration then closes by itself at that time, and is
opened again by saving a later date (or none), with the same password or a new one. Changing the password never
removes a student who joined; it only decides which password new students must type (the old one stops working).
The admin can also add students to a subject (PUT /admin/students/{id}, subject_ids).
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_instructor, require_student, student_subject_ids
from ..common import UTCDateTime, as_utc, instructor_subject, utcnow_naive
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
    # When registration closes by itself. Left out keeps the saved date; null removes it (open until switched off).
    ends_at: Optional[datetime] = None


class SubjectAccessOut(BaseModel):
    open: bool  # registration is open right now: switched on, a password is set, and the end date has not passed
    password: str = ""  # for the instructor to read back and share
    ends_at: Optional[UTCDateTime] = None  # the saved end date (also after it has passed)
    expired: bool = False  # switched on, but the end date has passed: registration is closed until a later date is saved


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
    registration_ends_at: Optional[UTCDateTime] = None  # when open registration closes by itself (None: no end date)


class JoinIn(BaseModel):
    password: str = Field(max_length=_PASSWORD_MAX)


class JoinedOut(BaseModel):
    id: int
    name: str
    code: str
    batch: str = ""


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _ended(subject: Subject) -> bool:
    """The end date is set and has passed."""
    return subject.registration_ends_at is not None and utcnow_naive() >= subject.registration_ends_at


def _registration_open(subject: Subject) -> bool:
    return bool(subject.open_to_students) and bool(subject.join_password) and not _ended(subject)


def _access_out(subject: Subject) -> SubjectAccessOut:
    return SubjectAccessOut(
        open=_registration_open(subject), password=subject.join_password or "",
        ends_at=as_utc(subject.registration_ends_at),
        expired=bool(subject.open_to_students) and _ended(subject),
    )


@router.get("/instructor/subjects/{subject_id}/access", response_model=SubjectAccessOut)
def get_subject_access(subject_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    return _access_out(instructor_subject(db, instructor, subject_id))


@router.put("/instructor/subjects/{subject_id}/access", response_model=SubjectAccessOut)
def set_subject_access(
    subject_id: int, payload: SubjectAccessIn,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Allow students to register for the subject (with a password, and optionally until an end date) or stop them.
    A password or end date left out stays as it was. A new password never removes students who already joined."""
    subject = instructor_subject(db, instructor, subject_id)
    password = payload.password.strip() or None if payload.password is not None else subject.join_password
    ends_at = _naive_utc(payload.ends_at) if payload.ends_at is not None else None
    if "ends_at" not in payload.model_fields_set:
        ends_at = subject.registration_ends_at
    if payload.open and not password:
        raise HTTPException(400, "Set a password before allowing students to register.")
    if payload.open and ends_at is not None and ends_at <= utcnow_naive():
        raise HTTPException(400, "The registration end date must be in the future. Set a later date, or remove it.")
    subject.join_password = password
    subject.registration_ends_at = ends_at
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
            joined=is_joined, registration_open=_registration_open(s),
            registration_ends_at=as_utc(s.registration_ends_at) if _registration_open(s) else None))
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
            if subject.open_to_students and _ended(subject):
                raise HTTPException(403, "Registration for this subject has closed. Ask your instructor.")
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
