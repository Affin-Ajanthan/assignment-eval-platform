"""The admin's subjects, instructors and students, including the spreadsheet import of students.

Moved out of app/main.py (Admin: subjects, Admin: instructors, Admin: students). Included in app/main.py."""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import exports as _exports, student_import as _student_import
from ..auth import hash_password, require_admin
from ..db import get_db
from ..models import (
    Assignment,
    AuthSession,
    Enrollment,
    Grade,
    InstructorAssignment,
    Rubric,
    Subject,
    Submission,
    TaskStart,
    TaskUnlock,
    User,
)
from ..route_helpers import _discard_derived_results, _remove_upload_part, _user_out
from ..schemas import (
    ImportPreviewOut,
    ImportResultOut,
    ImportRowOut,
    InstructorCreate,
    StudentCreate,
    SubjectCreate,
    SubjectIdsIn,
    SubjectOut,
    SubjectUpdate,
    UserOut,
    UserUpdate,
)


router = APIRouter()


_import_log = logging.getLogger("app.student_import")


REGISTER_PREFIX = "TST"  # every register number starts with it: TST/<batch>/<number>, e.g. TST/01/001


def _set_instructor_subjects(db: Session, instructor: User, subject_ids: list[int]) -> None:
    db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == instructor.id).delete()
    for sid in subject_ids:
        db.add(InstructorAssignment(instructor_id=instructor.id, subject_id=sid))
    db.commit()


def _set_student_subjects(db: Session, student: User, subject_ids: list[int]) -> None:
    db.query(Enrollment).filter(Enrollment.student_id == student.id).delete()
    for sid in subject_ids:
        db.add(Enrollment(student_id=student.id, subject_id=sid))
    db.commit()


def _require_subjects_exist(db: Session, subject_ids: list[int]) -> None:
    found = {s.id for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()}
    missing = set(subject_ids) - found
    if missing:
        raise HTTPException(400, f"Unknown subject id(s): {sorted(missing)}")


def _check_subject_code_free(db: Session, code: str, batch: str, own_id: Optional[int] = None) -> None:
    """The same subject code is fine in different batches (each batch has the same subjects), but not twice in one
    batch, where the two subjects could not be told apart. Or the HTTP error saying so."""
    query = db.query(Subject).filter(Subject.code == code, Subject.batch == batch)
    if own_id is not None:
        query = query.filter(Subject.id != own_id)
    if query.first():
        where = f"batch '{batch}'" if batch else "the subjects without a batch"
        raise HTTPException(400, f"Subject code '{code}' already exists in {where}")


def _require_instructors_exist(db: Session, instructor_ids: list[int]) -> None:
    found = {u.id for u in db.query(User).filter(User.id.in_(instructor_ids), User.role == "instructor")}
    missing = set(instructor_ids) - found
    if missing:
        raise HTTPException(400, f"Unknown instructor id(s): {sorted(missing)}")


def _set_subject_instructors(db: Session, subject: Subject, instructor_ids: list[int]) -> None:
    """Make these (and only these) instructors teach the subject. The caller commits."""
    db.query(InstructorAssignment).filter(InstructorAssignment.subject_id == subject.id).delete()
    for iid in dict.fromkeys(instructor_ids):
        db.add(InstructorAssignment(instructor_id=iid, subject_id=subject.id))


def _admin_subject_out(subject: Subject, instructor_ids: list[int]) -> SubjectOut:
    out = SubjectOut.model_validate(subject)
    out.instructor_ids = sorted(instructor_ids)
    return out


def _subject_instructors(db: Session, subject_id: int) -> list[int]:
    return [row.instructor_id for row in db.query(InstructorAssignment).filter_by(subject_id=subject_id)]


@router.post("/admin/subjects", response_model=SubjectOut)
def create_subject(payload: SubjectCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    batch = _student_batch(payload.batch) or ""
    _check_subject_code_free(db, payload.code, batch)
    _require_instructors_exist(db, payload.instructor_ids)
    subject = Subject(name=payload.name, code=payload.code, batch=batch)
    db.add(subject)
    db.flush()  # the subject's id, for the instructors
    _set_subject_instructors(db, subject, payload.instructor_ids)
    db.commit()
    db.refresh(subject)
    return _admin_subject_out(subject, _subject_instructors(db, subject.id))


@router.get("/admin/subjects", response_model=list[SubjectOut])
def list_subjects(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    teachers: dict[int, list[int]] = {}
    for row in db.query(InstructorAssignment).all():
        teachers.setdefault(row.subject_id, []).append(row.instructor_id)
    return [_admin_subject_out(s, teachers.get(s.id, [])) for s in db.query(Subject).order_by(Subject.name).all()]


@router.put("/admin/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int, payload: SubjectUpdate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """Rename a subject or change its code, batch or instructors. Everything else refers to it by id, so nothing else
    moves."""
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Subject not found")
    if payload.name is not None:
        name = " ".join(payload.name.split())
        if not name:
            raise HTTPException(400, "Subject name can't be empty")
        subject.name = name
    if payload.code is not None:
        code = payload.code.strip()
        if not code:
            raise HTTPException(400, "Subject code can't be empty")
        subject.code = code
    if payload.batch is not None:
        subject.batch = _student_batch(payload.batch) or ""
    if payload.code is not None or payload.batch is not None:
        _check_subject_code_free(db, subject.code, subject.batch, subject.id)
    if payload.instructor_ids is not None:
        _require_instructors_exist(db, payload.instructor_ids)
        _set_subject_instructors(db, subject, payload.instructor_ids)
    db.commit()
    db.refresh(subject)
    return _admin_subject_out(subject, _subject_instructors(db, subject.id))


@router.post("/admin/instructors", response_model=UserOut)
def create_instructor(payload: InstructorCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, f"An account with email '{payload.email}' already exists")
    _require_subjects_exist(db, payload.subject_ids)
    password_hash, salt = hash_password(payload.password)
    instructor = User(
        email=payload.email, full_name=payload.full_name, role="instructor",
        password_hash=password_hash, password_salt=salt,
        must_change_password=True,  # the admin chose it: the instructor sets their own at first login
    )
    db.add(instructor)
    db.commit()
    db.refresh(instructor)
    _set_instructor_subjects(db, instructor, payload.subject_ids)
    return _user_out(instructor, db)


@router.get("/admin/instructors", response_model=list[UserOut])
def list_instructors(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    instructors = db.query(User).filter(User.role == "instructor").order_by(User.full_name).all()
    return [_user_out(i, db) for i in instructors]


def _admin_managed_user(db: Session, user_id: int, role: str) -> User:
    user = db.get(User, user_id)
    if not user or user.role != role:
        raise HTTPException(404, f"{role.capitalize()} not found")
    return user


def _student_batch(value: Optional[str]) -> Optional[str]:
    """A batch as stored (e.g. "01"): extra spaces removed, None when blank. It is the middle part of the
    student's register number, so it can't hold the "/" that separates the parts."""
    batch = " ".join((value or "").split()) or None
    if batch and "/" in batch:
        raise HTTPException(400, "A batch can't contain '/'")
    return batch


def _student_register_number(db: Session, value: Optional[str], batch: Optional[str],
                             own_id: Optional[int] = None) -> Optional[str]:
    """A register number as stored, None when blank. It is <REGISTER_PREFIX>/<the student's batch>/<own number>,
    e.g. TST/01/001, so it needs the batch. Or the HTTP error saying what is wrong with it, or that another
    student has the same own number (in any batch). ``own_id`` is the student being edited, who may keep their
    own."""
    number = (value or "").strip()
    if not number:
        return None
    if not batch:
        raise HTTPException(400, f"Enter the student's batch first: a register number is "
                                 f"{REGISTER_PREFIX}/<batch>/<number>")
    prefix = f"{REGISTER_PREFIX}/{batch}/"
    last = number[len(prefix):]
    if not number.startswith(prefix) or not last or "/" in last or any(c.isspace() for c in last):
        raise HTTPException(400, f"The register number must look like {prefix}001: {REGISTER_PREFIX}, the batch, "
                                 "then the student's own number")
    # The student's own number (the last part) is unique across every batch, like an email: TST/01/0001 and
    # TST/02/0001 can't both exist. Case doesn't matter.
    others = db.query(User).filter(User.role == "student", User.register_number.isnot(None))
    if own_id is not None:
        others = others.filter(User.id != own_id)
    taken = next((o for o in others if o.register_number.rsplit("/", 1)[-1].lower() == last.lower()), None)
    if taken:
        raise HTTPException(400, f"Student number '{last}' already belongs to another student "
                                 f"({taken.register_number})")
    return number


def _update_user(db: Session, user: User, payload: UserUpdate) -> UserOut:
    if payload.full_name is not None:
        name = payload.full_name.strip()
        if not name:
            raise HTTPException(400, "Full name can't be empty")
        user.full_name = name
    if payload.email is not None:
        email = payload.email.strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(400, f"'{email}' is not a valid email address")
        clash = db.query(User).filter(func.lower(User.email) == email.lower(), User.id != user.id).first()
        if clash:
            raise HTTPException(400, f"An account with email '{email}' already exists")
        user.email = email
    if user.role == "student" and (payload.batch is not None or payload.register_number is not None):
        # An instructor has neither. The register number holds the batch, so the two are checked together: the
        # one left out of the request is the stored one.
        batch = _student_batch(payload.batch) if payload.batch is not None else user.batch
        number = payload.register_number if payload.register_number is not None else user.register_number
        user.register_number = _student_register_number(db, number, batch, user.id)
        user.batch = batch
    password_changed = False
    if payload.password:  # blank or missing: keep the current password
        if len(payload.password) < 4:
            raise HTTPException(400, "Password must be at least 4 characters")
        user.password_hash, user.password_salt = hash_password(payload.password)
        password_changed = True
        if user.role in ("student", "instructor"):
            user.must_change_password = True  # a password the admin reset: they choose their own at next login
    if payload.subject_ids is not None:
        _require_subjects_exist(db, payload.subject_ids)
    if password_changed:
        # Log them out everywhere: the old password must not keep working
        # through a session that was opened with it.
        db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(synchronize_session=False)
    db.add(user)
    db.commit()
    if payload.subject_ids is not None:
        if user.role == "instructor":
            _set_instructor_subjects(db, user, payload.subject_ids)
        else:
            _set_student_subjects(db, user, payload.subject_ids)
    db.refresh(user)
    return _user_out(user, db)


def _delete_user(db: Session, user: User) -> dict:
    """Delete an instructor or student and everything that belongs only to
    them. A student's submissions go too (grades, automated evaluations,
    similarity flags and the uploaded files). Records an instructor made
    for others stay: grades keep the grader's name, assignments and rubrics
    just lose their creator."""
    upload_parts: list[tuple[Optional[str], str]] = []
    submissions = db.query(Submission).filter(Submission.student_id == user.id).all()
    for submission in submissions:
        upload_parts += [(submission.code_path, "code"), (submission.report_path, "report"),
                         (submission.video_path, "video")]
        _discard_derived_results(db, submission.id)
        db.query(Grade).filter(Grade.submission_id == submission.id).delete(synchronize_session=False)
        db.delete(submission)
    db.query(Grade).filter(Grade.graded_by_id == user.id).update({Grade.graded_by_id: None},
                                                                 synchronize_session=False)
    db.query(Assignment).filter(Assignment.created_by_id == user.id).update({Assignment.created_by_id: None},
                                                                            synchronize_session=False)
    db.query(Rubric).filter(Rubric.created_by_id == user.id).update({Rubric.created_by_id: None},
                                                                    synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(synchronize_session=False)
    db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == user.id).delete(
        synchronize_session=False)
    db.query(Enrollment).filter(Enrollment.student_id == user.id).delete(synchronize_session=False)
    db.query(TaskUnlock).filter(TaskUnlock.student_id == user.id).delete(synchronize_session=False)
    db.query(TaskStart).filter(TaskStart.student_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    for rel_path, kind in upload_parts:  # files only after the database change succeeded
        _remove_upload_part(rel_path, kind)
    return {"status": "deleted", "submissions_deleted": len(submissions)}


@router.put("/admin/instructors/{instructor_id}", response_model=UserOut)
def update_instructor(
    instructor_id: int, payload: UserUpdate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _update_user(db, _admin_managed_user(db, instructor_id, "instructor"), payload)


@router.delete("/admin/instructors/{instructor_id}")
def delete_instructor(instructor_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _delete_user(db, _admin_managed_user(db, instructor_id, "instructor"))


@router.put("/admin/instructors/{instructor_id}/subjects", response_model=UserOut)
def set_instructor_subjects(
    instructor_id: int, payload: SubjectIdsIn, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    instructor = db.get(User, instructor_id)
    if not instructor or instructor.role != "instructor":
        raise HTTPException(404, "Instructor not found")
    _require_subjects_exist(db, payload.subject_ids)
    _set_instructor_subjects(db, instructor, payload.subject_ids)
    return _user_out(instructor, db)


@router.post("/admin/students", response_model=UserOut)
def create_student(payload: StudentCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, f"An account with email '{payload.email}' already exists")
    _require_subjects_exist(db, payload.subject_ids)
    batch = _student_batch(payload.batch)
    register_number = _student_register_number(db, payload.register_number, batch)
    password_hash, salt = hash_password(payload.password)
    student = User(
        email=payload.email, full_name=payload.full_name, role="student",
        password_hash=password_hash, password_salt=salt,
        batch=batch, register_number=register_number,
        must_change_password=True,  # the admin chose it: the student sets their own at first login
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    _set_student_subjects(db, student, payload.subject_ids)
    return _user_out(student, db)


def _checked_import_rows(file: UploadFile, db: Session) -> list[_student_import.ImportRow]:
    """The rows of an uploaded class list, each checked against the accounts there are now; or the HTTP error saying
    why the file can't be used."""
    content = file.file.read(_student_import.MAX_FILE_BYTES + 1)
    try:
        rows = _student_import.read_rows(file.filename or "", content)
    except _student_import.ImportFileError as exc:
        raise HTTPException(400, str(exc))
    emails = {email.lower() for (email,) in db.query(User.email)}
    numbers = {number.rsplit("/", 1)[-1].lower() for (number,) in
               db.query(User.register_number).filter(User.role == "student", User.register_number.isnot(None))}
    return _student_import.check_rows(rows, emails, numbers, REGISTER_PREFIX)


def _import_row_out(r: _student_import.ImportRow) -> ImportRowOut:
    return ImportRowOut(row=r.row, full_name=r.full_name, email=r.email, batch=r.batch,
                        register_number=r.register_number, problems=r.problems)


@router.get("/admin/students/import-template")
def student_import_template(_admin: User = Depends(require_admin)):
    return Response(content=_student_import.template_xlsx(), media_type=_exports.XLSX_MEDIA_TYPE, headers={
        "Content-Disposition": 'attachment; filename="student-import-template.xlsx"'})


@router.post("/admin/students/import/preview", response_model=ImportPreviewOut)
def preview_student_import(
    file: UploadFile = File(...), _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """What an import of this file would do. Nothing is created or kept."""
    rows = _checked_import_rows(file, db)
    with_problems = sum(1 for r in rows if r.problems)
    return ImportPreviewOut(rows=[_import_row_out(r) for r in rows], ready=len(rows) - with_problems,
                            with_problems=with_problems)


@router.post("/admin/students/import", response_model=ImportResultOut)
def run_student_import(
    response: Response,
    file: UploadFile = File(...),
    subject_ids: str = Form(""),  # the subjects every created student joins: ids separated by commas
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create the students of the rows with no problems, each with a random first password they must change at first
    login; the other rows are left out and reported. All or nothing: if the database refuses one, none are created.
    Every row is checked again here, not trusted from the preview. The answer is the only place the passwords exist."""
    try:
        ids = sorted({int(part) for part in subject_ids.split(",") if part.strip()})
    except ValueError:
        raise HTTPException(400, "subject_ids must be numbers separated by commas")
    _require_subjects_exist(db, ids)
    rows = _checked_import_rows(file, db)
    ready = [r for r in rows if not r.problems]

    listed = []
    for r in ready:  # the slow part (about 80 ms a student), before anything is written
        password = _student_import.make_password()
        password_hash, salt = hash_password(password)
        student = User(
            email=r.email, full_name=r.full_name, role="student", password_hash=password_hash, password_salt=salt,
            batch=r.batch or None, register_number=r.register_number or None,
            must_change_password=True,  # they choose their own at first login
        )
        db.add(student)
        listed.append((student, (r.full_name, r.email, r.batch, r.register_number, password)))
    try:
        db.flush()  # gives the students their ids, for the enrolments
        for student, _line in listed:
            for subject_id in ids:
                db.add(Enrollment(student_id=student.id, subject_id=subject_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account was added while this import ran, so nothing was created. Check the file "
                                 "again and retry.")
    # Who imported what and when. Never the passwords.
    _import_log.warning("Student import by %s: %d created, %d skipped, %d subject(s), file %r", admin.email,
                        len(ready), len(rows) - len(ready), len(ids), file.filename)
    response.headers["Cache-Control"] = "no-store"  # the answer holds passwords
    return ImportResultOut(
        created=[_import_row_out(r) for r in ready],
        skipped=[_import_row_out(r) for r in rows if r.problems],
        passwords_file=_student_import.passwords_xlsx_base64([line for _student, line in listed]) if listed else "",
    )


@router.get("/admin/students", response_model=list[UserOut])
def list_students(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    students = db.query(User).filter(User.role == "student").order_by(User.full_name).all()
    counts = dict(
        db.query(Submission.student_id, func.count(Submission.id)).group_by(Submission.student_id).all()
    )
    return [_user_out(s, db).model_copy(update={"submission_count": counts.get(s.id, 0)}) for s in students]


@router.put("/admin/students/{student_id}", response_model=UserOut)
def update_student(
    student_id: int, payload: UserUpdate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _update_user(db, _admin_managed_user(db, student_id, "student"), payload)


@router.delete("/admin/students/{student_id}")
def delete_student(student_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _delete_user(db, _admin_managed_user(db, student_id, "student"))


@router.put("/admin/students/{student_id}/subjects", response_model=UserOut)
def set_student_subjects(
    student_id: int, payload: SubjectIdsIn, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "Student not found")
    _require_subjects_exist(db, payload.subject_ids)
    _set_student_subjects(db, student, payload.subject_ids)
    return _user_out(student, db)
