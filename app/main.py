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

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import bootstrap_admin
from .db import Base, add_missing_columns, engine, get_db, make_index_non_unique
from .demo_data import demo_data_enabled, seed_demo_data
from .evaluator.ai_text_detection import get_ai_text_detector, model_name as ai_text_model_name
from .evaluator.semantic_consistency import get_consistency_service
from .routers.ai_content import router as _ai_content_router
from .routers.auto_evaluation import _mark_interrupted_batch_jobs
from .routers.rubrics import _ensure_criterion_ids
from .routers.self_checks import router as _self_check_router
from .routers.similarity import router as _similarity_router
from .routers.student_runs import router as _student_run_router
from .routers.subject_access import router as _subject_access_router
from .similarity.semantic import get_semantic_service
from .routers.admin import router as _admin_router
from .routers.assignments import router as _assignments_router
from .routers.auth import router as _auth_router
from .routers.auto_evaluation import router as _auto_evaluation_router
from .routers.grading import router as _grading_router
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


app.include_router(_auth_router)


app.include_router(_admin_router)


_ensure_criterion_ids()


app.include_router(_rubrics_router)


app.include_router(_assignments_router)


app.include_router(_submissions_router)


app.include_router(_grading_router)


app.include_router(_auto_evaluation_router)


app.include_router(_self_check_router)


app.include_router(_student_run_router)


app.include_router(_subject_access_router)


app.include_router(_similarity_router)


app.include_router(_ai_content_router)
