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

import re
import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
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
from .db import BASE_DIR, UPLOAD_DIR, Base, add_missing_columns, engine, get_db
from .evaluator.document_extraction import (
    SUPPORTED_REPORT_EXTENSIONS,
    ReportValidationError,
    extract_and_store,
    EXTRACTED_MARKDOWN_NAME,
    EXTRACTION_META_NAME,
    load_extraction,
    report_max_bytes,
    validate_report_file,
)
from .evaluator.pipeline import evaluate_submission as _run_pipeline
from .evaluator.semantic_consistency import get_consistency_service
from .evaluator.ai_text_detection import get_ai_text_detector
from .evaluator.rubric_grading import Criterion as _EvalCriterion
from .models import (
    Assignment,
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
from .similarity.semantic import (
    MODEL_NAME as _SEMANTIC_MODEL,
    apply_semantic_signal,
    get_semantic_service,
    normalize_code,
    submissions_needing_semantic,
)

_CODE_EXTENSIONS = {".py", ".java", ".js", ".ts", ".c", ".cpp", ".go", ".rb"}

Base.metadata.create_all(bind=engine)
add_missing_columns("similarity_flags", {
    "semantic_similarity": "FLOAT", "flag_level": "VARCHAR", "flag_reason": "VARCHAR",
})
add_missing_columns("auto_evaluations", {"cross_modal_consistency": "JSON", "ai_signals": "JSON"})
# Submissions made before assignments existed keep assignment_id NULL (and
# their free-text assignment_name); nothing else about them changes.
add_missing_columns("submissions", {"assignment_id": "INTEGER REFERENCES assignments(id)"})


# --------------------------------------------------------------------------
# Pydantic schemas
# --------------------------------------------------------------------------

def _assume_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# Timestamps are stored as naive UTC (SQLite drops the offset). Responses
# mark them as UTC so browsers convert them to local time instead of
# mistaking them for local time.
UTCDateTime = Annotated[datetime, AfterValidator(_assume_utc)]


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
    created_at: UTCDateTime

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
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    max_points: float = Field(gt=0, le=10_000)


class CriterionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    max_points: Optional[float] = Field(default=None, gt=0, le=10_000)


class RubricCreate(BaseModel):
    name: str = Field(max_length=200)
    subject_id: int
    # A rubric is created with all of its criteria in one record; more can
    # be added later with POST /rubrics/{id}/criteria.
    criteria: list[Criterion] = Field(min_length=1)


class RubricUpdate(BaseModel):
    name: str = Field(max_length=200)


class RubricOut(BaseModel):
    id: int
    name: str
    subject_id: int
    subject_name: str
    criteria: list[dict]  # [{"id", "name", "description", "max_points"}, ...]
    max_total: float
    created_at: UTCDateTime
    # Grades recorded against this rubric. Once > 0 its structure (criterion
    # names, points, add/delete) is locked so recorded marks stay meaningful.
    graded_count: int = 0
    locked: bool = False
    assignment_names: list[str] = []


class AssignmentIn(BaseModel):
    subject_id: int
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=10_000)
    # ISO 8601. Times with an offset are converted to UTC; times without
    # one are taken as UTC (the frontend always sends UTC).
    available_from: datetime
    deadline: datetime
    rubric_id: Optional[int] = None


class AssignmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    available_from: Optional[datetime] = None
    deadline: Optional[datetime] = None
    rubric_id: Optional[int] = None  # send null explicitly to detach the rubric


class AssignmentOut(BaseModel):
    """Instructor view of an assignment."""

    id: int
    subject_id: int
    subject_name: str
    name: str
    description: str
    available_from: UTCDateTime
    deadline: UTCDateTime
    status: str  # upcoming | open | closed
    rubric_id: Optional[int]
    rubric_name: Optional[str]
    max_points: Optional[float]
    submission_count: int
    graded_count: int
    created_at: UTCDateTime
    updated_at: Optional[UTCDateTime]


class MySubmissionOut(BaseModel):
    """What a student sees about their own submission: status and the
    final total only -- no criterion-level marks, comments or evaluator
    output."""

    id: int
    submitted_at: UTCDateTime
    status: str  # submitted | graded
    has_code: bool
    has_report: bool
    has_video: bool
    final_mark: Optional[float]
    max_mark: Optional[float]
    can_edit: bool  # assignment open and not yet graded


class StudentAssignmentOut(BaseModel):
    id: int
    subject_id: int
    subject_name: str
    name: str
    description: str
    available_from: UTCDateTime
    deadline: UTCDateTime
    status: str  # open | closed (upcoming assignments aren't listed)
    my_submission: Optional[MySubmissionOut]


class SubmissionOut(BaseModel):
    id: int
    student_id: int
    student_name: str
    student_email: str
    subject_id: int
    subject_name: str
    assignment_name: str
    assignment_id: Optional[int] = None
    code_path: Optional[str]
    report_path: Optional[str]
    video_path: Optional[str]
    submitted_at: UTCDateTime
    status: str
    # Final total of the latest grade (and the rubric's maximum); the only
    # grading information this response carries.
    final_mark: Optional[float] = None
    max_mark: Optional[float] = None

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
    graded_at: UTCDateTime

    model_config = ConfigDict(from_attributes=True)


class AutoEvaluateIn(BaseModel):
    rubric_id: int


class ConsistencyComponentOut(BaseModel):
    available: bool
    words: int = 0
    chunks: int = 0
    note: Optional[str] = None  # why it's unavailable


class ReportExtractionOut(BaseModel):
    """How the report text was obtained (MarkItDown); shown to instructors."""

    status: str  # ok | empty | failed | unsupported
    backend: str
    chars: int = 0
    words: int = 0
    error: Optional[str] = None
    extracted_at: Optional[str] = None


class CrossModalConsistencyOut(BaseModel):
    """Semantic similarity (0-1) between the code documentation, report and
    video transcript. None = not evaluated (component missing / analysis
    unavailable) -- never a stand-in for 0. A review signal only."""

    code_report: Optional[float]
    code_transcript: Optional[float]
    report_transcript: Optional[float]
    overall: Optional[float]
    status: str  # consistent | review_recommended | limited_data | unavailable | disabled
    reason: str
    threshold: float
    model: str
    warning: Optional[str] = None
    components: dict[str, ConsistencyComponentOut] = {}
    report_extraction: Optional[ReportExtractionOut] = None


class AISignalOut(BaseModel):
    signal: str  # low | medium | high
    score: int  # 0-100, higher = more AI-like
    method: str  # e.g. "style-heuristic", "fast-detectgpt:Qwen2.5-0.5B"
    reasons: list[str]


class AISignalsOut(BaseModel):
    """AI-content estimates for the report and the code. Review signals
    only: they never change the suggested score. None = not assessed."""

    report: Optional[AISignalOut] = None
    code: Optional[AISignalOut] = None


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
    cross_modal_consistency: Optional[CrossModalConsistencyOut] = None
    ai_signals: Optional[AISignalsOut] = None
    created_at: UTCDateTime

    model_config = ConfigDict(from_attributes=True)


class SimilarityPairOut(BaseModel):
    submission_a_id: int
    submission_b_id: int
    student_a: str
    student_b: str
    shared_fingerprints: int
    jaccard: float
    containment: float
    # UniXcoder cosine similarity (0-1); None when semantic analysis
    # was unavailable or skipped for this pair (e.g. a tiny submission).
    semantic_similarity: Optional[float]
    token_flagged: bool
    # Final flag: token overlap OR a semantic "review" signal.
    flagged: bool
    flag_level: Optional[str]  # "high" | "review" | None
    flag_reason: Optional[str]


class SemanticSummaryOut(BaseModel):
    status: str  # "ok" | "unavailable" | "disabled"
    model: str
    warning: Optional[str] = None
    submissions_encoded: int = 0
    cache_hits: int = 0
    skipped_too_small: list[int] = []
    pairs_compared: int = 0
    cohort_median: Optional[float] = None
    review_threshold: Optional[float] = None


class SimilarityCheckOut(BaseModel):
    subject_id: int
    assignment_name: str
    compared: int
    pairs: list[SimilarityPairOut]
    semantic: SemanticSummaryOut


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
    # Load UniXcoder once, in the background, so startup isn't blocked
    # by the first-run model download.
    get_semantic_service().preload_in_background()
    # Same for the sentence-embedding model behind cross-modal consistency.
    get_consistency_service().preload_in_background()
    # And the small language model behind the report AI-text signal.
    get_ai_text_detector().preload_in_background()
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
#
# One rubric holds all of its criteria (Rubric.criteria). Criteria are
# added, edited and removed through /rubrics/{id}/criteria -- never by
# creating another rubric -- and a second rubric with the same name in a
# subject is rejected. Grades store scores keyed by criterion name, so once
# a rubric has been used for grading its structure is locked: only
# descriptions can still be edited.

def _norm_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _clean_name(name: Optional[str], what: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(400, f"{what} is required")
    return cleaned


def _instructor_rubric(db: Session, instructor: User, rubric_id: int) -> Rubric:
    rubric = db.get(Rubric, rubric_id)
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    if rubric.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    return rubric


def _rubric_graded_count(db: Session, rubric: Rubric) -> int:
    return db.query(Grade).filter(Grade.rubric_id == rubric.id).count()


def _require_unlocked(db: Session, rubric: Rubric, action: str) -> None:
    graded = _rubric_graded_count(db, rubric)
    if graded:
        raise HTTPException(
            409,
            f"Cannot {action}: this rubric has already been used to grade {graded} submission(s), and changing "
            "its criteria would change the meaning of those marks. Create a new rubric instead.",
        )


def _require_unique_rubric_name(db: Session, subject_id: int, name: str, exclude_id: Optional[int] = None) -> None:
    for other in db.query(Rubric).filter(Rubric.subject_id == subject_id).all():
        if other.id != exclude_id and _norm_name(other.name) == _norm_name(name):
            raise HTTPException(
                409, f"A rubric named '{other.name}' already exists in this subject -- add criteria to it instead."
            )


def _require_unique_criterion_names(criteria: list[dict]) -> None:
    seen: set[str] = set()
    for c in criteria:
        key = _norm_name(c["name"])
        if key in seen:
            raise HTTPException(400, f"Criterion names must be unique within a rubric ('{c['name']}' is repeated)")
        seen.add(key)


def _criterion_dict(cid: int, c: Criterion) -> dict:
    return {"id": cid, "name": _clean_name(c.name, "Criterion name"),
            "description": c.description.strip(), "max_points": c.max_points}


def _ensure_criterion_ids() -> None:
    """One-time upgrade for rubrics saved before criteria had ids."""
    from .db import SessionLocal

    db = SessionLocal()
    try:
        changed = False
        for rubric in db.query(Rubric).all():
            if any("id" not in c for c in rubric.criteria):
                rubric.criteria = [{**c, "id": i} for i, c in enumerate(rubric.criteria, start=1)]
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


_ensure_criterion_ids()


def _rubric_out(db: Session, rubric: Rubric) -> RubricOut:
    graded = _rubric_graded_count(db, rubric)
    assignments = db.query(Assignment).filter(Assignment.rubric_id == rubric.id).order_by(Assignment.name).all()
    return RubricOut(
        id=rubric.id, name=rubric.name, subject_id=rubric.subject_id, subject_name=rubric.subject_name,
        criteria=rubric.criteria, max_total=rubric.max_total, created_at=rubric.created_at,
        graded_count=graded, locked=graded > 0, assignment_names=[a.name for a in assignments],
    )


@app.post("/rubrics", response_model=RubricOut)
def create_rubric(payload: RubricCreate, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    if payload.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    name = _clean_name(payload.name, "Rubric name")
    _require_unique_rubric_name(db, payload.subject_id, name)
    criteria = [_criterion_dict(i, c) for i, c in enumerate(payload.criteria, start=1)]
    _require_unique_criterion_names(criteria)
    rubric = Rubric(name=name, subject_id=payload.subject_id, criteria=criteria, created_by_id=instructor.id)
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return _rubric_out(db, rubric)


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
    return [_rubric_out(db, r) for r in query.order_by(Rubric.created_at.desc()).all()]


@app.get("/rubrics/{rubric_id}", response_model=RubricOut)
def get_rubric(rubric_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    return _rubric_out(db, _instructor_rubric(db, instructor, rubric_id))


@app.put("/rubrics/{rubric_id}", response_model=RubricOut)
def rename_rubric(
    rubric_id: int, payload: RubricUpdate, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    rubric = _instructor_rubric(db, instructor, rubric_id)
    name = _clean_name(payload.name, "Rubric name")
    if name != rubric.name:
        _require_unlocked(db, rubric, "rename this rubric")
        _require_unique_rubric_name(db, rubric.subject_id, name, exclude_id=rubric.id)
        rubric.name = name
        db.commit()
    return _rubric_out(db, rubric)


@app.delete("/rubrics/{rubric_id}")
def delete_rubric(rubric_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Refused while grades use the rubric (academic records). Otherwise the
    rubric is removed, assignments using it are left without a rubric, and
    automated evaluations run against it (re-runnable) are discarded."""
    rubric = _instructor_rubric(db, instructor, rubric_id)
    graded = _rubric_graded_count(db, rubric)
    if graded:
        raise HTTPException(
            409, f"This rubric can't be deleted: {graded} submission(s) have been graded with it. "
                 "Those marks must keep their rubric."
        )
    detached = db.query(Assignment).filter(Assignment.rubric_id == rubric.id).update({Assignment.rubric_id: None})
    removed_evals = db.query(AutoEvaluation).filter(AutoEvaluation.rubric_id == rubric.id).delete()
    db.delete(rubric)
    db.commit()
    return {"status": "deleted", "assignments_detached": detached, "auto_evaluations_removed": removed_evals}


@app.post("/rubrics/{rubric_id}/criteria", response_model=RubricOut)
def add_criterion(
    rubric_id: int, payload: Criterion, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Adds one more criterion to an EXISTING rubric (no new rubric record)."""
    rubric = _instructor_rubric(db, instructor, rubric_id)
    _require_unlocked(db, rubric, "add a criterion")
    next_id = max((c["id"] for c in rubric.criteria), default=0) + 1
    criteria = [*rubric.criteria, _criterion_dict(next_id, payload)]
    _require_unique_criterion_names(criteria)
    rubric.criteria = criteria  # reassign so SQLAlchemy sees the JSON change
    db.commit()
    return _rubric_out(db, rubric)


@app.put("/rubrics/{rubric_id}/criteria/{criterion_id}", response_model=RubricOut)
def update_criterion(
    rubric_id: int, criterion_id: int, payload: CriterionUpdate,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    rubric = _instructor_rubric(db, instructor, rubric_id)
    current = next((c for c in rubric.criteria if c["id"] == criterion_id), None)
    if current is None:
        raise HTTPException(404, "Criterion not found in this rubric")
    updated = dict(current)
    if payload.name is not None:
        updated["name"] = _clean_name(payload.name, "Criterion name")
    if payload.description is not None:
        updated["description"] = payload.description.strip()
    if payload.max_points is not None:
        updated["max_points"] = payload.max_points
    if updated["name"] != current["name"] or updated["max_points"] != current["max_points"]:
        _require_unlocked(db, rubric, "change a criterion's name or points")
    criteria = [updated if c["id"] == criterion_id else c for c in rubric.criteria]
    _require_unique_criterion_names(criteria)
    rubric.criteria = criteria
    db.commit()
    return _rubric_out(db, rubric)


@app.delete("/rubrics/{rubric_id}/criteria/{criterion_id}", response_model=RubricOut)
def delete_criterion(
    rubric_id: int, criterion_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    rubric = _instructor_rubric(db, instructor, rubric_id)
    if not any(c["id"] == criterion_id for c in rubric.criteria):
        raise HTTPException(404, "Criterion not found in this rubric")
    _require_unlocked(db, rubric, "delete a criterion")
    if len(rubric.criteria) == 1:
        raise HTTPException(400, "A rubric needs at least one criterion -- delete the rubric instead.")
    rubric.criteria = [c for c in rubric.criteria if c["id"] != criterion_id]
    db.commit()
    return _rubric_out(db, rubric)


# ---- Assignments -------------------------------------------------------------
#
# Times are stored as naive UTC, like every other timestamp in this app, and
# returned with an explicit UTC offset so browsers show them in local time.
# The submission window is enforced here, in the API:
#   now < available_from  -> not available (students don't even see it)
#   available_from <= now <= deadline -> submissions allowed
#   now > deadline -> submissions, edits and deletions rejected

def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _validate_window(available_from: datetime, deadline: datetime) -> None:
    if deadline <= available_from:
        raise HTTPException(400, "The submission deadline must be later than the available-from date and time.")


def _instructor_assignment(db: Session, instructor: User, assignment_id: int) -> Assignment:
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    return assignment


def _check_assignment_rubric(db: Session, subject_id: int, rubric_id: Optional[int]) -> None:
    if rubric_id is None:
        return
    rubric = db.get(Rubric, rubric_id)
    if not rubric or rubric.subject_id != subject_id:
        raise HTTPException(400, "That rubric doesn't belong to this assignment's subject")


def _require_unique_assignment_name(db: Session, subject_id: int, name: str, exclude_id: Optional[int] = None) -> None:
    for other in db.query(Assignment).filter(Assignment.subject_id == subject_id).all():
        if other.id != exclude_id and _norm_name(other.name) == _norm_name(name):
            raise HTTPException(409, f"An assignment named '{other.name}' already exists in this subject")


def _assignment_out(db: Session, a: Assignment) -> AssignmentOut:
    subs = db.query(Submission).filter(Submission.assignment_id == a.id).all()
    return AssignmentOut(
        id=a.id, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
        name=a.name, description=a.description or "",
        available_from=_as_utc(a.available_from), deadline=_as_utc(a.deadline),
        status=a.status_at(_utcnow_naive()),
        rubric_id=a.rubric_id, rubric_name=a.rubric.name if a.rubric else None,
        max_points=a.rubric.max_total if a.rubric else None,
        submission_count=len(subs), graded_count=sum(1 for s in subs if s.status == "graded"),
        created_at=_as_utc(a.created_at), updated_at=_as_utc(a.updated_at),
    )


def _my_submission_out(submission: Submission, assignment_open: bool) -> MySubmissionOut:
    return MySubmissionOut(
        id=submission.id, submitted_at=_as_utc(submission.submitted_at), status=submission.status,
        has_code=bool(submission.code_path), has_report=bool(submission.report_path),
        has_video=bool(submission.video_path),
        final_mark=submission.final_mark, max_mark=submission.max_mark,
        can_edit=assignment_open and submission.status != "graded",
    )


def _student_assignment_out(db: Session, student: User, a: Assignment, now: datetime) -> StudentAssignmentOut:
    status = a.status_at(now)
    mine = (
        db.query(Submission)
        .filter(Submission.assignment_id == a.id, Submission.student_id == student.id)
        .order_by(Submission.id.desc())
        .first()
    )
    return StudentAssignmentOut(
        id=a.id, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
        name=a.name, description=a.description or "",
        available_from=_as_utc(a.available_from), deadline=_as_utc(a.deadline), status=status,
        my_submission=_my_submission_out(mine, status == "open") if mine else None,
    )


@app.post("/assignments", response_model=AssignmentOut)
def create_assignment(payload: AssignmentIn, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    if payload.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    name = _clean_name(payload.name, "Assignment name")
    available_from, deadline = _to_naive_utc(payload.available_from), _to_naive_utc(payload.deadline)
    _validate_window(available_from, deadline)
    _require_unique_assignment_name(db, payload.subject_id, name)
    _check_assignment_rubric(db, payload.subject_id, payload.rubric_id)
    assignment = Assignment(
        subject_id=payload.subject_id, name=name, description=payload.description.strip(),
        available_from=available_from, deadline=deadline, rubric_id=payload.rubric_id,
        created_by_id=instructor.id,
    )
    db.add(assignment)
    db.flush()
    # Submissions made before assignments existed were free-text names; ones
    # matching this assignment in this subject are linked to it.
    for legacy in db.query(Submission).filter(Submission.subject_id == payload.subject_id,
                                              Submission.assignment_id.is_(None)).all():
        if _norm_name(legacy.assignment_name) == _norm_name(name):
            legacy.assignment_id = assignment.id
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@app.get("/assignments")
def list_assignments(
    subject_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Instructors: every assignment in their subjects (AssignmentOut).
    Students: assignments in their enrolled subjects that have opened --
    open and closed, never upcoming -- with only their own submission and
    final mark (StudentAssignmentOut)."""
    if user.role == "student":
        allowed = student_subject_ids(db, user)
    elif user.role == "instructor":
        allowed = instructor_subject_ids(db, user)
    else:
        allowed = {s.id for s in db.query(Subject).all()}
    if subject_id is not None:
        if subject_id not in allowed:
            raise HTTPException(403, "You don't have access to this subject")
        allowed = {subject_id}
    query = db.query(Assignment).filter(Assignment.subject_id.in_(allowed)).order_by(Assignment.deadline)
    now = _utcnow_naive()
    if user.role == "student":
        visible = query.filter(Assignment.available_from <= now).all()
        return [_student_assignment_out(db, user, a, now) for a in visible]
    return [_assignment_out(db, a) for a in query.all()]


@app.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assignment = db.get(Assignment, assignment_id)
    now = _utcnow_naive()
    if user.role == "student":
        if (not assignment or assignment.subject_id not in student_subject_ids(db, user)
                or assignment.status_at(now) == "upcoming"):
            raise HTTPException(404, "Assignment not found")
        return _student_assignment_out(db, user, assignment, now)
    if user.role == "instructor":
        return _assignment_out(db, _instructor_assignment(db, user, assignment_id))
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return _assignment_out(db, assignment)


@app.put("/assignments/{assignment_id}", response_model=AssignmentOut)
def update_assignment(
    assignment_id: int, payload: AssignmentUpdate,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    assignment = _instructor_assignment(db, instructor, assignment_id)
    if payload.name is not None:
        name = _clean_name(payload.name, "Assignment name")
        _require_unique_assignment_name(db, assignment.subject_id, name, exclude_id=assignment.id)
    else:
        name = assignment.name
    available_from = _to_naive_utc(payload.available_from) if payload.available_from else assignment.available_from
    deadline = _to_naive_utc(payload.deadline) if payload.deadline else assignment.deadline
    _validate_window(available_from, deadline)
    if "rubric_id" in payload.model_fields_set:
        _check_assignment_rubric(db, assignment.subject_id, payload.rubric_id)
        assignment.rubric_id = payload.rubric_id

    if name != assignment.name:
        # Keep linked submissions and stored similarity results under the new
        # name, so the similarity check still groups them together.
        db.query(Submission).filter(Submission.assignment_id == assignment.id).update(
            {Submission.assignment_name: name})
        db.query(SimilarityFlag).filter(
            SimilarityFlag.subject_id == assignment.subject_id, SimilarityFlag.assignment_name == assignment.name
        ).update({SimilarityFlag.assignment_name: name})
        assignment.name = name
    if payload.description is not None:
        assignment.description = payload.description.strip()
    assignment.available_from, assignment.deadline = available_from, deadline
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@app.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Removes the assignment (students stop seeing it). Its submissions and
    grades are academic records and are kept: they're detached and keep
    their assignment name."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    kept = db.query(Submission).filter(Submission.assignment_id == assignment.id).update(
        {Submission.assignment_id: None})
    db.delete(assignment)
    db.commit()
    return {"status": "deleted", "submissions_kept": kept}


# ---- Submissions -----------------------------------------------------------

# Uploads are untrusted input: every file is checked for type and size,
# saved under a sanitized name inside its own uploads/<uuid>/ folder, and
# never executed. A rejected upload removes everything already written.
_UPLOAD_CODE_EXTENSIONS = _CODE_EXTENSIONS | {".zip", ".h", ".hpp", ".cs", ".jsx", ".tsx", ".kt", ".swift", ".php", ".rs"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
_CODE_MAX_BYTES = 50 * 1024 * 1024
_ZIP_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_ZIP_MAX_ENTRIES = 5000
_VIDEO_MAX_BYTES = 1024 * 1024 * 1024
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


class _UploadRejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _submission_dir(submission_uuid: str) -> Path:
    d = UPLOAD_DIR / submission_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(name: Optional[str], fallback: str = "upload") -> str:
    """Last path component only (either slash style), restricted to a
    plain character set, never a dotfile -- so a crafted name like
    '../../app/main.py' or 'C:/Windows/x' can only ever land inside the
    submission's own folder."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = _UNSAFE_NAME_CHARS.sub("_", base).strip(" .")
    return base or fallback


def _write_limited(file: UploadFile, dest: Path, limit: int, what: str) -> None:
    written = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                raise _UploadRejected(413, f"The {what} is too large (limit {limit // (1024 * 1024)} MB).")
            out.write(chunk)


def _save_code_upload(file: UploadFile, submission_uuid: str) -> str:
    """Saves the code upload under uploads/<uuid>/code/. A .zip is
    extracted in place so the evaluator's static/similarity analysis
    (which walks a directory) works the same whether the student
    uploaded one file or a whole project."""
    filename = _safe_filename(file.filename)
    if Path(filename).suffix.lower() not in _UPLOAD_CODE_EXTENSIONS:
        raise _UploadRejected(400, "Code must be a .zip file or a single source-code file.")
    code_dir = _submission_dir(submission_uuid) / "code"
    code_dir.mkdir(parents=True, exist_ok=True)

    if filename.lower().endswith(".zip"):
        zip_path = _submission_dir(submission_uuid) / "code-upload.zip"
        _write_limited(file, zip_path, _CODE_MAX_BYTES, "code archive")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                infos = zf.infolist()
                if len(infos) > _ZIP_MAX_ENTRIES or sum(i.file_size for i in infos) > _ZIP_MAX_UNCOMPRESSED_BYTES:
                    raise _UploadRejected(413, "The code archive is too large once unpacked.")
                root = code_dir.resolve()
                for info in infos:
                    target = (code_dir / info.filename).resolve()
                    if info.is_dir() or not target.is_relative_to(root):
                        continue  # skip directories and any entry pointing outside code/
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile:
            raise _UploadRejected(400, "The code archive is not a valid .zip file.")
        finally:
            zip_path.unlink(missing_ok=True)
    else:
        _write_limited(file, code_dir / filename, _CODE_MAX_BYTES, "code file")

    return str(code_dir.relative_to(BASE_DIR))


def _save_file_upload(file: UploadFile, submission_uuid: str, kind: str, limit: int, what: str) -> Path:
    sub_dir = _submission_dir(submission_uuid) / kind
    sub_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_dir / _safe_filename(file.filename, fallback=kind)
    _write_limited(file, dest, limit, what)
    return dest


def _save_report_upload(file: UploadFile, submission_uuid: str) -> str:
    if Path(_safe_filename(file.filename)).suffix.lower() not in SUPPORTED_REPORT_EXTENSIONS:
        raise _UploadRejected(400, "Report must be a PDF or DOCX file.")
    dest = _save_file_upload(file, submission_uuid, "report", report_max_bytes(), "report")
    try:
        validate_report_file(dest, dest.name, file.content_type)
    except ReportValidationError as exc:
        raise _UploadRejected(400, str(exc))
    return str(dest.relative_to(BASE_DIR))


def _save_video_upload(file: UploadFile, submission_uuid: str) -> str:
    if Path(_safe_filename(file.filename)).suffix.lower() not in _VIDEO_EXTENSIONS:
        raise _UploadRejected(400, "Presentation video must be an MP4, MOV, AVI, MKV, WEBM or M4V file.")
    dest = _save_file_upload(file, submission_uuid, "video", _VIDEO_MAX_BYTES, "video")
    return str(dest.relative_to(BASE_DIR))


@app.post("/submissions", response_model=SubmissionOut)
def create_submission(
    background_tasks: BackgroundTasks,
    subject_id: int = Form(...),
    # Either identifies the assignment; assignment_name is matched against
    # the subject's assignments (case/spacing-insensitive).
    assignment_id: Optional[int] = Form(None),
    assignment_name: Optional[str] = Form(None),
    code: Optional[UploadFile] = File(None),
    report: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    if subject_id not in student_subject_ids(db, student):
        raise HTTPException(403, "You are not enrolled in this subject")
    assignment = _resolve_assignment_for_submission(db, subject_id, assignment_id, assignment_name)
    _require_open(assignment)
    code, report, video = (f if f is not None and f.filename else None for f in (code, report, video))
    if not (code or report or video):
        raise HTTPException(400, "Upload at least one file (code, report or presentation video).")
    existing = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id, Submission.student_id == student.id)
        .first()
    )
    if existing:
        raise HTTPException(409, "You have already submitted this assignment. Use Edit submission to change your files.")

    submission_uuid = uuid.uuid4().hex[:8]
    # code_path points at a DIRECTORY (uploads/<uuid>/code/); report_path
    # and video_path point at the uploaded FILE itself.
    try:
        code_path = _save_code_upload(code, submission_uuid) if code else None
        report_path = _save_report_upload(report, submission_uuid) if report else None
        video_path = _save_video_upload(video, submission_uuid) if video else None
    except _UploadRejected as exc:
        shutil.rmtree(UPLOAD_DIR / submission_uuid, ignore_errors=True)
        raise HTTPException(exc.status, exc.message)

    submission = Submission(
        student_id=student.id,
        subject_id=subject_id,
        assignment_name=assignment.name,
        assignment_id=assignment.id,
        code_path=code_path,
        report_path=report_path,
        video_path=video_path,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    if report_path:
        # Convert the report to text (MarkItDown) after the response is sent;
        # the student never waits for it or sees its outcome.
        background_tasks.add_task(extract_and_store, BASE_DIR / report_path)
    return submission


def _resolve_assignment_for_submission(
    db: Session, subject_id: int, assignment_id: Optional[int], assignment_name: Optional[str]
) -> Assignment:
    if assignment_id is not None:
        assignment = db.get(Assignment, assignment_id)
        if not assignment or assignment.subject_id != subject_id:
            raise HTTPException(404, "Assignment not found in this subject")
        return assignment
    if not (assignment_name or "").strip():
        raise HTTPException(400, "Choose the assignment you are submitting to.")
    for assignment in db.query(Assignment).filter(Assignment.subject_id == subject_id).all():
        if _norm_name(assignment.name) == _norm_name(assignment_name):
            return assignment
    raise HTTPException(404, f"There is no assignment called '{assignment_name.strip()}' in this subject.")


def _require_open(assignment: Assignment) -> None:
    """The deadline check every student write goes through."""
    status = assignment.status_at(_utcnow_naive())
    if status == "upcoming":
        raise HTTPException(403, f"'{assignment.name}' is not open for submissions yet.")
    if status == "closed":
        raise HTTPException(403, f"The submission deadline for '{assignment.name}' has passed.")


def _own_changeable_submission(db: Session, student: User, submission_id: int) -> Submission:
    submission = db.get(Submission, submission_id)
    if not submission or submission.student_id != student.id:
        raise HTTPException(404, "Submission not found")  # never confirm other students' submissions exist
    if submission.assignment is None:
        raise HTTPException(409, "This submission isn't linked to an open assignment, so it can't be changed.")
    if submission.status == "graded":
        raise HTTPException(409, "This submission has already been graded and can no longer be changed.")
    _require_open(submission.assignment)
    return submission


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


@app.put("/submissions/{submission_id}", response_model=SubmissionOut)
def update_submission(
    submission_id: int,
    background_tasks: BackgroundTasks,
    code: Optional[UploadFile] = File(None),
    report: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """Replace one or more files of the student's own submission while the
    assignment is open and before it's graded. Files not sent are kept."""
    submission = _own_changeable_submission(db, student, submission_id)
    code, report, video = (f if f is not None and f.filename else None for f in (code, report, video))
    if not (code or report or video):
        raise HTTPException(400, "Choose at least one file to replace.")

    batch = uuid.uuid4().hex[:8]
    try:
        new_code = _save_code_upload(code, batch) if code else None
        new_report = _save_report_upload(report, batch) if report else None
        new_video = _save_video_upload(video, batch) if video else None
    except _UploadRejected as exc:
        shutil.rmtree(UPLOAD_DIR / batch, ignore_errors=True)
        raise HTTPException(exc.status, exc.message)

    replaced = []
    if new_code:
        replaced.append((submission.code_path, "code"))
        submission.code_path = new_code
    if new_report:
        replaced.append((submission.report_path, "report"))
        submission.report_path = new_report
    if new_video:
        replaced.append((submission.video_path, "video"))
        submission.video_path = new_video
    submission.submitted_at = datetime.now(timezone.utc)
    _discard_derived_results(db, submission.id)
    db.commit()
    db.refresh(submission)
    for rel_path, kind in replaced:
        _remove_upload_part(rel_path, kind)
    if new_report:
        background_tasks.add_task(extract_and_store, BASE_DIR / new_report)
    return submission


@app.delete("/submissions/{submission_id}")
def delete_submission(submission_id: int, student: User = Depends(require_student), db: Session = Depends(get_db)):
    """Withdraw the student's own submission while the assignment is open
    and before it's graded (a graded submission is an academic record)."""
    submission = _own_changeable_submission(db, student, submission_id)
    parts = [(submission.code_path, "code"), (submission.report_path, "report"), (submission.video_path, "video")]
    _discard_derived_results(db, submission.id)
    db.delete(submission)
    db.commit()
    for rel_path, kind in parts:
        _remove_upload_part(rel_path, kind)
    return {"status": "deleted"}


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


# ---- Submitted files (owning student, the subject's instructors, admins) ----
#
# Uploaded files are untrusted: they're only ever sent as downloads
# (Content-Disposition: attachment, nosniff), and anything that a browser
# could execute or render (HTML, SVG, JS, ...) is sent as text/plain.

_SUBMISSION_KINDS = ("code", "report", "video")
_SAFE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".zip": "application/zip",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
}


class SubmissionFileOut(BaseModel):
    kind: str  # code | report | video
    path: str  # relative to that part of the submission, "/"-separated
    name: str
    size: int


def _viewable_submission(db: Session, user: User, submission_id: int) -> Submission:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if not _can_view_submission(user, submission, db):
        raise HTTPException(403, "You cannot view this submission")
    return submission


def _kind_root(submission: Submission, kind: str) -> Optional[Path]:
    """The folder holding one part of a submission (code dir, or the folder
    containing the single report/video file), or None if it wasn't submitted."""
    rel = {"code": submission.code_path, "report": submission.report_path, "video": submission.video_path}.get(kind)
    if not rel:
        return None
    path = BASE_DIR / rel
    return path if kind == "code" else path.parent


def _kind_files(submission: Submission, kind: str) -> list[Path]:
    root = _kind_root(submission, kind)
    if root is None or not root.is_dir():
        return []
    if kind == "code":
        return sorted(p for p in root.rglob("*") if p.is_file())
    stored = BASE_DIR / (submission.report_path if kind == "report" else submission.video_path)
    return [stored] if stored.is_file() else []


@app.get("/submissions/{submission_id}/files", response_model=list[SubmissionFileOut])
def list_submission_files(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    submission = _viewable_submission(db, user, submission_id)
    out = []
    for kind in _SUBMISSION_KINDS:
        root = _kind_root(submission, kind)
        for path in _kind_files(submission, kind):
            out.append(SubmissionFileOut(kind=kind, path=path.relative_to(root).as_posix(), name=path.name,
                                         size=path.stat().st_size))
    return out


@app.get("/submissions/{submission_id}/files/{kind}/{file_path:path}")
def download_submission_file(
    submission_id: int, kind: str, file_path: str,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    submission = _viewable_submission(db, user, submission_id)
    if kind not in _SUBMISSION_KINDS:
        raise HTTPException(404, "File not found")
    root = _kind_root(submission, kind)
    if root is None:
        raise HTTPException(404, "File not found")
    target = (root / file_path).resolve()
    # Only files that belong to this part of this submission; never a path outside it.
    if target not in {p.resolve() for p in _kind_files(submission, kind)}:
        raise HTTPException(404, "File not found")
    media_type = _SAFE_MEDIA_TYPES.get(target.suffix.lower(), "text/plain; charset=utf-8")
    return FileResponse(target, media_type=media_type, filename=target.name,
                        headers={"X-Content-Type-Options": "nosniff"})


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

    # 1-4: read + normalize each submission once, fingerprint it, and
    # compare every unordered pair (A-B only, never B-A) on tokens.
    fingerprints: dict[str, "Fingerprint"] = {}
    semantic_sources: dict[str, str] = {}
    for submission in submissions:
        code_dir = BASE_DIR / submission.code_path
        merged = Fingerprint(submission_id=str(submission.id), filename="(all files)", token_count=0)
        normalized_files: list[str] = []
        if code_dir.is_dir():
            for path in sorted(code_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in _CODE_EXTENSIONS:
                    source = path.read_text(encoding="utf-8", errors="ignore")
                    fp = fingerprint_source(str(submission.id), path.name, source)
                    merged.hashes |= fp.hashes
                    merged.token_count += fp.token_count
                    normalized_files.append(normalize_code(source, path.name))
        fingerprints[str(submission.id)] = merged
        semantic_sources[str(submission.id)] = "\n".join(f for f in normalized_files if f)

    pairs = compare_all(fingerprints)

    # 5-7: UniXcoder as an extra signal. The expensive step -- model
    # inference -- runs once per submission (cached by content), and
    # only for submissions in at least one pair the token check didn't
    # already flag; pair scores are then cosine similarities between
    # the stored vectors. A failure here leaves the token results intact.
    needed = submissions_needing_semantic(pairs)
    batch = get_semantic_service().embed_submissions(
        {sid: text for sid, text in semantic_sources.items() if sid in needed}
    )
    stats = apply_semantic_signal(pairs, batch.embeddings) if batch.status == "ok" else {}

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
                semantic_similarity=pair.semantic_similarity,
                flag_level=pair.flag_level or "high",
                flag_reason=pair.flag_reason or "High token/fingerprint overlap",
            ))
    db.commit()

    names = {str(s.id): s.student_name for s in submissions}
    return SimilarityCheckOut(
        subject_id=subject_id,
        assignment_name=assignment_name,
        compared=len(submissions),
        pairs=[
            SimilarityPairOut(
                submission_a_id=int(p.submission_a), submission_b_id=int(p.submission_b),
                student_a=names[p.submission_a], student_b=names[p.submission_b],
                shared_fingerprints=p.shared_fingerprints,
                jaccard=p.jaccard, containment=p.containment,
                semantic_similarity=p.semantic_similarity,
                token_flagged=p.token_flagged,
                flagged=p.flagged,
                flag_level=p.flag_level or ("high" if p.token_flagged else None),
                flag_reason=p.flag_reason or ("High token/fingerprint overlap" if p.token_flagged else None),
            )
            for p in pairs
        ],
        semantic=SemanticSummaryOut(
            status=batch.status,
            model=_SEMANTIC_MODEL,
            warning=batch.warning,
            submissions_encoded=batch.encoded,
            cache_hits=batch.cache_hits,
            skipped_too_small=sorted(int(s) for s in batch.skipped_too_small),
            pairs_compared=stats.get("semantic_pairs_compared", 0),
            cohort_median=stats.get("cohort_median"),
            review_threshold=stats.get("review_threshold"),
        ),
    )


# ---- Automated multi-modal evaluation --------------------------

def _ai_signal_dict(result, method: Optional[str] = None) -> dict:
    return {"signal": result.signal, "score": result.score,
            "method": method or getattr(result, "method", "style-heuristic"), "reasons": list(result.reasons)}


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
    code_ai = None
    if code_dir:
        combined_source = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in sorted(code_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() in _CODE_EXTENSIONS
        )
        if combined_source.strip():
            code_ai = _score_ai_code(str(submission_id), combined_source)
            code_ai_flagged = code_ai.signal == "high"

    flags = (
        db.query(SimilarityFlag)
        .filter(
            (SimilarityFlag.submission_a_id == submission_id)
            | (SimilarityFlag.submission_b_id == submission_id)
        )
        .all()
    )
    # Only token/fingerprint overlap counts as a similarity flag that can
    # cap an integrity score; a semantic-only "review" flag is surfaced
    # to the instructor but never penalizes on its own.
    similarity_flagged = any(f.flag_level in (None, "high") for f in flags)
    semantic_review_flagged = any(f.flag_level == "review" for f in flags)

    criteria = [
        _EvalCriterion(name=c["name"], description=c.get("description", ""), max_points=c["max_points"])
        for c in rubric.criteria
    ]

    # Report text extracted with MarkItDown right after upload; extract now
    # (and keep it) for submissions made before that existed.
    report_extraction = None
    if report_path:
        report_extraction = load_extraction(report_path) or extract_and_store(report_path)

    result = _run_pipeline(
        code_dir=code_dir,
        report_path=report_path,
        video_path=video_path,
        criteria=criteria,
        similarity_flagged=similarity_flagged,
        semantic_review_flagged=semantic_review_flagged,
        code_ai_flagged=code_ai_flagged,
        report_extraction=report_extraction,
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
        cross_modal_consistency=(
            result.semantic_consistency.to_dict() if result.semantic_consistency else None
        ),
        ai_signals={
            "report": _ai_signal_dict(result.report_analysis.ai_text) if result.report_analysis else None,
            "code": _ai_signal_dict(code_ai, method="style-heuristic") if code_ai else None,
        },
    )
    db.add(auto_eval)
    db.commit()
    db.refresh(auto_eval)
    return auto_eval


@app.get("/submissions/{submission_id}/auto-evaluate", response_model=Optional[AutoEvaluationOut])
def get_auto_evaluation(submission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "student":
        raise HTTPException(403, "Automated evaluation results are only available to instructors.")
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
