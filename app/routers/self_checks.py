"""Student self-checks: the API.

While an assignment is open, a student can check their own submission for
code similarity, report similarity and AI content. The instructor switches
each on or off per assignment (on by default); every rule below is enforced
here, whatever the UI shows. Results go to SelfCheck only -- never to the
instructor's SimilarityFlag / AutoEvaluation records -- and a student only
ever sees bands and their own matching passages (app/self_checks.py).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import self_checks as _self_checks
from ..auth import require_instructor, require_student
from ..common import ANALYZED_EXTENSIONS, UTCDateTime, as_utc, instructor_assignment, on_flag, utcnow_naive
from ..db import BASE_DIR, SessionLocal, get_db
from ..evaluator.document_extraction import extract_report_text, load_extraction
from ..evaluator.report_analysis import ai_text_signal
from ..evaluator.semantic_consistency import get_consistency_service
from ..models import SelfCheck, Submission, User
from ..notebook import read_code
from ..similarity import report_similarity as _report_sim
from ..similarity.ai_heuristics import score_source as _score_ai_code
from ..similarity_runs import code_similarity_run, report_similarity_text

router = APIRouter()

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
        id=check.id, kind=check.kind, status=check.status, created_at=as_utc(check.created_at),
        finished_at=as_utc(check.finished_at) if check.finished_at else None,
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
    status = a.status_at(utcnow_naive())
    if status == "upcoming":
        return f"'{a.name}' is not open yet."
    if status == "closed":
        return f"The deadline for '{a.name}' has passed, so self-checks are closed."
    if submission.status == "graded":
        return "This submission has been graded, so self-checks are closed."
    return None


def _expire_stale_checks(db: Session, submission_id: int) -> None:
    cutoff = utcnow_naive() - timedelta(minutes=_self_checks.STALE_AFTER_MINUTES)
    for check in db.query(SelfCheck).filter(SelfCheck.submission_id == submission_id,
                                            SelfCheck.status == "running",
                                            SelfCheck.created_at < cutoff).all():
        check.status, check.error, check.finished_at = "failed", "timed out", utcnow_naive()
    db.commit()


def _checks_this_hour(db: Session, submission: Submission, kind: str) -> list[SelfCheck]:
    """This student's checks of one kind in the last hour, for ONE assignment:
    each assignment has its own limit."""
    since = utcnow_naive() - timedelta(hours=1)
    scope = (SelfCheck.assignment_id == submission.assignment_id if submission.assignment_id is not None
             else SelfCheck.submission_id == submission.id)
    return (db.query(SelfCheck)
            .filter(SelfCheck.student_id == submission.student_id, scope, SelfCheck.kind == kind,
                    SelfCheck.created_at >= since)
            .order_by(SelfCheck.created_at).all())


@router.post("/submissions/{submission_id}/self-checks", response_model=SelfCheckOut, status_code=202)
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
    if kind in ("code_similarity", "report_similarity") and not on_flag(a.student_similarity_check):
        raise HTTPException(403, "Your instructor has turned off similarity self-checks for this assignment.")
    if kind == "ai_content" and not on_flag(a.student_ai_check):
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
        free_at = as_utc(recent[0].created_at) + timedelta(hours=1)
        minutes = max(1, int((free_at - as_utc(utcnow_naive())).total_seconds() // 60) + 1)
        raise HTTPException(
            429, f"You've used all {_self_checks.LIMIT_PER_HOUR} {_self_checks.KIND_LABELS[kind].lower()} "
                 f"checks for '{a.name}' this hour. You can check again in about {minutes} minute(s).")

    check = SelfCheck(submission_id=submission.id, student_id=student.id, assignment_id=a.id, kind=kind,
                      status="running", created_at=utcnow_naive())
    db.add(check)
    db.commit()
    db.refresh(check)
    background_tasks.add_task(_run_self_check, check.id)
    return _self_check_out(check)


@router.get("/submissions/{submission_id}/self-checks", response_model=SelfCheckStatusOut)
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
        similarity_enabled=bool(a) and on_flag(a.student_similarity_check),
        ai_enabled=bool(a) and on_flag(a.student_ai_check),
        limit_per_hour=_self_checks.LIMIT_PER_HOUR, remaining=remaining, latest=latest,
    )


@router.get("/assignments/{assignment_id}/self-checks", response_model=list[SelfCheckHistoryRow])
def self_check_history(assignment_id: int, instructor: User = Depends(require_instructor),
                       db: Session = Depends(get_db)):
    """How often each student has run each self-check. For monitoring and
    troubleshooting -- repeated checks usually just mean a student is
    improving their work, not misconduct."""
    assignment = instructor_assignment(db, instructor, assignment_id)
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
            last_check_at=as_utc(last.created_at) if last else None,
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
        check.finished_at = utcnow_naive()
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
    run = code_similarity_run(db, submission.subject_id, submission.assignment_name, others)
    return _self_checks.code_result(
        str(submission.id), run.pairs, run.files_by_submission.get(str(submission.id), []),
        {sid: fp.hashes for sid, fp in run.fingerprints.items()}, run.batch.status)


def _self_check_report(db: Session, submission: Submission) -> dict:
    own, reason = report_similarity_text(submission)
    if own is None:
        return _self_checks.report_result(str(submission.id), [], "disabled", skipped_reason=reason)
    texts = {str(submission.id): own}
    for other in (db.query(Submission)
                  .filter(Submission.subject_id == submission.subject_id,
                          Submission.assignment_name == submission.assignment_name,
                          Submission.id != submission.id).all()):
        text, _ = report_similarity_text(other)
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
                           if p.is_file() and p.suffix.lower() in ANALYZED_EXTENSIONS) if code_dir.is_dir() else ""
        if source.strip():
            signal = _score_ai_code(str(submission.id), source)
            code_band = _self_checks.ai_band(signal.signal)
            detail["code"] = {"signal": signal.signal, "score": signal.score, "method": "style-heuristic"}
    return {"report": report_band, "code": code_band, "detail": detail}
