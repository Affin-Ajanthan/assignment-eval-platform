"""
The single FastAPI application: accounts + subject-wise access control
(admin/instructor/student, see app/auth.py and app/models.py), the
submission portal + rubric engine + manual grading, the code-similarity
checker (see ``app/similarity/``), and the multi-modal evaluator --
report/code analysis, rubric grading, video analysis, cross-modal
consistency (see ``app/evaluator/``). One process, one database, one
set of dependencies.

Access control, in one paragraph: an admin creates every account --
there is no self-registration. An admin also creates subjects and
assigns instructors to them / enrolls students in them. An instructor
only ever sees and manages rubrics, submissions and grading for the
subjects they've been assigned. A student only ever sees and submits
to the subjects they're enrolled in, and only ever sees their own
submissions and grades.

Run it from the repo root:
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

On first run this creates a default admin account (printed to the
console -- see app/auth.py::bootstrap_admin) so there's a way to log
in before any other account exists.

Then open frontend/login.html in a browser (it calls this API at
http://localhost:8000) and sign in.
"""

from __future__ import annotations

import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .auth import (
    bootstrap_admin,
    create_session,
    get_current_user,
    hash_password,
    instructor_subject_ids,
    invalidate_session,
    require_admin,
    require_instructor,
    require_student,
    student_subject_ids,
    verify_password,
)
from .db import BASE_DIR, UPLOAD_DIR, Base, engine, get_db
from .evaluator.pipeline import evaluate_submission as _run_pipeline
from .evaluator.rubric_grading import Criterion as _EvalCriterion
from .models import (
    AutoEvaluation,
    Enrollment,
    Grade,
    InstructorAssignment,
    Rubric,
    SimilarityFlag,
    Subject,
    Submission,
    User,
)
from .similarity.ai_heuristics import score_source as _score_ai_code
from .similarity.core import Fingerprint, compare_all, fingerprint_source

_CODE_EXTENSIONS = {".py", ".java", ".js", ".ts", ".c", ".cpp", ".go", ".rb"}

Base.metadata.create_all(bind=engine)


# --------------------------------------------------------------------------
# Pydantic schemas
# --------------------------------------------------------------------------

class LoginIn(BaseModel):
    email: str
    password: str


class SubjectCreate(BaseModel):
    name: str
    code: str


class SubjectOut(BaseModel):
    id: int
    name: str
    code: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    subjects: list[SubjectOut] = []

    model_config = ConfigDict(from_attributes=True)


class LoginOut(BaseModel):
    token: str
    user: UserOut


class SubjectIdsIn(BaseModel):
    subject_ids: list[int] = []


class InstructorCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=4)
    subject_ids: list[int] = []


class StudentCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=4)
    subject_ids: list[int] = []


class Criterion(BaseModel):
    name: str
    description: str = ""
    max_points: float = Field(gt=0)


class RubricCreate(BaseModel):
    name: str
    subject_id: int
    criteria: list[Criterion]


class RubricOut(BaseModel):
    id: int
    name: str
    subject_id: int
    subject_name: str
    criteria: list[dict]
    max_total: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionOut(BaseModel):
    id: int
    student_id: int
    student_name: str
    student_email: str
    subject_id: int
    subject_name: str
    assignment_name: str
    code_path: Optional[str]
    report_path: Optional[str]
    video_path: Optional[str]
    submitted_at: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class GradeIn(BaseModel):
    rubric_id: int
    criterion_scores: dict[str, float]
    comments: Optional[str] = None


class GradeOut(BaseModel):
    id: int
    submission_id: int
    rubric_id: int
    criterion_scores: dict[str, float]
    total_score: float
    comments: Optional[str]
    graded_by: Optional[str]
    graded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AutoEvaluateIn(BaseModel):
    rubric_id: int


class AutoEvaluationOut(BaseModel):
    id: int
    submission_id: int
    rubric_id: int
    recommended_score: float
    recommended_max: float
    review_flags: list[str]
    criterion_breakdown: list[dict]
    grader: str
    similarity_flagged: bool
    code_ai_flagged: bool
    report_ai_signal: Optional[str]
    consistency_score: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SimilarityPairOut(BaseModel):
    submission_a_id: int
    submission_b_id: int
    jaccard: float
    containment: float
    flagged: bool


class SimilarityCheckOut(BaseModel):
    subject_id: int
    assignment_name: str
    compared: int
    pairs: list[SimilarityPairOut]


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db = next(get_db())
    try:
        bootstrap_admin(db)
    finally:
        db.close()
    yield


app = FastAPI(title="AI-Assisted Assignment Evaluation Platform", version="0.2.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # scaffold: tighten this before real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---- helpers ---------------------------------------------------------------

def _user_out(user: User, db: Session) -> UserOut:
    if user.role == "instructor":
        rows = db.query(InstructorAssignment).filter(InstructorAssignment.instructor_id == user.id).all()
        subjects = [row.subject for row in rows]
    elif user.role == "student":
        rows = db.query(Enrollment).filter(Enrollment.student_id == user.id).all()
        subjects = [row.subject for row in rows]
    else:
        subjects = []
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role, subjects=subjects)


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


def _can_view_submission(user: User, submission: Submission, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return submission.student_id == user.id
    if user.role == "instructor":
        return submission.subject_id in instructor_subject_ids(db, user)
    return False


# ---- Auth -------------------------------------------------------------------

@app.post("/auth/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash, user.password_salt):
        raise HTTPException(401, "Incorrect email or password")
    token = create_session(db, user)
    return LoginOut(token=token, user=_user_out(user, db))


@app.post("/auth/logout")
def logout(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    if authorization and authorization.lower().startswith("bearer "):
        invalidate_session(db, authorization.split(" ", 1)[1].strip())
    return {"status": "ok"}


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_out(user, db)


# ---- Admin: subjects ---------------------------------------------------------

@app.post("/admin/subjects", response_model=SubjectOut)
def create_subject(payload: SubjectCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(Subject).filter(Subject.code == payload.code).first():
        raise HTTPException(400, f"Subject code '{payload.code}' already exists")
    subject = Subject(name=payload.name, code=payload.code)
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@app.get("/admin/subjects", response_model=list[SubjectOut])
def list_subjects(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(Subject).order_by(Subject.name).all()


# ---- Admin: instructors -------------------------------------------------------

@app.post("/admin/instructors", response_model=UserOut)
def create_instructor(payload: InstructorCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, f"An account with email '{payload.email}' already exists")
    _require_subjects_exist(db, payload.subject_ids)
    password_hash, salt = hash_password(payload.password)
    instructor = User(
        email=payload.email, full_name=payload.full_name, role="instructor",
        password_hash=password_hash, password_salt=salt,
    )
    db.add(instructor)
    db.commit()
    db.refresh(instructor)
    _set_instructor_subjects(db, instructor, payload.subject_ids)
    return _user_out(instructor, db)


@app.get("/admin/instructors", response_model=list[UserOut])
def list_instructors(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    instructors = db.query(User).filter(User.role == "instructor").order_by(User.full_name).all()
    return [_user_out(i, db) for i in instructors]


@app.put("/admin/instructors/{instructor_id}/subjects", response_model=UserOut)
def set_instructor_subjects(
    instructor_id: int, payload: SubjectIdsIn, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    instructor = db.get(User, instructor_id)
    if not instructor or instructor.role != "instructor":
        raise HTTPException(404, "Instructor not found")
    _require_subjects_exist(db, payload.subject_ids)
    _set_instructor_subjects(db, instructor, payload.subject_ids)
    return _user_out(instructor, db)


# ---- Admin: students -----------------------------------------------------------

@app.post("/admin/students", response_model=UserOut)
def create_student(payload: StudentCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, f"An account with email '{payload.email}' already exists")
    _require_subjects_exist(db, payload.subject_ids)
    password_hash, salt = hash_password(payload.password)
    student = User(
        email=payload.email, full_name=payload.full_name, role="student",
        password_hash=password_hash, password_salt=salt,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    _set_student_subjects(db, student, payload.subject_ids)
    return _user_out(student, db)


@app.get("/admin/students", response_model=list[UserOut])
def list_students(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    students = db.query(User).filter(User.role == "student").order_by(User.full_name).all()
    return [_user_out(s, db) for s in students]


@app.put("/admin/students/{student_id}/subjects", response_model=UserOut)
def set_student_subjects(
    student_id: int, payload: SubjectIdsIn, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "Student not found")
    _require_subjects_exist(db, payload.subject_ids)
    _set_student_subjects(db, student, payload.subject_ids)
    return _user_out(student, db)


# ---- Rubrics --------------------------------------------------------------

@app.post("/rubrics", response_model=RubricOut)
def create_rubric(payload: RubricCreate, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    if payload.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    rubric = Rubric(
        name=payload.name,
        subject_id=payload.subject_id,
        criteria=[c.model_dump() for c in payload.criteria],
        created_by_id=instructor.id,
    )
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return rubric


@app.get("/rubrics", response_model=list[RubricOut])
def list_rubrics(
    subject_id: Optional[int] = None, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    allowed = instructor_subject_ids(db, instructor)
    query = db.query(Rubric).filter(Rubric.subject_id.in_(allowed))
    if subject_id is not None:
        if subject_id not in allowed:
            raise HTTPException(403, "You are not assigned to this subject")
        query = query.filter(Rubric.subject_id == subject_id)
    return query.order_by(Rubric.created_at.desc()).all()


@app.get("/rubrics/{rubric_id}", response_model=RubricOut)
def get_rubric(rubric_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    rubric = db.get(Rubric, rubric_id)
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    if rubric.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    return rubric


# ---- Submissions -----------------------------------------------------------

def _submission_dir(submission_uuid: str) -> Path:
    d = UPLOAD_DIR / submission_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_code_upload(file: UploadFile, submission_uuid: str) -> str:
    """Saves the code upload under uploads/<uuid>/code/. A .zip is
    extracted in place so the evaluator's static/similarity analysis
    (which walks a directory) works the same whether the student
    uploaded one file or a whole project."""
    code_dir = _submission_dir(submission_uuid) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    filename = file.filename or "upload"

    if filename.lower().endswith(".zip"):
        zip_path = code_dir / filename
        with zip_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(code_dir)
        zip_path.unlink()
    else:
        dest = code_dir / filename
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)

    return str(code_dir.relative_to(BASE_DIR))


def _save_file_upload(file: UploadFile, submission_uuid: str, kind: str) -> str:
    sub_dir = _submission_dir(submission_uuid) / kind
    sub_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_dir / (file.filename or "upload")
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return str(dest.relative_to(BASE_DIR))


@app.post("/submissions", response_model=SubmissionOut)
def create_submission(
    subject_id: int = Form(...),
    assignment_name: str = Form(...),
    code: Optional[UploadFile] = File(None),
    report: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    if subject_id not in student_subject_ids(db, student):
        raise HTTPException(403, "You are not enrolled in this subject")

    submission_uuid = uuid.uuid4().hex[:8]
    # code_path points at a DIRECTORY (uploads/<uuid>/code/); report_path
    # and video_path point at the uploaded FILE itself.
    code_path = _save_code_upload(code, submission_uuid) if code else None
    report_path = _save_file_upload(report, submission_uuid, "report") if report else None
    video_path = _save_file_upload(video, submission_uuid, "video") if video else None

    submission = Submission(
        student_id=student.id,
        subject_id=subject_id,
        assignment_name=assignment_name,
        code_path=code_path,
        report_path=report_path,
        video_path=video_path,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@app.get("/submissions", response_model=list[SubmissionOut])
def list_submissions(
    subject_id: Optional[int] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Submission)
    if user.role == "student":
        query = query.filter(Submission.student_id == user.id)
    elif user.role == "instructor":
        allowed = instructor_subject_ids(db, user)
        query = query.filter(Submission.subject_id.in_(allowed))
    # admin sees everything

    if subject_id is not None:
        query = query.filter(Submission.subject_id == subject_id)
    if status:
        query = query.filter(Submission.status == status)
    return query.order_by(Submission.submitted_at.desc()).all()


@app.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not _can_view_submission(user, submission, db):
        raise HTTPException(403, "You cannot view this submission")
    return submission


# ---- Manual grading ---------------------------------------------------------

@app.post("/submissions/{submission_id}/grade", response_model=GradeOut)
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

    total = sum(payload.criterion_scores.values())
    grade = Grade(
        submission_id=submission_id,
        rubric_id=payload.rubric_id,
        criterion_scores=payload.criterion_scores,
        total_score=total,
        comments=payload.comments,
        graded_by_id=instructor.id,
        graded_by=instructor.full_name,
    )
    submission.status = "graded"
    db.add(grade)
    db.add(submission)
    db.commit()
    db.refresh(grade)
    return grade


@app.get("/submissions/{submission_id}/grade", response_model=Optional[GradeOut])
def get_grade(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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


# ---- Similarity check across one subject's assignment submissions ---------

@app.post("/subjects/{subject_id}/assignments/{assignment_name}/check-similarity", response_model=SimilarityCheckOut)
def check_similarity(
    subject_id: int, assignment_name: str, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")

    submissions = (
        db.query(Submission)
        .filter(
            Submission.subject_id == subject_id,
            Submission.assignment_name == assignment_name,
            Submission.code_path.isnot(None),
        )
        .all()
    )
    if len(submissions) < 2:
        raise HTTPException(400, "Need at least 2 code submissions for this assignment to compare")

    fingerprints: dict[str, "Fingerprint"] = {}
    for submission in submissions:
        code_dir = BASE_DIR / submission.code_path
        merged = Fingerprint(submission_id=str(submission.id), filename="(all files)", token_count=0)
        if code_dir.is_dir():
            for path in sorted(code_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in _CODE_EXTENSIONS:
                    source = path.read_text(encoding="utf-8", errors="ignore")
                    fp = fingerprint_source(str(submission.id), path.name, source)
                    merged.hashes |= fp.hashes
                    merged.token_count += fp.token_count
        fingerprints[str(submission.id)] = merged

    pairs = compare_all(fingerprints)

    db.query(SimilarityFlag).filter(
        SimilarityFlag.subject_id == subject_id, SimilarityFlag.assignment_name == assignment_name
    ).delete()
    for pair in pairs:
        if pair.flagged:
            db.add(SimilarityFlag(
                subject_id=subject_id,
                assignment_name=assignment_name,
                submission_a_id=int(pair.submission_a),
                submission_b_id=int(pair.submission_b),
                jaccard=pair.jaccard,
                containment=pair.containment,
            ))
    db.commit()

    return SimilarityCheckOut(
        subject_id=subject_id,
        assignment_name=assignment_name,
        compared=len(submissions),
        pairs=[
            SimilarityPairOut(
                submission_a_id=int(p.submission_a), submission_b_id=int(p.submission_b),
                jaccard=p.jaccard, containment=p.containment, flagged=p.flagged,
            )
            for p in pairs
        ],
    )


# ---- Automated multi-modal evaluation --------------------------

@app.post("/submissions/{submission_id}/auto-evaluate", response_model=AutoEvaluationOut)
def auto_evaluate(
    submission_id: int, payload: AutoEvaluateIn, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
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

    code_dir = BASE_DIR / submission.code_path if submission.code_path else None
    report_path = BASE_DIR / submission.report_path if submission.report_path else None
    video_path = BASE_DIR / submission.video_path if submission.video_path else None
    code_dir = code_dir if code_dir and code_dir.is_dir() else None
    report_path = report_path if report_path and report_path.is_file() else None
    video_path = video_path if video_path and video_path.is_file() else None

    code_ai_flagged = False
    if code_dir:
        combined_source = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in sorted(code_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() in _CODE_EXTENSIONS
        )
        if combined_source.strip():
            code_ai_flagged = _score_ai_code(str(submission_id), combined_source).signal == "high"

    similarity_flagged = (
        db.query(SimilarityFlag)
        .filter(
            (SimilarityFlag.submission_a_id == submission_id)
            | (SimilarityFlag.submission_b_id == submission_id)
        )
        .first()
        is not None
    )

    criteria = [
        _EvalCriterion(name=c["name"], description=c.get("description", ""), max_points=c["max_points"])
        for c in rubric.criteria
    ]

    result = _run_pipeline(
        code_dir=code_dir,
        report_path=report_path,
        video_path=video_path,
        criteria=criteria,
        similarity_flagged=similarity_flagged,
        code_ai_flagged=code_ai_flagged,
    )

    auto_eval = AutoEvaluation(
        submission_id=submission_id,
        rubric_id=payload.rubric_id,
        recommended_score=result.recommended_score,
        recommended_max=result.recommended_max,
        review_flags=result.review_flags,
        criterion_breakdown=[
            {"name": c.name, "score": c.score, "max_points": c.max_points, "justification": c.justification}
            for c in result.grading.criteria
        ],
        grader=result.grading.grader,
        similarity_flagged=result.similarity_flagged,
        code_ai_flagged=result.code_ai_flagged,
        report_ai_signal=result.report_analysis.ai_text.signal if result.report_analysis else None,
        consistency_score=result.consistency.consistency_score,
    )
    db.add(auto_eval)
    db.commit()
    db.refresh(auto_eval)
    return auto_eval


@app.get("/submissions/{submission_id}/auto-evaluate", response_model=Optional[AutoEvaluationOut])
def get_auto_evaluation(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not _can_view_submission(user, submission, db):
        raise HTTPException(403, "You cannot view this submission")
    return (
        db.query(AutoEvaluation)
        .filter(AutoEvaluation.submission_id == submission_id)
        .order_by(AutoEvaluation.created_at.desc())
        .first()
    )
