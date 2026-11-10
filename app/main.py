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
import re
import shutil
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from . import code_answers as _code_answers, code_languages as _langs, exports as _exports
from .auth import (
    bootstrap_admin,
    get_current_user,
    instructor_subject_ids,
    require_instructor,
    require_student,
    student_subject_ids,
)
from .common import (
    ANALYZED_EXTENSIONS as _ANALYZED_EXTENSIONS,
    CODE_EXTENSIONS as _CODE_EXTENSIONS,
    as_utc as _as_utc,
    instructor_assignment as _instructor_assignment,
    instructor_subject as _instructor_subject,
    norm_name as _norm_name,
    on_flag as _on,
    utcnow_naive as _utcnow_naive,
)
from .db import Base, BASE_DIR, SessionLocal, UPLOAD_DIR, add_missing_columns, engine, get_db, make_index_non_unique
from .demo_data import demo_data_enabled, seed_demo_data
from .evaluator import code_testing as _code_testing
from .evaluator.ai_text_detection import get_ai_text_detector, model_name as ai_text_model_name
from .evaluator.code_execution import SandboxUnavailable, sandbox_enabled as _sandbox_enabled
from .evaluator.document_extraction import (
    ReportValidationError,
    SUPPORTED_REPORT_EXTENSIONS,
    extract_and_store,
    load_extraction,
    report_max_bytes,
    validate_report_file,
)
from .evaluator.pipeline import evaluate_submission as _run_pipeline
from .evaluator.rubric_grading import Criterion as _EvalCriterion, HeuristicRubricGrader
from .evaluator.semantic_consistency import get_consistency_service
from .models import (
    Assignment,
    AutoEvaluation,
    BatchJob,
    Grade,
    Rubric,
    SimilarityFlag,
    Subject,
    Submission,
    SUBMISSION_TYPES,
    TaskStart,
    TaskUnlock,
    User,
)
from .notebook import read_code
from .routers.admin import _discard_derived_results, _remove_upload_part
from .routers.ai_content import router as _ai_content_router
from .routers.rubrics import _clean_name, _ensure_criterion_ids
from .routers.self_checks import router as _self_check_router
from .routers.similarity import router as _similarity_router
from .routers.student_runs import router as _student_run_router
from .routers.subject_access import router as _subject_access_router
from .schemas import (
    AssignmentIn,
    AssignmentOut,
    AssignmentUpdate,
    AutoEvaluateIn,
    AutoEvaluationOut,
    BatchAutoEvaluateIn,
    BatchAutoEvaluateOut,
    BatchEvaluationItemOut,
    BatchJobOut,
    CriterionMarkOut,
    GradeIn,
    GradeOut,
    MySubmissionOut,
    QuestionIn,
    QuestionOut,
    StudentAssignmentOut,
    SubmissionFileOut,
    SubmissionOut,
    TestCaseIn,
    TestCaseOut,
    TestResultOut,
    TestRunOut,
    TestRunQuestionOut,
    UpcomingAssignmentOut,
)
from .similarity import report_similarity as _report_sim
from .similarity.ai_heuristics import score_source as _score_ai_code
from .similarity.semantic import get_semantic_service
from .routers.admin import router as _admin_router
from .routers.auth import router as _auth_router
from .routers.rubrics import router as _rubrics_router


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


def _can_view_submission(user: User, submission: Submission, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return submission.student_id == user.id
    if user.role == "instructor":
        return submission.subject_id in instructor_subject_ids(db, user)
    return False


app.include_router(_auth_router)


app.include_router(_admin_router)


_ensure_criterion_ids()


app.include_router(_rubrics_router)


#
# Times are stored as naive UTC, like every other timestamp in this app, and
# returned with an explicit UTC offset so browsers show them in local time.
# The submission window is enforced here, in the API:
#   now < available_from  -> not available (students don't even see it)
#   available_from <= now <= deadline -> submissions allowed
#   now > deadline -> submissions, edits and deletions rejected

def _to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _validate_window(available_from: datetime, deadline: datetime) -> None:
    if deadline <= available_from:
        raise HTTPException(400, "The submission deadline must be later than the available-from date and time.")


def _clean_late_until(late_until: Optional[datetime], deadline: datetime) -> Optional[datetime]:
    """The date until which late work is taken, as naive UTC, or None. It can't be before the deadline."""
    if late_until is None:
        return None
    until = _to_naive_utc(late_until)
    if until < deadline:
        raise HTTPException(400, "Accept late submissions until a date after the deadline.")
    return until


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
        submission_types=a.accepted_types(),
        submission_count=len(subs), graded_count=sum(1 for s in subs if s.status == "graded"),
        created_at=_as_utc(a.created_at), updated_at=_as_utc(a.updated_at),
        starter_code=a.starter_code or "", starter_code_filename=a.starter_code_filename or "",
        report_template_filename=a.report_template_filename or "",
        report_template_words=len((a.report_template_text or "").split()),
        code_languages=a.code_languages or [],
        student_similarity_check=_on(a.student_similarity_check),
        student_ai_check=_on(a.student_ai_check),
        ignore_common_code=_on(a.ignore_common_code),
        marks_release_at=_as_utc(a.marks_release_at),
        marks_released=a.marks_released_at(_utcnow_naive()),
        test_cases=[TestCaseOut(**t) for t in a.test_cases or []],
        questions=[QuestionOut(**q) for q in a.questions],
        test_main_file=a.test_main_file or "",
        assignment_type=a.kind,
        task_password=(a.task_password or "") if a.kind == "code_challenge" else "",
        tasks_in_order=_on(a.tasks_in_order) if a.kind == "code_challenge" else False,
        late_grace_minutes=a.late_grace_minutes or 0, late_until=_as_utc(a.late_until),
        late_penalty_percent=a.late_penalty_percent or 0,
        late_penalty_max_percent=100 if a.late_penalty_max_percent is None else a.late_penalty_max_percent,
        late_penalty_unit=a.late_penalty_unit or "percent", late_penalty_marks=a.late_penalty_marks or 0,
        late_penalty_max_marks=a.late_penalty_max_marks,
        late_count=sum(1 for s in subs if s.late_seconds is not None),
    )


def _assignment_kind(payload: AssignmentIn) -> str:
    """The type of a new assignment, checked against its other fields. A code
    challenge accepts code only and needs at least one test case; test cases
    belong to code challenges only. Without an explicit type, test cases make
    it a code challenge."""
    kind = payload.assignment_type or ("code_challenge" if payload.test_cases else "submission")
    if kind == "code_challenge":
        if payload.rubric_id is not None:
            raise HTTPException(400, "A code challenge is marked by its test cases, not by a rubric.")
        if "submission_types" in payload.model_fields_set and list(set(payload.submission_types)) != ["code"]:
            raise HTTPException(400, "A code challenge accepts code submissions only.")
        if not payload.test_cases:
            raise HTTPException(400, "A code challenge needs at least one test case.")
    elif payload.test_cases or payload.questions:
        raise HTTPException(400, "Test cases and tasks belong to code challenges: choose the code challenge type.")
    return kind


def _clean_questions(questions: list[QuestionIn]) -> Optional[list[dict]]:
    """Number the tasks 1, 2, ... and title blank ones "Task N" (a lone task keeps a blank title, as a
    challenge made without tasks has). None when there are no tasks."""
    if not questions:
        return None
    return [
        {"id": n, "title": q.title.strip() or (f"Task {n}" if len(questions) > 1 else ""),
         "statement": q.statement.strip(), "starter_code": q.starter_code if q.starter_code.strip() else "",
         "time_limit_seconds": q.time_limit_seconds}
        for n, q in enumerate(questions, start=1)
    ]


def _number_tests(tests: list[TestCaseIn]) -> list[dict]:
    """Number the tests 1, 2, ... question by question (the order inside a question is kept) and
    name blank ones "Test N", N counting within the question."""
    counts: dict[int, int] = {}
    numbered = []
    for n, t in enumerate(sorted(tests, key=lambda test: test.question), start=1):
        counts[t.question] = counts.get(t.question, 0) + 1
        numbered.append({**t.model_dump(), "id": n, "name": t.name.strip() or f"Test {counts[t.question]}"})
    return numbered


def _check_question_tests(tests: list[dict], question_count: int) -> None:
    """Every test belongs to a task that exists, and every task has a test."""
    for t in tests:
        if t.get("question", 1) > question_count:
            raise HTTPException(
                400, f"The test case '{t['name']}' belongs to task {t['question']}, but this assignment "
                     f"has only {question_count} task{'' if question_count == 1 else 's'}.")
    for q in range(1, question_count + 1):
        if not any(t.get("question", 1) == q for t in tests):
            raise HTTPException(400, f"Task {q} needs at least one test case.")


def _clean_test_cases(tests: list[TestCaseIn], accepted_types: list[str], question_count: int = 1) -> Optional[list[dict]]:
    """Number the tests and check them against the challenge's questions. Tests run on
    submitted code, so they need an assignment that accepts code. None when
    there are no tests."""
    if not tests:
        return None
    if "code" not in accepted_types:
        raise HTTPException(400, "Test cases need an assignment that accepts code submissions.")
    numbered = _number_tests(tests)
    _check_question_tests(numbered, question_count)
    return numbered


def _update_questions_and_tests(db: Session, assignment: Assignment, payload: AssignmentUpdate) -> None:
    """Apply new questions and/or test cases to a code challenge, keeping the two consistent: the tests
    are checked against the questions that will exist afterwards, whichever of the two was sent."""
    if payload.test_cases is not None and not payload.test_cases:
        raise HTTPException(400, "A code challenge needs at least one test case.")
    questions = _clean_questions(payload.questions) if payload.questions is not None else assignment.code_questions
    count = len(questions or [1])
    if count != len(assignment.questions):
        # A submission keeps one file per task, so tasks can't be added or removed afterwards.
        if db.query(Submission.id).filter(Submission.assignment_id == assignment.id).first():
            raise HTTPException(
                409, "The number of tasks can't be changed after students have submitted to this assignment.")
    if payload.test_cases is not None:
        tests = _clean_test_cases(payload.test_cases, assignment.accepted_types(), count)
    else:
        tests = assignment.test_cases or []
        _check_question_tests(tests, count)
    assignment.code_questions, assignment.test_cases = questions, tests


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


def _is_code_challenge(submission: Submission) -> bool:
    return submission.assignment is not None and submission.assignment.kind == "code_challenge"


def _my_submission_out(submission: Submission, assignment_open: bool, now: datetime) -> MySubmissionOut:
    # The code of a code challenge cannot be replaced once handed in (it is marked from its tests at once), but
    # the whole submission can be deleted while the assignment is open, unless the instructor graded it.
    # Other work can be changed or deleted until the deadline or until it is graded.
    challenge = _is_code_challenge(submission)
    can_edit = assignment_open and submission.status != "graded" and not challenge
    # A challenge with time limits is final: doing it again would start every clock over.
    can_delete = assignment_open and (
        submission.latest_grade is None and not submission.assignment.is_timed if challenge
        else submission.status != "graded")
    common = dict(
        id=submission.id, submitted_at=_as_utc(submission.submitted_at),
        has_code=bool(submission.code_path), has_report=bool(submission.report_path),
        has_video=bool(submission.video_path), can_edit=can_edit, can_delete=can_delete,
        questions_submitted=_code_answers.answer_count(submission.assignment, submission)
        if _is_code_challenge(submission) else 0,
        late_seconds=submission.late_seconds, late_penalty_percent=submission.late_penalty_percent or 0,
        late_penalty_marks=submission.late_penalty_marks or 0,
    )
    if not _marks_released(submission, now):
        return MySubmissionOut(**common, status="submitted", final_mark=None, max_mark=None)
    grade = submission.latest_grade
    return MySubmissionOut(
        **common, status=submission.status,
        final_mark=submission.final_mark, max_mark=submission.max_mark, raw_mark=submission.raw_mark,
        criterion_marks=_criterion_marks(grade),
        feedback=grade.feedback if grade else None,
    )


def _student_submission_out(submission: Submission, now: datetime) -> SubmissionOut:
    """A submission as its student sees it: no mark before the release date."""
    out = SubmissionOut.model_validate(submission)
    if not _marks_released(submission, now):
        out = out.model_copy(update={"status": "submitted", "final_mark": None, "max_mark": None, "raw_mark": None})
    return out


def _student_assignment_out(db: Session, student: User, a: Assignment, now: datetime) -> StudentAssignmentOut:
    status = a.status_at(now)
    past_deadline = status == "closed"
    if past_deadline and a.accepts_at(now):
        status = "open"  # late work is still taken: the page treats the assignment as open (see `past_deadline`)
    mine = (
        db.query(Submission)
        .filter(Submission.assignment_id == a.id, Submission.student_id == student.id)
        .order_by(Submission.id.desc())
        .first()
    )
    unlocked = _code_answers.tasks_unlocked(db, student.id, a)
    return StudentAssignmentOut(
        id=a.id, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
        name=a.name, description=a.description or "",
        available_from=_as_utc(a.available_from), deadline=_as_utc(a.deadline), status=status,
        assignment_type=a.kind,
        submission_types=a.accepted_types(),
        code_languages=a.code_languages or [],
        student_similarity_check=_on(a.student_similarity_check),
        student_ai_check=_on(a.student_ai_check),
        marks_release_at=None if a.marks_released_at(now) else _as_utc(a.marks_release_at),
        # Behind the password only the titles are shown: the questions and starting code come after it is entered.
        questions=[QuestionOut(**(q if unlocked else {**q, "statement": "", "starter_code": ""})) for q in a.questions],
        has_task_password=a.requires_password,
        tasks_unlocked=unlocked,
        tasks_in_order=_on(a.tasks_in_order) if a.kind == "code_challenge" else False,
        past_deadline=past_deadline,
        accept_until=_as_utc(a.accept_until) if a.accept_until > a.deadline else None,
        late_grace_minutes=a.late_grace_minutes or 0,
        late_penalty_percent=a.late_penalty_percent or 0,
        late_penalty_max_percent=100 if a.late_penalty_max_percent is None else a.late_penalty_max_percent,
        late_penalty_unit=a.late_penalty_unit or "percent", late_penalty_marks=a.late_penalty_marks or 0,
        late_penalty_max_marks=a.late_penalty_max_marks,
        penalty_now_percent=a.lateness_at(now)[1], penalty_now_marks=a.lateness_at(now)[2],
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
    kind = _assignment_kind(payload)
    types = ["code"] if kind == "code_challenge" else _normalise_submission_types(payload.submission_types)
    questions = _clean_questions(payload.questions)
    assignment = Assignment(
        assignment_type=kind,
        subject_id=payload.subject_id, name=name, description=payload.description.strip(),
        available_from=available_from, deadline=deadline, rubric_id=payload.rubric_id,
        submission_types=types, starter_code=starter_code, starter_code_filename=starter_filename,
        code_languages=_langs.normalise_languages(payload.code_languages),
        student_similarity_check=payload.student_similarity_check,
        student_ai_check=payload.student_ai_check,
        ignore_common_code=payload.ignore_common_code,
        marks_release_at=_to_naive_utc(payload.marks_release_at) if payload.marks_release_at else None,
        test_cases=_clean_test_cases(payload.test_cases, types, len(questions or [1])),
        code_questions=questions,
        test_main_file=payload.test_main_file.strip() or None,
        task_password=(payload.task_password.strip() or None) if kind == "code_challenge" else None,
        tasks_in_order=payload.tasks_in_order and kind == "code_challenge",
        late_grace_minutes=payload.late_grace_minutes, late_until=_clean_late_until(payload.late_until, deadline),
        late_penalty_percent=payload.late_penalty_percent, late_penalty_max_percent=payload.late_penalty_max_percent,
        late_penalty_unit=payload.late_penalty_unit, late_penalty_marks=payload.late_penalty_marks,
        late_penalty_max_marks=payload.late_penalty_max_marks,
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


@app.get("/upcoming-assignments", response_model=list[UpcomingAssignmentOut])
def list_upcoming_assignments(student: User = Depends(require_student), db: Session = Depends(get_db)):
    """The not-yet-open assignments of the student's subjects, soonest first. GET /assignments still lists
    only opened ones, and an upcoming assignment's own page stays 404 until it opens."""
    now = _utcnow_naive()
    upcoming = (db.query(Assignment)
                .filter(Assignment.subject_id.in_(student_subject_ids(db, student)), Assignment.available_from > now)
                .order_by(Assignment.available_from).all())
    return [UpcomingAssignmentOut(name=a.name, subject_id=a.subject_id, subject_name=a.subject.name if a.subject else "",
                                  assignment_type=a.kind, available_from=_as_utc(a.available_from),
                                  deadline=_as_utc(a.deadline))
            for a in upcoming]


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
        if assignment.kind == "code_challenge" and payload.rubric_id is not None:
            raise HTTPException(400, "A code challenge is marked by its test cases, not by a rubric.")
        _check_assignment_rubric(db, assignment.subject_id, payload.rubric_id)
        assignment.rubric_id = payload.rubric_id
    if payload.submission_types is not None:
        types = _normalise_submission_types(payload.submission_types)
        if assignment.kind == "code_challenge" and types != ["code"]:
            raise HTTPException(400, "A code challenge accepts code submissions only.")
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
    if payload.ignore_common_code is not None:
        assignment.ignore_common_code = payload.ignore_common_code
    # Like the self-check switches, the release date can change at any time;
    # an explicit null releases the marks straight away.
    if "marks_release_at" in payload.model_fields_set:
        release = payload.marks_release_at
        assignment.marks_release_at = _to_naive_utc(release) if release else None
    # Tests can be changed at any time (e.g. to fix an expected output); the
    # list is replaced as a whole. Checked against the types as saved above.
    if payload.test_main_file is not None:
        assignment.test_main_file = payload.test_main_file.strip() or None
    # The password and the order can change at any time (a student who has entered the password stays in).
    if assignment.kind == "code_challenge":
        if payload.task_password is not None:
            assignment.task_password = payload.task_password.strip() or None
        if payload.tasks_in_order is not None:
            assignment.tasks_in_order = payload.tasks_in_order
    if payload.test_cases is not None or payload.questions is not None:
        if assignment.kind == "code_challenge":
            _update_questions_and_tests(db, assignment, payload)
        elif payload.test_cases or payload.questions:
            raise HTTPException(400, "Test cases and tasks belong to code challenges: choose the code challenge type.")
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
    # The late rules can change at any time; work already handed in keeps the penalty it got.
    if payload.late_grace_minutes is not None:
        assignment.late_grace_minutes = payload.late_grace_minutes
    if payload.late_penalty_percent is not None:
        assignment.late_penalty_percent = payload.late_penalty_percent
    if payload.late_penalty_max_percent is not None:
        assignment.late_penalty_max_percent = payload.late_penalty_max_percent
    if payload.late_penalty_unit is not None:
        assignment.late_penalty_unit = payload.late_penalty_unit
    if payload.late_penalty_marks is not None:
        assignment.late_penalty_marks = payload.late_penalty_marks
    if "late_penalty_max_marks" in payload.model_fields_set:
        assignment.late_penalty_max_marks = payload.late_penalty_max_marks  # null: no limit
    if "late_until" in payload.model_fields_set:
        assignment.late_until = _clean_late_until(payload.late_until, deadline)
    elif assignment.late_until is not None and assignment.late_until < deadline:
        assignment.late_until = deadline  # the deadline moved past the old date
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
    db.query(TaskUnlock).filter(TaskUnlock.assignment_id == assignment.id).delete(synchronize_session=False)
    db.query(TaskStart).filter(TaskStart.assignment_id == assignment.id).delete(synchronize_session=False)
    db.delete(assignment)
    db.commit()
    return {"status": "deleted", "submissions_kept": kept}


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
    if len(assignment.questions) > 1:
        # Each task is answered by its own file, which only the challenge's own code page makes.
        raise HTTPException(
            400, "This code challenge has several tasks: answer them on its code page, one at a time.")
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
    submission.apply_lateness(assignment, _utcnow_naive())
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
    """The deadline check every student write goes through. Work is taken until the deadline, then through the
    grace period and up to the accept-late-until date, when the instructor set them (it is then marked late)."""
    now = _utcnow_naive()
    if assignment.status_at(now) == "upcoming":
        raise HTTPException(403, f"'{assignment.name}' is not open for submissions yet.")
    if now > assignment.accept_until:
        raise HTTPException(403, f"The submission deadline for '{assignment.name}' has passed.")


def _own_changeable_submission(db: Session, student: User, submission_id: int, *,
                               deleting: bool = False) -> Submission:
    """The student's own submission, if they may still change it. A code challenge's code can never be
    replaced; with `deleting` it can be withdrawn while the assignment is open (it is marked from its tests at
    once, so "graded" does not stop it) unless the instructor graded it."""
    submission = db.get(Submission, submission_id)
    if not submission or submission.student_id != student.id:
        raise HTTPException(404, "Submission not found")  # never confirm other students' submissions exist
    if submission.assignment is None:
        raise HTTPException(409, "This submission isn't linked to an open assignment, so it can't be changed.")
    if submission.assignment.kind == "code_challenge":
        if not deleting:
            raise HTTPException(409, "A code challenge's code can't be changed once it is submitted. "
                                     "Delete the submission to do it again.")
        if submission.latest_grade is not None:
            raise HTTPException(409, "This submission has already been graded by your instructor and can no "
                                     "longer be deleted.")
        if submission.assignment.is_timed:
            raise HTTPException(409, "This code challenge has time limits, so a submission to it can't be deleted.")
    elif submission.status == "graded":
        raise HTTPException(409, "This submission has already been graded and can no longer be changed.")
    _require_open(submission.assignment)
    return submission


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
    assignment is open and before it's graded. Files not sent are kept.
    Not for a code challenge: its code cannot be replaced once it is submitted (delete it to start again)."""
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
    submission.apply_lateness(submission.assignment, _utcnow_naive())  # replacing files late makes the work late
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
    and before it's graded (a graded submission is an academic record).
    A code challenge may be deleted (and then done again) while it is open, even though its tests
    marked it at once, unless the instructor graded it."""
    submission = _own_changeable_submission(db, student, submission_id, deleting=True)
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
