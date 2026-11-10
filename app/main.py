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
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from . import code_answers as _code_answers, exports as _exports
from .auth import bootstrap_admin, get_current_user, instructor_subject_ids, require_instructor
from .common import (
    ANALYZED_EXTENSIONS as _ANALYZED_EXTENSIONS,
    as_utc as _as_utc,
    instructor_subject as _instructor_subject,
    utcnow_naive as _utcnow_naive,
)
from .db import Base, BASE_DIR, SessionLocal, add_missing_columns, engine, get_db, make_index_non_unique
from .demo_data import demo_data_enabled, seed_demo_data
from .evaluator import code_testing as _code_testing
from .evaluator.ai_text_detection import get_ai_text_detector, model_name as ai_text_model_name
from .evaluator.code_execution import SandboxUnavailable, sandbox_enabled as _sandbox_enabled
from .evaluator.document_extraction import extract_and_store, load_extraction
from .evaluator.pipeline import evaluate_submission as _run_pipeline
from .evaluator.rubric_grading import Criterion as _EvalCriterion, HeuristicRubricGrader
from .evaluator.semantic_consistency import get_consistency_service
from .models import Assignment, AutoEvaluation, BatchJob, Grade, Rubric, SimilarityFlag, Submission, User
from .notebook import read_code
from .routers.ai_content import router as _ai_content_router
from .routers.rubrics import _ensure_criterion_ids
from .routers.self_checks import router as _self_check_router
from .routers.similarity import router as _similarity_router
from .routers.student_runs import router as _student_run_router
from .routers.subject_access import router as _subject_access_router
from .routers.submissions import _can_view_submission
from .schemas import (
    AutoEvaluateIn,
    AutoEvaluationOut,
    BatchAutoEvaluateIn,
    BatchAutoEvaluateOut,
    BatchEvaluationItemOut,
    BatchJobOut,
    GradeIn,
    GradeOut,
    TestResultOut,
    TestRunOut,
    TestRunQuestionOut,
)
from .similarity.ai_heuristics import score_source as _score_ai_code
from .similarity.semantic import get_semantic_service
from .routers.admin import router as _admin_router
from .routers.assignments import router as _assignments_router
from .routers.auth import router as _auth_router
from .routers.rubrics import router as _rubrics_router
from .routers.submissions import router as _submissions_router


Base.metadata.create_all(bind=engine)


add_missing_columns("similarity_flags", {
    "semantic_similarity": "FLOAT", "flag_level": "VARCHAR", "flag_reason": "VARCHAR",
})


add_missing_columns("auto_evaluations", {"cross_modal_consistency": "JSON", "ai_signals": "JSON", "model": "VARCHAR"})


# Submissions made before assignments existed keep assignment_id NULL (and
# their free-text assignment_name); nothing else about them changes.
add_missing_columns("submissions", {"assignment_id": "INTEGER REFERENCES assignments(id)"})


add_missing_columns("grades", {"feedback": "TEXT"})


add_missing_columns("users", {"batch": "VARCHAR", "register_number": "VARCHAR"})


# Existing accounts get False: nobody already using the platform is asked to change their password.
add_missing_columns("users", {"must_change_password": "BOOLEAN NOT NULL DEFAULT 0"})


# Every batch has the same subjects with the same codes, so a subject code is no longer unique.
make_index_non_unique("subjects", "code")


add_missing_columns("subjects", {"batch": "VARCHAR NOT NULL DEFAULT ''"})


add_missing_columns("subjects", {"open_to_students": "BOOLEAN NOT NULL DEFAULT 0", "join_password": "VARCHAR"})


add_missing_columns("subjects", {"registration_ends_at": "DATETIME"})


add_missing_columns("assignments", {"marks_release_at": "DATETIME"})


add_missing_columns("submissions", {"test_earned": "FLOAT", "test_total": "FLOAT", "tests_run_at": "DATETIME"})


add_missing_columns("submissions", {"question_results": "JSON"})


add_missing_columns("assignments", {"test_cases": "JSON"})


add_missing_columns("assignments", {"test_main_file": "VARCHAR"})


add_missing_columns("assignments", {"code_questions": "JSON"})


add_missing_columns("assignments", {"task_password": "VARCHAR", "tasks_in_order": "BOOLEAN NOT NULL DEFAULT 0"})


add_missing_columns("assignments", {"assignment_type": "VARCHAR NOT NULL DEFAULT 'submission'"})


add_missing_columns("assignments", {"submission_types": "JSON"})


add_missing_columns("assignments", {"starter_code": "TEXT", "starter_code_filename": "VARCHAR"})


add_missing_columns("assignments", {"report_template_text": "TEXT", "report_template_filename": "VARCHAR"})


add_missing_columns("assignments", {"code_languages": "JSON"})


add_missing_columns("assignments", {"student_similarity_check": "BOOLEAN NOT NULL DEFAULT 1",
                                    "student_ai_check": "BOOLEAN NOT NULL DEFAULT 1"})


add_missing_columns("assignments", {"ignore_common_code": "BOOLEAN NOT NULL DEFAULT 1"})


add_missing_columns("assignments", {
    "late_grace_minutes": "INTEGER NOT NULL DEFAULT 0", "late_until": "DATETIME",
    "late_penalty_percent": "FLOAT NOT NULL DEFAULT 0", "late_penalty_max_percent": "FLOAT NOT NULL DEFAULT 100",
    "late_penalty_unit": "VARCHAR NOT NULL DEFAULT 'percent'", "late_penalty_marks": "FLOAT NOT NULL DEFAULT 0",
    "late_penalty_max_marks": "FLOAT"})


add_missing_columns("submissions", {"late_seconds": "INTEGER", "late_penalty_percent": "FLOAT NOT NULL DEFAULT 0",
                                    "late_penalty_marks": "FLOAT NOT NULL DEFAULT 0"})


def _ai_flagged(code_ai_flagged: bool, report_ai_signal: Optional[str]) -> bool:
    """AI-content review flag: the code or report signal is high. Never changes marks."""
    return bool(code_ai_flagged) or report_ai_signal == "high"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db = next(get_db())
    try:
        bootstrap_admin(db)
        if demo_data_enabled():
            seed_demo_data(db)
        _mark_interrupted_batch_jobs(db)
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


def _require_two_decimals(label: str, score: float) -> None:
    """Manual marks have at most 2 decimal places (7.25 is fine, 7.3333 is not)."""
    if round(score, 2) != score:
        raise HTTPException(400, f"{label} must have at most 2 decimal places, got {score}")


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


app.include_router(_auth_router)


app.include_router(_admin_router)


_ensure_criterion_ids()


app.include_router(_rubrics_router)


app.include_router(_assignments_router)


app.include_router(_submissions_router)


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


#
# The browser sends back the result it received and gets the same data as
# .xlsx, so nothing is re-run. Instructor-only, for their own subjects. (The
# similarity exports are in app/routers/similarity.py.)

@app.post("/exports/batch-evaluation.xlsx")
def export_batch_evaluation(
    payload: BatchAutoEvaluateOut, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)
):
    subject = _instructor_subject(db, instructor, payload.subject_id)
    rubric = db.get(Rubric, payload.rubric_id)
    rubric_name = rubric.name if rubric and rubric.subject_id == subject.id else f"Rubric #{payload.rubric_id}"
    return _exports.xlsx_response(
        _exports.batch_evaluation_xlsx(payload, f"{subject.name} ({subject.code})", rubric_name),
        "evaluation", payload.assignment_name)


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


def _batch_job_status_out(job: BatchJob) -> BatchJobOut:
    return BatchJobOut(
        id=job.id, subject_id=job.subject_id, assignment_name=job.assignment_name, rubric_id=job.rubric_id,
        status=job.status, total=job.total, done=job.done, evaluated=job.evaluated, skipped=job.skipped,
        failed=job.failed, error=job.error,
        results=[BatchEvaluationItemOut.model_validate(r) if r is not None else None for r in job.results or []],
        created_at=_as_utc(job.created_at), started_at=_as_utc(job.started_at),
        finished_at=_as_utc(job.finished_at),
    )


def _create_batch_job(
    db: Session, instructor: User, subject_id: int, assignment_name: str, payload: BatchAutoEvaluateIn,
) -> BatchJob:
    """Check access and inputs, then save a queued job for the run."""
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    rubric = db.get(Rubric, payload.rubric_id)
    if not rubric:
        raise HTTPException(404, "Rubric not found")
    if rubric.subject_id != subject_id:
        raise HTTPException(400, "That rubric belongs to a different subject than this assignment")
    total = (
        db.query(Submission)
        .filter(Submission.subject_id == subject_id, Submission.assignment_name == assignment_name)
        .count()
    )
    if not total:
        raise HTTPException(404, "No submissions found for this assignment")
    named = db.query(Assignment).filter(Assignment.subject_id == subject_id, Assignment.name == assignment_name).first()
    if named is not None and named.kind == "code_challenge":
        raise HTTPException(400, "A code challenge is marked from its tests, not with a rubric.")
    # One run per assignment at a time: a second one would grade the same
    # submissions again, in parallel, for nothing.
    active = (
        db.query(BatchJob)
        .filter(BatchJob.subject_id == subject_id, BatchJob.assignment_name == assignment_name,
                BatchJob.status.in_(("queued", "running")))
        .first()
    )
    if active:
        raise HTTPException(
            409, f"This assignment is already being evaluated ({active.done} of {active.total} done). "
                 "Wait for that run to finish.",
        )

    job = BatchJob(
        subject_id=subject_id, assignment_name=assignment_name, rubric_id=rubric.id,
        options=payload.model_dump(include={"skip_already_evaluated", "use_rubric_model", "use_ai_detection"}),
        status="queued", total=total, created_by_id=instructor.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@app.post(
    "/subjects/{subject_id}/assignments/{assignment_name}/auto-evaluate/jobs",
    response_model=BatchJobOut, status_code=202,
)
def start_auto_evaluate_job(
    subject_id: int, assignment_name: str, payload: BatchAutoEvaluateIn, background_tasks: BackgroundTasks,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Start the same run as POST .../auto-evaluate, but in the background:
    answers at once with the queued job, while the submissions are evaluated
    (AUTO_EVAL_WORKERS at a time) and the job's progress is updated as each
    one finishes."""
    job = _create_batch_job(db, instructor, subject_id, assignment_name, payload)
    background_tasks.add_task(_run_batch_job, job.id)
    return _batch_job_status_out(job)


@app.get(
    "/subjects/{subject_id}/assignments/{assignment_name}/auto-evaluate/jobs/latest",
    response_model=Optional[BatchJobOut],
)
def get_latest_auto_evaluate_job(
    subject_id: int, assignment_name: str,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """The assignment's most recent batch job (running or finished), or null
    if it was never run. Lets the page show a run again after the instructor
    left and came back."""
    if subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    job = (
        db.query(BatchJob)
        .filter(BatchJob.subject_id == subject_id, BatchJob.assignment_name == assignment_name)
        .order_by(BatchJob.id.desc())
        .first()
    )
    return _batch_job_status_out(job) if job else None


def _mark_interrupted_batch_jobs(db: Session) -> int:
    """Run at server start: a job still queued or running cannot be -- its
    background thread died with the previous server process. Mark it
    "interrupted" (so it no longer blocks its assignment) and let the
    instructor resume it. Returns how many were marked."""
    stale = db.query(BatchJob).filter(BatchJob.status.in_(("queued", "running"))).all()
    for job in stale:
        job.status, job.finished_at = "interrupted", _utcnow_naive()
        job.error = f"The server stopped after {job.done} of {job.total} submissions."
    db.commit()
    return len(stale)


@app.post("/auto-evaluate/jobs/{job_id}/resume", response_model=BatchJobOut, status_code=202)
def resume_auto_evaluate_job(
    job_id: int, background_tasks: BackgroundTasks,
    instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Finish an interrupted (or failed) run: start a new job for the same
    assignment and rubric with the same options, skipping submissions that
    already have an evaluation, so only the rest are graded."""
    job = db.get(BatchJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    if job.status not in ("interrupted", "failed", "stopped"):
        raise HTTPException(
            409, f"Only an interrupted, failed or stopped run can be resumed; this one is {job.status}.")
    payload = BatchAutoEvaluateIn(
        rubric_id=job.rubric_id,
        use_rubric_model=job.options.get("use_rubric_model", True),
        use_ai_detection=job.options.get("use_ai_detection", True),
        skip_already_evaluated=True,
    )
    resumed = _create_batch_job(db, instructor, job.subject_id, job.assignment_name, payload)
    background_tasks.add_task(_run_batch_job, resumed.id)
    return _batch_job_status_out(resumed)


@app.post("/auto-evaluate/jobs/{job_id}/stop", response_model=BatchJobOut)
def stop_auto_evaluate_job(
    job_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Stop a running batch evaluation at any time. The run is marked "stopped" at once (so the assignment is free
    for a new run); the worker sees that before it starts the next submission, so the one being graded right now
    still finishes. Everything evaluated so far is kept: Resume grades the rest, or a new run grades everything."""
    job = db.get(BatchJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    if job.status not in ("queued", "running"):
        raise HTTPException(409, f"Only a running evaluation can be stopped; this one is {job.status}.")
    job.status, job.finished_at = "stopped", _utcnow_naive()
    job.error = f"Stopped by you after {job.done} of {job.total} submissions."
    db.commit()
    db.refresh(job)
    return _batch_job_status_out(job)


@app.get("/auto-evaluate/jobs/{job_id}", response_model=BatchJobOut)
def get_auto_evaluate_job(
    job_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """A batch auto-evaluation job's progress so far: poll it while it runs.
    Finished submissions already have their result; the others are null."""
    job = db.get(BatchJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    return _batch_job_status_out(job)


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

    Waits until every submission is done; POST .../auto-evaluate/jobs starts
    the same run in the background instead.
    """
    job = _create_batch_job(db, instructor, subject_id, assignment_name, payload)
    _run_batch_job(job.id)
    db.refresh(job)
    if job.status == "failed":
        raise HTTPException(500, f"Batch evaluation failed: {job.error}")
    return _batch_job_out(job)


def _batch_job_out(job: BatchJob) -> BatchAutoEvaluateOut:
    return BatchAutoEvaluateOut(
        subject_id=job.subject_id, assignment_name=job.assignment_name, rubric_id=job.rubric_id,
        job_id=job.id, total=job.total, evaluated=job.evaluated, skipped=job.skipped, failed=job.failed,
        results=[BatchEvaluationItemOut.model_validate(r) for r in job.results or [] if r is not None],
    )


def _run_batch_job(job_id: int) -> None:
    """Evaluate every submission of the job's assignment, recording progress
    in the job as each one finishes. Uses its own database sessions, so it
    can run outside the request that started it.

    Submissions are processed AUTO_EVAL_WORKERS at a time; the worker threads
    only write their own evaluations, and this thread alone updates the job."""
    db = SessionLocal()
    try:
        job = db.get(BatchJob, job_id)
        if job.status == "stopped":  # stopped before the worker even started
            return
        options = job.options

        def stop_requested() -> bool:
            """True once the instructor pressed Stop (POST .../stop sets the status)."""
            db.refresh(job)
            return job.status == "stopped"

        submissions = (
            db.query(Submission)
            .filter(Submission.subject_id == job.subject_id, Submission.assignment_name == job.assignment_name)
            .order_by(Submission.id)
            .all()
        )

        # Latest stored evaluation per submission. A skipped submission is not re-run,
        # but its stored marks and flags still go into the table.
        stored: dict[int, AutoEvaluation] = {}
        if options.get("skip_already_evaluated"):
            stored_rows = (
                db.query(AutoEvaluation)
                .filter(
                    AutoEvaluation.rubric_id == job.rubric_id,
                    AutoEvaluation.submission_id.in_([s.id for s in submissions]),
                )
                .order_by(AutoEvaluation.id)
                .all()
            )
            stored = {row.submission_id: row for row in stored_rows}  # later rows overwrite earlier ones

        results: list[dict | None] = [None] * len(submissions)
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
                    ai_signals=prev.ai_signals,
                    cross_modal_consistency=prev.cross_modal_consistency).model_dump(mode="json")
            else:
                to_run.append((position, submission.id))

        job.status, job.started_at = "running", _utcnow_naive()
        job.total, job.skipped, job.evaluated, job.failed = len(submissions), len(stored), 0, 0
        job.results = list(results)
        db.commit()

        rubric_id = job.rubric_id

        def evaluate(submission_id: int) -> BatchEvaluationItemOut:
            # Its own session: a SQLAlchemy session must not be shared between threads.
            worker_db = SessionLocal()
            try:
                submission = worker_db.get(Submission, submission_id)
                name = submission.student_name
                try:
                    ev = _run_auto_evaluation(worker_db, submission, worker_db.get(Rubric, rubric_id),
                                              use_rubric_model=options.get("use_rubric_model", True),
                                              use_ai_detection=options.get("use_ai_detection", True))
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
                    ai_signals=ev.ai_signals,
                    cross_modal_consistency=ev.cross_modal_consistency)
            finally:
                worker_db.close()

        def record(position: int, item: BatchEvaluationItemOut) -> None:
            results[position] = item.model_dump(mode="json")
            job.results = list(results)
            flag_modified(job, "results")  # a JSON column: tell SQLAlchemy it changed
            if item.status == "failed":
                job.failed += 1
            else:
                job.evaluated += 1
            db.commit()

        workers = min(AUTO_EVAL_WORKERS, len(to_run))
        if workers <= 1:
            for position, submission_id in to_run:
                if stop_requested():
                    break
                record(position, evaluate(submission_id))
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="auto-eval") as pool:
                futures = {pool.submit(evaluate, submission_id): position for position, submission_id in to_run}
                for future in as_completed(futures):  # record each one as soon as it finishes
                    if future.cancelled():
                        continue
                    record(futures[future], future.result())
                    if stop_requested():  # the ones not started yet are dropped; running ones finish
                        for pending in futures:
                            pending.cancel()

        if not stop_requested():  # a stopped job keeps its "stopped" status
            job.status, job.finished_at = "done", _utcnow_naive()
            db.commit()
    except Exception as exc:  # the job itself broke (not one submission): record why
        db.rollback()
        job = db.get(BatchJob, job_id)
        if job is not None:
            job.status, job.finished_at = "failed", _utcnow_naive()
            job.error = f"{exc.__class__.__name__}: {exc}"[:500]
            db.commit()
    finally:
        db.close()


def _run_tests_for(db: Session, instructor: User, submission_id: int, *, challenge_only: bool = False):
    """Check access, then run the assignment's tests on a submission's code in
    the Docker sandbox, question by question. Returns (submission, runs, score), `runs` being
    a QuestionRun for each question."""
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if submission.subject_id not in instructor_subject_ids(db, instructor):
        raise HTTPException(403, "You are not assigned to this subject")
    assignment = submission.assignment
    if assignment is None or not assignment.test_cases:
        raise HTTPException(400, "This assignment has no test cases.")
    if challenge_only and assignment.kind != "code_challenge":
        raise HTTPException(400, "Only a code challenge is marked from its tests.")
    if not submission.code_path:
        raise HTTPException(400, "This submission has no code.")
    if not _sandbox_enabled():
        raise HTTPException(503, "Code execution is off. Set CODE_SANDBOX=docker and restart the backend.")
    try:
        runs = _code_testing.run_questions(
            BASE_DIR / submission.code_path, assignment.questions, assignment.test_cases,
            main_file=assignment.test_main_file or "")
    except _code_testing.CodeTestError as exc:
        raise HTTPException(400, str(exc))
    except SandboxUnavailable as exc:
        raise HTTPException(503, str(exc))
    return submission, runs, _code_testing.score_run([r for q in runs for r in q.results])


def _test_run_out(submission: Submission, runs: list, score, *, saved: bool = False) -> TestRunOut:
    def per_question(q) -> TestRunQuestionOut:
        mine = _code_testing.score_run(q.results)
        return TestRunQuestionOut(
            question=q.question, title=q.title, answered=q.answered, file=q.file, language=q.language,
            passed=mine.passed, total=mine.count, earned_points=mine.earned, total_points=mine.total)

    return TestRunOut(
        submission_id=submission.id, saved=saved,
        file=", ".join(q.file for q in runs if q.answered),
        language=", ".join(dict.fromkeys(q.language for q in runs if q.answered)),
        passed=score.passed, total=score.count, earned_points=score.earned, total_points=score.total,
        results=[TestResultOut(**vars(r)) for q in runs for r in q.results],
        questions=[per_question(q) for q in runs],
    )


@app.post("/submissions/{submission_id}/run-tests", response_model=TestRunOut)
def run_submission_tests(
    submission_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Run the assignment's test cases on this submission's code in the Docker
    sandbox and return every test's result. Changes nothing. Needs CODE_SANDBOX=docker."""
    submission, runs, score = _run_tests_for(db, instructor, submission_id)
    return _test_run_out(submission, runs, score)


@app.post("/submissions/{submission_id}/mark-from-tests", response_model=TestRunOut)
def mark_submission_from_tests(
    submission_id: int, instructor: User = Depends(require_instructor), db: Session = Depends(get_db),
):
    """Run the tests (as run-tests does) and save the points of the tests passed
    as this code challenge submission's mark, e.g. 12 of 16. Running again
    replaces the mark. The student sees it like any other mark, once the
    assignment's marks are released."""
    submission, runs, score = _run_tests_for(db, instructor, submission_id, challenge_only=True)
    # Every answered question's result is replaced, so what the student sees per question follows the mark.
    _code_answers.record_runs(submission.assignment, submission, runs, now=_utcnow_naive())
    db.commit()
    return _test_run_out(submission, runs, score, saved=True)


app.include_router(_self_check_router)


app.include_router(_student_run_router)


app.include_router(_subject_access_router)


app.include_router(_similarity_router)


app.include_router(_ai_content_router)
