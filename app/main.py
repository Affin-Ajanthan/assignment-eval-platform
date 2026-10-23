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

import os
from dataclasses import dataclass
import re
import tempfile
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .demo_data import demo_data_enabled, seed_demo_data
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
from .db import BASE_DIR, UPLOAD_DIR, Base, SessionLocal, add_missing_columns, engine, get_db
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
from .evaluator.ai_text_detection import get_ai_text_detector, model_name as ai_text_model_name
from .evaluator.rubric_grading import Criterion as _EvalCriterion, HeuristicRubricGrader
from .models import (
    SUBMISSION_TYPES,
    Assignment,
    AuthSession,
    AutoEvaluation,
    Enrollment,
    Grade,
    InstructorAssignment,
    Rubric,
    SelfCheck,
    SimilarityFlag,
    Subject,
    Submission,
    User,
)
from .similarity.ai_heuristics import score_source as _score_ai_code
from .similarity.core import Fingerprint, compare_all, fingerprint_source, subtract_starter
from .similarity.python_cleanup import names_in
from .notebook import NOTEBOOK_SUFFIX, read_code
from . import code_languages as _langs
from . import self_checks as _self_checks
from .code_languages import CodeLanguage
from .similarity import report_similarity as _report_sim
from . import exports as _exports
from .similarity.semantic import (
    MODEL_NAME as _SEMANTIC_MODEL,
    apply_semantic_signal,
    get_semantic_service,
    normalize_code,
    submissions_needing_semantic,
)

# Source files the similarity check and code analysis read. Includes C# and
# C/C++ headers, which unixcoder-base-nine was trained on.
_CODE_EXTENSIONS = {".py", ".java", ".js", ".c", ".cpp",".cc",".cxx",".hh",".hxx", ".h", ".hpp", ".cs", ".go", ".rb",".php"}
# Files the code checks read: source files plus Jupyter notebooks, whose code
# cells are read as Python (app/notebook.py).
_ANALYZED_EXTENSIONS = _CODE_EXTENSIONS | {NOTEBOOK_SUFFIX}

Base.metadata.create_all(bind=engine)
add_missing_columns("similarity_flags", {
    "semantic_similarity": "FLOAT", "flag_level": "VARCHAR", "flag_reason": "VARCHAR",
})
add_missing_columns("auto_evaluations", {"cross_modal_consistency": "JSON", "ai_signals": "JSON", "model": "VARCHAR"})
# Submissions made before assignments existed keep assignment_id NULL (and
# their free-text assignment_name); nothing else about them changes.
add_missing_columns("submissions", {"assignment_id": "INTEGER REFERENCES assignments(id)"})
add_missing_columns("grades", {"feedback": "TEXT"})
add_missing_columns("assignments", {"marks_release_at": "DATETIME"})
add_missing_columns("assignments", {"submission_types": "JSON"})
add_missing_columns("assignments", {"starter_code": "TEXT", "starter_code_filename": "VARCHAR"})
add_missing_columns("assignments", {"report_template_text": "TEXT", "report_template_filename": "VARCHAR"})
add_missing_columns("assignments", {"code_languages": "JSON"})
add_missing_columns("assignments", {"student_similarity_check": "BOOLEAN NOT NULL DEFAULT 1",
                                    "student_ai_check": "BOOLEAN NOT NULL DEFAULT 1"})


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
    # Admin lists only: how many submissions a student has (shown before
    # deleting the account, which deletes them too).
    submission_count: int = 0

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


class UserUpdate(BaseModel):
    """Admin edit of an instructor or student. Fields left out are kept;
    a blank password keeps the current one."""
    email: Optional[str] = Field(default=None, max_length=254)
    full_name: Optional[str] = Field(default=None, max_length=200)
    password: Optional[str] = Field(default=None, max_length=200)
    subject_ids: Optional[list[int]] = None


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


SubmissionType = Literal["code", "report", "video"]
_STARTER_CODE_MAX = 200_000


class AssignmentIn(BaseModel):
    subject_id: int
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=10_000)
    # ISO 8601. Times with an offset are converted to UTC; times without
    # one are taken as UTC (the frontend always sends UTC).
    available_from: datetime
    deadline: datetime
    rubric_id: Optional[int] = None
    # Which kinds of file students may submit. Defaults to all of them.
    submission_types: list[SubmissionType] = Field(default_factory=lambda: list(SUBMISSION_TYPES))
    # Optional instructor starter code (one file). Its fingerprints are left
    # out of the token similarity check; the file name's extension decides
    # which submitted files it is subtracted from.
    starter_code: str = Field(default="", max_length=_STARTER_CODE_MAX)
    starter_code_filename: str = Field(default="", max_length=200)
    # Optional: the only languages students may submit code in. Empty = any.
    code_languages: list[CodeLanguage] = Field(default_factory=list)
    # Student self-checks before the deadline; both on by default.
    student_similarity_check: bool = True
    student_ai_check: bool = True
    # Optional: students see no marks or feedback before this time. None shows
    # each mark as soon as it is saved.
    marks_release_at: Optional[datetime] = None


class AssignmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    available_from: Optional[datetime] = None
    deadline: Optional[datetime] = None
    rubric_id: Optional[int] = None  # send null explicitly to detach the rubric
    submission_types: Optional[list[SubmissionType]] = None
    starter_code: Optional[str] = Field(default=None, max_length=_STARTER_CODE_MAX)  # "" removes it
    starter_code_filename: Optional[str] = Field(default=None, max_length=200)
    code_languages: Optional[list[CodeLanguage]] = None  # [] removes the restriction
    student_similarity_check: Optional[bool] = None  # can be changed at any time
    student_ai_check: Optional[bool] = None
    marks_release_at: Optional[datetime] = None  # send null explicitly to release marks now


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
    submission_types: list[str]
    submission_count: int
    graded_count: int
    created_at: UTCDateTime
    updated_at: Optional[UTCDateTime]
    starter_code: str = ""
    starter_code_filename: str = ""
    # Template PDF cut out of student reports before the report similarity check.
    report_template_filename: str = ""
    report_template_words: int = 0
    # Languages students must use for code; empty = any supported language.
    code_languages: list[str] = []
    student_similarity_check: bool = True
    student_ai_check: bool = True
    marks_release_at: Optional[UTCDateTime] = None
    marks_released: bool = True  # whether students can see marks and feedback now


class CriterionMarkOut(BaseModel):
    name: str
    score: float
    max_points: float


class MySubmissionOut(BaseModel):
    """What a student sees about their own submission: status, the final
    total, the per-criterion marks and the instructor's feedback for them
    -- never the internal comments or the evaluator output."""

    id: int
    submitted_at: UTCDateTime
    status: str  # submitted | graded
    has_code: bool
    has_report: bool
    has_video: bool
    final_mark: Optional[float]
    max_mark: Optional[float]
    # Empty when graded with "Final mark only" (no per-criterion marks) or not graded.
    criterion_marks: list[CriterionMarkOut] = []
    feedback: Optional[str] = None
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
    submission_types: list[str]
    code_languages: list[str] = []  # empty = any supported language
    # Which self-checks the instructor allows for this assignment.
    student_similarity_check: bool = True
    student_ai_check: bool = True
    # Set only while marks are still held back: when they will be released.
    marks_release_at: Optional[UTCDateTime] = None
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
    # Kinds of file uploaded: a subset of code, report, video.
    submitted_types: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class GradeIn(BaseModel):
    rubric_id: int
    criterion_scores: dict[str, float] = Field(default_factory=dict)
    # Final mark only, without per-criterion marks. Send this OR criterion_scores.
    total_score: Optional[float] = None
    comments: Optional[str] = None  # internal notes, instructors only
    feedback: Optional[str] = Field(default=None, max_length=5000)  # for the student


class GradeOut(BaseModel):
    id: int
    submission_id: int
    rubric_id: int
    criterion_scores: dict[str, float]
    total_score: float
    comments: Optional[str]
    feedback: Optional[str] = None
    graded_by: Optional[str]
    graded_at: UTCDateTime

    model_config = ConfigDict(from_attributes=True)


class AutoEvaluateIn(BaseModel):
    rubric_id: int
    # False: grade with the built-in heuristic grader instead of the rubric
    # model (local Ollama). Everything else in the pipeline runs.
    use_rubric_model: bool = True
    # False: skip AI-content detection (the report's AI-text model and the
    # code heuristic). Cross-modal consistency and everything else still run.
    use_ai_detection: bool = True


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
    # True when the instructor switched AI-content detection off for this run.
    disabled: bool = False


class AutoEvaluationOut(BaseModel):
    id: int
    submission_id: int
    rubric_id: int
    recommended_score: float
    recommended_max: float
    review_flags: list[str]
    criterion_breakdown: list[dict]
    grader: str
    model: Optional[str] = None
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
    # True when the assignment's starter code was subtracted from the
    # token fingerprints before comparing.
    starter_code_excluded: bool = False


class ReportPassageOut(BaseModel):
    words: int
    text_a: str
    text_b: str


class ReportSimilarityPairOut(BaseModel):
    submission_a_id: int
    submission_b_id: int
    student_a: str
    student_b: str
    words_a: int
    words_b: int
    shared_fingerprints: int
    jaccard: float
    containment: float
    # Share of each report's words inside an identical passage.
    coverage_a: float
    coverage_b: float
    # all-MiniLM-L6-v2 best-match similarity; None when it didn't run.
    semantic_similarity: Optional[float]
    flag_level: Optional[str]  # "high" (identical passages) | "review" (semantic) | None
    flag_reason: Optional[str]
    passages: list[ReportPassageOut]


class ReportSkippedOut(BaseModel):
    submission_id: int
    student: str
    reason: str


class ReportSemanticSummaryOut(BaseModel):
    status: str  # ok | disabled | unavailable
    model: str
    warning: Optional[str] = None
    pairs_compared: int = 0
    cohort_median: Optional[float] = None
    review_threshold: Optional[float] = None


class ReportSimilarityOut(BaseModel):
    subject_id: int
    assignment_name: str
    compared: int
    skipped: list[ReportSkippedOut]
    # Fingerprints found in most reports (the assignment brief, a template)
    # that were left out of the comparison.
    common_fingerprints_excluded: int
    # The assignment's template PDF that was cut out of every report first.
    template_filename: Optional[str] = None
    template_words_removed: dict[str, int] = {}  # submission id -> words cut
    pairs: list[ReportSimilarityPairOut]
    semantic: ReportSemanticSummaryOut
    # Thresholds are uncalibrated: results are exploratory review signals.
    exploratory: bool = True


class BatchAutoEvaluateIn(BaseModel):
    rubric_id: int
    # Resume after an interruption: leave submissions that already have an
    # evaluation against this rubric untouched.
    skip_already_evaluated: bool = False
    # See AutoEvaluateIn.use_rubric_model / use_ai_detection.
    use_rubric_model: bool = True
    use_ai_detection: bool = True


def _ai_flagged(code_ai_flagged: bool, report_ai_signal: Optional[str]) -> bool:
    """AI-content review flag: the code or report signal is high. Never changes marks."""
    return bool(code_ai_flagged) or report_ai_signal == "high"


class BatchEvaluationItemOut(BaseModel):
    submission_id: int
    student_name: str
    status: str  # evaluated | skipped | failed
    recommended_score: Optional[float] = None
    recommended_max: Optional[float] = None
    grader: Optional[str] = None
    model: Optional[str] = None
    review_flags: list[str] = []
    error: Optional[str] = None
    # Review flags shown as their own table columns; None when the submission failed.
    similarity_flagged: Optional[bool] = None
    ai_flagged: Optional[bool] = None
    # Level, score and method behind ai_flagged, so the table can show which
    # detector ran. None when the submission failed or predates these details.
    ai_signals: Optional[AISignalsOut] = None


class BatchAutoEvaluateOut(BaseModel):
    subject_id: int
    assignment_name: str
    rubric_id: int
    total: int
    evaluated: int
    skipped: int
    failed: int
    results: list[BatchEvaluationItemOut]


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db = next(get_db())
    try:
        bootstrap_admin(db)
        if demo_data_enabled():
            seed_demo_data(db)
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
    # The AI-text detector falls back to the style heuristic silently when its
    # model is off or fails to load; this makes that visible. Public endpoint,
    # so only the error type is shown -- the full message is in the server log.
    detector = get_ai_text_detector()
    return {
        "status": "ok",
        "ai_text_detector": {
            "status": detector.status,  # not_loaded (still loading) | ready | unavailable | disabled
            "model": ai_text_model_name(),
            "fallback_to_heuristic": detector.status in ("unavailable", "disabled"),
            "error": detector.error.split(":", 1)[0] if detector.error else None,
        },
    }


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


def _require_two_decimals(label: str, score: float) -> None:
    """Manual marks have at most 2 decimal places (7.25 is fine, 7.3333 is not)."""
    if round(score, 2) != score:
        raise HTTPException(400, f"{label} must have at most 2 decimal places, got {score}")


def _require_assignment_rubric(submission: Submission, rubric: Rubric) -> None:
    """An assignment with a rubric is graded (and auto-evaluated) with that rubric
    only, so marks never end up on another rubric. Without one, any rubric of the
    subject is allowed."""
    assignment = submission.assignment
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


def _admin_managed_user(db: Session, user_id: int, role: str) -> User:
    user = db.get(User, user_id)
    if not user or user.role != role:
        raise HTTPException(404, f"{role.capitalize()} not found")
    return user


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
    password_changed = False
    if payload.password:  # blank or missing: keep the current password
        if len(payload.password) < 4:
            raise HTTPException(400, "Password must be at least 4 characters")
        user.password_hash, user.password_salt = hash_password(payload.password)
        password_changed = True
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
    db.delete(user)
    db.commit()
    for rel_path, kind in upload_parts:  # files only after the database change succeeded
        _remove_upload_part(rel_path, kind)
    return {"status": "deleted", "submissions_deleted": len(submissions)}


@app.put("/admin/instructors/{instructor_id}", response_model=UserOut)
def update_instructor(
    instructor_id: int, payload: UserUpdate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _update_user(db, _admin_managed_user(db, instructor_id, "instructor"), payload)


@app.delete("/admin/instructors/{instructor_id}")
def delete_instructor(instructor_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _delete_user(db, _admin_managed_user(db, instructor_id, "instructor"))


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
    counts = dict(
        db.query(Submission.student_id, func.count(Submission.id)).group_by(Submission.student_id).all()
    )
    return [_user_out(s, db).model_copy(update={"submission_count": counts.get(s.id, 0)}) for s in students]


@app.put("/admin/students/{student_id}", response_model=UserOut)
def update_student(
    student_id: int, payload: UserUpdate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _update_user(db, _admin_managed_user(db, student_id, "student"), payload)


@app.delete("/admin/students/{student_id}")
def delete_student(student_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _delete_user(db, _admin_managed_user(db, student_id, "student"))


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


def _on(flag: Optional[bool]) -> bool:
    """Self-check switches: NULL (rows made before the column existed) means on."""
    return flag is None or bool(flag)


def _assignment_out(db: Session, a: Assignment) -> AssignmentOut:
    subs = db.query(Submission).filter(Submission.assignment_id == a.id).all()
    return AssignmentOut(
        id=a.id, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
        name=a.name, description=a.description or "",
        available_from=_as_utc(a.available_from), deadline=_as_utc(a.deadline),
        status=a.status_at(_utcnow_naive()),
        rubric_id=a.rubric_id, rubric_name=a.rubric.name if a.rubric else None,
        max_points=a.rubric.max_total if a.rubric else None,
        submission_types=a.accepted_types(),
        submission_count=len(subs), graded_count=sum(1 for s in subs if s.status == "graded"),
        created_at=_as_utc(a.created_at), updated_at=_as_utc(a.updated_at),
        starter_code=a.starter_code or "", starter_code_filename=a.starter_code_filename or "",
        report_template_filename=a.report_template_filename or "",
        report_template_words=len((a.report_template_text or "").split()),
        code_languages=a.code_languages or [],
        student_similarity_check=_on(a.student_similarity_check),
        student_ai_check=_on(a.student_ai_check),
        marks_release_at=_as_utc(a.marks_release_at),
        marks_released=a.marks_released_at(_utcnow_naive()),
    )


def _clean_starter_code(code: str, filename: str) -> tuple[Optional[str], Optional[str]]:
    """Blank code means no starter code. Otherwise the file name must carry
    a code extension the similarity check reads, since that's what decides
    which submitted files the starter is subtracted from."""
    if not code.strip():
        return None, None
    filename = Path(filename.strip()).name
    if Path(filename).suffix.lower() not in _CODE_EXTENSIONS:
        raise HTTPException(
            400, "Starter code needs a file name ending in a code extension "
                 f"({', '.join(sorted(_CODE_EXTENSIONS))}), e.g. starter.py",
        )
    return code, filename


def _criterion_marks(grade: Grade | None) -> list[CriterionMarkOut]:
    """The grade's per-criterion marks in the rubric's order; empty for a
    "Final mark only" grade (it has no per-criterion marks)."""
    if grade is None or not grade.criterion_scores or grade.rubric is None:
        return []
    return [
        CriterionMarkOut(name=c["name"], score=grade.criterion_scores[c["name"]], max_points=c["max_points"])
        for c in grade.rubric.criteria
        if c["name"] in grade.criterion_scores
    ]


def _marks_released(submission: Submission, now: datetime) -> bool:
    """Whether the student may see this submission's marks and feedback yet.
    Before the assignment's release date the student is told only that the
    work was submitted -- not even that it has been graded."""
    return submission.assignment is None or submission.assignment.marks_released_at(now)


def _my_submission_out(submission: Submission, assignment_open: bool, now: datetime) -> MySubmissionOut:
    can_edit = assignment_open and submission.status != "graded"
    common = dict(
        id=submission.id, submitted_at=_as_utc(submission.submitted_at),
        has_code=bool(submission.code_path), has_report=bool(submission.report_path),
        has_video=bool(submission.video_path), can_edit=can_edit,
    )
    if not _marks_released(submission, now):
        return MySubmissionOut(**common, status="submitted", final_mark=None, max_mark=None)
    grade = submission.latest_grade
    return MySubmissionOut(
        **common, status=submission.status,
        final_mark=submission.final_mark, max_mark=submission.max_mark,
        criterion_marks=_criterion_marks(grade),
        feedback=grade.feedback if grade else None,
    )


def _student_submission_out(submission: Submission, now: datetime) -> SubmissionOut:
    """A submission as its student sees it: no mark before the release date."""
    out = SubmissionOut.model_validate(submission)
    if not _marks_released(submission, now):
        out = out.model_copy(update={"status": "submitted", "final_mark": None, "max_mark": None})
    return out


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
        submission_types=a.accepted_types(),
        code_languages=a.code_languages or [],
        student_similarity_check=_on(a.student_similarity_check),
        student_ai_check=_on(a.student_ai_check),
        marks_release_at=None if a.marks_released_at(now) else _as_utc(a.marks_release_at),
        my_submission=_my_submission_out(mine, status == "open", now) if mine else None,
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
    starter_code, starter_filename = _clean_starter_code(payload.starter_code, payload.starter_code_filename)
    types = _normalise_submission_types(payload.submission_types)
    assignment = Assignment(
        subject_id=payload.subject_id, name=name, description=payload.description.strip(),
        available_from=available_from, deadline=deadline, rubric_id=payload.rubric_id,
        submission_types=types, starter_code=starter_code, starter_code_filename=starter_filename,
        code_languages=_langs.normalise_languages(payload.code_languages),
        student_similarity_check=payload.student_similarity_check,
        student_ai_check=payload.student_ai_check,
        marks_release_at=_to_naive_utc(payload.marks_release_at) if payload.marks_release_at else None,
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
    if payload.submission_types is not None:
        types = _normalise_submission_types(payload.submission_types)
        if types != assignment.accepted_types():
            has_submissions = db.query(Submission.id).filter(Submission.assignment_id == assignment.id).first()
            if has_submissions:
                raise HTTPException(
                    409, "The accepted submission types can't be changed after students have submitted to this assignment.")
            assignment.submission_types = types
    # The self-check switches never lock: the instructor may turn them on or
    # off at any time (e.g. off for the last day before the deadline).
    if payload.student_similarity_check is not None:
        assignment.student_similarity_check = payload.student_similarity_check
    if payload.student_ai_check is not None:
        assignment.student_ai_check = payload.student_ai_check
    # Like the self-check switches, the release date can change at any time;
    # an explicit null releases the marks straight away.
    if "marks_release_at" in payload.model_fields_set:
        release = payload.marks_release_at
        assignment.marks_release_at = _to_naive_utc(release) if release else None
    if payload.code_languages is not None:
        languages = _langs.normalise_languages(payload.code_languages)
        if languages != (assignment.code_languages or None):
            has_submissions = db.query(Submission.id).filter(Submission.assignment_id == assignment.id).first()
            if has_submissions:
                raise HTTPException(
                    409, "The required programming language can't be changed after students have submitted "
                         "to this assignment.")
            assignment.code_languages = languages

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
    if payload.starter_code is not None or payload.starter_code_filename is not None:
        # Either field may be sent alone; the other keeps its stored value.
        code = payload.starter_code if payload.starter_code is not None else (assignment.starter_code or "")
        filename = (payload.starter_code_filename if payload.starter_code_filename is not None
                    else (assignment.starter_code_filename or ""))
        assignment.starter_code, assignment.starter_code_filename = _clean_starter_code(code, filename)
    assignment.available_from, assignment.deadline = available_from, deadline
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


_TEMPLATE_MIN_WORDS = 20


@app.post("/assignments/{assignment_id}/report-template", response_model=AssignmentOut)
def upload_report_template(
    assignment_id: int, file: UploadFile = File(...),
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Attach the assignment's template PDF (question paper / report
    template). Its text is cut out of every student report before the
    report similarity check, so pasted questions can't make reports look
    copied. Replaces an earlier template; only the extracted text is kept."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "The template must be a PDF file")
    data = file.file.read(report_max_bytes() + 1)
    if len(data) > report_max_bytes():
        raise HTTPException(400, f"The template PDF is larger than {report_max_bytes() // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a valid PDF")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "template.pdf"
        path.write_bytes(data)
        try:
            text = _report_sim.clean_report_pages(_report_sim.extract_pdf_pages(path))
        except Exception as exc:
            raise HTTPException(400, f"Could not read the PDF ({exc.__class__.__name__})") from None
    if len(text.split()) < _TEMPLATE_MIN_WORDS:
        raise HTTPException(400, "The PDF has almost no text to read (a scanned PDF has no text layer)")
    assignment.report_template_text = text
    assignment.report_template_filename = filename[:200]
    db.commit()
    db.refresh(assignment)
    return _assignment_out(db, assignment)


@app.delete("/assignments/{assignment_id}/report-template", response_model=AssignmentOut)
def delete_report_template(
    assignment_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Remove the assignment's template PDF."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    assignment.report_template_text = None
    assignment.report_template_filename = None
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
# Only languages the code checks actually read: a file type that is stored but
# never compared (TypeScript, Kotlin, Swift, Rust, JSX, ...) would leave a
# submission silently unchecked, so it is refused at upload instead.
_UPLOAD_CODE_EXTENSIONS = _ANALYZED_EXTENSIONS | {".zip"}
_ACCEPTED_LANGUAGES_TEXT = (
    "Python (.py, .ipynb), Java (.java), JavaScript (.js), C (.c, .h), "
    "C++ (.cpp, .cc, .cxx, .h, .hpp, .hh, .hxx), C# (.cs), Go (.go), Ruby (.rb), PHP (.php)"
)
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


def _wrong_language(assignment: Assignment, what: str) -> _UploadRejected:
    return _UploadRejected(
        400,
        f"'{assignment.name}' must be written in {_langs.describe(assignment.code_languages)}. "
        f"{what} Upload your code in the required language.",
    )


def _save_code_upload(file: UploadFile, submission_uuid: str, assignment: Optional[Assignment] = None) -> str:
    """Saves the code upload under uploads/<uuid>/code/. A .zip is
    extracted in place so the evaluator's static/similarity analysis
    (which walks a directory) works the same whether the student
    uploaded one file or a whole project. When the assignment requires
    particular languages, code in any other language is refused."""
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in _UPLOAD_CODE_EXTENSIONS:
        raise _UploadRejected(
            400,
            f"'{filename}' can't be checked: {suffix or 'files without an extension'} is not a supported "
            f"language. Upload a .zip or a single file in one of: {_ACCEPTED_LANGUAGES_TEXT}.",
        )
    allowed = _langs.allowed_extensions(assignment.code_languages if assignment else None)
    if allowed is not None and suffix != ".zip" and suffix not in allowed:
        raise _wrong_language(assignment, f"'{filename}' is {_langs.language_of(suffix)}.")
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
        # Other files (README, data, images) may come along, but at least one
        # file must be code the checks can read.
        if not any(p.is_file() and p.suffix.lower() in _ANALYZED_EXTENSIONS for p in code_dir.rglob("*")):
            raise _UploadRejected(
                400,
                f"'{filename}' contains no code in a supported language, so it can't be checked. "
                f"Include your source files in one of: {_ACCEPTED_LANGUAGES_TEXT}.",
            )
        if allowed is not None:
            # Non-code files (README, data) are fine; code in another language is not.
            others = sorted(
                p.relative_to(code_dir).as_posix() for p in code_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in _ANALYZED_EXTENSIONS and p.suffix.lower() not in allowed
            )
            if others:
                shown = ", ".join(f"{name} ({_langs.language_of(Path(name).suffix.lower())})" for name in others[:5])
                more = f" and {len(others) - 5} more" if len(others) > 5 else ""
                raise _wrong_language(assignment, f"'{filename}' contains code in another language: {shown}{more}.")
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


_TYPE_LABELS = {"code": "code (.zip or a source file)", "report": "report (PDF or DOCX)", "video": "video"}


def _normalise_submission_types(types: list[str]) -> list[str]:
    chosen = [t for t in SUBMISSION_TYPES if t in set(types)]
    if not chosen:
        raise HTTPException(400, "Choose at least one submission type (code, report or video).")
    return chosen


def _accepted_label(assignment: Assignment) -> str:
    return ", ".join(_TYPE_LABELS[t] for t in assignment.accepted_types())


def _reject_unaccepted_types(assignment: Assignment, **uploads) -> None:
    """Refuse files of a kind the instructor did not enable for this assignment."""
    accepted = set(assignment.accepted_types())
    rejected = [kind for kind, upload in uploads.items() if upload and kind not in accepted]
    if rejected:
        raise HTTPException(
            400,
            f"'{assignment.name}' accepts only: {_accepted_label(assignment)}. "
            f"Remove the {', '.join(rejected)} file(s) you uploaded.",
        )


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
        raise HTTPException(400, f"Upload at least one file: {_accepted_label(assignment)}.")
    _reject_unaccepted_types(assignment, code=code, report=report, video=video)
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
        code_path = _save_code_upload(code, submission_uuid, assignment) if code else None
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
    _reject_unaccepted_types(submission.assignment, code=code, report=report, video=video)

    batch = uuid.uuid4().hex[:8]
    try:
        new_code = _save_code_upload(code, batch, submission.assignment) if code else None
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
    if user.role == "student":
        # Filter by the status the student is shown, after held-back grades
        # are hidden, so the filter cannot reveal them either.
        now = _utcnow_naive()
        shown = [_student_submission_out(s, now) for s in query.order_by(Submission.submitted_at.desc()).all()]
        return [s for s in shown if not status or s.status == status]
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
    if user.role == "student":
        return _student_submission_out(submission, _utcnow_naive())
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
    _require_assignment_rubric(submission, rubric)

    if payload.total_score is not None:
        # Final mark only: no per-criterion marks are stored, rather than
        # inventing a split the instructor never decided.
        if payload.criterion_scores:
            raise HTTPException(400, "Send either criterion_scores or total_score, not both")
        if payload.total_score < 0 or payload.total_score > rubric.max_total:
            raise HTTPException(
                400,
                f"Final mark must be between 0 and {rubric.max_total}, got {payload.total_score}",
            )
        _require_two_decimals("Final mark", payload.total_score)
        total = payload.total_score
    else:
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
            _require_two_decimals(f"Score for '{name}'", score)
        total = round(sum(payload.criterion_scores.values()), 2)  # no 0.1 + 0.2 float noise


    grade = Grade(
        submission_id=submission_id,
        rubric_id=payload.rubric_id,
        criterion_scores=payload.criterion_scores,
        total_score=total,
        comments=payload.comments,
        feedback=(payload.feedback or "").strip() or None,
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

@dataclass
class _CodeSimilarityRun:
    pairs: list
    batch: object
    stats: dict
    starter_fp: object
    fingerprints: dict
    files_by_submission: dict  # submission id -> [self_checks.OwnFile]


def _display_name(code_dir: Path, path: Path, name: str) -> str:
    """The file's path inside the submission, keeping the tokenizer's name
    (a notebook's code cells are read as "<name>.ipynb.py")."""
    rel = path.relative_to(code_dir).as_posix()
    return rel + name[len(path.name):] if name.startswith(path.name) else rel


def _code_similarity_run(db: Session, subject_id: int, assignment_name: str,
                         submissions: list) -> _CodeSimilarityRun:
    """Token (Winnowing) + semantic (UniXcoder) comparison of every pair of
    code submissions. Stores nothing: the instructor's check stores flags,
    a student self-check never does."""
    # Starter code every student was given is subtracted from each file's
    # fingerprint (same extension only) so shared boilerplate can't flag a
    # pair on its own. The semantic path below still sees the full files.
    assignment = next(
        (a for a in db.query(Assignment).filter(Assignment.subject_id == subject_id).all()
         if _norm_name(a.name) == _norm_name(assignment_name)),
        None,
    )
    starter_fp = None
    if assignment and assignment.starter_code and assignment.starter_code_filename:
        starter_fp = fingerprint_source("starter", assignment.starter_code_filename, assignment.starter_code)

    # 1-4: read + normalize each submission once, fingerprint it, and
    # compare every unordered pair (A-B only, never B-A) on tokens.
    fingerprints: dict[str, "Fingerprint"] = {}
    files_by_submission: dict[str, list] = {}
    semantic_sources: dict[str, str] = {}
    for submission in submissions:
        code_dir = BASE_DIR / submission.code_path
        merged = Fingerprint(submission_id=str(submission.id), filename="(all files)", token_count=0)
        normalized_files: list[str] = []
        files = []
        if code_dir.is_dir():
            # (name, source) per file; a notebook is its code cells as "<name>.ipynb.py".
            files = [(path, *read_code(path)) for path in sorted(code_dir.rglob("*"))
                     if path.is_file() and path.suffix.lower() in _ANALYZED_EXTENSIONS]
        # Names each code file uses, so a top-level constant read by
        # another file isn't removed as "unused" before the semantic check.
        py_names = {path: names_in(source) for path, _, source in files}
        own_files = []
        for path, name, source in files:
            fp = subtract_starter(fingerprint_source(str(submission.id), name, source), starter_fp)
            merged.hashes |= fp.hashes
            own_files.append(_self_checks.OwnFile(name=_display_name(code_dir, path, name),
                                                  source=source, hashes=set(fp.hashes)))
            merged.token_count += fp.token_count
            external = set().union(*(names for other, names in py_names.items() if other != path))
            normalized_files.append(normalize_code(source, name, external))
        fingerprints[str(submission.id)] = merged
        files_by_submission[str(submission.id)] = own_files
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
    return _CodeSimilarityRun(pairs=pairs, batch=batch, stats=stats, starter_fp=starter_fp,
                              fingerprints=fingerprints, files_by_submission=files_by_submission)


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

    run = _code_similarity_run(db, subject_id, assignment_name, submissions)
    pairs, batch, stats, starter_fp = run.pairs, run.batch, run.stats, run.starter_fp

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
        starter_code_excluded=starter_fp is not None,
    )


# ---- Excel exports of results already shown to the instructor ---------------
#
# The browser sends back the result it received (similarity check, report
# similarity, whole-assignment evaluation) and gets the same data as .xlsx,
# so nothing expensive is re-run. Instructor-only, for their own subjects.

def _export_subject(db: Session, instructor: User, subject_id: int) -> Subject:
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "Subject not found")
    return subject


def _xlsx_response(content: bytes, kind: str, assignment_name: str) -> Response:
    return Response(content=content, media_type=_exports.XLSX_MEDIA_TYPE, headers={
        "Content-Disposition": f'attachment; filename="{_exports.filename(kind, assignment_name)}"'})


@app.post("/exports/code-similarity.xlsx")
def export_code_similarity(
    payload: SimilarityCheckOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = _export_subject(db, instructor, payload.subject_id)
    return _xlsx_response(_exports.code_similarity_xlsx(payload, f"{subject.name} ({subject.code})"),
                          "code-similarity", payload.assignment_name)


@app.post("/exports/report-similarity.xlsx")
def export_report_similarity(
    payload: ReportSimilarityOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = _export_subject(db, instructor, payload.subject_id)
    return _xlsx_response(_exports.report_similarity_xlsx(payload, f"{subject.name} ({subject.code})"),
                          "report-similarity", payload.assignment_name)


@app.post("/exports/batch-evaluation.xlsx")
def export_batch_evaluation(
    payload: BatchAutoEvaluateOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = _export_subject(db, instructor, payload.subject_id)
    rubric = db.get(Rubric, payload.rubric_id)
    rubric_name = rubric.name if rubric and rubric.subject_id == subject.id else f"Rubric #{payload.rubric_id}"
    return _xlsx_response(_exports.batch_evaluation_xlsx(payload, f"{subject.name} ({subject.code})", rubric_name),
                          "evaluation", payload.assignment_name)


def _report_similarity_text(submission: Submission) -> tuple[Optional[str], Optional[str]]:
    """(text, None) for a report the similarity check can compare, else
    (None, why not). PDFs are read page by page (so running headers and
    footers are dropped); DOCX reports through the MarkItDown extraction."""
    if not submission.report_path:
        return None, "No report submitted"
    path = BASE_DIR / submission.report_path
    if not path.is_file():
        return None, "Report file not found"
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _report_sim.clean_report_pages(_report_sim.extract_pdf_pages(path))
        elif suffix == ".docx":
            extraction = load_extraction(path) or extract_report_text(path)
            if not extraction.ok:
                return None, f"Could not read the DOCX ({extraction.status})"
            text = _report_sim.clean_report_pages([extraction.text])
        else:
            return None, f"Report is not a PDF or DOCX ({suffix or 'no extension'})"
    except Exception as exc:  # corrupt / encrypted document: compare the rest
        return None, f"Could not read the {suffix.lstrip('.').upper()} ({exc.__class__.__name__})"
    if len(text.split()) < _report_sim.MIN_REPORT_WORDS:
        return None, (f"Too little text to compare (under {_report_sim.MIN_REPORT_WORDS} words; "
                      "a scanned PDF has no extractable text)")
    return text, None


@app.post("/subjects/{subject_id}/assignments/{assignment_name}/check-report-similarity",
          response_model=ReportSimilarityOut)
def check_report_similarity(
    subject_id: int, assignment_name: str, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    """Compare the PDF reports of one assignment pairwise: identical
    passages (Winnowing over words) and similar meaning (all-MiniLM-L6-v2).
    Review signal only -- nothing is stored, so it never affects grading."""
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")

    submissions = (
        db.query(Submission)
        .filter(Submission.subject_id == subject_id, Submission.assignment_name == assignment_name)
        .order_by(Submission.id)
        .all()
    )
    names = {str(s.id): s.student_name for s in submissions}
    texts: dict[str, str] = {}
    skipped: list[ReportSkippedOut] = []
    for submission in submissions:
        def skip(reason: str) -> None:
            skipped.append(ReportSkippedOut(submission_id=submission.id, student=submission.student_name,
                                            reason=reason))

        text, reason = _report_similarity_text(submission)
        if text is None:
            skip(reason)
            continue
        texts[str(submission.id)] = text

    if len(texts) < 2:
        raise HTTPException(400, "Need at least 2 readable PDF reports for this assignment to compare")

    assignment = next(
        (a for a in db.query(Assignment).filter(Assignment.subject_id == subject_id).all()
         if _norm_name(a.name) == _norm_name(assignment_name)),
        None,
    )
    template = assignment.report_template_text if assignment else None
    result = _report_sim.compare_reports(texts, get_consistency_service(), template_text=template)
    return ReportSimilarityOut(
        subject_id=subject_id,
        assignment_name=assignment_name,
        compared=len(texts),
        skipped=skipped,
        common_fingerprints_excluded=result.common_fingerprints_excluded,
        template_filename=(assignment.report_template_filename if template else None),
        template_words_removed=result.template_words_removed,
        pairs=[
            ReportSimilarityPairOut(
                submission_a_id=int(p.submission_a), submission_b_id=int(p.submission_b),
                student_a=names[p.submission_a], student_b=names[p.submission_b],
                words_a=p.words_a, words_b=p.words_b, shared_fingerprints=p.shared_fingerprints,
                jaccard=p.jaccard, containment=p.containment, coverage_a=p.coverage_a, coverage_b=p.coverage_b,
                semantic_similarity=p.semantic_similarity, flag_level=p.flag_level, flag_reason=p.flag_reason,
                passages=[ReportPassageOut(words=x.words, text_a=x.text_a, text_b=x.text_b) for x in p.passages],
            )
            for p in result.pairs
        ],
        semantic=ReportSemanticSummaryOut(
            status=result.semantic_status, model="sentence-transformers/all-MiniLM-L6-v2",
            warning=result.semantic_warning, pairs_compared=result.semantic_pairs_compared,
            cohort_median=result.cohort_median, review_threshold=result.review_threshold,
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
    _require_assignment_rubric(submission, rubric)
    return _run_auto_evaluation(db, submission, rubric, use_rubric_model=payload.use_rubric_model,
                                use_ai_detection=payload.use_ai_detection)


def _run_auto_evaluation(
    db: Session, submission: Submission, rubric: Rubric, use_rubric_model: bool = True,
    use_ai_detection: bool = True,
) -> AutoEvaluation:
    """Run the full pipeline for one submission against one rubric, store
    and return the AutoEvaluation. Shared by the single and batch endpoints;
    callers have already checked access and that the rubric matches.
    ``use_rubric_model=False`` grades with the heuristic grader instead of
    the rubric model (the instructor's on/off switch)."""
    submission_id = submission.id
    code_dir = BASE_DIR / submission.code_path if submission.code_path else None
    report_path = BASE_DIR / submission.report_path if submission.report_path else None
    video_path = BASE_DIR / submission.video_path if submission.video_path else None
    code_dir = code_dir if code_dir and code_dir.is_dir() else None
    report_path = report_path if report_path and report_path.is_file() else None
    video_path = video_path if video_path and video_path.is_file() else None

    code_ai_flagged = False
    code_ai = None
    if code_dir and use_ai_detection:
        combined_source = "\n".join(
            read_code(p)[1]
            for p in sorted(code_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() in _ANALYZED_EXTENSIONS
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
    # Similarity flags are review signals only and never change marks in
    # any grader. Token/fingerprint overlap is the "high" flag; a
    # semantic-only "review" flag is surfaced the same way, just worded
    # as a weaker signal.
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
        grader=None if use_rubric_model else HeuristicRubricGrader(),
        ai_detection=use_ai_detection,
    )

    auto_eval = AutoEvaluation(
        submission_id=submission_id,
        rubric_id=rubric.id,
        recommended_score=result.recommended_score,
        recommended_max=result.recommended_max,
        review_flags=result.review_flags,
        criterion_breakdown=[
            {"name": c.name, "score": c.score, "max_points": c.max_points, "justification": c.justification}
            for c in result.grading.criteria
        ],
        grader=result.grading.grader,
        model=result.grading.model,
        similarity_flagged=result.similarity_flagged,
        code_ai_flagged=result.code_ai_flagged,
        report_ai_signal=result.report_analysis.ai_text.signal if result.report_analysis and use_ai_detection else None,
        consistency_score=result.consistency.consistency_score,
        cross_modal_consistency=(
            result.semantic_consistency.to_dict() if result.semantic_consistency else None
        ),
        ai_signals={
            "report": _ai_signal_dict(result.report_analysis.ai_text) if result.report_analysis else None,
            "code": _ai_signal_dict(code_ai, method="style-heuristic") if code_ai else None,
        } if use_ai_detection else {"report": None, "code": None, "disabled": True},
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


# How many submissions a batch auto-evaluation grades at the same time. 1 (the
# default) runs them one after another. More workers overlap the CPU steps
# (unzipping, report extraction, code analysis) with grading, and with
# OLLAMA_NUM_PARALLEL set to the same number Ollama grades that many at once.
# All of them share one GPU, so the gain depends on its memory: measure first.
AUTO_EVAL_WORKERS = max(1, int(os.environ.get("AUTO_EVAL_WORKERS", "1")))


@app.post(
    "/subjects/{subject_id}/assignments/{assignment_name}/auto-evaluate",
    response_model=BatchAutoEvaluateOut,
)
def auto_evaluate_assignment(
    subject_id: int, assignment_name: str, payload: BatchAutoEvaluateIn,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Auto-evaluate every submission of one assignment against one rubric.

    Submissions are processed AUTO_EVAL_WORKERS at a time (one after another
    by default). Each result is saved as soon as it is produced and one
    failing submission never aborts the rest, so after an interruption the
    call can simply be repeated with ``skip_already_evaluated`` set. Results
    keep the submissions' order whatever order they finish in.
    Running the similarity check first lets its flags feed the grading.
    """
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    rubric = db.get(Rubric, payload.rubric_id)
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    if rubric.subject_id != subject_id:
        raise HTTPException(400, "That rubric belongs to a different subject than this assignment")

    submissions = (
        db.query(Submission)
        .filter(Submission.subject_id == subject_id, Submission.assignment_name == assignment_name)
        .order_by(Submission.id)
        .all()
    )
    if not submissions:
        raise HTTPException(404, "No submissions found for this assignment")

    # Latest stored evaluation per submission. A skipped submission is not re-run,
    # but its stored marks and flags still go into the table.
    stored: dict[int, AutoEvaluation] = {}
    if payload.skip_already_evaluated:
        stored_rows = (
            db.query(AutoEvaluation)
            .filter(
                AutoEvaluation.rubric_id == rubric.id,
                AutoEvaluation.submission_id.in_([s.id for s in submissions]),
            )
            .order_by(AutoEvaluation.id)
            .all()
        )
        stored = {row.submission_id: row for row in stored_rows}  # later rows overwrite earlier ones

    results: list[BatchEvaluationItemOut | None] = [None] * len(submissions)
    to_run: list[tuple[int, int]] = []  # (position in results, submission id)
    for position, submission in enumerate(submissions):
        if submission.id in stored:
            prev = stored[submission.id]
            results[position] = BatchEvaluationItemOut(
                submission_id=submission.id, student_name=submission.student_name, status="skipped",
                recommended_score=prev.recommended_score, recommended_max=prev.recommended_max,
                grader=prev.grader, model=prev.model, review_flags=list(prev.review_flags or []),
                similarity_flagged=prev.similarity_flagged,
                ai_flagged=_ai_flagged(prev.code_ai_flagged, prev.report_ai_signal),
                ai_signals=prev.ai_signals)
        else:
            to_run.append((position, submission.id))

    rubric_id = rubric.id

    def evaluate(submission_id: int) -> BatchEvaluationItemOut:
        # Its own session: a SQLAlchemy session must not be shared between threads.
        worker_db = SessionLocal()
        try:
            submission = worker_db.get(Submission, submission_id)
            name = submission.student_name
            try:
                ev = _run_auto_evaluation(worker_db, submission, worker_db.get(Rubric, rubric_id),
                                          use_rubric_model=payload.use_rubric_model,
                                          use_ai_detection=payload.use_ai_detection)
            except Exception as exc:  # one bad submission must not stop the batch
                worker_db.rollback()
                return BatchEvaluationItemOut(
                    submission_id=submission_id, student_name=name, status="failed",
                    error=f"{exc.__class__.__name__}: {exc}"[:200])
            return BatchEvaluationItemOut(
                submission_id=submission_id, student_name=name, status="evaluated",
                recommended_score=ev.recommended_score, recommended_max=ev.recommended_max,
                grader=ev.grader, model=ev.model, review_flags=list(ev.review_flags or []),
                similarity_flagged=ev.similarity_flagged,
                ai_flagged=_ai_flagged(ev.code_ai_flagged, ev.report_ai_signal),
                ai_signals=ev.ai_signals)
        finally:
            worker_db.close()

    ids = [submission_id for _, submission_id in to_run]
    workers = min(AUTO_EVAL_WORKERS, len(ids))
    if workers <= 1:
        items = [evaluate(submission_id) for submission_id in ids]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="auto-eval") as pool:
            items = list(pool.map(evaluate, ids))  # map keeps the input order
    for (position, _), item in zip(to_run, items):
        results[position] = item

    def _count(status: str) -> int:
        return sum(1 for r in results if r.status == status)

    return BatchAutoEvaluateOut(
        subject_id=subject_id, assignment_name=assignment_name, rubric_id=rubric.id,
        total=len(results), evaluated=_count("evaluated"), skipped=_count("skipped"),
        failed=_count("failed"), results=results,
    )


# ---- Student self-checks ------------------------------------------------------
#
# While an assignment is open, a student can check their own submission for
# code similarity, report similarity and AI content. The instructor switches
# each on or off per assignment (on by default); every rule below is enforced
# here, whatever the UI shows. Results go to SelfCheck only -- never to the
# instructor's SimilarityFlag / AutoEvaluation records -- and a student only
# ever sees bands and their own matching passages (app/self_checks.py).

SelfCheckKind = Literal["code_similarity", "report_similarity", "ai_content"]


class SelfCheckIn(BaseModel):
    kind: SelfCheckKind


class SelfCheckOut(BaseModel):
    id: int
    kind: str
    status: str  # running | done | failed
    created_at: UTCDateTime
    finished_at: Optional[UTCDateTime] = None
    error: Optional[str] = None
    result: Optional[dict] = None  # student-safe: bands and their own passages only


class SelfCheckStatusOut(BaseModel):
    submission_id: int
    can_run: bool  # assignment open and submission not graded
    similarity_enabled: bool
    ai_enabled: bool
    limit_per_hour: int
    remaining: dict[str, int]  # checks left this hour, per kind
    latest: dict[str, Optional[SelfCheckOut]]  # most recent check per kind


class SelfCheckHistoryRow(BaseModel):
    submission_id: int
    student_name: str
    student_email: str
    code_similarity_checks: int
    report_similarity_checks: int
    ai_checks: int
    last_check_at: Optional[UTCDateTime] = None
    latest_kind: Optional[str] = None
    latest_status: Optional[str] = None


_SELF_CHECK_FAILED = "The check could not be completed. Please try again later."


def _self_check_out(check: SelfCheck) -> SelfCheckOut:
    return SelfCheckOut(
        id=check.id, kind=check.kind, status=check.status, created_at=_as_utc(check.created_at),
        finished_at=_as_utc(check.finished_at) if check.finished_at else None,
        error=_SELF_CHECK_FAILED if check.status == "failed" else None,
        result=_self_checks.for_student(check.kind, check.result) if check.status == "done" else None,
    )


def _own_submission(db: Session, student: User, submission_id: int) -> Submission:
    submission = db.get(Submission, submission_id)
    if not submission or submission.student_id != student.id:
        raise HTTPException(404, "Submission not found")  # never confirm other students' submissions exist
    return submission


def _self_check_allowed(submission: Submission) -> Optional[str]:
    """Why the student can't run a self-check now, or None."""
    a = submission.assignment
    if a is None:
        return "Self-checks are only available for assignment submissions."
    status = a.status_at(_utcnow_naive())
    if status == "upcoming":
        return f"'{a.name}' is not open yet."
    if status == "closed":
        return f"The deadline for '{a.name}' has passed, so self-checks are closed."
    if submission.status == "graded":
        return "This submission has been graded, so self-checks are closed."
    return None


def _expire_stale_checks(db: Session, submission_id: int) -> None:
    cutoff = _utcnow_naive() - timedelta(minutes=_self_checks.STALE_AFTER_MINUTES)
    for check in db.query(SelfCheck).filter(SelfCheck.submission_id == submission_id,
                                            SelfCheck.status == "running",
                                            SelfCheck.created_at < cutoff).all():
        check.status, check.error, check.finished_at = "failed", "timed out", _utcnow_naive()
    db.commit()


def _checks_this_hour(db: Session, submission: Submission, kind: str) -> list[SelfCheck]:
    """This student's checks of one kind in the last hour, for ONE assignment:
    each assignment has its own limit."""
    since = _utcnow_naive() - timedelta(hours=1)
    scope = (SelfCheck.assignment_id == submission.assignment_id if submission.assignment_id is not None
             else SelfCheck.submission_id == submission.id)
    return (db.query(SelfCheck)
            .filter(SelfCheck.student_id == submission.student_id, scope, SelfCheck.kind == kind,
                    SelfCheck.created_at >= since)
            .order_by(SelfCheck.created_at).all())


@app.post("/submissions/{submission_id}/self-checks", response_model=SelfCheckOut, status_code=202)
def start_self_check(
    submission_id: int, payload: SelfCheckIn, background_tasks: BackgroundTasks,
    student: User = Depends(require_student), db: Session = Depends(get_db),
):
    """Start one self-check in the background; poll GET .../self-checks for the result."""
    submission = _own_submission(db, student, submission_id)
    blocked = _self_check_allowed(submission)
    if blocked:
        raise HTTPException(403, blocked)
    a = submission.assignment
    kind = payload.kind
    if kind in ("code_similarity", "report_similarity") and not _on(a.student_similarity_check):
        raise HTTPException(403, "Your instructor has turned off similarity self-checks for this assignment.")
    if kind == "ai_content" and not _on(a.student_ai_check):
        raise HTTPException(403, "Your instructor has turned off AI-content self-checks for this assignment.")
    if kind == "code_similarity" and not submission.code_path:
        raise HTTPException(400, "Upload your code first, then check it.")
    if kind == "report_similarity" and not submission.report_path:
        raise HTTPException(400, "Upload your report first, then check it.")
    if kind == "ai_content" and not (submission.code_path or submission.report_path):
        raise HTTPException(400, "Upload your code or report first, then check it.")

    _expire_stale_checks(db, submission.id)
    if db.query(SelfCheck.id).filter(SelfCheck.submission_id == submission.id, SelfCheck.kind == kind,
                                     SelfCheck.status == "running").first():
        raise HTTPException(409, f"Your {_self_checks.KIND_LABELS[kind].lower()} check is still running.")
    recent = _checks_this_hour(db, submission, kind)
    if len(recent) >= _self_checks.LIMIT_PER_HOUR:
        free_at = _as_utc(recent[0].created_at) + timedelta(hours=1)
        minutes = max(1, int((free_at - _as_utc(_utcnow_naive())).total_seconds() // 60) + 1)
        raise HTTPException(
            429, f"You've used all {_self_checks.LIMIT_PER_HOUR} {_self_checks.KIND_LABELS[kind].lower()} "
                 f"checks for '{a.name}' this hour. You can check again in about {minutes} minute(s).")

    check = SelfCheck(submission_id=submission.id, student_id=student.id, assignment_id=a.id, kind=kind,
                      status="running", created_at=_utcnow_naive())
    db.add(check)
    db.commit()
    db.refresh(check)
    background_tasks.add_task(_run_self_check, check.id)
    return _self_check_out(check)


@app.get("/submissions/{submission_id}/self-checks", response_model=SelfCheckStatusOut)
def self_check_status(submission_id: int, student: User = Depends(require_student), db: Session = Depends(get_db)):
    submission = _own_submission(db, student, submission_id)
    _expire_stale_checks(db, submission.id)
    a = submission.assignment
    latest: dict[str, Optional[SelfCheckOut]] = {}
    remaining: dict[str, int] = {}
    for kind in _self_checks.KINDS:
        last = (db.query(SelfCheck).filter(SelfCheck.submission_id == submission.id, SelfCheck.kind == kind)
                .order_by(SelfCheck.id.desc()).first())
        latest[kind] = _self_check_out(last) if last else None
        remaining[kind] = max(0, _self_checks.LIMIT_PER_HOUR - len(_checks_this_hour(db, submission, kind)))
    return SelfCheckStatusOut(
        submission_id=submission.id, can_run=_self_check_allowed(submission) is None,
        similarity_enabled=bool(a) and _on(a.student_similarity_check),
        ai_enabled=bool(a) and _on(a.student_ai_check),
        limit_per_hour=_self_checks.LIMIT_PER_HOUR, remaining=remaining, latest=latest,
    )


@app.get("/assignments/{assignment_id}/self-checks", response_model=list[SelfCheckHistoryRow])
def self_check_history(assignment_id: int, instructor: User = Depends(require_instructor),
                       db: Session = Depends(get_db)):
    """How often each student has run each self-check. For monitoring and
    troubleshooting -- repeated checks usually just mean a student is
    improving their work, not misconduct."""
    assignment = _instructor_assignment(db, instructor, assignment_id)
    rows = []
    subs = (db.query(Submission).filter(Submission.assignment_id == assignment.id)
            .order_by(Submission.id).all())
    for sub in subs:
        checks = db.query(SelfCheck).filter(SelfCheck.submission_id == sub.id).order_by(SelfCheck.id).all()
        count = lambda kind: sum(c.kind == kind for c in checks)  # noqa: E731
        last = checks[-1] if checks else None
        rows.append(SelfCheckHistoryRow(
            submission_id=sub.id, student_name=sub.student_name, student_email=sub.student_email,
            code_similarity_checks=count("code_similarity"), report_similarity_checks=count("report_similarity"),
            ai_checks=count("ai_content"),
            last_check_at=_as_utc(last.created_at) if last else None,
            latest_kind=last.kind if last else None, latest_status=last.status if last else None,
        ))
    rows.sort(key=lambda r: (r.last_check_at is None, -(r.last_check_at.timestamp() if r.last_check_at else 0)))
    return rows


def _run_self_check(check_id: int) -> None:
    """Background job: compute one self-check and store it. Never raises."""
    db = SessionLocal()
    try:
        check = db.get(SelfCheck, check_id)
        if check is None:
            return
        try:
            submission = db.get(Submission, check.submission_id)
            if check.kind == "code_similarity":
                check.result = _self_check_code(db, submission)
            elif check.kind == "report_similarity":
                check.result = _self_check_report(db, submission)
            else:
                check.result = _self_check_ai(submission)
            check.status = "done"
        except Exception as exc:  # stored for the instructor; the student sees a generic message
            check.status, check.error = "failed", f"{exc.__class__.__name__}: {exc}"[:300]
        check.finished_at = _utcnow_naive()
        db.commit()
    finally:
        db.close()


def _self_check_code(db: Session, submission: Submission) -> dict:
    others = (db.query(Submission)
              .filter(Submission.subject_id == submission.subject_id,
                      Submission.assignment_name == submission.assignment_name,
                      Submission.code_path.isnot(None)).all())
    if len(others) < 2:
        result = _self_checks.code_result(str(submission.id), [], [], {}, "disabled")
        result["note"] = "No other code submissions to compare with yet."
        return result
    run = _code_similarity_run(db, submission.subject_id, submission.assignment_name, others)
    return _self_checks.code_result(
        str(submission.id), run.pairs, run.files_by_submission.get(str(submission.id), []),
        {sid: fp.hashes for sid, fp in run.fingerprints.items()}, run.batch.status)


def _self_check_report(db: Session, submission: Submission) -> dict:
    own, reason = _report_similarity_text(submission)
    if own is None:
        return _self_checks.report_result(str(submission.id), [], "disabled", skipped_reason=reason)
    texts = {str(submission.id): own}
    for other in (db.query(Submission)
                  .filter(Submission.subject_id == submission.subject_id,
                          Submission.assignment_name == submission.assignment_name,
                          Submission.id != submission.id).all()):
        text, _ = _report_similarity_text(other)
        if text is not None:
            texts[str(other.id)] = text
    if len(texts) < 2:
        return _self_checks.report_result(str(submission.id), [], "disabled",
                                          skipped_reason="No other reports to compare with yet.")
    a = submission.assignment
    comparison = _report_sim.compare_reports(texts, get_consistency_service(),
                                             template_text=a.report_template_text if a else None)
    return _self_checks.report_result(str(submission.id), comparison.pairs, comparison.semantic_status)


def _self_check_ai(submission: Submission) -> dict:
    from .evaluator.report_analysis import ai_text_signal

    detail: dict = {}
    report_band = code_band = None
    if submission.report_path:
        path = BASE_DIR / submission.report_path
        extraction = (load_extraction(path) or extract_report_text(path)) if path.is_file() else None
        if extraction and extraction.ok and extraction.text.strip():
            signal = ai_text_signal(extraction.text)
            report_band = _self_checks.ai_band(signal.signal)
            detail["report"] = {"signal": signal.signal, "score": signal.score, "method": signal.method}
    if submission.code_path:
        code_dir = BASE_DIR / submission.code_path
        source = "\n".join(read_code(p)[1] for p in sorted(code_dir.rglob("*"))
                           if p.is_file() and p.suffix.lower() in _ANALYZED_EXTENSIONS) if code_dir.is_dir() else ""
        if source.strip():
            signal = _score_ai_code(str(submission.id), source)
            code_band = _self_checks.ai_band(signal.signal)
            detail["code"] = {"signal": signal.signal, "score": signal.score, "method": "style-heuristic"}
    return {"report": report_band, "code": code_band, "detail": detail}
